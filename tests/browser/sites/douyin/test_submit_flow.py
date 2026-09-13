"""互动填写与提交确认测试（``SubmitFlow``）。

覆盖两条提交路径：需平台确认的评论发布（``require_comment_confirmation``）与
只需触发响应标记的私信发送；以及提交前的上下文校验（作品页/回复状态）、
发送控件缺失/不可激活、平台拒绝/风控/歧义结果的分类，与
``wait_comment_submission`` 的 UI 层面判定。文件末尾用 AST 守卫
``fill_and_submit`` 的错误码归类：新增错误码必须显式归类，否则红灯。
"""

import ast
import asyncio
import pathlib
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
from crawler.browser.interactions.submit_flow import PAGE_VERDICT_CODES, SubmitFlow
from crawler.browser.page import primitives as dom
from playwright.async_api import Error as PlaywrightError
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


def _stub_unactivated_control(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[AsyncMock, PlaywrightError]:
    """替换发送控件查找：返回一个存在、但三种激活方式全部失败的控件。

    真实的 ``PageController.dispatch_comment_submit`` 仍然生效（不替换），
    因此测的是「控件点不动」在生产路径上被归成哪一类异常。返回控件替身与
    原始 Playwright 异常（用于断言根因被保留）。
    """
    detached = PlaywrightError("Element is not attached to the DOM")
    control = AsyncMock()
    control.dispatch_event.side_effect = detached
    control.click.side_effect = detached
    monkeypatch.setattr(
        PageController, "find_submit_control", AsyncMock(return_value=control)
    )
    monkeypatch.setattr(dom, "click_control_center", AsyncMock(side_effect=detached))
    return control, detached


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


@pytest.mark.parametrize(
    ("require_explicit_submit", "require_comment_confirmation"),
    [(True, False), (True, True)],
)
def test_fill_and_submit_requires_a_clickable_send_control(
    monkeypatch: pytest.MonkeyPatch,
    require_explicit_submit: bool,
    require_comment_confirmation: bool,
) -> None:
    """需要发送控件的模式（显式提交 / 平台确认）找不到控件时报可重试的 submit_not_available。"""
    page = MagicMock()
    editor = AsyncMock()
    _stub_submit_control(monkeypatch, submit=None)

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.fill_and_submit(
                page,
                editor,
                "测试内容",
                None,
                require_explicit_submit=require_explicit_submit,
                require_comment_confirmation=require_comment_confirmation,
            )
        )

    error = captured.value
    assert error.code == "submit_not_available"
    assert error.retryable is True
    assert error.ambiguous is False
    # 缺发送控件是页面缺失，不是账号健康问题。
    assert error.affects_account_health is False
    # 前置检查在提交流程之外：还没进入 try 就终止了。
    page.expect_response.assert_not_called()
    editor.press.assert_not_awaited()


