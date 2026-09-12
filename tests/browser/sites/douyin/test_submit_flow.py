"""互动填写与提交确认测试（``SubmitFlow``）。

覆盖两条提交路径：需平台确认的评论发布（``require_comment_confirmation``）与
只需触发响应标记的私信发送；以及提交前的上下文校验（作品页/回复状态）、
发送控件缺失、平台拒绝/风控/歧义结果的分类，与 ``wait_comment_submission``
的 UI 层面判定。
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from crawler.browser.errors import InteractionExecutionError
from crawler.browser.interactions.comment_locator import CommentLocator
from crawler.browser.interactions.page_controller import PageController
from crawler.browser.interactions.selectors import (
    COMMENT_FAILURE_MESSAGES,
    COMMENT_RISK_MESSAGES,
    COMMENT_SUCCESS_MESSAGES,
)
from crawler.browser.interactions.submit_flow import SubmitFlow
from crawler.browser.page import primitives as dom
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


class _ExpectedResponse:
    """模拟 ``page.expect_response`` 的异步上下文：``value`` 为可等待的响应。"""

    def __init__(self, response: AsyncMock) -> None:
        """以预置响应初始化。"""
        self.response = response

    @property
    def value(self) -> Any:
        """返回一个可 await 出预置响应的协程。"""

        async def resolve() -> AsyncMock:
            """解析出预置响应。"""
            return self.response

        return resolve()

    async def __aenter__(self) -> "_ExpectedResponse":
        """进入异步上下文。"""
        return self

    async def __aexit__(self, *_args: object) -> None:
        """正常退出（不抑制上下文内的异常）。"""
        return None


class _TimeoutResponse:
    """模拟 ``expect_response`` 等待超时：退出上下文时抛 Playwright 超时。"""

    async def __aenter__(self) -> "_TimeoutResponse":
        """进入异步上下文。"""
        return self

    async def __aexit__(self, *_args: object) -> None:
        """退出时抛超时（与真实 ``expect_response`` 行为一致）。"""
        raise PlaywrightTimeoutError("等待发布响应超时")

    @property
    def value(self) -> Any:  # pragma: no cover - 超时路径不会读取响应
        """超时路径不应读取响应。"""
        raise AssertionError("超时路径不应读取 response_info.value")


class _RaisingResponse:
    """模拟 ``expect_response`` 上下文在退出时抛非超时异常。"""

    def __init__(self, error: Exception) -> None:
        """以预置异常初始化。"""
        self.error = error

    async def __aenter__(self) -> "_RaisingResponse":
        """进入异步上下文。"""
        return self

    async def __aexit__(self, *_args: object) -> None:
        """退出时抛出预置异常。"""
        raise self.error


def _make_response(
    *,
    ok: bool = True,
    status: int = 200,
    payload: dict[str, Any] | None = None,
    post_data: str = "",
) -> AsyncMock:
    """构造一个抖音发布响应替身。"""
    response = AsyncMock()
    response.ok = ok
    response.status = status
    response.json.return_value = payload if payload is not None else {}
    response.request = MagicMock()
    response.request.post_data = post_data
    return response


def _page_with_response(response: AsyncMock) -> MagicMock:
    """构造一个 ``expect_response`` 立即给出预置响应的页面。"""
    page = MagicMock()
    page.expect_response.return_value = _ExpectedResponse(response)
    return page


def _message_probe(
    *,
    success: str | None = None,
    risk: str | None = None,
    failure: str | None = None,
) -> AsyncMock:
    """构造 ``visible_page_message`` 替身：按被查询的文案集合返回预置命中。"""
    table = {
        COMMENT_SUCCESS_MESSAGES: success,
        COMMENT_RISK_MESSAGES: risk,
        COMMENT_FAILURE_MESSAGES: failure,
    }

    async def probe(_page: object, messages: tuple[str, ...]) -> str | None:
        """按消息集合返回预置命中文案。"""
        return table.get(messages)

    return AsyncMock(side_effect=probe)


def _stub_submit_control(
    monkeypatch: pytest.MonkeyPatch,
    *,
    submit: object = None,
    dispatch: bool = True,
) -> AsyncMock:
    """替换发送控件查找与评论提交触发，返回 ``find_submit_control`` 替身。"""
    find = AsyncMock(return_value=submit)
    monkeypatch.setattr(PageController, "find_submit_control", find)
    monkeypatch.setattr(
        PageController, "dispatch_comment_submit", AsyncMock(return_value=dispatch)
    )
    return find


# ---- 填写与发送控件 ----


def test_fill_and_submit_fills_then_clicks_the_send_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """私信路径：填写内容后点击发送控件，并按序上报三个步骤。"""
    page = _page_with_response(
        _make_response(payload={"status_code": 0, "comment": {"cid": "cid-1"}})
    )
    editor = AsyncMock()
    submit = AsyncMock()
    callback = AsyncMock()
    _stub_submit_control(monkeypatch, submit=submit)

    result = asyncio.run(
        SubmitFlow.fill_and_submit(
            page, editor, "测试内容", callback, require_explicit_submit=True
        )
    )

    assert result.platform_id == "cid-1"
    editor.click.assert_awaited_once_with()
    editor.fill.assert_awaited_once_with("测试内容")
    submit.scroll_into_view_if_needed.assert_awaited_once()
    submit.click.assert_awaited_once_with(timeout=5_000)
    assert [call.args[1] for call in callback.await_args_list] == [
        "content_filled",
        "submit_triggered",
        "platform_accepted",
    ]
    page.expect_response.assert_called_once()


def test_fill_and_submit_uses_keyboard_shortcut_without_explicit_submit_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """找不到发送控件且不强制显式提交时，回退为 Ctrl+Enter 快捷键。"""
    page = _page_with_response(_make_response(payload={"status_code": 0}))
    editor = AsyncMock()
    _stub_submit_control(monkeypatch, submit=None)

    result = asyncio.run(SubmitFlow.fill_and_submit(page, editor, "测试内容", None))

    assert result.platform_id is None
    editor.press.assert_awaited_once_with("Control+Enter")


def test_fill_and_submit_requires_a_clickable_send_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """强制显式提交但找不到发送控件时报可重试的 submit_not_available。"""
    page = MagicMock()
    editor = AsyncMock()
    _stub_submit_control(monkeypatch, submit=None)

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.fill_and_submit(
                page, editor, "测试内容", None, require_explicit_submit=True
            )
        )

    assert captured.value.code == "submit_not_available"
    assert captured.value.retryable is True


def test_fill_and_submit_reports_an_unusable_editor() -> None:
    """输入框不可点击/不可填写时报可重试的 editor_unavailable。"""
    page = MagicMock()
    editor = AsyncMock()
    editor.click.side_effect = RuntimeError("detached from DOM")

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(SubmitFlow.fill_and_submit(page, editor, "测试内容", None))

    assert captured.value.code == "editor_unavailable"
    assert captured.value.retryable is True
    editor.fill.assert_not_awaited()


# ---- 提交前上下文校验 ----


def test_fill_and_submit_aborts_when_the_reply_context_is_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """回复状态在发送前丢失时停止发送，且不再去找发送控件。"""
    page = MagicMock()
    editor = AsyncMock()
    find = _stub_submit_control(monkeypatch, submit=AsyncMock())
    monkeypatch.setattr(
        CommentLocator, "reply_context_is_active", AsyncMock(return_value=False)
    )

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.fill_and_submit(
                page,
                editor,
                "回复内容",
                None,
                require_explicit_submit=True,
                expected_reply_context=MagicMock(),
                expected_reply_comment_id="child-2",
            )
        )

    assert captured.value.code == "reply_context_lost"
    assert captured.value.retryable is True
    find.assert_not_awaited()


def test_fill_and_submit_aborts_when_the_page_left_the_target_video() -> None:
    """页面已离开目标作品页时安全终止发送（page_interrupted）。"""
    page = MagicMock()
    page.is_closed.return_value = False
    page.url = "https://www.douyin.com/"
    editor = AsyncMock()

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.fill_and_submit(
                page, editor, "测试内容", None, expected_aweme_id="123"
            )
        )

    assert captured.value.code == "page_interrupted"
    assert captured.value.retryable is True


def test_reply_submit_is_accepted_only_when_the_request_targets_the_comment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """回复请求确实绑定到目标评论时才提交成功（正向分支）。"""
    page = _page_with_response(
        _make_response(
            payload={"status_code": 0, "comment": {"cid": "reply-cid"}},
            post_data="reply_id=child-2&reply_to_reply_id=0",
        )
    )
    editor = AsyncMock()
    _stub_submit_control(monkeypatch, submit=AsyncMock())

    result = asyncio.run(
        SubmitFlow.fill_and_submit(
            page,
            editor,
            "回复内容",
            None,
            require_explicit_submit=True,
            require_comment_confirmation=True,
            expected_reply_comment_id="child-2",
        )
    )

    assert result.platform_id == "reply-cid"


def test_reply_submit_binds_to_the_wrong_comment_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """发布请求没有绑定到预期评论时，结果需人工核对（ambiguous）。"""
    page = _page_with_response(
        _make_response(payload={"status_code": 0}, post_data="reply_id=other")
    )
    editor = AsyncMock()
    _stub_submit_control(monkeypatch, submit=AsyncMock())

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.fill_and_submit(
                page,
                editor,
                "回复内容",
                None,
                require_explicit_submit=True,
                require_comment_confirmation=True,
                expected_reply_comment_id="child-2",
                expected_parent_comment_id="parent-1",
            )
        )

    assert captured.value.code == "reply_target_mismatch"
    assert captured.value.ambiguous is True
    assert captured.value.affects_account_health is False


# ---- 评论发布确认的分支 ----


def test_comment_confirmation_requires_an_observed_publish_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """点击未触发发布请求时是确定性失败（可重试、非歧义）。"""
    page = _page_with_response(AsyncMock())
    editor = AsyncMock()
    _stub_submit_control(monkeypatch, submit=AsyncMock(), dispatch=False)

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.fill_and_submit(
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


def test_comment_confirmation_rejects_http_200_business_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP 200 但业务状态码非 0 时按平台拒绝处理，并带上平台文案。"""
    page = _page_with_response(
        _make_response(payload={"status_code": 8, "status_msg": "评论发送失败"})
    )
    editor = AsyncMock()
    _stub_submit_control(monkeypatch, submit=AsyncMock())

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.fill_and_submit(
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
    assert captured.value.affects_account_health is True


@pytest.mark.parametrize("status", [403, 429])
def test_comment_confirmation_treats_auth_wall_as_account_health_risk(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """403/429 归类为风控，并标记影响账号健康。"""
    page = _page_with_response(_make_response(ok=False, status=status))
    editor = AsyncMock()
    _stub_submit_control(monkeypatch, submit=AsyncMock())

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.fill_and_submit(
                page,
                editor,
                "测试评论",
                None,
                require_explicit_submit=True,
                require_comment_confirmation=True,
            )
        )

    assert captured.value.code == "risk_controlled"
    assert captured.value.affects_account_health is True


def test_comment_confirmation_reports_plain_platform_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非 403/429 的 HTTP 失败不计入账号健康（仅平台拒绝）。"""
    page = _page_with_response(_make_response(ok=False, status=500))
    editor = AsyncMock()
    _stub_submit_control(monkeypatch, submit=AsyncMock())

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.fill_and_submit(
                page,
                editor,
                "测试评论",
                None,
                require_explicit_submit=True,
                require_comment_confirmation=True,
            )
        )

    assert captured.value.code == "platform_rejected"
    assert captured.value.affects_account_health is False


@pytest.mark.parametrize(
    ("payload", "expected_platform_id"),
    [
        ({"status_code": 0}, None),
        ({"status_code": "0"}, None),
        ({"status_code": 0, "comment": {"cid": "cid-1"}}, "cid-1"),
        ({"status_code": 0, "data": {"comment": {"cid": "cid-2"}}}, "cid-2"),
        ({"data": {"status_code": 0, "cid": "cid-3"}}, "cid-3"),
        ({"result": {"status_code": "0", "comment_id": "cid-4"}}, "cid-4"),
    ],
)
def test_comment_confirmation_accepts_platform_success_payloads(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
    expected_platform_id: str | None,
) -> None:
    """平台明确成功（状态码 0 或带评论 id）时直接返回，不必再等 UI 判定。"""
    page = _page_with_response(_make_response(payload=payload))
    editor = AsyncMock()
    wait = AsyncMock()
    _stub_submit_control(monkeypatch, submit=AsyncMock())
    monkeypatch.setattr(SubmitFlow, "wait_comment_submission", wait)

    result = asyncio.run(
        SubmitFlow.fill_and_submit(
            page,
            editor,
            "测试评论",
            None,
            require_explicit_submit=True,
            require_comment_confirmation=True,
        )
    )

    assert result.platform_id == expected_platform_id
    wait.assert_not_awaited()


def test_comment_confirmation_marks_ambiguous_when_content_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """发布请求已触发但内容仍留在输入框中：不能判定成功（ambiguous）。"""
    page = _page_with_response(_make_response(payload={}))
    editor = AsyncMock()
    _stub_submit_control(monkeypatch, submit=AsyncMock())
    monkeypatch.setattr(SubmitFlow, "wait_comment_submission", AsyncMock())
    monkeypatch.setattr(dom, "wait_editor_empty", AsyncMock(return_value=False))

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.fill_and_submit(
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


def test_comment_confirmation_succeeds_when_the_editor_is_cleared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """发布请求已触发且输入框已清空：按成功返回（平台未给出 id）。"""
    page = _page_with_response(_make_response(payload={}))
    editor = AsyncMock()
    callback = AsyncMock()
    _stub_submit_control(monkeypatch, submit=AsyncMock())
    monkeypatch.setattr(SubmitFlow, "wait_comment_submission", AsyncMock())
    monkeypatch.setattr(dom, "wait_editor_empty", AsyncMock(return_value=True))

    result = asyncio.run(
        SubmitFlow.fill_and_submit(
            page,
            editor,
            "测试评论",
            callback,
            require_explicit_submit=True,
            require_comment_confirmation=True,
        )
    )

    assert result.platform_id is None
    assert [call.args[1] for call in callback.await_args_list][
        -1
    ] == "platform_accepted"


# ---- 超时与异常分类 ----


def test_publish_timeout_with_visible_security_check_is_risk_controlled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """等待发布响应超时且页面出现安全验证提示时归类为风控（非歧义）。"""
    page = MagicMock()
    page.expect_response.return_value = _TimeoutResponse()
    editor = AsyncMock()
    _stub_submit_control(monkeypatch, submit=AsyncMock())
    monkeypatch.setattr(
        dom, "visible_page_message", _message_probe(risk="接收短信验证码")
    )

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.fill_and_submit(
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
    assert captured.value.affects_account_health is True


def test_publish_timeout_with_visible_failure_toast_is_platform_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """超时后页面出现失败提示文案时归类为平台拒绝。"""
    page = MagicMock()
    page.expect_response.return_value = _TimeoutResponse()
    editor = AsyncMock()
    _stub_submit_control(monkeypatch, submit=AsyncMock())
    monkeypatch.setattr(
        dom, "visible_page_message", _message_probe(failure="发布评论失败")
    )

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.fill_and_submit(
                page,
                editor,
                "测试评论",
                None,
                require_explicit_submit=True,
                require_comment_confirmation=True,
            )
        )

    assert captured.value.code == "platform_rejected"
    assert "发布评论失败" in str(captured.value)


def test_publish_timeout_without_any_signal_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已触发发布请求但没有任何判定信号时：歧义、不可自动重试。"""
    page = MagicMock()
    page.expect_response.return_value = _TimeoutResponse()
    editor = AsyncMock()
    _stub_submit_control(monkeypatch, submit=AsyncMock())
    monkeypatch.setattr(dom, "visible_page_message", _message_probe())

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.fill_and_submit(
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
    assert captured.value.retryable is False
    assert captured.value.affects_account_health is False


def test_message_timeout_with_cleared_editor_is_treated_as_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """私信路径超时但输入框已清空：视为已发送（不报歧义）。"""
    page = MagicMock()
    page.expect_response.return_value = _TimeoutResponse()
    editor = AsyncMock()
    _stub_submit_control(monkeypatch, submit=AsyncMock())
    monkeypatch.setattr(dom, "editor_is_empty", AsyncMock(return_value=True))

    result = asyncio.run(
        SubmitFlow.fill_and_submit(
            page, editor, "测试私信", None, require_explicit_submit=True
        )
    )

    assert result.platform_id is None


def test_failure_before_submit_is_reported_as_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """发送前发生异常且未提交：network_error（可重试、影响账号健康）。"""
    page = MagicMock()
    page.expect_response.side_effect = RuntimeError("browser closed")
    editor = AsyncMock()
    _stub_submit_control(monkeypatch, submit=AsyncMock())

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.fill_and_submit(
                page, editor, "测试私信", None, require_explicit_submit=True
            )
        )

    assert captured.value.code == "network_error"
    assert captured.value.retryable is True
    assert captured.value.ambiguous is False


def test_failure_after_submit_is_reported_as_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已提交后发生非超时异常：结果不明确，需人工核对。"""
    page = MagicMock()
    page.expect_response.return_value = _RaisingResponse(RuntimeError("boom"))
    editor = AsyncMock()
    _stub_submit_control(monkeypatch, submit=AsyncMock())

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.fill_and_submit(
                page, editor, "测试私信", None, require_explicit_submit=True
            )
        )

    assert captured.value.code == "ambiguous_result"
    assert captured.value.ambiguous is True
    assert captured.value.retryable is False


# ---- wait_comment_submission：UI 层面判定 ----


def test_wait_comment_submission_returns_on_success_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """页面出现成功文案即视为发布完成。"""
    monkeypatch.setattr(dom, "visible_page_message", _message_probe(success="已发布"))

    asyncio.run(
        SubmitFlow.wait_comment_submission(MagicMock(), request_content="测试评论")
    )


def test_wait_comment_submission_raises_on_security_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """页面出现安全验证文案时抛风控错误。"""
    monkeypatch.setattr(
        dom, "visible_page_message", _message_probe(risk="接收短信验证码")
    )

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.wait_comment_submission(MagicMock(), request_content="测试评论")
        )

    assert captured.value.code == "risk_controlled"
    assert captured.value.affects_account_health is True


def test_wait_comment_submission_raises_on_failure_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """页面出现失败文案时抛平台拒绝错误。"""
    monkeypatch.setattr(
        dom, "visible_page_message", _message_probe(failure="发布评论失败")
    )

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.wait_comment_submission(MagicMock(), request_content="测试评论")
        )

    assert captured.value.code == "platform_rejected"


def test_wait_comment_submission_returns_when_the_editor_is_cleared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有提示文案时，输入框与容器都已清空即视为发布完成。"""
    monkeypatch.setattr(dom, "visible_page_message", _message_probe())
    page = MagicMock()
    editor = MagicMock()
    editor.count = AsyncMock(return_value=0)
    page.locator.return_value = MagicMock(first=editor)

    asyncio.run(SubmitFlow.wait_comment_submission(page, request_content="测试评论"))

    editor.count.assert_awaited()


def test_wait_comment_submission_times_out_when_content_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """内容始终留在输入框中且没有提示文案时，判为歧义结果。"""
    monkeypatch.setattr(dom, "visible_page_message", _message_probe())
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    editor = MagicMock()
    editor.count = AsyncMock(return_value=1)
    editor.text_content = AsyncMock(return_value="测试评论")
    page.locator.return_value = MagicMock(first=editor)

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.wait_comment_submission(
                page, request_content="测试评论", timeout_ms=1
            )
        )

    assert captured.value.code == "ambiguous_result"
    assert captured.value.ambiguous is True
