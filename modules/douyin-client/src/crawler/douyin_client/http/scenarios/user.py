# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音用户（本人/其他）读接口客户端（按业务场景拆分）。

承载资料、发布/喜欢/收藏列表；底层带签名的 GET/POST 请求由注入的 ``DouyinClient`` 提供。
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from crawler.douyin_client.http.client import DouyinClient


class UserApi:
    """抖音用户（本人/其他）读接口客户端。"""

    def __init__(self, client: DouyinClient) -> None:
        self._client = client

    async def get_user_info(self, sec_user_id: str) -> dict[str, Any]:
        """获取其他用户的公开资料（/aweme/v1/web/user/profile/other/）。

        参数：
            sec_user_id: 目标用户的 sec_user_id。

        返回：
            用户资料接口原始响应 JSON。
        """
        return await self._client.get(
            "/aweme/v1/web/user/profile/other/",
            {
                "sec_user_id": sec_user_id,
                "publish_video_strategy_type": 2,
                "personal_center_strategy": 1,
            },
        )

    async def get_self_profile(self) -> dict[str, Any]:
        """获取当前登录账号的资料（/aweme/v1/web/user/profile/self/），亦用于登录状态校验。

        返回：
            本人资料接口原始响应 JSON。
        """
        headers = copy.copy(self._client.headers)
        headers["Referer"] = "https://www.douyin.com/user/self"
        return await self._client.get(
            "/aweme/v1/web/user/profile/self/", {"aid": "6383"}, headers
        )

    async def get_followings(
        self,
        sec_user_id: str,
        cursor: int | str = 0,
        count: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """获取用户（自己）的关注列表（/aweme/v1/web/user/following/list/）。

        2026-09-24 在真机（已登录浏览器页面）探索确认：参数为
        ``sec_user_id`` + ``count`` + ``offset`` + ``max_time`` + ``source_type=1``，
        返回 ``followings`` 列表与 ``has_more`` / ``max_time``，翻页用返回的
        ``max_time`` 作为下一页入参（``offset`` 同步累加）。

        参数：
            sec_user_id: 目标账号（本人）的 sec_user_id。
            cursor: 分页游标（上一页返回的 ``max_time``），首页传 0。
            count: 每页数量。
            offset: 已拉取条数（服务端按它做偏移）。

        返回：
            关注列表接口原始响应 JSON（``followings`` 为关注用户列表）。
        """
        headers = copy.copy(self._client.headers)
        headers["Referer"] = "https://www.douyin.com/user/self?showTab=following"
        return await self._client.get(
            "/aweme/v1/web/user/following/list/",
            {
                "sec_user_id": sec_user_id,
                "count": count,
                "offset": offset,
                "max_time": cursor,
                "source_type": 1,
            },
            headers,
        )

    async def get_liked(
        self, sec_user_id: str, cursor: int | str, count: int
    ) -> dict[str, Any]:
        """获取用户喜欢（点赞）的作品列表（/aweme/v1/web/aweme/favorite/）。

        参数：
            sec_user_id: 目标用户的 sec_user_id。
            cursor: 分页游标。
            count: 每页数量。

        返回：
            喜欢列表接口原始响应 JSON。
        """
        headers = copy.copy(self._client.headers)
        headers["Referer"] = "https://www.douyin.com/user/self?showTab=like"
        return await self._client.get(
            "/aweme/v1/web/aweme/favorite/",
            {
                "aid": "6383",
                "sec_user_id": sec_user_id,
                "max_cursor": cursor,
                "count": count,
            },
            headers,
        )

    async def get_collected(self, cursor: int | str, count: int) -> dict[str, Any]:
        """获取当前登录账号收藏的作品列表（/aweme/v1/web/aweme/listcollection/，POST）。

        参数：
            cursor: 分页游标。
            count: 每页数量。

        返回：
            收藏列表接口原始响应 JSON。
        """
        headers = copy.copy(self._client.headers)
        headers["Referer"] = (
            "https://www.douyin.com/user/self?showTab=favorite_collection"
        )
        headers["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8"
        return await self._client.post(
            "/aweme/v1/web/aweme/listcollection/",
            {"count": count, "cursor": cursor},
            headers,
            {"aid": "6383"},
        )
