import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.core.config import settings
from app.douyin.browser import CDPBrowserSession


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
