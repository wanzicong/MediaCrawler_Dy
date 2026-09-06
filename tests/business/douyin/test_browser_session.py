"""浏览器运行时组件测试：覆盖模式枚举语义、异常类型边界、页面复用/归属/标记隔离，以及本地 CDP 连接器（探测/发现/附加）。"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from crawler.bootstrap.settings import settings
from crawler.browser import (
    BrowserAutomationError,
    BrowserAutomationTimeoutError,
    CDPBrowserSession,
)
from crawler.browser.base.modes import DouyinBrowserMode as NeutralMode
from crawler.browser.runtime.connect import LocalCdpConnector
from crawler.browser.runtime.pages import PageAcquisitionPolicy
from crawler.business.douyin.accounts.models import DouyinBrowserMode
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


class FakeAsyncClient:
    """模拟 httpx.AsyncClient：返回预置响应。"""

    def __init__(self, response: httpx.Response):
        """以预置响应初始化。"""
        self.response = response

    async def __aenter__(self) -> "FakeAsyncClient":
        """进入异步上下文，返回自身。"""
        return self

    async def __aexit__(self, *_: object) -> None:
        """退出异步上下文（空实现）。"""
        return None

    async def get(self, _url: str, **_kwargs: Any) -> httpx.Response:
        """返回预置响应。"""
        return self.response


def _connector() -> LocalCdpConnector:
    """构造一个按当前配置初始化的本地连接器。"""
    return LocalCdpConnector(
        host=settings.DOUYIN_CDP_HOST,
        connect_existing=settings.DOUYIN_CDP_CONNECT_EXISTING,
    )


def test_browser_mode_keeps_historical_enum_value_semantics() -> None:
    """验证浏览器模式枚举保持历史取值语义：默认取配置值、字符串形式稳定、显式传参原样保留。"""
    configured = CDPBrowserSession(settings)
    supplied_mode = DouyinBrowserMode.remote
    supplied = CDPBrowserSession(settings, browser_mode=supplied_mode)

    assert configured.browser_mode.value == settings.DOUYIN_BROWSER_MODE  # type: ignore[attr-defined]
    assert isinstance(configured.browser_mode, NeutralMode)
    assert str(configured.browser_mode) == (
        f"DouyinBrowserMode.{settings.DOUYIN_BROWSER_MODE}"
    )
    assert supplied.browser_mode is supplied_mode


def test_browser_exception_boundary_preserves_playwright_identity() -> None:
    """验证浏览器自动化异常边界类型就是 playwright 原生异常（保持上层捕获兼容）。"""
    assert BrowserAutomationError is PlaywrightError
    assert BrowserAutomationTimeoutError is PlaywrightTimeoutError


def test_interaction_policy_reuses_and_preserves_existing_page() -> None:
    """验证复用策略取已存在页面、不新建、不拥有页面所有权。"""
    existing_page = MagicMock()
    existing_page.is_closed.return_value = False
    created_page = MagicMock()
    context = MagicMock()
    context.pages = [existing_page]
    context.new_page = AsyncMock(return_value=created_page)
    policy = PageAcquisitionPolicy(reuse_existing_page=True)

    asyncio.run(policy.acquire(context))

    assert policy.page is existing_page
    assert policy.owns_page is False
    context.new_page.assert_not_awaited()


def test_default_policy_owns_a_new_page() -> None:
    """验证默认策略新建页面并拥有所有权，关闭页面由会话负责。"""
    existing_page = MagicMock()
    existing_page.is_closed.return_value = False
    created_page = MagicMock()
    context = MagicMock()
    context.pages = [existing_page]
    context.new_page = AsyncMock(return_value=created_page)
    policy = PageAcquisitionPolicy()

    asyncio.run(policy.acquire(context))

    assert policy.page is created_page
    assert policy.owns_page is True


def test_marked_policy_ignores_unrelated_user_pages() -> None:
    """验证带标记的策略通过 window.name 识别自动化页面，忽略用户手工打开的页面。"""
    user_page = MagicMock()
    user_page.is_closed.return_value = False
    user_page.evaluate = AsyncMock(return_value="")
    automation_page = MagicMock()
    automation_page.is_closed.return_value = False
    automation_page.evaluate = AsyncMock(return_value="mediacrawler:interaction")
    context = MagicMock()
    context.pages = [user_page, automation_page]
    context.new_page = AsyncMock()
    policy = PageAcquisitionPolicy(page_marker="mediacrawler:interaction")

    asyncio.run(policy.acquire(context))

    assert policy.page is automation_page
    assert policy.unrelated_page_count == 1
    context.new_page.assert_not_awaited()


def test_marked_policy_creates_dedicated_page_without_hijacking_user_page() -> None:
    """验证无标记页面时新建专属自动化页面并写入标记，绝不劫持用户已有页面。"""
    user_page = MagicMock()
    user_page.is_closed.return_value = False
    user_page.evaluate = AsyncMock(return_value="")
    automation_page = MagicMock()
    automation_page.evaluate = AsyncMock()
    context = MagicMock()
    context.pages = [user_page]
    context.new_page = AsyncMock(return_value=automation_page)
    policy = PageAcquisitionPolicy(page_marker="mediacrawler:interaction")

    asyncio.run(policy.acquire(context))

    assert policy.page is automation_page
    assert policy.unrelated_page_count == 1
    automation_page.evaluate.assert_awaited_once_with(
        "marker => { window.name = marker; }", "mediacrawler:interaction"
    )


def test_owned_page_is_closed_for_default_session() -> None:
    """验证默认会话拥有页面所有权，关闭会话时页面随之关闭。"""
    page = MagicMock()
    page.close = AsyncMock()
    session = CDPBrowserSession(settings)
    session.page = page
    session.owns_page = True

    asyncio.run(session.close())

    page.close.assert_awaited_once()


def test_local_discovery_keeps_legacy_httpx_monkeypatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证本地 CDP 的 WebSocket 地址发现仍通过可猴子补丁的 httpx.AsyncClient 实现。"""
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "http://127.0.0.1/json/version"),
        json={"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/local-id"},
    )
    client = FakeAsyncClient(response)
    monkeypatch.setattr(
        "crawler.browser.runtime.connect.httpx.AsyncClient", lambda **_: client
    )
    connector = _connector()

    websocket_url = asyncio.run(connector.websocket_url(settings.DOUYIN_CDP_PORT))

    assert websocket_url == "ws://127.0.0.1/devtools/browser/local-id"


