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


class _ExpectedResponse:
    def __init__(self, response: AsyncMock) -> None:
        self.response = response

    @property
    def value(self):  # type: ignore[no-untyped-def]
        async def resolve() -> AsyncMock:
            return self.response

        return resolve()

    async def __aenter__(self) -> "_ExpectedResponse":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


def test_open_comment_panel_expands_real_douyin_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = DouyinInteractionExecutor(settings)
    entry = AsyncMock()
    editor = AsyncMock()
    find_visible = AsyncMock(side_effect=[None, None, entry])
    monkeypatch.setattr(executor, "_find_visible", find_visible)
    activate = AsyncMock(return_value=editor)
    monkeypatch.setattr(executor, "_activate_comment_control", activate)

    page = MagicMock()
    page.context.pages = [page]
    page.is_closed.return_value = False
    page.url = "https://www.douyin.com/note/123"
    page.wait_for_timeout = AsyncMock()
    active_page, result = asyncio.run(
        executor._open_comment_panel(page, aweme_id="123")
    )

    assert active_page is page
    assert result is editor
    activate.assert_awaited_once_with(page, entry, require_editor=True)
    assert find_visible.await_args_list[2].args[1] == (
        ".comment-input-inner-container",
        "#comment-input-container",
    )


def test_comment_control_uses_real_click_when_dispatch_does_not_open_editor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = DouyinInteractionExecutor(settings)
    entry = AsyncMock()
    editor = AsyncMock()
    find_visible = AsyncMock(side_effect=[None, editor])
    monkeypatch.setattr(executor, "_find_visible", find_visible)
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()

    result = asyncio.run(
        executor._activate_comment_control(page, entry, require_editor=True)
    )

    assert result is editor
    entry.dispatch_event.assert_awaited_once_with("click")
    entry.click.assert_awaited_once_with(timeout=2_000)


def test_open_comment_panel_activates_note_comment_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = DouyinInteractionExecutor(settings)
    tab = AsyncMock()
    editor = AsyncMock()
    find_visible = AsyncMock(side_effect=[None, tab])
    monkeypatch.setattr(executor, "_find_visible", find_visible)
    activate = AsyncMock(return_value=editor)
    monkeypatch.setattr(executor, "_activate_comment_control", activate)
    page = MagicMock()
    page.context.pages = [page]
    page.is_closed.return_value = False
    page.url = "https://www.douyin.com/note/123"
    page.wait_for_timeout = AsyncMock()

    active_page, result = asyncio.run(
        executor._open_comment_panel(page, aweme_id="123")
    )

    assert active_page is page
    assert result is editor
    activate.assert_awaited_once_with(page, tab)


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
        '#comment-input-container .commentInput-right-ct span:has(path[fill="#fff"])'
    )


def test_comment_selectors_cover_note_page_class_container() -> None:
    executor = DouyinInteractionExecutor(settings)

    assert (
        '.comment-input-container [contenteditable="true"][role="combobox"]'
        in executor.editor_selectors
    )
    assert (
        '.comment-input-container .commentInput-right-ct span:has(path[fill="#fff"])'
        in executor.comment_submit_selectors
    )
    assert "div.X9EiuBV4:nth-of-type(2)" in executor.comment_tab_selectors


def test_click_reply_walks_to_deep_comment_card_and_dispatches_activation() -> None:
    nodes = [MagicMock() for _ in range(12)]
    reply_controls: list[MagicMock] = []
    for index, node in enumerate(nodes):
        replies = MagicMock()
        reply = MagicMock()
        reply.is_visible = AsyncMock(return_value=index == 10)
        reply.dispatch_event = AsyncMock()
        replies.count = AsyncMock(return_value=1 if index == 10 else 0)
        replies.nth.return_value = reply
        node.get_by_text.return_value = replies
        reply_controls.append(reply)
        if index + 1 < len(nodes):
            node.locator.return_value = nodes[index + 1]

    result = asyncio.run(DouyinInteractionExecutor._click_reply(nodes[0]))

    assert result is True
    reply_controls[10].dispatch_event.assert_awaited_once_with("click")


