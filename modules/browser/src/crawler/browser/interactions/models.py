# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""互动执行的数据模型：请求、结果与步骤回调契约。

纯数据结构集中于此；页面操作实现见同目录的 ``response_inspector`` /
``page_controller`` / ``comment_locator`` / ``submit_flow``，编排与连接参数解析见
``executor``。互动执行异常定义在 ``crawler.browser.errors``。

旧的 ``InteractionBrowserConnection`` 与旧版 account 结构化协议已删除：连接参数
统一由 ``crawler.browser.facade.spec.BrowserSessionSpec`` 承载，业务侧的
``resolve_account_browser`` 是唯一真源。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from crawler.browser.page.port import BrowserPage

# 互动步骤回调：参数为只读页面端口、步骤标识与步骤说明。
# 首个参数刻意是 ``BrowserPage`` 而非 Playwright ``Page``：上层（business）只能
# 拿到只读端口，无法通过回调把裸 Playwright 对象带出 browser。
InteractionStepCallback = Callable[[BrowserPage, str, str], Awaitable[None]]


@dataclass(frozen=True)
class InteractionExecutionRequest:
    """互动执行请求参数。

    属性：
        interaction_type: 互动类型：video_comment（评论作品）/ comment_reply（回复评论）/ 其他为私信作者。
        aweme_id: 目标作品 ID。
        content: 互动文本内容。
        target_comment_id: 目标评论 ID（comment_reply 时使用）。
        target_comment_content: 目标评论内容，用于页面内定位。
        target_parent_comment_id: 目标评论的父评论 ID（回复二级评论时使用）。
    """

    interaction_type: str  # 互动类型：video_comment / comment_reply / 私信作者
    aweme_id: str  # 目标作品 ID
    content: str  # 互动文本内容
    target_comment_id: str | None = None  # 目标评论 ID
    target_comment_content: str | None = None  # 目标评论内容，用于页面内定位
    target_parent_comment_id: str | None = None  # 目标评论的父评论 ID


@dataclass(frozen=True)
class InteractionExecutionResult:
    """互动执行结果。

    属性：
        platform_id: 平台侧返回的评论 ID 等标识，未能解析时为 None。
    """

    platform_id: str | None = None  # 平台侧返回的评论 ID 等标识


__all__ = [
    "InteractionExecutionRequest",
    "InteractionExecutionResult",
    "InteractionStepCallback",
]
