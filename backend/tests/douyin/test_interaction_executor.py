import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints
from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.bootstrap.settings import settings
from app.domain.douyin.interactions.models import DouyinInteractionType
from app.integrations.douyin.interactions import (
    DouyinInteractionExecutor,
    InteractionBrowserConnection,
    InteractionExecutionError,
    InteractionExecutionRequest,
    InteractionExecutionResult,
)


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


def test_executor_boundary_supports_neutral_and_legacy_inputs() -> None:
    connection = InteractionBrowserConnection(
        browser_mode="local",
        user_data_dir=Path("profile"),
        debug_port=9222,
    )
    request = InteractionExecutionRequest(
        interaction_type=DouyinInteractionType.video_comment,
        aweme_id="123",
        content="测试评论",
    )
    parameters = inspect.signature(DouyinInteractionExecutor.execute).parameters

    assert get_type_hints(InteractionExecutionRequest)["interaction_type"] is str
    assert connection.browser_mode == "local"
    assert request.interaction_type == "video_comment"
    assert "connection" in parameters
    assert "account" in parameters

    account_id = SimpleNamespace(int=503)
    account = SimpleNamespace(
        id=account_id,
        browser_mode="local",
        profile_key="legacy-profile",
        remote_slot=None,
    )
    legacy_connection = DouyinInteractionExecutor(
        settings
    )._connection_from_legacy_account(account)
    assert legacy_connection.browser_mode == "local"
    assert legacy_connection.user_data_dir == (
        settings.DOUYIN_CDP_USER_DATA_DIR.resolve().parent
        / "accounts"
        / "legacy-profile"
    )
    assert legacy_connection.debug_port == settings.DOUYIN_CDP_PORT + 3


def test_executor_execute_accepts_both_legacy_account_and_neutral_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []

    class FakeBrowserSession:
        page = None
        context = None

        def __init__(self, *_args: object, **kwargs: object) -> None:
            captured.append(kwargs)

        async def __aenter__(self) -> "FakeBrowserSession":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(
        "app.integrations.douyin.interactions.CDPBrowserSession", FakeBrowserSession
    )
    account = SimpleNamespace(
        id=SimpleNamespace(int=503),
        browser_mode="local",
        profile_key="legacy-profile",
        remote_slot=None,
    )
    connection = InteractionBrowserConnection(
        browser_mode="remote",
        remote_host="browser.example.test",
        remote_port=9222,
    )
    request = InteractionExecutionRequest(
        interaction_type="video_comment",
        aweme_id="123",
        content="兼容调用",
    )
    executor = DouyinInteractionExecutor(settings)

    for input_values in ({"account": account}, {"connection": connection}):
        with pytest.raises(InteractionExecutionError) as exc_info:
            asyncio.run(executor.execute(request=request, **input_values))
        assert exc_info.value.code == "browser_unavailable"

    assert captured[0]["browser_mode"] == "local"
    assert captured[0]["debug_port"] == settings.DOUYIN_CDP_PORT + 3
    assert captured[1]["browser_mode"] == "remote"
    assert captured[1]["remote_host"] == "browser.example.test"


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
        DouyinInteractionExecutor._find_submit_control(AsyncMock(), AsyncMock())
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


def test_message_submit_selectors_cover_real_douyin_arrow() -> None:
    executor = DouyinInteractionExecutor(settings)

    assert "svg.e2e-send-msg-btn" in executor.message_submit_selectors
    assert "svg.messageMsgInputpublishRedBtn" in executor.message_submit_selectors


def test_open_reply_editor_walks_to_card_and_verifies_reply_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = DouyinInteractionExecutor(settings)
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
    comment_card = MagicMock()
    comment_card.count = AsyncMock(return_value=1)
    comment_card.is_visible = AsyncMock(return_value=True)
    nodes[0].locator.side_effect = lambda selector: (
        comment_card if "ancestor-or-self" in selector else nodes[1]
    )
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    editor = AsyncMock()
    monkeypatch.setattr(executor, "_find_visible", AsyncMock(return_value=editor))
    monkeypatch.setattr(
        executor, "_reply_context_is_active", AsyncMock(return_value=True)
    )
    request = InteractionExecutionRequest(
        interaction_type=DouyinInteractionType.comment_reply,
        aweme_id="123",
        content="测试回复",
        target_comment_id="456",
        target_comment_content="目标评论",
    )

    context, result = asyncio.run(executor._open_reply_editor(page, nodes[0], request))

    assert context is comment_card
    assert result is editor
    reply_controls[10].dispatch_event.assert_awaited_once_with("click")


