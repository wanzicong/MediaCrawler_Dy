"""远程浏览器管理器（RemoteBrowserManager）的测试：覆盖 WebSocket 地址改写、CDP 连接方式、IPv6 地址格式化与非法主机名校验。"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from crawler.browser.remote import RemoteBrowserManager


class FakeAsyncClient:
    """模拟 httpx.AsyncClient：返回预置响应并记录请求头。"""

    def __init__(self, response: httpx.Response):
        """以预置响应初始化。"""
        self.response = response
        self.request_headers: dict[str, str] = {}

    async def __aenter__(self) -> "FakeAsyncClient":
        """进入异步上下文，返回自身。"""
        return self

    async def __aexit__(self, *_: object) -> None:
        """退出异步上下文（空实现）。"""
        return None

    async def get(self, _url: str, **kwargs: Any) -> httpx.Response:
        """记录请求头并返回预置响应。"""
        self.request_headers = kwargs["headers"]
        return self.response


def test_remote_browser_rewrites_container_local_websocket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证容器返回的 localhost WebSocket 调试地址被改写为容器可达的主机名与端口。"""
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "http://douyin-browser:9222/json/version"),
        json={
            "webSocketDebuggerUrl": (
                "ws://localhost:9223/devtools/browser/browser-instance-id"
            )
        },
    )
    client = FakeAsyncClient(response)
    monkeypatch.setattr("crawler.browser.remote.httpx.AsyncClient", lambda **_: client)
    manager = RemoteBrowserManager(host="douyin-browser", port=9222, timeout=1)

    websocket_url = asyncio.run(manager.resolve_websocket_url())

    assert websocket_url == (
        "ws://douyin-browser:9222/devtools/browser/browser-instance-id"
    )
    assert client.request_headers == {"Host": "localhost"}


def test_remote_browser_connects_only_with_connect_over_cdp() -> None:
    """验证连接远程浏览器仅使用 connect_over_cdp 且超时换算为毫秒。"""
    manager = RemoteBrowserManager(host="douyin-browser", port=9222, timeout=3)
    manager.resolve_websocket_url = AsyncMock(  # type: ignore[method-assign]
        return_value="ws://douyin-browser:9222/devtools/browser/id"
    )
    browser = MagicMock()
    playwright = MagicMock()
    playwright.chromium.connect_over_cdp = AsyncMock(return_value=browser)

    result = asyncio.run(manager.connect(playwright))

    assert result is browser
    playwright.chromium.connect_over_cdp.assert_awaited_once_with(
        "ws://douyin-browser:9222/devtools/browser/id", timeout=3000
    )


def test_remote_browser_brackets_ipv6_websocket_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 IPv6 主机在改写 WebSocket 地址时被正确加上方括号。"""
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "http://localhost/json/version"),
        json={"webSocketDebuggerUrl": "ws://localhost:9222/devtools/browser/ipv6-id"},
    )
    client = FakeAsyncClient(response)
    monkeypatch.setattr("crawler.browser.remote.httpx.AsyncClient", lambda **_: client)
    manager = RemoteBrowserManager(host="2001:db8::1", port=9222, timeout=1)

    websocket_url = asyncio.run(manager.resolve_websocket_url())

    assert websocket_url == "ws://[2001:db8::1]:9222/devtools/browser/ipv6-id"


def test_remote_browser_rejects_url_in_host() -> None:
    """验证 host 参数传入完整 URL（含协议）时被拒绝，仅接受主机名或 IP。"""
    with pytest.raises(ValueError, match="主机名或 IP"):
        RemoteBrowserManager(host="http://example.com", port=9222, timeout=1)
