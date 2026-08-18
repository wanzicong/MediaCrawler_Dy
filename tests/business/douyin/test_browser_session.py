import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from crawler.bootstrap.settings import settings
from crawler.browser.session import (
    BrowserAutomationError,
    BrowserAutomationTimeoutError,
    CDPBrowserSession,
)
from crawler.browser.session import DouyinBrowserMode as BrowserModuleMode
from crawler.business.douyin.accounts.models import DouyinBrowserMode
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


class FakeAsyncClient:
    def __init__(self, response: httpx.Response):
        self.response = response

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, _url: str, **_kwargs: Any) -> httpx.Response:
        return self.response


def test_browser_mode_keeps_historical_enum_value_semantics() -> None:
    configured = CDPBrowserSession(settings)
    supplied_mode = DouyinBrowserMode.remote
    supplied = CDPBrowserSession(settings, browser_mode=supplied_mode)

    assert configured.browser_mode.value == settings.DOUYIN_BROWSER_MODE  # type: ignore[attr-defined]
    assert isinstance(configured.browser_mode, BrowserModuleMode)
    assert str(configured.browser_mode) == (
        f"DouyinBrowserMode.{settings.DOUYIN_BROWSER_MODE}"
    )
    assert supplied.browser_mode is supplied_mode


def test_browser_exception_boundary_preserves_playwright_identity() -> None:
    assert BrowserAutomationError is PlaywrightError
    assert BrowserAutomationTimeoutError is PlaywrightTimeoutError


def test_interaction_session_reuses_and_preserves_existing_page() -> None:
    existing_page = MagicMock()
    existing_page.is_closed.return_value = False
    existing_page.close = AsyncMock()
    created_page = MagicMock()
    context = MagicMock()
    context.pages = [existing_page]
    context.new_page = AsyncMock(return_value=created_page)
    session = CDPBrowserSession(
        settings,
        reuse_existing_page=True,
        close_page_on_exit=False,
    )
    session.context = context

    asyncio.run(session._acquire_page())

    assert session.page is existing_page
    assert session.owns_page is False
    context.new_page.assert_not_awaited()
    asyncio.run(session.close())
    existing_page.close.assert_not_awaited()


def test_owned_page_is_closed_for_default_session() -> None:
    page = MagicMock()
    page.close = AsyncMock()
    session = CDPBrowserSession(settings)
    session.page = page
    session.owns_page = True

    asyncio.run(session.close())

    page.close.assert_awaited_once()


def test_marked_session_ignores_unrelated_user_pages() -> None:
    user_page = MagicMock()
    user_page.is_closed.return_value = False
    user_page.evaluate = AsyncMock(return_value="")
    automation_page = MagicMock()
    automation_page.is_closed.return_value = False
    automation_page.evaluate = AsyncMock(return_value="mediacrawler:interaction")
    context = MagicMock()
    context.pages = [user_page, automation_page]
    context.new_page = AsyncMock()
    session = CDPBrowserSession(
        settings,
        page_marker="mediacrawler:interaction",
        close_page_on_exit=False,
    )
    session.context = context

    asyncio.run(session._acquire_page())

    assert session.page is automation_page
    assert session.unrelated_page_count == 1
    context.new_page.assert_not_awaited()


def test_marked_session_creates_dedicated_page_without_hijacking_user_page() -> None:
    user_page = MagicMock()
    user_page.is_closed.return_value = False
    user_page.evaluate = AsyncMock(return_value="")
    automation_page = MagicMock()
    automation_page.evaluate = AsyncMock()
    context = MagicMock()
    context.pages = [user_page]
    context.new_page = AsyncMock(return_value=automation_page)
    session = CDPBrowserSession(
        settings,
        page_marker="mediacrawler:interaction",
        close_page_on_exit=False,
    )
    session.context = context

    asyncio.run(session._acquire_page())

    assert session.page is automation_page
    assert session.unrelated_page_count == 1
    automation_page.evaluate.assert_awaited_once_with(
        "marker => { window.name = marker; }", "mediacrawler:interaction"
    )


def test_local_discovery_keeps_legacy_httpx_monkeypatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "http://127.0.0.1/json/version"),
        json={"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/local-id"},
    )
    client = FakeAsyncClient(response)
    monkeypatch.setattr("crawler.browser.session.httpx.AsyncClient", lambda **_: client)
    session = CDPBrowserSession(settings)

    websocket_url = asyncio.run(session._websocket_url())

    assert websocket_url == "ws://127.0.0.1/devtools/browser/local-id"


def test_local_probe_keeps_legacy_socket_monkeypatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *_: object) -> None:
            return None

    calls: list[tuple[tuple[str, int], float]] = []

    def fake_connection(address: tuple[str, int], timeout: float) -> FakeConnection:
        calls.append((address, timeout))
        return FakeConnection()

    monkeypatch.setattr(
        "crawler.browser.session.socket.create_connection",
        fake_connection,
    )
    session = CDPBrowserSession(settings)

    assert asyncio.run(session._probe(9222)) is True
    assert calls == [((settings.DOUYIN_CDP_HOST, 9222), 0.5)]


def test_local_connection_uses_only_connect_over_cdp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = MagicMock()
    playwright = MagicMock()
    playwright.chromium.connect_over_cdp = AsyncMock(return_value=browser)
    monkeypatch.setattr(settings, "DOUYIN_CDP_CONNECT_EXISTING", False)
    session = CDPBrowserSession(settings)
    session.playwright = playwright
    session._websocket_url = AsyncMock(  # type: ignore[method-assign]
        return_value="ws://127.0.0.1:9222/devtools/browser/local-id"
    )

    result = asyncio.run(session._connect())

    assert result is browser
    playwright.chromium.connect_over_cdp.assert_awaited_once_with(
        "ws://127.0.0.1:9222/devtools/browser/local-id"
    )