def test_open_reply_editor_stops_before_ambiguous_comment_list() -> None:
    executor = DouyinInteractionExecutor(settings)
    target = MagicMock()
    comment_card = MagicMock()
    comment_card.count = AsyncMock(return_value=1)
    comment_card.is_visible = AsyncMock(return_value=True)
    target.locator.return_value = comment_card
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
    request = InteractionExecutionRequest(
        interaction_type=DouyinInteractionType.comment_reply,
        aweme_id="123",
        content="测试回复",
        target_comment_id="456",
        target_comment_content="目标评论",
    )

    context, editor = asyncio.run(
        executor._open_reply_editor(AsyncMock(), target, request)
    )

    assert context is None
    assert editor is None
    first.dispatch_event.assert_not_awaited()
    second.dispatch_event.assert_not_awaited()


def test_reply_context_accepts_legacy_comment_id_attribute() -> None:
    comment_card = MagicMock()
    comment_card.get_attribute = AsyncMock(
        side_effect=lambda attribute: "456" if attribute == "data-cid" else None
    )
    empty = MagicMock()
    empty.count = AsyncMock(return_value=0)
    comment_card.locator.return_value = empty
    active = MagicMock()
    active.count = AsyncMock(return_value=1)
    active_node = AsyncMock()
    active_node.is_visible.return_value = True
    active.nth.return_value = active_node
    comment_card.get_by_text.return_value = active

    assert (
        asyncio.run(
            DouyinInteractionExecutor._reply_context_is_active(comment_card, "456")
        )
        is True
    )


def test_reply_publish_request_must_target_confirmed_top_level_comment() -> None:
    request = MagicMock()
    request.post_data = "aweme_id=123&text=reply&reply_id=456&reply_to_reply_id=0"

    assert (
        DouyinInteractionExecutor._request_targets_reply(
            request,
            target_comment_id="456",
            parent_comment_id="0",
        )
        is True
    )
    assert (
        DouyinInteractionExecutor._request_targets_reply(
            request,
            target_comment_id="789",
            parent_comment_id="0",
        )
        is False
    )


def test_reply_publish_request_must_target_confirmed_sub_comment() -> None:
    request = MagicMock()
    request.post_data = "reply_id=parent-1&reply_to_reply_id=child-2"

    assert (
        DouyinInteractionExecutor._request_targets_reply(
            request,
            target_comment_id="child-2",
            parent_comment_id="parent-1",
        )
        is True
    )


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
        asyncio.run(executor._wait_comment_submission(page, request_content="测试评论"))

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
        asyncio.run(executor._wait_comment_submission(page, request_content="测试评论"))

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

    async def visible_message(_page: object, messages: tuple[str, ...]) -> str | None:
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
    monkeypatch.setattr(executor, "_find_submit_control", AsyncMock(return_value=None))

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

    assert DouyinInteractionExecutor._interaction_pages(target, aweme_id="123") == [
        target
    ]


def test_comment_scroller_uses_visible_internal_route_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = MagicMock()
    comment_list = AsyncMock()
    comment_list.evaluate.return_value = True
    find_visible = AsyncMock(return_value=comment_list)
    monkeypatch.setattr(DouyinInteractionExecutor, "_find_visible", find_visible)

    result = asyncio.run(DouyinInteractionExecutor._scroll_comment_list(page))

    assert result is True
    comment_list.evaluate.assert_awaited_once()
    assert "let node = element" in comment_list.evaluate.await_args.args[0]
    page.mouse.wheel.assert_not_called()


def test_comment_scroller_falls_back_to_visible_comment_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = MagicMock()
    comment_item = AsyncMock()
    comment_item.evaluate.return_value = True
    find_visible = AsyncMock(side_effect=[None, comment_item])
    monkeypatch.setattr(DouyinInteractionExecutor, "_find_visible", find_visible)

    result = asyncio.run(DouyinInteractionExecutor._scroll_comment_list(page))

    assert result is True
    comment_item.evaluate.assert_awaited_once()
    assert (
        "node.scrollTo(0, node.scrollHeight)"
        in (comment_item.evaluate.await_args.args[0])
    )
    page.mouse.wheel.assert_not_called()


