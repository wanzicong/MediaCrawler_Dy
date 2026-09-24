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
        user_id: str = "",
    ) -> dict[str, Any]:
        """获取用户（自己）的关注列表（/aweme/v1/web/user/following/list/）。

        2026-09-24 抓浏览器「关注」标签页的真实请求确认并实测：

        - ``source_type`` 必须是 **4**（我们原先发 1，接口只给前 ~40 条就
          ``has_more=false``，怎么改游标都翻不动）；
        - 翻页靠 **``offset``** 递增（``min_time`` / ``max_time`` 恒为 0，
          浏览器自己也是这么发的），offset=0/20/40… 每页 20 条且不重复；
        - 真实请求还带 ``user_id`` / ``is_top=1`` / ``gps_access=0`` /
          ``address_book_access=0``，一并对齐。

        参数：
            sec_user_id: 目标账号（本人）的 sec_user_id。
            cursor: 保留的历史游标参数（当前固定发 0，分页以 offset 为准）。
            count: 每页数量。
            offset: 已拉取条数（服务端按它做偏移，是唯一有效的分页游标）。
            user_id: 本人 uid（浏览器真实请求会带，缺失时传空串）。

        返回：
            关注列表接口原始响应 JSON（``followings`` 为关注用户列表）。
        """
        headers = copy.copy(self._client.headers)
        headers["Referer"] = "https://www.douyin.com/user/self?showTab=following"
        return await self._client.get(
            "/aweme/v1/web/user/following/list/",
            {
                "user_id": user_id,
                "sec_user_id": sec_user_id,
                "offset": offset,
                "min_time": 0,
                "max_time": cursor,
                "count": count,
                "source_type": 4,
                "is_top": 1,
                "gps_access": 0,
                "address_book_access": 0,
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
