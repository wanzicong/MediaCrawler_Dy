# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音评论读接口客户端（按业务场景拆分）。

承载一级/子评论分页、整批抓取与目标评论存在性核验；底层带签名的 GET 请求由注入的
``DouyinClient`` 提供。
"""

from __future__ import annotations

import asyncio
import copy
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote

from crawler.douyin_client.http.request_log import (
    CommentCallback,
    IntervalProvider,
    _interval_seconds,
)

if TYPE_CHECKING:
    from crawler.douyin_client.http.client import DouyinClient

# 目标评论存在性核验结论。``crawler.browser`` 侧自带一份同名 Literal（两模块互不
# import 是硬约束，允许重复声明），本模块只做真源实现，不经门面导出。
CommentPresence = Literal["present", "unavailable", "inconclusive"]

# 目标评论核验的翻页节奏：与浏览器层旧实现逐行等价（0.2s 间隔）。
_LOOKUP_PAGE_INTERVAL_SECONDS = 0.2


class CommentsApi:
    """抖音评论读接口客户端。"""

    def __init__(self, client: DouyinClient) -> None:
        self._client = client

    async def get_comments_page(
        self, aweme_id: str, cursor: int, keyword: str = ""
    ) -> dict[str, Any]:
        """获取作品一级评论分页（/aweme/v1/web/comment/list/）。

        参数：
            aweme_id: 作品 ID。
            cursor: 分页游标。
            keyword: 来源搜索关键词，仅用于构造 Referer。

        返回：
            评论接口原始响应 JSON（含 comments、cursor、has_more）。
        """
        headers = copy.copy(self._client.headers)
        headers["Referer"] = quote(
            f"https://www.douyin.com/search/{keyword}?type=general", safe=":/"
        )
        return await self._client.get(
            "/aweme/v1/web/comment/list/",
            {"aweme_id": aweme_id, "cursor": cursor, "count": 20, "item_type": 0},
            headers,
        )

    async def get_sub_comments_page(
        self, aweme_id: str, comment_id: str, cursor: int, keyword: str = ""
    ) -> dict[str, Any]:
        """获取某条评论的子评论（回复）分页（/aweme/v1/web/comment/list/reply/）。

        参数：
            aweme_id: 作品 ID。
            comment_id: 一级评论 ID。
            cursor: 分页游标。
            keyword: 来源搜索关键词，仅用于构造 Referer。

        返回：
            子评论接口原始响应 JSON。
        """
        headers = copy.copy(self._client.headers)
        headers["Referer"] = quote(
            f"https://www.douyin.com/search/{keyword}?type=general", safe=":/"
        )
        return await self._client.get(
            "/aweme/v1/web/comment/list/reply/",
            {
                "comment_id": comment_id,
                "cursor": cursor,
                "count": 20,
                "item_type": 0,
                "item_id": aweme_id,
            },
            headers,
        )

    async def find_comment(
        self,
        *,
        aweme_id: str,
        comment_id: str,
        parent_comment_id: str | None = None,
        max_pages: int = 50,
        max_comments: int = 1_000,
    ) -> CommentPresence:
        """翻页核验目标评论是否仍然存在。

        一级评论直接翻作品评论页，``parent_comment_id`` 非空且不为 ``"0"`` 时改翻
        该条评论的子评论页。只有「完整翻完所有页且目标未出现」才判定 ``unavailable``；
        任何无法定论的情形（接口异常、业务状态失败、分页契约字段缺失、游标异常或
        重复、超过翻页/条数上限）一律返回 ``inconclusive``，保证调用方可安全重试。

        参数：
            aweme_id: 目标评论所属作品 ID。
            comment_id: 目标评论 ID；为空时直接返回 ``inconclusive``。
            parent_comment_id: 目标评论的父评论 ID（回复场景）；``None``/``""``/``"0"``
                视为一级评论。
            max_pages: 最多翻页次数，默认 50。
            max_comments: 累计翻过的评论条数上限，默认 1000。

        返回：
            ``present`` / ``unavailable`` / ``inconclusive``。
        """
        return (
            await self.find_comment_item(
                aweme_id=aweme_id,
                comment_id=comment_id,
                parent_comment_id=parent_comment_id,
                max_pages=max_pages,
                max_comments=max_comments,
            )
        )[0]

    async def find_comment_item(
        self,
        *,
        aweme_id: str,
        comment_id: str,
        parent_comment_id: str | None = None,
        max_pages: int = 50,
        max_comments: int = 1_000,
    ) -> tuple[CommentPresence, dict[str, Any] | None]:
        """翻页定位目标评论，同时返回该评论的原始数据（含评论者字段）。

        与 :meth:`find_comment` 是同一套翻页实现（后者只取结论）。评论者身份
        （``user.sec_uid`` / ``user.uid``）只能在这里拿到原始值：调用方需要立刻
        用它发起后续抓取，任何落库/日志都必须先做脱敏（见 ``map_comment``）。

        参数：
            aweme_id: 目标评论所属作品 ID。
            comment_id: 目标评论 ID；为空时直接返回 ``("inconclusive", None)``。
            parent_comment_id: 目标评论的父评论 ID（回复场景）；``None``/``""``/``"0"``
                视为一级评论。
            max_pages: 最多翻页次数，默认 50。
            max_comments: 累计翻过的评论条数上限，默认 1000。

        返回：
            ``(presence, item)``：presence 同 :meth:`find_comment`；
            命中（``present``）时 item 为该条评论的原始字典，否则为 ``None``。
        """
        if not comment_id:
            return "inconclusive", None
        cursor = 0
        total = 0
        seen_cursors: set[int] = set()
        for _ in range(max_pages):
            try:
                if parent_comment_id not in {None, "", "0"}:
                    assert parent_comment_id is not None
                    payload = await self.get_sub_comments_page(
                        aweme_id,
                        parent_comment_id,
                        cursor,
                    )
                else:
                    payload = await self.get_comments_page(aweme_id, cursor)
            except Exception:
                return "inconclusive", None
            # 抖音业务状态码非零、或响应缺少分页契约字段，都不能证明评论已消失；
            # 统一按 inconclusive 处理，保证任务可安全重试。
            if payload.get("status_code") not in (0, "0"):
                return "inconclusive", None
            if "comments" not in payload or "has_more" not in payload:
                return "inconclusive", None
            comments = payload["comments"]
            if not isinstance(comments, list):
                return "inconclusive", None
            for comment in comments:
                if str(comment.get("cid") or "") == comment_id:
                    if not isinstance(comment, dict):
                        return "inconclusive", None
                    return "present", comment
            total += len(comments)
            has_more = payload.get("has_more")
            if has_more in (False, 0, "0"):
                return "unavailable", None
            if has_more not in (True, 1, "1"):
                return "inconclusive", None
            if not comments or total >= max_comments:
                return "inconclusive", None
            try:
                next_cursor = int(payload.get("cursor") or 0)
            except (TypeError, ValueError):
                return "inconclusive", None
            if next_cursor == cursor or next_cursor in seen_cursors:
                return "inconclusive", None
            seen_cursors.add(cursor)
            cursor = next_cursor
            await asyncio.sleep(_LOOKUP_PAGE_INTERVAL_SECONDS)
        return "inconclusive", None

    async def get_all_comments(
        self,
        aweme_id: str,
        *,
        interval: IntervalProvider,
        include_sub_comments: bool,
        callback: CommentCallback,
        max_count: int,
        keyword: str = "",
    ) -> int:
        """抓取作品全部评论（含可选子评论），按批次回调给调用方。

        参数：
            aweme_id: 作品 ID。
            interval: 翻页请求间隔（秒），可为固定值或可调用对象。
            include_sub_comments: 是否同时抓取有回复的一级评论的子评论。
            callback: 评论批次回调。
            max_count: 抓取评论总数上限（含子评论）。
            keyword: 来源搜索关键词，仅用于构造 Referer。

        返回：
            实际抓取的评论总数。
        """
        total = 0
        cursor = 0
        has_more = True
        seen_cursors: set[int] = set()
        while has_more and total < max_count:
            response = await self.get_comments_page(aweme_id, cursor, keyword)
            comments = response.get("comments") or []
            if not isinstance(comments, list) or not comments:
                break
            comments = comments[: max_count - total]
            await callback(aweme_id, comments)
            total += len(comments)
            if include_sub_comments and total < max_count:
                for comment in comments:
                    if int(comment.get("reply_comment_total") or 0) > 0:
                        total += await self._get_sub_comments(
                            aweme_id,
                            str(comment.get("cid") or ""),
                            keyword,
                            interval,
                            callback,
                            max_count - total,
                        )
                        if total >= max_count:
                            break
            has_more = response.get("has_more") in (True, 1, "1")
            next_cursor = int(response.get("cursor") or 0)
            if not has_more or next_cursor in seen_cursors or next_cursor == cursor:
                break
            seen_cursors.add(cursor)
            cursor = next_cursor
            await asyncio.sleep(_interval_seconds(interval))
        return total

    async def _get_sub_comments(
        self,
        aweme_id: str,
        comment_id: str,
        keyword: str,
        interval: IntervalProvider,
        callback: CommentCallback,
        max_count: int,
    ) -> int:
        """分页抓取某条一级评论的子评论并按批回调，返回实际抓取数。"""
        if not comment_id or max_count <= 0:
            return 0
        total = 0
        cursor = 0
        while total < max_count:
            response = await self.get_sub_comments_page(
                aweme_id, comment_id, cursor, keyword
            )
            comments = response.get("comments") or []
            if not isinstance(comments, list) or not comments:
                break
            comments = comments[: max_count - total]
            await callback(aweme_id, comments)
            total += len(comments)
            if response.get("has_more") not in (True, 1, "1"):
                break
            next_cursor = int(response.get("cursor") or 0)
            if next_cursor == cursor:
                break
            cursor = next_cursor
            await asyncio.sleep(_interval_seconds(interval))
        return total
