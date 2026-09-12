"""本地 CDP 连接的测试：端口探测、WebSocket 地址发现、附加连接与本机启动器。"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from crawler.bootstrap.settings import settings
from crawler.browser.connection.connector import LocalCdpConnector
from crawler.browser.connection.launcher import LocalChromeLauncher


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
        "crawler.browser.connection.connector.httpx.AsyncClient", lambda **_: client
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
        "crawler.browser.connection.connector.socket.create_connection",
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


def test_local_launcher_finds_a_bindable_port_from_start() -> None:
    """验证本机启动器从起始端口起找到可绑定的空闲端口（找不到时不返回 -1）。"""
    launcher = LocalChromeLauncher(settings)

    port = launcher.find_free_port(9222)

    assert 9222 <= port < 9322
