# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音作品（aweme）读接口客户端（按业务场景拆分）。

承载作品详情与用户发布列表；底层带签名的 GET 请求由注入的 ``DouyinClient`` 提供。
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from crawler.douyin_client.http.client import DouyinClient


class AwemeApi:
    """抖音作品（aweme）读接口客户端。"""

    def __init__(self, client: DouyinClient) -> None:
        self._client = client

    async def get_video(self, aweme_id: str) -> dict[str, Any]:
        """获取作品详情（/aweme/v1/web/aweme/detail/）。

        参数：
            aweme_id: 作品 ID。

        返回：
            作品详情字典（aweme_detail），缺失或类型不符时返回空字典。
        """
        headers = copy.copy(self._client.headers)
        headers.pop("Origin", None)
        response = await self._client.get(
            "/aweme/v1/web/aweme/detail/", {"aweme_id": aweme_id}, headers
        )
        detail = response.get("aweme_detail") or {}
        return detail if isinstance(detail, dict) else {}

    async def get_user_posts(
        self, sec_user_id: str, cursor: str = ""
    ) -> dict[str, Any]:
        """获取用户发布的作品列表（/aweme/v1/web/aweme/post/）。

        参数：
            sec_user_id: 目标用户的 sec_user_id。
            cursor: 分页游标。

        返回：
            作品列表接口原始响应 JSON。
        """
        return await self._client.get(
            "/aweme/v1/web/aweme/post/",
            {
                "sec_user_id": sec_user_id,
                "count": 18,
                "max_cursor": cursor,
                "locate_query": "false",
                "publish_video_strategy_type": 2,
            },
        )
