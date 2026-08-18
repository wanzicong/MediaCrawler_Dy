# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

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

# Application orchestration catches these integration-owned names while runtime
# identity remains exactly the Playwright exception classes used before.
BrowserAutomationError: TypeAlias = PlaywrightError
BrowserAutomationTimeoutError: TypeAlias = PlaywrightTimeoutError


class DouyinBrowserMode(str, Enum):
    """CDP mode value kept independent from the ORM-facing domain enum.

    The historical browser module exposed a ``DouyinBrowserMode`` symbol as an
    import side effect.  Keeping the neutral equivalent here also preserves that
    import and the enum's ``.value``/string behavior without a reverse dependency.
    """

    local = "local"
    remote = "remote"


class CDPBrowserSession:
    """Own a page connected exclusively through Chrome DevTools Protocol."""

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
        self.config = config
        requested_mode = browser_mode or config.DOUYIN_BROWSER_MODE
        browser_mode_value = str(getattr(requested_mode, "value", requested_mode))
        try:
            compatible_mode = DouyinBrowserMode(browser_mode_value)
        except ValueError:
            # Preserve the historical domain-enum validation message without
            # importing that ORM-facing enum into the integration layer.
            raise ValueError(
                f"{browser_mode_value!r} is not a valid DouyinBrowserMode"
            ) from None
        # Existing callers sometimes inspect ``session.browser_mode.value``.  If
        # they supplied the historical enum, retain that exact object; otherwise
        # expose an equivalent neutral enum instead of the refactor's plain str.
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
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def start(self) -> None:
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
        return await probe_tcp_port(
            self.config.DOUYIN_CDP_HOST,
            port,
            timeout=0.5,
            connection_factory=socket.create_connection,
        )

    @staticmethod
    def _available_port(start: int) -> int:
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
