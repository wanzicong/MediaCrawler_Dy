import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.core.config import settings
from app.douyin.interactions import (
    DouyinInteractionExecutor,
    InteractionExecutionError,
    InteractionExecutionRequest,
    InteractionExecutionResult,
)
from app.models import DouyinInteractionType


def test_open_comment_panel_expands_real_douyin_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = DouyinInteractionExecutor(settings)
    entry = AsyncMock()
    editor = AsyncMock()
    find_visible = AsyncMock(side_effect=[None, entry, editor])
    monkeypatch.setattr(executor, "_find_visible", find_visible)

    result = asyncio.run(executor._open_comment_panel(AsyncMock()))

    assert result is editor
    entry.click.assert_awaited_once()
    assert find_visible.await_args_list[1].args[1] == (
        "#comment-input-container",
        ".comment-input-inner-container",
    )
    assert find_visible.await_args_list[2].args[1][0] == (
        '#comment-input-container [contenteditable="true"][role="combobox"]'
    )


def test_find_submit_control_prefers_real_douyin_arrow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submit = AsyncMock()
    find_visible = AsyncMock(return_value=submit)
    monkeypatch.setattr(DouyinInteractionExecutor, "_find_visible", find_visible)

    result = asyncio.run(
        DouyinInteractionExecutor._find_submit_control(
            AsyncMock(), AsyncMock()
        )
    )

    assert result is submit
    assert find_visible.await_args.args[1][0] == (
        "#comment-input-container .commentInput-right-ct > div > span:last-child"
    )


def test_find_visible_skips_hidden_duplicate_nodes() -> None:
    hidden = AsyncMock()
    hidden.is_visible.return_value = False
    visible = AsyncMock()
    visible.is_visible.return_value = True
    matches = MagicMock()
    matches.count = AsyncMock(return_value=2)
    matches.nth.side_effect = [hidden, visible]
    page = MagicMock()
    page.locator.return_value = matches
    page.wait_for_timeout = AsyncMock()

    result = asyncio.run(
        DouyinInteractionExecutor._find_visible(
            page, ('[data-e2e="feed-comment-icon"]',), timeout=250
        )
    )

    assert result is visible
    matches.nth.assert_any_call(0)
    matches.nth.assert_any_call(1)


def test_video_comment_records_meaningful_browser_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = DouyinInteractionExecutor(settings)
    page = AsyncMock()
    editor = AsyncMock()
    callback = AsyncMock()
    monkeypatch.setattr(executor, "_open_video", AsyncMock())
    monkeypatch.setattr(
        executor, "_open_comment_panel", AsyncMock(return_value=editor)
    )
    submit = AsyncMock(return_value=InteractionExecutionResult())
    monkeypatch.setattr(executor, "_fill_and_submit", submit)
    request = InteractionExecutionRequest(
        interaction_type=DouyinInteractionType.video_comment,
        aweme_id="123",
        content="测试评论",
    )

    asyncio.run(executor._comment_video(page, request, callback))

    assert [call.args[1] for call in callback.await_args_list] == [
        "video_opened",
        "comment_editor_ready",
    ]
    submit.assert_awaited_once_with(page, editor, "测试评论", callback)


def test_open_video_waits_until_page_is_really_interactive() -> None:
    executor = DouyinInteractionExecutor(settings)
    page = AsyncMock()

    asyncio.run(executor._open_video(page, "123"))

    page.goto.assert_awaited_once()
    page.wait_for_function.assert_awaited_once_with(
        executor.video_page_ready_script,
        timeout=settings.DOUYIN_INTERACTION_PAGE_READY_TIMEOUT_SECONDS * 1000,
    )


def test_open_video_reports_page_load_timeout() -> None:
    executor = DouyinInteractionExecutor(settings)
    page = AsyncMock()
    page.wait_for_function.side_effect = PlaywrightTimeoutError("timeout")

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(executor._open_video(page, "123"))

    assert captured.value.code == "page_load_timeout"
    assert captured.value.retryable is True
    assert page.wait_for_function.await_count == (
        settings.DOUYIN_INTERACTION_NAVIGATION_ATTEMPTS
    )
    target_calls = [
        call
        for call in page.goto.await_args_list
        if call.args[0] == "https://www.douyin.com/video/123"
    ]
    assert len(target_calls) == settings.DOUYIN_INTERACTION_NAVIGATION_ATTEMPTS


def test_open_video_recovers_from_stuck_loading_shell() -> None:
    executor = DouyinInteractionExecutor(settings)
    page = AsyncMock()
    page.wait_for_function.side_effect = [PlaywrightTimeoutError("timeout"), None]

    asyncio.run(executor._open_video(page, "123"))

    assert [call.args[0] for call in page.goto.await_args_list] == [
        "https://www.douyin.com/video/123",
        "about:blank",
        "https://www.douyin.com/video/123",
    ]
    page.wait_for_timeout.assert_awaited_once_with(1_000)
    assert page.wait_for_function.await_count == 2


def test_open_video_retries_transient_navigation_errors() -> None:
    executor = DouyinInteractionExecutor(settings)
    page = AsyncMock()
    page.goto.side_effect = [PlaywrightError("temporary ssl error"), None]

    asyncio.run(executor._open_video(page, "123"))

    assert page.goto.await_count == 2
    page.wait_for_timeout.assert_awaited_once_with(1_000)
    page.wait_for_function.assert_awaited_once()