def test_comment_confirmation_without_a_send_control_is_not_a_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OI-1 回归：需平台确认但只要求快捷键兜底、页面上又没有发送控件时，
    前置条件以类型化的 submit_not_available 抛出，不得被兜底 except 误标成
    network_error（那会错报错误码并把账号判为不健康）。"""
    page = MagicMock()
    editor = AsyncMock()
    _stub_submit_control(monkeypatch, submit=None)

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.fill_and_submit(
                page,
                editor,
                "测试评论",
                None,
                require_explicit_submit=False,
                require_comment_confirmation=True,
            )
        )

    error = captured.value
    assert error.code == "submit_not_available"
    assert error.retryable is True
    assert error.ambiguous is False
    assert error.affects_account_health is False
    page.expect_response.assert_not_called()


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


def test_reply_risk_control_wins_over_a_mismatched_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP 403/429 必须先于「未绑定到预期评论」判定。

    否则风控撞上回复目标不匹配时会被归类成 ``reply_target_mismatch``
    （``ambiguous`` 且不计账号健康），风控信号丢掉一次——账号连续被风控也攒不到
    ``unhealthy``。HTTP 状态是平台对本次请求的权威判定，与请求绑定到哪条评论无关。
    """
    page = _page_with_response(
        _make_response(ok=False, status=403, post_data="reply_id=other")
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

    assert captured.value.code == "risk_controlled"
    assert captured.value.affects_account_health is True
    assert captured.value.ambiguous is False


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


def test_untriggered_submit_with_a_security_check_is_risk_controlled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """回归（对抗式验证证伪点）：三种激活方式都「执行成功」却没有观测到发布请求、
    而页面上正显示风控文案时，内部归类必须让位给页面文案——最终 code 为
    ``risk_controlled`` 且计入账号健康。

    漏掉这条，业务侧 ``account_healthy = not exc.affects_account_health`` 就会
    拿到 True，``release_account(success=True)`` 随之把 failure_streak 归零、
    清空 last_error：连续被风控也永远攒不到 unhealthy/blocked 的阈值，账号状态
    只会落 failed 而进不了 blocked。
    """
    page = _page_with_response(AsyncMock())
    editor = AsyncMock()
    _stub_submit_control(monkeypatch, submit=AsyncMock(), dispatch=False)
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

    error = captured.value
    assert error.code == "risk_controlled"
    assert error.affects_account_health is True
    assert error.ambiguous is False
    # 确实是「未触发」这条路径被页面判定升格的，根因没有被吞掉。
    assert isinstance(error.__cause__, InteractionExecutionError)
    assert error.__cause__.code == "submit_not_triggered"


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


# ---- 发送控件存在但无法激活的归类 ----


def test_unclickable_submit_control_is_not_reported_as_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OI-1 同族回归：发送控件存在、但三种激活方式都执行不了时，抛出类型化的
    页面条件错误 ``submit_not_activated``，不得被兜底 except 标成 network_error，
    更不能因为一次确定性的页面条件把账号判为不健康。"""
    page = _page_with_response(AsyncMock())
    editor = AsyncMock()
    control, detached = _stub_unactivated_control(monkeypatch)

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

    error = captured.value
    assert error.code == "submit_not_activated"
    # 兜底分支的两种归类都不能出现：这不是网络故障，也不是歧义结果。
    assert error.code not in {"network_error", "ambiguous_result"}
    assert error.retryable is True
    assert error.ambiguous is False
    # 页面条件不是账号健康问题。
    assert error.affects_account_health is False
    # 原始 Playwright 异常保留为根因，排障时仍能看到控件为什么点不动。
    assert error.__cause__ is detached
    control.dispatch_event.assert_awaited_once_with("click")
    control.click.assert_awaited_once_with(timeout=5_000)


def test_unclickable_submit_control_with_a_security_check_is_risk_controlled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """控件点不动、但页面已弹出安全验证：页面文案优先，仍报风控并计入账号健康，
    不能被降级成普通页面条件（验证蒙层拦点击正是风控的典型表现）。"""
    page = _page_with_response(AsyncMock())
    editor = AsyncMock()
    _stub_unactivated_control(monkeypatch)
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
    assert captured.value.affects_account_health is True


def test_unclickable_submit_control_with_a_failure_toast_is_platform_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """控件点不动、但页面已提示限流/发布失败：按平台拒绝归类并计入账号健康，
    与超时分支对同一批文案的处置保持一致。"""
    page = _page_with_response(AsyncMock())
    editor = AsyncMock()
    _stub_unactivated_control(monkeypatch)
    monkeypatch.setattr(dom, "visible_page_message", _message_probe(failure="操作频繁"))

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
    assert "操作频繁" in str(captured.value)


def test_detached_submit_control_before_activation_is_not_a_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """评论路径：控件在「找到」与「激活」之间脱离 DOM（滚动即失败），此时连点击
    都没有发出，必须类型化抛出而不是 network_error；激活入口不应被调用。"""
    page = _page_with_response(AsyncMock())
    editor = AsyncMock()
    control = AsyncMock()
    control.scroll_into_view_if_needed.side_effect = PlaywrightError(
        "Element is not attached to the DOM"
    )
    monkeypatch.setattr(
        PageController, "find_submit_control", AsyncMock(return_value=control)
    )
    dispatch = AsyncMock()
    monkeypatch.setattr(PageController, "dispatch_comment_submit", dispatch)

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

    assert captured.value.code == "submit_not_activated"
    assert captured.value.retryable is True
    assert captured.value.ambiguous is False
    assert captured.value.affects_account_health is False
    dispatch.assert_not_awaited()


def test_detached_message_submit_control_is_not_an_ambiguous_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """私信路径：滚动失败同样证明点击没有发出，判为「未发送、可重试」，
    而不是笼统的歧义结果（歧义会连带影响账号健康且需要人工核对）。"""
    page = _page_with_response(AsyncMock())
    editor = AsyncMock()
    control = AsyncMock()
    control.scroll_into_view_if_needed.side_effect = PlaywrightError(
        "Element is not attached to the DOM"
    )
    monkeypatch.setattr(
        PageController, "find_submit_control", AsyncMock(return_value=control)
    )

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            SubmitFlow.fill_and_submit(
                page, editor, "测试私信", None, require_explicit_submit=True
            )
        )

    assert captured.value.code == "submit_not_activated"
    assert captured.value.ambiguous is False
    assert captured.value.retryable is True
    assert captured.value.affects_account_health is False
    control.click.assert_not_awaited()


def test_publish_request_observed_after_activation_failures_is_not_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """激活方式全部抛错、但发布请求已被观测到（CDP 点击已落点，随后命令通道断开）：
    必须按「已触发」继续等待平台确认，绝不能报「未发送」——那会让调用方重试并
    可能重复发布。"""
    page = _page_with_response(
        _make_response(payload={"status_code": 0, "comment": {"cid": "cid-1"}})
    )
    observed: list[Any] = []
    page.on = MagicMock(side_effect=lambda _event, handler: observed.append(handler))
    editor = AsyncMock()
    detached = PlaywrightError("Element is not attached to the DOM")
    control = AsyncMock()
    control.dispatch_event.side_effect = detached
    control.click.side_effect = detached

    async def click_then_fail(_page: object, _control: object) -> None:
        """模拟 CDP 鼠标点击已落点（触发发布请求），随后命令通道报错。"""
        request = MagicMock()
        request.method = "POST"
        request.url = "https://www.douyin.com/aweme/v1/web/comment/publish/"
        observed[0](request)
        raise detached

    monkeypatch.setattr(dom, "click_control_center", click_then_fail)
    monkeypatch.setattr(
        PageController, "find_submit_control", AsyncMock(return_value=control)
    )

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

    assert observed, "必须已注册发布请求监听器"
    assert result.platform_id == "cid-1"


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


# ---- 错误码归类穷尽性守卫 ----
# 页面判定必须绑在「这类失败」上，而不是绑在某个具体 code 上：只补单点是点修，
# 下一个人新增同类错误码时又会被静默漏掉，风控信号随之丢失。下面用 AST 把「记得补」
# 变成机制——新增错误码而没有归类，这条测试直接红灯。

# 被审计的模块路径：以本文件位置定位，不依赖 CWD（仓库根是 parents[4]）。
_SUBMIT_FLOW_PATH = (
    pathlib.Path(__file__).resolve().parents[4]
    / "modules/browser/src/crawler/browser/interactions/submit_flow.py"
)

_ERROR_TYPE_NAME = "InteractionExecutionError"

# 无需页面判定的错误码 → 理由（一条一因，新增条目必须写清为什么不需要）。
# 「需要页面判定」的那批不在此表，而是复用生产常量 submit_flow.PAGE_VERDICT_CODES：
# 测试与实现共用同一份声明，避免两处定义漂移。
_CODES_WITHOUT_PAGE_VERDICT: dict[str, str] = {
    # 在页面判定那条 try 之外抛出：异常到不了 except InteractionExecutionError，
    # 页面判定分支根本不会被触发（与「要不要查」无关）。
    "editor_unavailable": "填写输入框阶段失败（try 之前），尚未进入提交",
    "reply_context_lost": "发送前的回复上下文校验（try 之前），未执行发送",
    "submit_not_available": "发送控件缺失的前置校验（try 之前），未执行发送",
    # try 块内，但已经是平台对本次请求的判定结论。
    "risk_controlled": "HTTP 403/429 或页面风控的既有结论，已计入账号健康；重复判定只会覆盖明确结论",
    "platform_rejected": "平台业务状态码/失败文案的既有结论，已按平台语义设置账号健康标记",
    # try 块内，但结果已不明确、或只有请求本身能证明问题。
    "reply_target_mismatch": "发布请求已观测到且绑定关系不符，只有请求能证明，已标歧义交人工核对",
    "ambiguous_result": "发布请求已观测到但结果不明确，构造点已自行决定是否计入账号健康",
    "network_error": "真正未知的异常，兜底分支已按「发送前失败」计入账号健康",
}


def _fill_and_submit_node() -> ast.AsyncFunctionDef:
    """解析被审计模块，返回 ``fill_and_submit`` 的语法树节点。"""
    source = _SUBMIT_FLOW_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_SUBMIT_FLOW_PATH))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "fill_and_submit":
            return node
    raise AssertionError(f"{_SUBMIT_FLOW_PATH} 中找不到 fill_and_submit")


def _page_verdict_try(func: ast.AsyncFunctionDef) -> ast.Try:
    """返回 ``func`` 中捕获 ``InteractionExecutionError`` 的那条 try 语句。"""
    for node in ast.walk(func):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            if handler.type is not None and _ERROR_TYPE_NAME in ast.unparse(
                handler.type
            ):
                return node
    raise AssertionError(
        f"{_SUBMIT_FLOW_PATH} 的 fill_and_submit 中找不到捕获 {_ERROR_TYPE_NAME} 的 try"
    )


def _code_sites(
    func: ast.AsyncFunctionDef, try_node: ast.Try
) -> tuple[dict[str, list[tuple[int, bool]]], list[tuple[int, str]]]:
    """收集 ``func`` 体内每个错误码构造点。

    返回 ``(code -> [(行号, 是否位于 try 体)], 无法静态解析的构造点列表)``。

    「位于 try 体」指该构造点在 ``try_node`` 的 ``try:`` 体内（含其嵌套语句）：只有
    从那里抛出的异常才会被 ``except InteractionExecutionError`` 捕获、进而走到页面
    判定分支；在 ``try_node`` 自己的 except/finally 处理器里抛出的不算。

    code 取第一个位置参数（或 ``code=`` 关键字实参）：字面量直接取用；形如
    ``code = "risk_controlled" if ... else "platform_rejected"`` 的局部变量，按同函数
    内的赋值解析出全部字符串常量——动态取值同样要归类，否则会留下盲区。
    """
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(func):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent

    def in_try_body(node: ast.AST) -> bool:
        """判断构造点是否位于 ``try_node`` 的 try 体内（而非其处理器内）。"""
        child = node
        while id(child) in parents:
            parent = parents[id(child)]
            if parent is try_node:
                return any(child is statement for statement in try_node.body)
            child = parent
        return False

    def resolve(
        argument: ast.AST | None, seen: frozenset[str] = frozenset()
    ) -> set[str] | None:
        """把 code 实参解析成可能的取值集合；无法静态解析时返回 None。

        支持字面量、``a if ... else b`` 条件式，以及同函数内赋值给局部变量的
        名字（``seen`` 防止自引用赋值死循环）。任何一处解析不出来就整体返回
        ``None``——宁可让测试报「无法静态解析」，也不静默漏掉一个 code。
        """
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            return {argument.value}
        if isinstance(argument, ast.IfExp):
            branches: set[str] = set()
            for branch in (argument.body, argument.orelse):
                resolved_branch = resolve(branch, seen)
                if resolved_branch is None:
                    return None
                branches |= resolved_branch
            return branches
        if not isinstance(argument, ast.Name) or argument.id in seen:
            return None
        resolved: set[str] = set()
        for statement in ast.walk(func):
            if not isinstance(statement, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == argument.id
                for target in statement.targets
            ):
                continue
            assigned = resolve(statement.value, seen | {argument.id})
            if assigned is None:
                return None
            resolved |= assigned
        return resolved or None

    sites: dict[str, list[tuple[int, bool]]] = {}
    unresolved: list[tuple[int, str]] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if isinstance(callee, ast.Name):
            name: str | None = callee.id
        elif isinstance(callee, ast.Attribute):
            name = callee.attr
        else:
            name = None
        if name != _ERROR_TYPE_NAME:
            continue
        argument: ast.AST | None = node.args[0] if node.args else None
        if argument is None:
            argument = next((k.value for k in node.keywords if k.arg == "code"), None)
        codes = resolve(argument)
        if codes is None:
            unresolved.append((node.lineno, ast.unparse(node)))
            continue
        for code in codes:
            sites.setdefault(code, []).append((node.lineno, in_try_body(node)))
    return sites, unresolved


def _describe_sites(sites: dict[str, list[tuple[int, bool]]]) -> str:
    """把构造点渲染成 ``code：L行号（try 块内/外）``，便于直接排错。"""
    rendered = "\n".join(
        "    {code}：{lines}（{location}）".format(
            code=code,
            lines="/".join(f"L{lineno}" for lineno, _ in where),
            location="try 块内" if any(inside for _, inside in where) else "try 块外",
        )
        for code, where in sorted(sites.items())
    )
    return rendered or "    （无）"


def test_fill_and_submit_error_codes_are_all_classified() -> None:
    """穷尽性守卫：``fill_and_submit`` 的每个错误码都必须被显式归类。

    归类只有两条路：
      * 属于「本次未发出、且尚未观测到平台判定」→ 在 ``PAGE_VERDICT_CODES`` 中声明
        （本测试直接复用生产常量，不抄第二份），抛出时自动多查一次页面文案；
      * 不需要页面判定 → 写进本文件的 ``_CODES_WITHOUT_PAGE_VERDICT`` 并说明理由。

    新增错误码而没有归类时，这条测试会红灯并直接点名是哪个 code、在哪一行、是否
    落在 try 块内，强迫作者做出归类，而不是静默漏掉页面判定（漏掉会让风控信号丢失，
    账号健康永远攒不满）。
    """
    func = _fill_and_submit_node()
    sites, unresolved = _code_sites(func, _page_verdict_try(func))

    assert not unresolved, (
        "以下错误码构造点的 code 无法静态解析，穷尽性守卫会失效。请改用字符串字面量，"
        '或写成 `code = "a" if ... else "b"` 这类可解析的赋值：\n'
        + "\n".join(f"    L{lineno}：{snippet}" for lineno, snippet in unresolved)
    )

    overlap = sorted(PAGE_VERDICT_CODES & set(_CODES_WITHOUT_PAGE_VERDICT))
    assert not overlap, f"同一错误码不能同时出现在两张表里，请二选一：{overlap}"

    classified = PAGE_VERDICT_CODES | set(_CODES_WITHOUT_PAGE_VERDICT)
    unclassified = {
        code: where for code, where in sites.items() if code not in classified
    }
    assert not unclassified, (
        "fill_and_submit 里出现了未归类的错误码，请二选一：\n"
        "  * 属于「本次未发出、且尚未观测到平台判定」→ 加入 "
        "modules/browser/src/crawler/browser/interactions/submit_flow.py 的 "
        "PAGE_VERDICT_CODES（抛出前会自动再查一次页面文案，风控信号不丢）；\n"
        "  * 不需要页面判定 → 加入本文件的 _CODES_WITHOUT_PAGE_VERDICT 并写明理由。\n"
        "未归类：\n" + _describe_sites(unclassified)
    )

    stale = sorted(code for code in _CODES_WITHOUT_PAGE_VERDICT if code not in sites)
    assert not stale, (
        "以下错误码在 _CODES_WITHOUT_PAGE_VERDICT 里已失效（fill_and_submit 不再构造），"
        f"请删除以免归类表与实现漂移：{stale}"
    )