def test_comment_surface_falls_back_to_visible_comment_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = DouyinInteractionExecutor(settings)
    comment_item = AsyncMock()
    find_visible = AsyncMock(side_effect=[None, comment_item])
    monkeypatch.setattr(executor, "_find_visible", find_visible)

    result = asyncio.run(
        executor._find_visible_comment_surface(MagicMock(), timeout=300)
    )

    assert result is comment_item
    assert find_visible.await_args_list[1].args[1] == executor.comment_item_selectors


def test_find_comment_target_skips_hidden_duplicate_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    comment_list = MagicMock()
    tooltip = MagicMock()
    empty = MagicMock()
    empty.count = AsyncMock(return_value=0)
    tooltip.locator.return_value = empty
    comment_list.locator.side_effect = lambda selector: (
        tooltip if selector.startswith('[id="tooltip_') else empty
    )
    hidden = AsyncMock()
    hidden.is_visible.return_value = False
    visible = AsyncMock()
    visible.is_visible.return_value = True
    text_matches = MagicMock()
    text_matches.count = AsyncMock(return_value=2)
    text_matches.nth.side_effect = [hidden, visible]
    comment_list.get_by_text.return_value = text_matches
    monkeypatch.setattr(
        DouyinInteractionExecutor,
        "_find_visible",
        AsyncMock(return_value=comment_list),
    )
    page = MagicMock()
    request = InteractionExecutionRequest(
        interaction_type=DouyinInteractionType.comment_reply,
        aweme_id="123",
        content="回复",
        target_comment_id="456",
        target_comment_content="重复评论文本",
    )

    result = asyncio.run(DouyinInteractionExecutor._find_comment_target(page, request))

    assert result is visible


def test_find_comment_target_prefers_stable_tooltip_comment_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    comment_list = MagicMock()
    tooltip = MagicMock()
    card = MagicMock()
    card.count = AsyncMock(return_value=1)
    visible_card = MagicMock()
    visible_card.is_visible = AsyncMock(return_value=True)
    card.nth.return_value = visible_card
    tooltip.locator.return_value = card
    empty = MagicMock()
    empty.count = AsyncMock(return_value=0)
    comment_list.locator.side_effect = lambda selector: (
        tooltip if selector.startswith('[id="tooltip_') else empty
    )
    comment_list.get_by_text.return_value = empty
    monkeypatch.setattr(
        DouyinInteractionExecutor,
        "_find_visible",
        AsyncMock(return_value=comment_list),
    )
    request = InteractionExecutionRequest(
        interaction_type=DouyinInteractionType.comment_reply,
        aweme_id="123",
        content="回复",
        target_comment_id="456",
        target_comment_content="数据库里的旧文本",
    )

    result = asyncio.run(
        DouyinInteractionExecutor._find_comment_target(MagicMock(), request)
    )

    assert result is visible_card


def test_live_target_lookup_distinguishes_present_and_unavailable() -> None:
    request = InteractionExecutionRequest(
        interaction_type=DouyinInteractionType.comment_reply,
        aweme_id="123",
        content="回复",
        target_comment_id="target-2",
        target_comment_content="目标",
    )
    present_client = AsyncMock()
    present_client.get_comments_page.side_effect = [
        {
            "status_code": 0,
            "comments": [{"cid": "other"}],
            "has_more": 1,
            "cursor": 20,
        },
        {
            "status_code": 0,
            "comments": [{"cid": "target-2"}],
            "has_more": 0,
            "cursor": 40,
        },
    ]
    unavailable_client = AsyncMock()
    unavailable_client.get_comments_page.return_value = {
        "status_code": 0,
        "comments": [{"cid": "other"}],
        "has_more": 0,
        "cursor": 20,
    }

    assert (
        asyncio.run(
            DouyinInteractionExecutor._lookup_target_comment(present_client, request)
        )
        == "present"
    )
    assert (
        asyncio.run(
            DouyinInteractionExecutor._lookup_target_comment(
                unavailable_client, request
            )
        )
        == "unavailable"
    )


def test_live_sub_comment_lookup_uses_parent_comment_id() -> None:
    request = InteractionExecutionRequest(
        interaction_type=DouyinInteractionType.comment_reply,
        aweme_id="123",
        content="回复",
        target_comment_id="child-2",
        target_comment_content="目标",
        target_parent_comment_id="parent-1",
    )
    client = AsyncMock()
    client.get_sub_comments_page.return_value = {
        "status_code": 0,
        "comments": [{"cid": "child-2"}],
        "has_more": 0,
        "cursor": 10,
    }

    assert (
        asyncio.run(DouyinInteractionExecutor._lookup_target_comment(client, request))
        == "present"
    )
    client.get_sub_comments_page.assert_awaited_once_with("123", "parent-1", 0)


