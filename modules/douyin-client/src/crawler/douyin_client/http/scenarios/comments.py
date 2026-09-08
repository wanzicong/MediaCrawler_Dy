# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音评论读接口客户端（按业务场景拆分）。

承载一级/子评论分页与整批抓取；底层带签名的 GET 请求由注入的 ``DouyinClient`` 提供。
"""

from __future__ import annotations

import asyncio
import copy
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from crawler.douyin_client.http.request_log import (
    CommentCallback,
    IntervalProvider,
    _interval_seconds,
)

if TYPE_CHECKING:
    from crawler.douyin_client.http.client import DouyinClient


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
