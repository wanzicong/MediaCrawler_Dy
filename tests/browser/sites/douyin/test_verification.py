"""目标评论核验测试：CommentPresence 的三条分支与实现方异常的翻译。

翻页判定本身已下沉到 douyin_client 的 ``CommentsApi.find_comment``（S3），browser
侧只负责「调用注入端口 + 把结论翻译成 InteractionExecutionError」。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from crawler.browser.errors import InteractionExecutionError
from crawler.browser.facade import CommentPresence
from crawler.browser.interactions.models import InteractionExecutionRequest
from crawler.browser.interactions.verification import lookup_target_comment


class FakeTargetCommentApi:
    """互动端口替身：只实现核验所需的 ``verify_target_comment``。"""

    def __init__(
        self,
        *,
        state: CommentPresence = "present",
        error: Exception | None = None,
    ) -> None:
        """记录预置结论与预置异常。"""
        self.state = state
        self.error = error
        self.calls: list[dict[str, str | None]] = []

    async def verify_target_comment(
        self,
        *,
        aweme_id: str,
        comment_id: str,
        parent_comment_id: str | None = None,
    ) -> CommentPresence:
        """记录调用参数并返回预置结论（或抛出预置异常）。"""
        self.calls.append(
            {
                "aweme_id": aweme_id,
                "comment_id": comment_id,
                "parent_comment_id": parent_comment_id,
            }
        )
        if self.error is not None:
            raise self.error
        return self.state


def _request(
    *,
    target_comment_id: str | None = "target-2",
    target_parent_comment_id: str | None = None,
) -> InteractionExecutionRequest:
    """构造一个回复评论请求。"""
    return InteractionExecutionRequest(
        interaction_type="comment_reply",
        aweme_id="123",
        content="回复",
        target_comment_id=target_comment_id,
        target_comment_content="目标",
        target_parent_comment_id=target_parent_comment_id,
    )


def test_present_target_passes_without_raising() -> None:
    """present：核验通过（返回 present），由调用方决定后续处置。"""
    api = FakeTargetCommentApi(state="present")

    state = asyncio.run(lookup_target_comment(api, _request(), page=MagicMock()))

    assert state == "present"
    assert api.calls == [
        {"aweme_id": "123", "comment_id": "target-2", "parent_comment_id": None}
    ]


def test_sub_comment_verification_forwards_parent_comment_id() -> None:
    """二级回复的核验把父评论 ID 一并透传给端口（分页归属端口实现）。"""
    api = FakeTargetCommentApi(state="present")

    asyncio.run(
        lookup_target_comment(
            api, _request(target_parent_comment_id="parent-1"), page=MagicMock()
        )
    )

    assert api.calls[0]["parent_comment_id"] == "parent-1"


def test_unavailable_target_raises_terminal_error_and_reports_step() -> None:
    """unavailable：真实评论列表已完整翻页仍无目标 → 终态 target_unavailable。"""
    api = FakeTargetCommentApi(state="unavailable")
    callback = AsyncMock()

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            lookup_target_comment(
                api, _request(), page=MagicMock(), step_callback=callback
            )
        )

    assert captured.value.code == "target_unavailable"
    assert captured.value.retryable is False
    assert [call.args[1] for call in callback.await_args_list] == [
        "reply_target_unavailable"
    ]


def test_inconclusive_target_raises_retryable_error() -> None:
    """inconclusive：接口不可判定 → 可重试的 target_lookup_inconclusive。"""
    api = FakeTargetCommentApi(state="inconclusive")

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(lookup_target_comment(api, _request(), page=MagicMock()))

    assert captured.value.code == "target_lookup_inconclusive"
    assert captured.value.retryable is True


def test_missing_target_comment_id_is_inconclusive_without_calling_api() -> None:
    """缺目标评论 ID 时无法核验，直接判不可重试的不可判定，且不调用端口。"""
    api = FakeTargetCommentApi()

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            lookup_target_comment(
                api, _request(target_comment_id=None), page=MagicMock()
            )
        )

    assert captured.value.code == "target_lookup_inconclusive"
    assert api.calls == []


def test_api_level_failure_from_adapter_propagates_unchanged() -> None:
    """实现方按 §4.3 约定抛出的 InteractionExecutionError 原样传播（不被改写）。"""
    api = FakeTargetCommentApi(
        error=InteractionExecutionError(
            "api_unavailable", "抖音评论接口不可用", retryable=True
        )
    )

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(lookup_target_comment(api, _request(), page=MagicMock()))

    assert captured.value.code == "api_unavailable"
    assert captured.value.retryable is True


def test_unexpected_api_exception_is_translated_to_inconclusive() -> None:
    """端口抛出的非契约异常不能证明评论消失，按可重试的不可判定处理。"""
    api = FakeTargetCommentApi(error=ValueError("boom"))

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(lookup_target_comment(api, _request(), page=MagicMock()))

    assert captured.value.code == "target_lookup_inconclusive"
    assert captured.value.retryable is True
