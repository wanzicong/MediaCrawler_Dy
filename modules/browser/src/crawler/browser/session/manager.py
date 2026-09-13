"""CDP 浏览器会话门面：统一管理本地/远程浏览器的启动、连接与页面生命周期。

属于浏览器集成层的编排入口，是上层业务（登录、采集、互动）获取浏览器能力的
统一入口。本类只做编排——把远程/本地分支交给连接器与启动器、页面获取交给页面
策略，自身不再实现进程管理或协议细节，绝不回退到 launch 方式。

对外只暴露只读的 ``browser_page``（``BrowserPage`` 端口）与 ``session_context()``；
``page_handle`` 是 browser 内部专用的写操作入口。原生 Playwright 的 page / context
不再对外暴露，只作为 ``_page`` / ``_context`` 私有字段在包内使用。
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from crawler.bootstrap.settings import Settings
from crawler.browser.connection.connector import LocalCdpConnector
from crawler.browser.connection.launcher import LocalChromeLauncher
from crawler.browser.connection.remote import RemoteBrowserManager
from crawler.browser.errors import CDPConnectionError
from crawler.browser.page.handle import PlaywrightPageHandle
from crawler.browser.page.port import BrowserPage
from crawler.browser.session.context import BrowserSessionContext
from crawler.browser.session.mode import BrowserMode, coerce_browser_mode
from crawler.browser.session.policy import PageAcquisitionPolicy
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

if TYPE_CHECKING:  # facade 包反向 import 本模块，运行时 import 会构成环。
    from crawler.browser.facade.spec import BrowserSessionSpec

logger = logging.getLogger(__name__)

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

# 反检测脚本路径。本模块必须始终处于 crawler/browser/<子包>/ 的第 2 层，
# 否则 parents[1] 会解析到 crawler/browser 之外，stealth.js 静默失效
# （测试里 context 是 mock，路径错了不会红）。模块内唯一出处，便于直测断言。
STEALTH_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "resources" / "stealth.js"


class CDPBrowserSession:
    """管理一个仅通过 Chrome DevTools Protocol 连接的页面会话。

    封装 Playwright 驱动、浏览器、上下文与页面的完整生命周期：支持附加本机已有
    浏览器、代为启动本地浏览器、连接远程 CDP 浏览器，并按标记复用或新建页面。
    """

    def __init__(
        self,
        config: Settings,
        *,
        browser_mode: str | object | None = None,
        remote_host: str | None = None,
        remote_port: int | None = None,
        user_data_dir: Path | None = None,
        debug_port: int | None = None,
        slot_name: str | None = None,
        keep_alive: bool = False,
        reuse_existing_page: bool = False,
        close_page_on_exit: bool = True,
        page_marker: str | None = None,
    ):
        """初始化会话配置；实际的连接与页面获取在 start() 中完成。

        参数：
            config: 应用配置对象，未显式传入的参数从其中读取默认值。
            browser_mode: 浏览器模式（"local"/"remote" 或对应领域枚举）；为 None 时取配置。
            remote_host: 远程 CDP 主机，覆盖配置中的 DOUYIN_REMOTE_CDP_HOST。
            remote_port: 远程 CDP 端口，覆盖配置中的 DOUYIN_REMOTE_CDP_PORT。
            user_data_dir: 本地浏览器用户数据目录。
            debug_port: CDP 调试端口。
            slot_name: 槽位名；仅作诊断标识，连接参数由调用方解析得到。
            keep_alive: 为 True 时本会话启动的浏览器进程在会话结束后保留，
                供同槽位的后续会话直接附加（常驻本机槽位）。
            reuse_existing_page: 为 True 时复用上下文中的既有页面。
            close_page_on_exit: 退出时是否关闭本会话拥有的页面。
            page_marker: 页面标记；设置后按 window.name 匹配并复用同名页面。

        异常：
            ValueError: browser_mode 不是合法的 BrowserMode 取值时抛出。
        """
        self.config = config
        requested_mode = browser_mode or config.DOUYIN_BROWSER_MODE
        # 既有调用方有时会访问 ``session.browser_mode.value``。若调用方传入的是
        # 历史领域枚举，则原样保留该对象；否则暴露等价的中立枚举。
        exposed_mode, canonical_mode = coerce_browser_mode(
            requested_mode,
            config.DOUYIN_BROWSER_MODE,
        )
        self.browser_mode: object = exposed_mode
        self._browser_mode_value = canonical_mode.value
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._session_context: BrowserSessionContext | None = None
        self._page_handle: PlaywrightPageHandle | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.managed = False
        self.remote_host = remote_host or config.DOUYIN_REMOTE_CDP_HOST
        self.remote_port = remote_port or config.DOUYIN_REMOTE_CDP_PORT
        self.user_data_dir = user_data_dir or config.DOUYIN_CDP_USER_DATA_DIR
        self.debug_port = debug_port or config.DOUYIN_CDP_PORT
        self.slot_name = slot_name
        self.keep_alive = keep_alive
        self.reuse_existing_page = reuse_existing_page
        self.close_page_on_exit = close_page_on_exit
        self.page_marker = page_marker
        self.owns_page = False
        self.unrelated_page_count = 0

    @classmethod
    def from_spec(
        cls,
        config: Settings,
        spec: BrowserSessionSpec,
        *,
        reuse_existing_page: bool = False,
        close_page_on_exit: bool = True,
        page_marker: str | None = None,
    ) -> CDPBrowserSession:
        """按连接参数 ``BrowserSessionSpec`` 构造会话（business 解析账号后的入口）。

        参数：
            config: 应用配置对象。
            spec: 账号解析得到的连接参数（本地 profile 或远程 CDP）。
            reuse_existing_page: 为 True 时复用上下文中的既有页面。
            close_page_on_exit: 退出时是否关闭本会话拥有的页面。
            page_marker: 页面标记；设置后按 window.name 匹配并复用同名页面。
        """
        return cls(
            config,
            browser_mode=spec.browser_mode,
            remote_host=spec.remote_host,
            remote_port=spec.remote_port,
            user_data_dir=spec.user_data_dir,
            debug_port=spec.debug_port,
            slot_name=spec.slot_name,
            keep_alive=spec.keep_alive,
            reuse_existing_page=reuse_existing_page,
            close_page_on_exit=close_page_on_exit,
            page_marker=page_marker,
        )

    async def __aenter__(self) -> CDPBrowserSession:
        """异步上下文入口：启动会话并返回自身。"""
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        """异步上下文出口：关闭会话并释放资源。"""
        await self.close()

    async def start(self) -> None:
        """启动 Playwright，按模式建立浏览器连接并获取页面。

        remote 模式连接远程 CDP 浏览器；local 模式下若配置要求附加既有浏览器则直接
        探测端口，否则在本机启动一个开启 CDP 的 Chrome/Edge（可复用同一槽位已在
        运行的常驻浏览器）。随后注入 stealth.js 反检测脚本，并按页面标记复用或
        新建页面。

        异常：
            CDPConnectionError: CDP 端口不可用、未找到浏览器或连接失败时抛出。
            Exception: 任意失败都会先执行 close() 清理资源再继续抛出。
        """
        self.playwright = await async_playwright().start()
        try:
            connector = LocalCdpConnector(
                host=self.config.DOUYIN_CDP_HOST,
                connect_existing=self.config.DOUYIN_CDP_CONNECT_EXISTING,
            )
            browser: Browser | None = None
            if self._browser_mode_value == BrowserMode.remote.value:
                manager = RemoteBrowserManager(
                    host=self.remote_host,
                    port=self.remote_port,
                    timeout=self.config.DOUYIN_CDP_CONNECT_TIMEOUT,
                )
                browser = await manager.connect(self.playwright)
            elif self.config.DOUYIN_CDP_CONNECT_EXISTING:
                if not await connector.probe(self.debug_port):
                    raise CDPConnectionError(
                        f"CDP 端口不可用: {self.config.DOUYIN_CDP_HOST}:{self.debug_port}"
                    )
            else:
                if self.config.DOUYIN_CDP_HOST not in _LOOPBACK_HOSTS:
                    raise CDPConnectionError(
                        "启动本地浏览器时 DOUYIN_CDP_HOST 必须是本机地址"
                    )
                if not await connector.probe(self.debug_port):
                    launcher = LocalChromeLauncher(self.config)
                    self.debug_port = launcher.find_free_port(self.debug_port)
                    self.process = await launcher.launch(
                        playwright=self.playwright,
                        debug_port=self.debug_port,
                        user_data_dir=self.user_data_dir,
                    )
                    self.managed = True

            if browser is None:
                browser = await connector.connect(self.playwright, self.debug_port)
            self.browser = browser
            if browser.contexts:
                self._context = browser.contexts[0]
            else:
                self._context = await browser.new_context(
                    accept_downloads=False, viewport={"width": 1920, "height": 1080}
                )
            if not STEALTH_SCRIPT_PATH.exists():  # pragma: no cover - 部署自检
                raise CDPConnectionError(f"反检测脚本缺失: {STEALTH_SCRIPT_PATH}")
            await self._context.add_init_script(path=STEALTH_SCRIPT_PATH)
            await self._acquire_page()
        except Exception:
            await self.close()
            raise

    async def _acquire_page(self) -> None:
        """按页面标记或复用策略获取/创建页面，并记录页面归属。"""
        context = self._context
        if context is None:
            raise CDPConnectionError("浏览器上下文不可用，无法获取页面")
        policy = PageAcquisitionPolicy(
            page_marker=self.page_marker,
            reuse_existing_page=self.reuse_existing_page,
        )
        await policy.acquire(context)
        page = policy.page
        if page is None:
            raise CDPConnectionError("页面获取策略未能提供可用页面")
        self._page = page
        self.owns_page = policy.owns_page
        self.unrelated_page_count = policy.unrelated_page_count
        # 会话能力适配器在本会话内唯一：page_handle 与 session_context() 共享同一份指纹缓存。
        self._session_context = BrowserSessionContext(page=page, context=context)
        self._page_handle = None

    async def open(
        self,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        timeout_ms: int = 30_000,
    ) -> None:
        """导航到指定 URL，等同 ``page.goto`` 的语义。

        超时抛 ``BrowserAutomationTimeoutError``（Playwright 原生 TimeoutError），
        其余导航失败抛 ``BrowserAutomationError``（Playwright 原生 Error）；
        会话尚未启动或已关闭时抛 ``CDPConnectionError``。

        参数：
            url: 目标地址。
            wait_until: 等待到的加载状态。
            timeout_ms: 导航超时时间（毫秒）。
        """
        await self.page_handle.goto(url, wait_until=wait_until, timeout_ms=timeout_ms)

    def session_context(self) -> BrowserSessionContext:
        """返回会话能力适配器；未 start() 或已 close() 时抛 CDPConnectionError。"""
        if self._session_context is None:
            raise CDPConnectionError("浏览器会话尚未启动或已关闭，无法提供会话上下文")
        return self._session_context

    @property
    def browser_page(self) -> BrowserPage:
        """上层唯一可用的浏览器面（只读能力端口）。"""
        return self.page_handle

    @property
    def page_handle(self) -> PlaywrightPageHandle:
        """browser 内部专用的页面句柄；business/api/mcp 禁止出现该名字（门禁 G17）。"""
        page = self._page
        context = self._context
        if page is None or context is None:
            raise CDPConnectionError("浏览器会话尚未启动或已关闭，无法提供页面句柄")
        if self._page_handle is None:
            self._page_handle = PlaywrightPageHandle(
                page=page,
                context=context,
                session_context=self._session_context,
            )
        return self._page_handle

    def is_usable(self) -> bool:
        """会话是否仍可用于页面操作：驱动已启动、浏览器仍连接、页面未关闭。

        用于识别「浏览器窗口被用户关闭或进程退出，但会话对象仍在内存里」的失效
        会话；任何探测异常都按不可用处理，绝不向上抛出。

        返回：
            True 表示可以继续取页面、cookie 等能力。
        """
        if self.playwright is None or self.browser is None or self._page is None:
            return False
        try:
            return self.browser.is_connected() and not self._page.is_closed()
        except Exception:
            return False

    async def close(self) -> None:
        """按归属关系释放页面、浏览器、Playwright 驱动与托管进程。

        仅关闭本会话拥有且允许关闭的页面；仅当浏览器由本会话托管且配置允许自动
        关闭时才关闭浏览器与进程；``keep_alive`` 会话（常驻本机槽位）始终保留由
        本会话拉起的浏览器进程，供后续会话直接附加。各清理步骤的异常均被吞掉并
        记录 debug 日志。
        """
        if self._session_context is not None:
            self._session_context.close()
            self._session_context = None
        self._page_handle = None
        if self._page and self.owns_page and self.close_page_on_exit:
            try:
                await self._page.close()
            except Exception:
                logger.debug("CDP page already closed", exc_info=True)
        self._page = None
        self.owns_page = False
        # 常驻槽位会话不得关闭自己拉起的浏览器，否则同槽位的下一个会话
        # 每次都要重新拉起进程，账号登录态与页面状态也会被反复打断。
        close_managed = (
            self.managed and self.config.DOUYIN_CDP_AUTO_CLOSE and not self.keep_alive
        )
        if close_managed and self.browser:
            try:
                await self.browser.close()
            except Exception:
                logger.debug("Managed CDP browser already closed", exc_info=True)
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                logger.debug("Playwright driver already stopped", exc_info=True)
            self.playwright = None
        if self.managed and self.process:
            if close_managed and self.process.poll() is None:
                self.process.terminate()
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(self.process.wait), timeout=5
                    )
                except asyncio.TimeoutError:
                    self.process.kill()
            self.process = None


__all__ = ["CDPBrowserSession", "STEALTH_SCRIPT_PATH"]
