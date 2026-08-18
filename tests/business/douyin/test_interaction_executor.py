"""抖音互动执行器（DouyinInteractionExecutor）的测试：覆盖浏览器连接输入兼容、评论面板/回复编辑器定位、发布请求核验、风控与歧义结果分类、页面加载重试等浏览器自动化细节。"""

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints
from unittest.mock import AsyncMock, MagicMock

import pytest
from crawler.bootstrap.settings import settings
from crawler.business.douyin.interactions.models import DouyinInteractionType
from crawler.douyin_client.interactions import (
    DouyinInteractionExecutor,
    InteractionBrowserConnection,
    InteractionExecutionError,
    InteractionExecutionRequest,
    InteractionExecutionResult,
)
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


class _ExpectedResponse:
    """模拟 playwright expect_response 上下文管理器：value 为可等待的响应。"""

    def __init__(self, response: AsyncMock) -> None:
        """以预置响应初始化。"""
        self.response = response

    @property
    def value(self):  # type: ignore[no-untyped-def]
        """返回一个可 await 出预置响应的协程。"""

        async def resolve() -> AsyncMock:
            return self.response

        return resolve()

    async def __aenter__(self) -> "_ExpectedResponse":
        """进入异步上下文，返回自身。"""
        return self

    async def __aexit__(self, *_args: object) -> None:
        """退出异步上下文（空实现）。"""
        return None