def test_click_reply_stops_before_ambiguous_comment_list() -> None:
    target = MagicMock()
    replies = MagicMock()
    first = MagicMock()
    second = MagicMock()
    first.is_visible = AsyncMock(return_value=True)
    second.is_visible = AsyncMock(return_value=True)
    first.dispatch_event = AsyncMock()
    second.dispatch_event = AsyncMock()
    replies.count = AsyncMock(return_value=2)
    replies.nth.side_effect = [first, second]
    target.get_by_text.return_value = replies

    result = asyncio.run(DouyinInteractionExecutor._click_reply(target))

    assert result is False
    first.dispatch_event.assert_not_awaited()
    second.dispatch_event.assert_not_awaited()


@pytest.mark.parametrize(
    "url",
    [
        "https://www.douyin.com/aweme/v1/web/comment/publish/?aid=6383",
        "https://www.douyin.com/aweme/v1/web/comment/create/?aid=6383",
        "https://www.douyin.com/api/comment/post/?aid=6383",
    ],
)
def test_comment_publish_response_accepts_current_endpoint_variants(url: str) -> None:
    response = MagicMock()
    response.url = url
    response.request.method = "POST"
    response.request.url = url

    assert DouyinInteractionExecutor._is_comment_publish_response(response) is True


def test_comment_publish_response_rejects_reads_and_list_requests() -> None:
    response = MagicMock()
    response.url = "https://www.douyin.com/aweme/v1/web/comment/list/"
    response.request.method = "GET"

    assert DouyinInteractionExecutor._is_comment_publish_response(response) is False


def test_comment_submit_falls_back_to_component_activation_when_click_is_lost() -> None:
    page = MagicMock()
    listeners: dict[str, object] = {}
    page.on.side_effect = lambda event, callback: listeners.__setitem__(event, callback)
    control = AsyncMock()
    control.bounding_box.side_effect = PlaywrightError("no box")

    result = asyncio.run(
        DouyinInteractionExecutor._dispatch_comment_submit(page, control)
    )

    assert result is False
    control.dispatch_event.assert_awaited_once_with("click")
    control.click.assert_awaited_once_with(timeout=5_000)
    page.remove_listener.assert_called_once_with("request", listeners["request"])


def test_comment_submit_does_not_activate_twice_after_publish_request() -> None:
    page = MagicMock()
    control = AsyncMock()
    callback: object | None = None

    def register(_event: str, request_callback: object) -> None:
        nonlocal callback
        callback = request_callback

    async def click_control(*_args: object, **_kwargs: object) -> None:
        request = MagicMock()
        request.method = "POST"
        request.url = "https://www.douyin.com/aweme/v1/web/comment/publish"
        assert callback is not None
        callback(request)  # type: ignore[operator]

    page.on.side_effect = register
    control.dispatch_event.side_effect = click_control

    result = asyncio.run(
        DouyinInteractionExecutor._dispatch_comment_submit(page, control)
    )

    assert result is True
    control.dispatch_event.assert_awaited_once_with("click")
    control.click.assert_not_awaited()


def test_comment_submit_uses_real_mouse_after_component_and_locator_fallbacks() -> None:
    page = MagicMock()
    control = AsyncMock()
    control.bounding_box.return_value = {
        "x": 10.0,
        "y": 20.0,
        "width": 30.0,
        "height": 40.0,
    }
    callback: object | None = None

    def register(_event: str, request_callback: object) -> None:
        nonlocal callback
        callback = request_callback

    async def click_mouse(_x: float, _y: float) -> None:
        request = MagicMock()
        request.method = "POST"
        request.url = "https://www.douyin.com/aweme/v1/web/comment/publish"
        assert callback is not None
        callback(request)  # type: ignore[operator]

    page.on.side_effect = register
    page.mouse.click = AsyncMock(side_effect=click_mouse)

    result = asyncio.run(
        DouyinInteractionExecutor._dispatch_comment_submit(page, control)
    )

    assert result is True
    control.dispatch_event.assert_awaited_once_with("click")
    control.click.assert_awaited_once_with(timeout=5_000)
    page.mouse.click.assert_awaited_once_with(25.0, 40.0)


