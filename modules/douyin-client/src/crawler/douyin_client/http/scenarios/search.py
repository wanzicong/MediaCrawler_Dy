# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音综合搜索接口客户端（按业务场景拆分）。

底层带签名的 GET 请求由注入的 ``DouyinClient`` 提供；本类只负责组装搜索域参数
与 Referer。
"""

from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from crawler.douyin_client.base.types import (
    PublishTimeType,
    SearchChannelType,
    SearchSortType,
)

if TYPE_CHECKING:
    from crawler.douyin_client.http.client import DouyinClient


class SearchApi:
    """抖音综合搜索接口客户端。"""

    def __init__(self, client: DouyinClient) -> None:
        self._client = client

    async def search(
        self,
        keyword: str,
        *,
        offset: int,
        search_id: str,
        publish_time: PublishTimeType,
        search_channel: SearchChannelType = SearchChannelType.general,
        sort_type: SearchSortType = SearchSortType.general,
    ) -> dict[str, Any]:
        """调用抖音综合搜索接口（/aweme/v1/web/general/search/single/）。

        参数：
            keyword: 搜索关键词。
            offset: 分页偏移量。
            search_id: 搜索会话 ID（由调用方生成，分页间保持一致）。
            publish_time: 发布时间筛选。
            search_channel: 搜索频道（综合/视频/用户/直播）。
            sort_type: 排序方式。

        返回：
            搜索接口原始响应 JSON。
        """
        params: dict[str, Any] = {
            "search_channel": search_channel.value,
            "enable_history": "1",
            "keyword": keyword,
            "search_source": "tab_search",
            "query_correct_type": "1",
            "is_filter_search": "0",
            "from_group_id": "7378810571505847586",
            "offset": offset,
            "count": "15",
            "need_filter_settings": "1",
            "list_type": "multi",
            "search_id": search_id,
        }
        if (
            sort_type != SearchSortType.general
            or publish_time != PublishTimeType.unlimited
        ):
            params["filter_selected"] = json.dumps(
                {
                    "sort_type": str(sort_type.value),
                    "publish_time": str(publish_time.value),
                }
            )
            params["is_filter_search"] = 1
        referer = f"https://www.douyin.com/search/{keyword}?type=general"
        headers = copy.copy(self._client.headers)
        headers["Referer"] = quote(referer, safe=":/")
        return await self._client.get(
            "/aweme/v1/web/general/search/single/", params, headers
        )
