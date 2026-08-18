# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""CDP 浏览器会话封装：统一管理本地/远程浏览器的启动、连接与页面生命周期。

属于浏览器集成层，是上层业务（登录、采集、互动）获取 Playwright Page 的统一入口，
仅通过 Chrome DevTools Protocol 连接浏览器，绝不回退到 launch 方式。
"""

import asyncio
import logging
import os
import shutil
import socket
import subprocess
from enum import Enum
from pathlib import Path
from typing import TypeAlias

import httpx
from crawler.bootstrap.settings import Settings
from crawler.browser.cdp import (
    connect_over_cdp,
    discover_local_websocket_url,
    find_available_port,
    probe_tcp_port,
)
from crawler.browser.errors import CDPConnectionError
from crawler.browser.remote import RemoteBrowserManager
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)

# 应用编排层捕获这些由集成层拥有的别名，而其运行时身份仍然是
# 之前使用的 Playwright 异常类本身。
BrowserAutomationError: TypeAlias = PlaywrightError
BrowserAutomationTimeoutError: TypeAlias = PlaywrightTimeoutError


class DouyinBrowserMode(str, Enum):
    """与 ORM 领域枚举保持独立的 CDP 浏览器模式枚举。

    历史浏览器模块曾作为导入副作用暴露 ``DouyinBrowserMode`` 符号。在此保留
    等价的中立枚举，既维持该导入路径可用，也保留枚举的 ``.value``/字符串行为，
    同时避免对领域层形成反向依赖。
    """

    local = "local"  # 本地模式：附加本机已开启 CDP 的浏览器，或由会话代为启动
    remote = "remote"  # 远程模式：连接预先配置的远程 CDP 浏览器（如 Docker 容器中的 Chrome）


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
            reuse_existing_page: 为 True 时复用上下文中的既有页面。
            close_page_on_exit: 退出时是否关闭本会话拥有的页面。
            page_marker: 页面标记；设置后按 window.name 匹配并复用同名页面。

        异常：
            ValueError: browser_mode 不是合法的 DouyinBrowserMode 取值时抛出。
        """
        self.config = config
        requested_mode = browser_mode or config.DOUYIN_BROWSER_MODE
        browser_mode_value = str(getattr(requested_mode, "value", requested_mode))
        try:
            compatible_mode = DouyinBrowserMode(browser_mode_value)
        except ValueError:
            # 保留历史领域枚举的校验报错文案，同时避免把该 ORM 枚举
            # 引入集成层。
            raise ValueError(
                f"{browser_mode_value!r} is not a valid DouyinBrowserMode"
            ) from None
        # 既有调用方有时会访问 ``session.browser_mode.value``。若调用方传入的是
        # 历史枚举，则原样保留该对象；否则暴露等价的中立枚举，而不是重构后的
        # 纯字符串。
        self.browser_mode: object = (
            requested_mode if hasattr(requested_mode, "value") else compatible_mode
        )
        self._browser_mode_value = compatible_mode.value
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.managed = False
        self.remote_host = remote_host or config.DOUYIN_REMOTE_CDP_HOST
        self.remote_port = remote_port or config.DOUYIN_REMOTE_CDP_PORT
        self.user_data_dir = user_data_dir or config.DOUYIN_CDP_USER_DATA_DIR
        self.debug_port = debug_port or config.DOUYIN_CDP_PORT
        self.reuse_existing_page = reuse_existing_page
        self.close_page_on_exit = close_page_on_exit
        self.page_marker = page_marker
        self.owns_page = False
        self.unrelated_page_count = 0

    async def __aenter__(self) -> "CDPBrowserSession":
        """异步上下文入口：启动会话并返回自身。"""
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        """异步上下文出口：关闭会话并释放资源。"""
        await self.close()

    async def start(self) -> None:
        """启动 Playwright，按模式建立浏览器连接并获取页面。

        remote 模式连接远程 CDP 浏览器；local 模式下若配置要求附加既有浏览器则直接
        探测端口，否则在本机启动一个开启 CDP 的 Chrome/Edge。随后注入 stealth.js
        反检测脚本，并按页面标记复用或新建页面。

        异常：
            CDPConnectionError: CDP 端口不可用、未找到浏览器或连接失败时抛出。
            Exception: 任意失败都会先执行 close() 清理资源再继续抛出。
        """
        self.playwright = await async_playwright().start()
        try:
            if self._browser_mode_value == DouyinBrowserMode.remote.value:
                remote = RemoteBrowserManager(
                    host=self.remote_host,
                    port=self.remote_port,
                    timeout=self.config.DOUYIN_CDP_CONNECT_TIMEOUT,
                )
                self.browser = await remote.connect(self.playwright)
            elif self.config.DOUYIN_CDP_CONNECT_EXISTING:
                if not await self._probe(self.debug_port):
                    raise CDPConnectionError(
                        f"CDP 端口不可用: {self.config.DOUYIN_CDP_HOST}:{self.debug_port}"
                    )
            else:
                if self.config.DOUYIN_CDP_HOST not in {"127.0.0.1", "localhost", "::1"}:
                    raise CDPConnectionError(
                        "启动本地浏览器时 DOUYIN_CDP_HOST 必须是本机地址"
                    )
                if not await self._probe(self.debug_port):
                    self.debug_port = self._available_port(self.debug_port)
                    await self._launch_local_browser()
                    self.managed = True

            if self.browser is None:
                self.browser = await self._connect()
            if self.browser.contexts:
                self.context = self.browser.contexts[0]
            else:
                self.context = await self.browser.new_context(
                    accept_downloads=False, viewport={"width": 1920, "height": 1080}
                )
            stealth_path = Path(__file__).with_name("resources") / "stealth.js"
            await self.context.add_init_script(path=stealth_path)
            await self._acquire_page()
        except Exception:
            await self.close()
            raise

    async def _launch_local_browser(self) -> None:
        """在本机启动一个开启 CDP 调试端口的 Chrome/Edge 进程并等待其就绪。"""
        assert self.playwright is not None
        executable = self._find_browser() or self.playwright.chromium.executable_path
        if not executable or not Path(executable).is_file():
            raise CDPConnectionError(
                "未找到 Chrome/Edge。请设置 DOUYIN_CDP_BROWSER_PATH，或连接已开启 CDP 的浏览器"
            )
        user_data_dir = self.user_data_dir.resolve()
        user_data_dir.mkdir(parents=True, exist_ok=True)
        command = [
            executable,
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={self.debug_port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
        ]
        if self.config.DOUYIN_CDP_HEADLESS:
            command.append("--headless=new")
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        )
        self.process = subprocess.Popen(command, creationflags=creationflags)
        deadline = (
            asyncio.get_running_loop().time() + self.config.DOUYIN_CDP_CONNECT_TIMEOUT
        )
        while asyncio.get_running_loop().time() < deadline:
            if self.process.poll() is not None:
                raise CDPConnectionError(
                    f"浏览器进程提前退出，退出码: {self.process.returncode}"
                )
            if await self._probe(self.debug_port):
                return
            await asyncio.sleep(0.5)
        raise CDPConnectionError("等待 CDP 浏览器启动超时")

    async def _acquire_page(self) -> None:
        """按页面标记或复用策略获取/创建页面，并记录页面归属。"""
        assert self.context is not None
        reusable_pages = [page for page in self.context.pages if not page.is_closed()]
        if self.page_marker:
            marked_pages: list[Page] = []
            for candidate in reusable_pages:
                try:
                    marker = await candidate.evaluate("() => window.name")
                except Exception:
                    continue
                if marker == self.page_marker:
                    marked_pages.append(candidate)
            self.unrelated_page_count = len(reusable_pages) - len(marked_pages)
            if marked_pages:
                self.page = marked_pages[-1]
                self.owns_page = False
                return
            self.page = await self.context.new_page()
            await self.page.evaluate(
                "marker => { window.name = marker; }", self.page_marker
            )
            self.owns_page = True
            return
        if self.reuse_existing_page and reusable_pages:
            self.page = reusable_pages[-1]
            self.owns_page = False
            return
        self.page = await self.context.new_page()
        self.owns_page = True

    def _find_browser(self) -> str | None:
        """按配置与常见安装路径查找本机 Chrome/Edge 可执行文件。"""
        configured = self.config.DOUYIN_CDP_BROWSER_PATH.strip()
        if configured:
            return configured
        candidates = [
            shutil.which("google-chrome"),
            shutil.which("google-chrome-stable"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
            shutil.which("msedge"),
        ]
        if os.name == "nt":
            roots = [
                os.getenv("PROGRAMFILES"),
                os.getenv("PROGRAMFILES(X86)"),
                os.getenv("LOCALAPPDATA"),
            ]
            for root in filter(None, roots):
                candidates.extend(
                    [
                        str(Path(root) / "Google/Chrome/Application/chrome.exe"),
                        str(Path(root) / "Microsoft/Edge/Application/msedge.exe"),
                    ]
                )
        return next(
            (str(path) for path in candidates if path and Path(path).is_file()), None
        )

    async def _connect(self) -> Browser:
        """连接本地 CDP 浏览器：优先直连 ws 端点，失败后回退 /json/version 发现。"""
        assert self.playwright is not None
        host = self.config.DOUYIN_CDP_HOST
        if self.config.DOUYIN_CDP_CONNECT_EXISTING:
            direct_url = f"ws://{host}:{self.debug_port}/devtools/browser"
            try:
                return await connect_over_cdp(
                    self.playwright.chromium,
                    direct_url,
                    timeout_ms=5_000,
                )
            except Exception as direct_error:
                logger.info(
                    "CDP direct endpoint unavailable, trying /json/version: %s",
                    type(direct_error).__name__,
                )
        websocket_url = await self._websocket_url()
        try:
            return await connect_over_cdp(
                self.playwright.chromium,
                websocket_url,
            )
        except Exception as exc:
            raise CDPConnectionError(f"CDP 连接失败: {type(exc).__name__}") from exc

    async def _websocket_url(self) -> str:
        """通过本地 /json/version 端点发现浏览器 WebSocket 地址（带重试）。"""
        endpoint = (
            f"http://{self.config.DOUYIN_CDP_HOST}:{self.debug_port}/json/version"
        )
        return await discover_local_websocket_url(
            endpoint=endpoint,
            client_factory=httpx.AsyncClient,
            error_factory=lambda reason: CDPConnectionError(
                f"无法读取 CDP /json/version: {reason}"
            ),
            attempts=10,
            request_timeout=5,
            retry_interval=0.5,
            sleep=asyncio.sleep,
        )

    async def _probe(self, port: int) -> bool:
        """探测本机指定 CDP 端口是否可建立 TCP 连接。"""
        return await probe_tcp_port(
            self.config.DOUYIN_CDP_HOST,
            port,
            timeout=0.5,
            connection_factory=socket.create_connection,
        )

    @staticmethod
    def _available_port(start: int) -> int:
        """从起始端口向后寻找可用端口，找不到时抛出 CDPConnectionError。"""
        port = find_available_port(
            start,
            span=100,
            bind_host="127.0.0.1",
            socket_factory=socket.socket,
        )
        if port is None:
            raise CDPConnectionError("没有可用的 CDP 调试端口")
        return port

    async def close(self) -> None:
        """按归属关系释放页面、浏览器、Playwright 驱动与托管进程。

        仅关闭本会话拥有且允许关闭的页面；仅当浏览器由本会话托管且配置允许自动
        关闭时才关闭浏览器与进程。各清理步骤的异常均被吞掉并记录 debug 日志。
        """
        if self.page and self.owns_page and self.close_page_on_exit:
            try:
                await self.page.close()
            except Exception:
                logger.debug("CDP page already closed", exc_info=True)
        self.page = None
        self.owns_page = False
        if self.managed and self.browser and self.config.DOUYIN_CDP_AUTO_CLOSE:
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
        if self.managed and self.process and self.config.DOUYIN_CDP_AUTO_CLOSE:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(self.process.wait), timeout=5
                    )
                except asyncio.TimeoutError:
                    self.process.kill()
            self.process = None