def test_creator_message_waits_for_profile_and_requires_send_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = DouyinInteractionExecutor(settings)
    page = AsyncMock()
    page.url = "https://www.douyin.com/video/123"
    page.is_closed.return_value = False
    page.context.pages = [page]
    client = AsyncMock()
    client.get_video.return_value = {"author": {"sec_uid": "author-sec-id"}}
    profile = AsyncMock()
    button = AsyncMock()
    editor = AsyncMock()
    submit = AsyncMock(return_value=InteractionExecutionResult())
    monkeypatch.setattr(
        executor,
        "_find_visible",
        AsyncMock(return_value=profile),
    )
    monkeypatch.setattr(
        executor,
        "_find_text_control",
        AsyncMock(return_value=button),
    )
    monkeypatch.setattr(
        executor,
        "_find_message_editor",
        AsyncMock(return_value=(page, editor)),
    )
    monkeypatch.setattr(executor, "_fill_and_submit", submit)
    request = InteractionExecutionRequest(
        interaction_type=DouyinInteractionType.creator_message,
        aweme_id="123",
        content="测试私信",
    )

    asyncio.run(executor._message_creator(page, client, request, None))

    submit.assert_awaited_once_with(
        page,
        editor,
        "测试私信",
        None,
        require_explicit_submit=True,
    )


def test_creator_message_reports_retryable_page_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = DouyinInteractionExecutor(settings)
    page = AsyncMock()
    client = AsyncMock()
    client.get_video.return_value = {"author": {"sec_uid": "author-sec-id"}}
    monkeypatch.setattr(executor, "_find_visible", AsyncMock(return_value=None))
    monkeypatch.setattr(executor, "_find_text_control", AsyncMock(return_value=None))
    request = InteractionExecutionRequest(
        interaction_type=DouyinInteractionType.creator_message,
        aweme_id="123",
        content="测试私信",
    )

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(executor._message_creator(page, client, request, None))

    assert captured.value.code == "page_load_timeout"
    assert captured.value.retryable is True


def test_comment_submit_requires_publish_request_and_empty_editor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = DouyinInteractionExecutor(settings)
    page = MagicMock()
    response = AsyncMock()
    response.ok = True
    page.expect_response.return_value = _ExpectedResponse(response)
    submit = AsyncMock()
    editor = AsyncMock()
    editor.count.return_value = 1
    editor.input_value.return_value = ""
    monkeypatch.setattr(
        executor, "_find_submit_control", AsyncMock(return_value=submit)
    )
    monkeypatch.setattr(
        executor, "_dispatch_comment_submit", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(executor, "_wait_comment_submission", AsyncMock())

    result = asyncio.run(
        executor._fill_and_submit(
            page,
            editor,
            "测试评论",
            None,
            require_explicit_submit=True,
            require_comment_confirmation=True,
        )
    )

    assert result.platform_id is None
    submit.scroll_into_view_if_needed.assert_awaited_once()
    executor._dispatch_comment_submit.assert_awaited_once_with(page, submit)  # type: ignore[attr-defined]
    page.expect_response.assert_called_once()


def test_comment_submit_reports_definite_failure_when_no_request_is_triggered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = DouyinInteractionExecutor(settings)
    page = MagicMock()
    page.expect_response.return_value = _ExpectedResponse(AsyncMock())
    submit = AsyncMock()
    editor = AsyncMock()
    monkeypatch.setattr(
        executor, "_find_submit_control", AsyncMock(return_value=submit)
    )
    monkeypatch.setattr(
        executor, "_dispatch_comment_submit", AsyncMock(return_value=False)
    )

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            executor._fill_and_submit(
                page,
                editor,
                "测试评论",
                None,
                require_explicit_submit=True,
                require_comment_confirmation=True,
            )
        )

    assert captured.value.code == "submit_not_triggered"
    assert captured.value.retryable is True
    assert captured.value.ambiguous is False


