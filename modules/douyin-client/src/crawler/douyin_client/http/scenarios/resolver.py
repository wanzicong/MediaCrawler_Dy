# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音短链解析客户端（按业务场景拆分）。

跟随 v.douyin.com 短链重定向返回最终 URL；不经签名引擎，由注入的 ``DouyinClient``
提供底层 HTTP 客户端与请求日志上报。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx
from crawler.douyin_client.errors.family import DataFetchError
from crawler.douyin_client.http.request_log import DouyinRequestLogEntry

if TYPE_CHECKING:
    from crawler.douyin_client.http.client import DouyinClient


class ShortUrlApi:
    """抖音短链解析客户端。"""

    def __init__(self, client: DouyinClient) -> None:
        self._client = client

    async def resolve_short_url(self, short_url: str) -> str:
        """解析 v.douyin.com 短链，跟随重定向返回最终 URL。

        参数：
            short_url: 抖音短链。

        返回：
            重定向后的完整 URL。

        异常：
            DataFetchError: 请求或重定向失败时抛出。
        """
        started = time.monotonic()
        entry = DouyinRequestLogEntry(
            method="GET",
            path=urlsplit(short_url).path,
            url=short_url,
            query_params={},
            request_headers=dict(getattr(self._client, "headers", None) or {}),
            request_body=None,
            response_status=None,
            duration_ms=0,
            error=None,
        )
        try:
            response = await self._client.http.get(short_url, follow_redirects=True)
            entry.response_status = response.status_code
            response.raise_for_status()
            return str(response.url)
        except httpx.HTTPError as exc:
            entry.error = type(exc).__name__
            if isinstance(exc, httpx.HTTPStatusError):
                entry.failure_detail = self._client._failure_detail_from_response(
                    exc.response
                )
            else:
                entry.failure_detail = {
                    "kind": "transport_error",
                    "exception_type": type(exc).__name__,
                    "message": "网络请求未收到 HTTP 响应",
                }
            raise DataFetchError(f"抖音短链解析失败: {type(exc).__name__}") from exc
        finally:
            entry.duration_ms = int((time.monotonic() - started) * 1000)
            await self._client._emit_request_log(entry)