def test_local_probe_keeps_legacy_socket_monkeypatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证本地 CDP 端口探测仍通过可猴子补丁的 socket.create_connection 实现，超时为 0.5 秒。"""

    class FakeConnection:
        """模拟 socket 连接（上下文管理器空实现）。"""

        def __enter__(self) -> "FakeConnection":
            """进入上下文，返回自身。"""
            return self

        def __exit__(self, *_: object) -> None:
            """退出上下文（空实现）。"""
            return None

    calls: list[tuple[tuple[str, int], float]] = []

    def fake_connection(address: tuple[str, int], timeout: float) -> FakeConnection:
        """记录连接地址与超时并返回模拟连接。"""
        calls.append((address, timeout))
        return FakeConnection()

    monkeypatch.setattr(
        "crawler.browser.runtime.connect.socket.create_connection",
        fake_connection,
    )
    connector = _connector()

    assert asyncio.run(connector.probe(9222)) is True
    assert calls == [((settings.DOUYIN_CDP_HOST, 9222), 0.5)]


def test_local_connection_uses_only_connect_over_cdp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证本地浏览器连接仅通过 connect_over_cdp 完成（不使用 launch 系列方式）。"""
    browser = MagicMock()
    playwright = MagicMock()
    playwright.chromium.connect_over_cdp = AsyncMock(return_value=browser)
    monkeypatch.setattr(settings, "DOUYIN_CDP_CONNECT_EXISTING", False)
    connector = LocalCdpConnector(
        host=settings.DOUYIN_CDP_HOST,
        connect_existing=settings.DOUYIN_CDP_CONNECT_EXISTING,
    )
    connector.websocket_url = AsyncMock(  # type: ignore[method-assign]
        return_value="ws://127.0.0.1:9222/devtools/browser/local-id"
    )

    result = asyncio.run(connector.connect(playwright, 9222))

    assert result is browser
    playwright.chromium.connect_over_cdp.assert_awaited_once_with(
        "ws://127.0.0.1:9222/devtools/browser/local-id"
    )