@pytest.mark.parametrize(
    ("payload", "expected_platform_id"),
    [
        ({"status_code": 0}, None),
        ({"status_code": "0"}, None),
        ({"status_code": 0, "comment": {"cid": "cid-1"}}, "cid-1"),
        ({"status_code": 0, "comment": {"comment_id": "cid-2"}}, "cid-2"),
        ({"status_code": 0, "data": {"cid": "cid-3"}}, "cid-3"),
        ({"status_code": 0, "data": {"comment_id": "cid-4"}}, "cid-4"),
        (
            {"status_code": 0, "data": {"comment": {"cid": "cid-5"}}},
            "cid-5",
        ),
        ({"data": {"status_code": 0, "cid": "cid-6"}}, "cid-6"),
        ({"result": {"status_code": 0, "cid": "cid-7"}}, "cid-7"),
        (
            {"result": {"status_code": "0", "comment_id": "cid-8"}},
            "cid-8",
        ),
    ],
)
def test_ten_comment_publish_success_payloads(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
    expected_platform_id: str | None,
) -> None:
    executor = DouyinInteractionExecutor(settings)
    page = MagicMock()
    response = AsyncMock()
    response.ok = True
    response.json.return_value = payload
    page.expect_response.return_value = _ExpectedResponse(response)
    submit = AsyncMock()
    editor = AsyncMock()
    editor.input_value.return_value = "页面可能延迟清空"
    monkeypatch.setattr(
        executor, "_find_submit_control", AsyncMock(return_value=submit)
    )
    monkeypatch.setattr(
        executor, "_dispatch_comment_submit", AsyncMock(return_value=True)
    )
    wait_for_ui = AsyncMock()
    monkeypatch.setattr(executor, "_wait_comment_submission", wait_for_ui)

    result = asyncio.run(
        executor._fill_and_submit(
            page,
            editor,
            "测试评论",
            None,
            require_explicit_submit=True,
            require_comment_confirmation=True,
        )
    )

    assert result.platform_id == expected_platform_id
    wait_for_ui.assert_not_awaited()


def test_comment_submit_does_not_report_success_when_editor_stays_filled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = DouyinInteractionExecutor(settings)
    page = MagicMock()
    response = AsyncMock()
    response.ok = True
    page.expect_response.return_value = _ExpectedResponse(response)
    submit = AsyncMock()
    editor = AsyncMock()
    editor.count.return_value = 1
    editor.input_value.return_value = "测试评论"
    monkeypatch.setattr(
        executor, "_find_submit_control", AsyncMock(return_value=submit)
    )
    monkeypatch.setattr(
        executor, "_dispatch_comment_submit", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(executor, "_wait_comment_submission", AsyncMock())

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            executor._fill_and_submit(
                page,
                editor,
                "测试评论",
                None,
                require_explicit_submit=True,
                require_comment_confirmation=True,
            )
        )

    assert captured.value.code == "ambiguous_result"
    assert captured.value.ambiguous is True


def test_comment_submit_detects_platform_failure_toast() -> None:
    executor = DouyinInteractionExecutor(settings)
    failure = MagicMock()
    failure.count = AsyncMock(return_value=1)
    visible = AsyncMock()
    visible.is_visible.return_value = True
    failure.nth.return_value = visible
    empty = MagicMock()
    empty.count = AsyncMock(return_value=0)
    page = MagicMock()
    page.get_by_text.side_effect = lambda text, exact=False: (
        failure if text == "发布评论失败" else empty
    )

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            executor._wait_comment_submission(page, request_content="测试评论")
        )

    assert captured.value.code == "platform_rejected"
    assert "发布评论失败" in str(captured.value)


def test_comment_submit_rejects_http_200_business_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = DouyinInteractionExecutor(settings)
    page = MagicMock()
    response = AsyncMock()
    response.ok = True
    response.json.return_value = {"status_code": 8, "status_msg": "评论发送失败"}
    page.expect_response.return_value = _ExpectedResponse(response)
    submit = AsyncMock()
    editor = AsyncMock()
    monkeypatch.setattr(
        executor, "_find_submit_control", AsyncMock(return_value=submit)
    )
    monkeypatch.setattr(
        executor, "_dispatch_comment_submit", AsyncMock(return_value=True)
    )

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            executor._fill_and_submit(
                page,
                editor,
                "测试评论",
                None,
                require_explicit_submit=True,
                require_comment_confirmation=True,
            )
        )

    assert captured.value.code == "platform_rejected"
    assert "评论发送失败" in str(captured.value)