@pytest.mark.parametrize(
    "payload",
    [
        {"status_code": 8, "comments": [], "has_more": 0},
        {"status_code": 0, "comments": []},
        {"status_code": 0, "has_more": 0},
        {"status_code": 0, "comments": None, "has_more": 0},
        {"status_code": 0, "comments": [], "has_more": "unknown"},
    ],
)
def test_live_target_lookup_keeps_invalid_api_responses_retryable(
    payload: dict[str, object],
) -> None:
    request = InteractionExecutionRequest(
        interaction_type=DouyinInteractionType.comment_reply,
        aweme_id="123",
        content="回复",
        target_comment_id="target-2",
        target_comment_content="目标",
    )
    client = AsyncMock()
    client.get_comments_page.return_value = payload

    assert (
        asyncio.run(DouyinInteractionExecutor._lookup_target_comment(client, request))
        == "inconclusive"
    )


@pytest.mark.parametrize(
    ("target_state", "expected_code", "expected_retryable"),
    [
        ("unavailable", "target_unavailable", False),
        ("present", "target_dom_not_found", True),
        ("inconclusive", "target_lookup_inconclusive", True),
    ],
)
def test_reply_to_comment_classifies_live_target_state(
    monkeypatch: pytest.MonkeyPatch,
    target_state: str,
    expected_code: str,
    expected_retryable: bool,
) -> None:
    executor = DouyinInteractionExecutor(settings)
    page = MagicMock()
    page.url = "https://www.douyin.com/video/123"
    page.is_closed.return_value = False
    comment_editor = AsyncMock()
    monkeypatch.setattr(executor, "_open_video", AsyncMock())
    monkeypatch.setattr(
        executor,
        "_open_comment_panel",
        AsyncMock(return_value=(page, comment_editor)),
    )
    monkeypatch.setattr(
        executor, "_ensure_comment_list_active", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(executor, "_find_comment_target", AsyncMock(return_value=None))
    monkeypatch.setattr(
        executor, "_lookup_target_comment", AsyncMock(return_value=target_state)
    )
    monkeypatch.setattr(executor, "_trace", AsyncMock())
    request = InteractionExecutionRequest(
        interaction_type=DouyinInteractionType.comment_reply,
        aweme_id="123",
        content="回复",
        target_comment_id="target-2",
        target_comment_content="目标",
    )

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(executor._reply_to_comment(page, AsyncMock(), request, AsyncMock()))

    assert captured.value.code == expected_code
    assert captured.value.retryable is expected_retryable


def test_reply_to_comment_submits_only_with_confirmed_reply_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = DouyinInteractionExecutor(settings)
    page = MagicMock()
    page.url = "https://www.douyin.com/video/123"
    page.is_closed.return_value = False
    comment_editor = AsyncMock()
    target = MagicMock()
    reply_context = MagicMock()
    reply_editor = AsyncMock()
    result = InteractionExecutionResult(platform_id="reply-cid")
    submit = AsyncMock(return_value=result)
    monkeypatch.setattr(executor, "_open_video", AsyncMock())
    monkeypatch.setattr(
        executor,
        "_open_comment_panel",
        AsyncMock(return_value=(page, comment_editor)),
    )
    monkeypatch.setattr(
        executor, "_ensure_comment_list_active", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        executor, "_find_comment_target", AsyncMock(return_value=target)
    )
    monkeypatch.setattr(
        executor,
        "_open_reply_editor",
        AsyncMock(return_value=(reply_context, reply_editor)),
    )
    monkeypatch.setattr(executor, "_fill_and_submit", submit)
    monkeypatch.setattr(executor, "_trace", AsyncMock())
    request = InteractionExecutionRequest(
        interaction_type=DouyinInteractionType.comment_reply,
        aweme_id="123",
        content="回复",
        target_comment_id="child-2",
        target_comment_content="目标",
        target_parent_comment_id="parent-1",
    )

    actual = asyncio.run(
        executor._reply_to_comment(page, AsyncMock(), request, AsyncMock())
    )

    assert actual is result
    assert submit.await_args.kwargs["expected_reply_context"] is reply_context
    assert submit.await_args.kwargs["expected_reply_comment_id"] == "child-2"
    assert submit.await_args.kwargs["expected_parent_comment_id"] == "parent-1"


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
