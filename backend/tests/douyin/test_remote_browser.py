import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.douyin.remote_browser import RemoteBrowserManager


class FakeAsyncClient:
    def __init__(self, response: httpx.Response):
        self.response = response
        self.request_headers: dict[str, str] = {}

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, _url: str, **kwargs: Any) -> httpx.Response:
        self.request_headers = kwargs["headers"]
        return self.response


def test_remote_browser_rewrites_container_local_websocket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    monkeypatch.setattr(
        "app.douyin.remote_browser.httpx.AsyncClient", lambda **_: client
    )
    manager = RemoteBrowserManager(
        host="douyin-browser", port=9222, timeout=1
    )

    websocket_url = asyncio.run(manager.resolve_websocket_url())

    assert websocket_url == (
        "ws://douyin-browser:9222/devtools/browser/browser-instance-id"
    )
    assert client.request_headers == {"Host": "localhost"}


def test_remote_browser_connects_only_with_connect_over_cdp() -> None:
    manager = RemoteBrowserManager(
        host="douyin-browser", port=9222, timeout=3
    )
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
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "http://localhost/json/version"),
        json={
            "webSocketDebuggerUrl": "ws://localhost:9222/devtools/browser/ipv6-id"
        },
    )
    client = FakeAsyncClient(response)
    monkeypatch.setattr(
        "app.douyin.remote_browser.httpx.AsyncClient", lambda **_: client
    )
    manager = RemoteBrowserManager(host="2001:db8::1", port=9222, timeout=1)

    websocket_url = asyncio.run(manager.resolve_websocket_url())

    assert websocket_url == "ws://[2001:db8::1]:9222/devtools/browser/ipv6-id"


def test_remote_browser_rejects_url_in_host() -> None:
    with pytest.raises(ValueError, match="主机名或 IP"):
        RemoteBrowserManager(host="http://example.com", port=9222, timeout=1)