def test_comment_submit_detects_sms_verification() -> None:
    executor = DouyinInteractionExecutor(settings)
    challenge = MagicMock()
    challenge.count = AsyncMock(return_value=1)
    visible = AsyncMock()
    visible.is_visible.return_value = True
    challenge.nth.return_value = visible
    empty = MagicMock()
    empty.count = AsyncMock(return_value=0)
    page = MagicMock()
    page.get_by_text.side_effect = lambda text, exact=False: (
        challenge if text == "接收短信验证码" else empty
    )

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            executor._wait_comment_submission(page, request_content="测试评论")
        )

    assert captured.value.code == "risk_controlled"
    assert captured.value.affects_account_health is True
    assert "安全验证" in str(captured.value)


def test_comment_submit_timeout_reports_visible_sms_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = DouyinInteractionExecutor(settings)
    page = MagicMock()
    page.expect_response.return_value = _ExpectedResponse(AsyncMock())
    page.expect_response.return_value.__aexit__ = AsyncMock(
        side_effect=PlaywrightTimeoutError("timeout")
    )
    submit = AsyncMock()
    editor = AsyncMock()
    monkeypatch.setattr(
        executor, "_find_submit_control", AsyncMock(return_value=submit)
    )
    monkeypatch.setattr(
        executor, "_dispatch_comment_submit", AsyncMock(return_value=True)
    )
    async def visible_message(
        _page: object, messages: tuple[str, ...]
    ) -> str | None:
        return "接收短信验证码" if messages == executor.comment_risk_messages else None

    monkeypatch.setattr(executor, "_visible_page_message", visible_message)

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            executor._fill_and_submit(
                page,
                editor,
                "测试评论",
                None,
                require_explicit_submit=True,
                require_comment_confirmation=True,
            )
        )

    assert captured.value.code == "risk_controlled"
    assert captured.value.ambiguous is False


def test_comment_submit_requires_a_clickable_send_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = DouyinInteractionExecutor(settings)
    page = AsyncMock()
    editor = AsyncMock()
    monkeypatch.setattr(
        executor, "_find_submit_control", AsyncMock(return_value=None)
    )

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            executor._fill_and_submit(
                page,
                editor,
                "测试评论",
                None,
                require_explicit_submit=True,
                require_comment_confirmation=True,
            )
        )

    assert captured.value.code == "submit_not_available"
    assert captured.value.retryable is True


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


def test_interaction_pages_exclude_unrelated_manual_tabs() -> None:
    target = MagicMock()
    target.is_closed.return_value = False
    target.url = "https://www.douyin.com/video/123"
    manual = MagicMock()
    manual.is_closed.return_value = False
    manual.url = "https://www.douyin.com/video/456"
    target.context.pages = [manual, target]

    assert DouyinInteractionExecutor._interaction_pages(
        target, aweme_id="123"
    ) == [target]


def test_comment_scroller_uses_internal_route_container() -> None:
    page = MagicMock()
    comment_list = AsyncMock()
    comment_list.count.return_value = 1
    comment_list.evaluate.return_value = True
    page.locator.return_value.first = comment_list

    result = asyncio.run(DouyinInteractionExecutor._scroll_comment_list(page))

    assert result is True
    comment_list.evaluate.assert_awaited_once()
    page.mouse.wheel.assert_not_called()


def test_video_comment_records_meaningful_browser_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = DouyinInteractionExecutor(settings)
    page = MagicMock()
    page.url = "https://www.douyin.com/video/123"
    page.is_closed.return_value = False
    editor = AsyncMock()
    callback = AsyncMock()
    monkeypatch.setattr(executor, "_open_video", AsyncMock())
    monkeypatch.setattr(
        executor, "_open_comment_panel", AsyncMock(return_value=(page, editor))
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
    submit.assert_awaited_once_with(
        page,
        editor,
        "测试评论",
        callback,
        require_explicit_submit=True,
        require_comment_confirmation=True,
        expected_aweme_id="123",
    )


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