def test_executor_boundary_supports_neutral_and_legacy_inputs() -> None:
    """验证执行器边界同时支持中立连接描述与旧版账号对象输入，旧账号能正确换算为连接参数。"""
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
    """验证 execute 对旧版账号与中立连接两种入参都能换算出正确的浏览器会话参数。"""
    captured: list[dict[str, object]] = []

    class FakeBrowserSession:
        """模拟浏览器会话：记录构造参数，页面/上下文均为空。"""

        page = None
        context = None

        def __init__(self, *_args: object, **kwargs: object) -> None:
            """记录构造关键字参数。"""
            captured.append(kwargs)

        async def __aenter__(self) -> "FakeBrowserSession":
            """进入异步上下文，返回自身。"""
            return self

        async def __aexit__(self, *_args: object) -> None:
            """退出异步上下文（空实现）。"""
            return None

    monkeypatch.setattr(
        "crawler.douyin_client.interactions.CDPBrowserSession", FakeBrowserSession
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
    """验证打开评论面板时能通过真实抖音占位容器选择器激活出编辑器。"""
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
    """验证 dispatch_event 点击未能展开编辑器时回退为真实鼠标点击。"""
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
    """验证图文笔记页打开评论面板时会先激活评论 Tab 再定位编辑器。"""
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
    """验证发送按钮查找优先使用真实抖音页面的箭头图标选择器。"""
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
    """验证评论相关选择器集合覆盖图文笔记页的类容器写法（编辑器/发送按钮/评论 Tab）。"""
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
    """验证私信发送按钮选择器覆盖真实抖音页面的两种箭头图标。"""
    executor = DouyinInteractionExecutor(settings)

    assert "svg.e2e-send-msg-btn" in executor.message_submit_selectors
    assert "svg.messageMsgInputpublishRedBtn" in executor.message_submit_selectors


def test_open_reply_editor_walks_to_card_and_verifies_reply_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证打开回复编辑器会向上回溯到评论卡片、点击可见回复按钮并核验回复上下文已激活。"""
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
    """验证匹配到多个可见回复按钮（歧义）时不做任何点击，直接返回空上下文与空编辑器。"""
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
    """验证回复上下文激活判断兼容旧版 data-cid 属性标识的评论卡片。"""
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
    """验证一级评论回复的发布请求必须携带与确认目标一致的 reply_id。"""
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
    """验证二级评论回复的发布请求必须同时携带父评论 reply_id 与目标 reply_to_reply_id。"""
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
    """验证评论发布响应识别覆盖当前抖音多种发布端点 URL 变体。"""
    response = MagicMock()
    response.url = url
    response.request.method = "POST"
    response.request.url = url

    assert DouyinInteractionExecutor._is_comment_publish_response(response) is True


def test_comment_publish_response_rejects_reads_and_list_requests() -> None:
    """验证评论列表等只读请求不会被误判为发布响应。"""
    response = MagicMock()
    response.url = "https://www.douyin.com/aweme/v1/web/comment/list/"
    response.request.method = "GET"

    assert DouyinInteractionExecutor._is_comment_publish_response(response) is False


def test_comment_submit_falls_back_to_component_activation_when_click_is_lost() -> None:
    """验证组件事件点击未触发发布请求时回退为真实点击，仍未触发则返回 False 并移除请求监听器。"""
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
    """验证组件事件已触发发布请求后不再执行真实点击（避免重复提交）。"""
    page = MagicMock()
    control = AsyncMock()
    callback: object | None = None

    def register(_event: str, request_callback: object) -> None:
        """注册请求事件回调到闭包变量。"""
        nonlocal callback
        callback = request_callback

    async def click_control(*_args: object, **_kwargs: object) -> None:
        """模拟点击控件时同步发出评论发布请求。"""
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
    """验证组件事件与元素点击均未触发发布时，最终回退为按包围盒中心的真实鼠标点击。"""
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
        """注册请求事件回调到闭包变量。"""
        nonlocal callback
        callback = request_callback

    async def click_mouse(_x: float, _y: float) -> None:
        """模拟鼠标点击时同步发出评论发布请求。"""
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
    """验证私信作者流程会等待主页加载、定位私信入口与编辑器，并以显式提交方式发送。"""
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
    """验证私信作者流程在页面控件加载不出来时报告可重试的 page_load_timeout。"""
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
    """验证评论提交成功需同时满足发布请求被触发且编辑器被清空两个条件。"""
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
    """验证点击完全未触发发布请求时报告可重试的确定性失败 submit_not_triggered（非歧义）。"""
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
    """验证抖音评论发布成功响应的多种嵌套形态都能正确解析出平台评论 id。

    参数：
        payload: 模拟的发布接口 JSON 响应体。
        expected_platform_id: 期望解析出的平台评论 id，None 表示未返回。
    """
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
    """验证发布请求后编辑器仍残留内容时不报成功，而是标记为歧义结果等待人工核对。"""
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
    """验证页面出现「发布评论失败」提示时被识别为平台拒绝（platform_rejected）。"""
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
    """验证 HTTP 200 但业务状态码非 0 的响应被识别为平台拒绝并携带平台错误文案。"""
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
    """验证页面出现短信验证码安全验证时被识别为风控（risk_controlled）并标记影响账号健康。"""
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
    """验证等待发布响应超时后，若页面可见短信验证提示则归类为风控（非歧义）。"""
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
        """模拟页面可见文案探测：仅当查询的是风控文案集合时返回短信验证提示。"""
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
    """验证找不到可点击的发送按钮时报可重试的 submit_not_available。"""
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
    """验证可见元素查找会跳过隐藏的重复节点，返回真正可见的那个。"""
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
    """验证互动页面集合仅包含目标作品页，排除用户手工打开的其他作品标签页。"""
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
    """验证评论列表滚动优先使用可见的内部路由容器（JS 滚动而非鼠标滚轮）。"""
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
    """验证找不到路由容器时回退为在可见评论条目上向上查找可滚动祖先执行 JS 滚动。"""
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
    """验证评论区域定位在容器选择器未命中时回退到可见评论条目选择器。"""
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
    """验证按文本定位目标评论时跳过隐藏的重复文本节点，返回可见节点。"""
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
    """验证目标评论定位优先使用 tooltip 中稳定的评论 id（不依赖可能过期的评论文本）。"""
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
    """验证在线目标评论查询能区分「存在」（翻页找到）与「不可用」（翻到底仍无）两种结论。"""
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
    """验证二级评论的在线查询使用父评论 id 调用子评论分页接口。"""
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
    """验证评论接口返回异常载荷（错误码/缺字段/类型不符）时结论为 inconclusive，保持可重试。

    参数：
        payload: 模拟的评论分页接口异常响应体。
    """
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
    """验证回复评论时按在线目标状态分类错误：不可用为终态、DOM 未找到与查询不确定均可重试。

    参数：
        target_state: 模拟的在线目标查询结论。
        expected_code: 期望的错误码。
        expected_retryable: 期望的可重试标记。
    """
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
    """验证回复提交时携带已确认的回复上下文与目标/父评论 id，确保发布到正确评论下。"""
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
    """验证视频评论流程按序记录关键浏览器步骤（打开视频、编辑器就绪）并以显式提交执行。"""
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
    """验证打开视频页后等待页面就绪脚本通过（真正可交互）而非仅等待导航完成。"""
    executor = DouyinInteractionExecutor(settings)
    page = AsyncMock()

    asyncio.run(executor._open_video(page, "123"))

    page.goto.assert_awaited_once()
    page.wait_for_function.assert_awaited_once_with(
        executor.video_page_ready_script,
        timeout=settings.DOUYIN_INTERACTION_PAGE_READY_TIMEOUT_SECONDS * 1000,
    )


def test_open_video_reports_page_load_timeout() -> None:
    """验证视频页持续加载不出来时按配置次数重试后报告可重试的 page_load_timeout。"""
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
    """验证页面卡在加载壳时通过 about:blank 重置导航后恢复加载。"""
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
    """验证瞬时导航错误（如临时 SSL 错误）会重试一次后成功。"""
    executor = DouyinInteractionExecutor(settings)
    page = AsyncMock()
    page.goto.side_effect = [PlaywrightError("temporary ssl error"), None]

    asyncio.run(executor._open_video(page, "123"))

    assert page.goto.await_count == 2
    page.wait_for_timeout.assert_awaited_once_with(1_000)
    page.wait_for_function.assert_awaited_once()
