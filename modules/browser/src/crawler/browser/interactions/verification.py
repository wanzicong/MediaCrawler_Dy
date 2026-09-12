# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""目标评论的实时核验：把 ``CommentPresence`` 翻译成可处置的互动错误。

翻页判定（50 页 / 1000 条 / cursor 重复 / has_more 类型判定）已按规格下沉为
``CommentsApi.find_comment``，browser 侧只保留「调用注入端口 + 翻译结论」这一层：
不再有任何 HTTP 或分页逻辑，也不 import ``crawler.douyin_client``（裁决 R10.1）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from crawler.browser.errors import InteractionExecutionError
from crawler.browser.interactions.models import (
    InteractionExecutionRequest,
    InteractionStepCallback,
)
from crawler.browser.interactions.reporting import report_step
from playwright.async_api import Page

if TYPE_CHECKING:  # 门面协议只作类型注解，运行时不 import（避免 facade 包环）。
    from crawler.browser.facade.protocols import CommentPresence, InteractionApi


async def lookup_target_comment(
    api: InteractionApi,
    request: InteractionExecutionRequest,
    *,
    page: Page,
    step_callback: InteractionStepCallback | None = None,
) -> CommentPresence:
    """经注入的端口核验目标评论，并把结论翻译成互动错误。

    返回：
        ``"present"``：目标评论确实存在，此时页面未能定位属 DOM 问题，由调用方
        继续处置（抛 ``target_dom_not_found``）。

    异常：
        InteractionExecutionError: ``"unavailable"``（真实评论列表已完整翻页仍无
        目标，终态不重试）；``"inconclusive"``（接口故障或无法定论，可重试）。
        实现方按规格 §4.3 约定抛出的 ``InteractionExecutionError``（如
        ``api_unavailable``）原样传播，不被吞掉。
    """
    if not request.target_comment_id:
        raise InteractionExecutionError(
            "target_lookup_inconclusive",
            "缺少目标评论 ID，无法核验评论是否存在，请重试",
            retryable=True,
        )
    try:
        state = await api.verify_target_comment(
            aweme_id=request.aweme_id,
            comment_id=request.target_comment_id,
            parent_comment_id=request.target_parent_comment_id,
        )
    except InteractionExecutionError:
        # 实现方按 §4.3 约定抛出的失败（如 api_unavailable）原样传播。
        raise
    except Exception as exc:
        # 与迁移前的翻页核验一致：接口异常不能证明评论已消失，按不可判定处理。
        raise InteractionExecutionError(
            "target_lookup_inconclusive",
            "评论核验接口调用失败，无法确认目标评论状态，请重试",
            retryable=True,
        ) from exc
    if state == "unavailable":
        await report_step(
            step_callback,
            page,
            "reply_target_unavailable",
            "真实评论接口已完整翻页，目标评论当前不可见",
        )
        raise InteractionExecutionError(
            "target_unavailable",
            "真实评论列表已完整核验：目标评论不存在或当前账号不可见",
        )
    if state == "inconclusive":
        raise InteractionExecutionError(
            "target_lookup_inconclusive",
            "页面未定位到目标评论，实时接口核验也未能完整结束，请重试",
            retryable=True,
        )
    return state


__all__ = ["lookup_target_comment"]
