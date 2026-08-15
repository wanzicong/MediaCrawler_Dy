# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

import asyncio
import copy
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from playwright.async_api import BrowserContext, Page

from app.integrations.douyin.exceptions import DataFetchError
from app.integrations.douyin.signer import get_a_bogus, get_web_id
from app.integrations.douyin.types import (
    PublishTimeType,
    SearchChannelType,
    SearchSortType,
)

logger = logging.getLogger(__name__)
CommentCallback = Callable[[str, list[dict[str, Any]]], Awaitable[None]]
IntervalProvider = float | Callable[[], float]


def _interval_seconds(interval: IntervalProvider) -> float:
    return interval() if callable(interval) else interval


def convert_cookies(cookies: list[dict[str, Any]]) -> tuple[str, dict[str, str]]:
    cookie_dict = {
        str(cookie.get("name")): str(cookie.get("value"))
        for cookie in cookies
        if cookie.get("name")
    }
    cookie_string = ";".join(f"{key}={value}" for key, value in cookie_dict.items())
    return cookie_string, cookie_dict


async def browser_cookies(
    browser_context: BrowserContext, urls: list[str]
) -> tuple[str, dict[str, str]]:
    cookies = await browser_context.cookies(urls=urls)
    return convert_cookies(cookies)  # type: ignore[arg-type]


class DouyinClient:
    host = "https://www.douyin.com"
    cookie_urls = [
        "https://douyin.com",
        host,
        "https://creator.douyin.com",
        "https://douhot.douyin.com",
        "https://live.douyin.com",
    ]

    def __init__(
        self,
        *,
        page: Page,
        headers: dict[str, str],
        cookie_dict: dict[str, str],
        timeout: float,
        verify_ssl: bool,
    ):
        self.page = page
        self.headers = headers
        self.cookie_dict = cookie_dict
        self.http = httpx.AsyncClient(
            timeout=timeout,
            verify=verify_ssl,
            trust_env=False,
            follow_redirects=False,
        )

    @classmethod
    async def create(
        cls,
        *,
        page: Page,
        browser_context: BrowserContext,
        timeout: float,
        verify_ssl: bool,
    ) -> "DouyinClient":
        cookie_string, cookie_dict = await browser_cookies(
            browser_context, cls.cookie_urls
        )
        user_agent = str(await page.evaluate("() => navigator.userAgent"))
        return cls(
            page=page,
            headers={
                "User-Agent": user_agent,
                "Cookie": cookie_string,
                "Host": "www.douyin.com",
                "Origin": "https://www.douyin.com/",
                "Referer": "https://www.douyin.com/",
                "Content-Type": "application/json;charset=UTF-8",
            },
            cookie_dict=cookie_dict,
            timeout=timeout,
            verify_ssl=verify_ssl,
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def _process_params(
        self,
        uri: str,
        params: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        local_storage = await self.page.evaluate("() => window.localStorage")
        if not isinstance(local_storage, dict):
            local_storage = {}
        params.update(
            {
                "device_platform": "webapp",
                "aid": "6383",
                "channel": "channel_pc_web",
                "version_code": "190600",
                "version_name": "19.6.0",
                "update_version_code": "170400",
                "pc_client_type": "1",
                "cookie_enabled": "true",
                "browser_language": "zh-CN",
                "browser_platform": "MacIntel",
                "browser_name": "Chrome",
                "browser_version": "125.0.0.0",
                "browser_online": "true",
                "engine_name": "Blink",
                "engine_version": "109.0",
                "os_name": "Mac OS",
                "os_version": "10.15.7",
                "cpu_core_num": "8",
                "device_memory": "8",
                "platform": "PC",
                "screen_width": "2560",
                "screen_height": "1440",
                "effective_type": "4g",
                "round_trip_time": "50",
                "webid": get_web_id(),
                "msToken": local_storage.get("xmst"),
            }
        )
        if "/v1/web/general/search" not in uri:
            params["a_bogus"] = get_a_bogus(
                uri, urlencode(params), headers["User-Agent"]
            )
        return params

    async def request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self.http.request(method, url, **kwargs)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # HTTPX exceptions retain the fully signed request URL. Suppress the
            # exception chain so msToken/a_bogus can never reach traceback logs.
            raise DataFetchError(f"抖音请求失败: {type(exc).__name__}") from None
        body = response.text
        if not body or body == "blocked":
            raise DataFetchError(
                f"抖音请求被拒绝: status={response.status_code}, body={'empty' if not body else 'blocked'}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise DataFetchError(
                f"抖音响应不是 JSON: status={response.status_code}, length={len(response.content)}"
            ) from exc
        if not isinstance(payload, dict):
            raise DataFetchError("抖音响应 JSON 顶层不是对象")
        return payload

    async def get(
        self,
        uri: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        request_headers = headers or self.headers
        request_params = await self._process_params(
            uri, dict(params or {}), request_headers
        )
        return await self.request(
            "GET", f"{self.host}{uri}", params=request_params, headers=request_headers
        )

    async def post(
        self,
        uri: str,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_headers = headers or self.headers
        signing_params = dict(params if params is not None else data)
        signed_params = await self._process_params(uri, signing_params, request_headers)
        request_kwargs: dict[str, Any] = {
            "data": signed_params if params is None else data,
            "headers": request_headers,
        }
        if params is not None:
            request_kwargs["params"] = signed_params
        return await self.request("POST", f"{self.host}{uri}", **request_kwargs)

    async def update_cookies(self, browser_context: BrowserContext) -> None:
        cookie_string, cookie_dict = await browser_cookies(
            browser_context, self.cookie_urls
        )
        self.headers["Cookie"] = cookie_string
        self.cookie_dict = cookie_dict

    async def pong(
        self, browser_context: BrowserContext, require_self_profile: bool = False
    ) -> bool:
        if not require_self_profile:
            try:
                local_storage = await self.page.evaluate("() => window.localStorage")
            except Exception:
                local_storage = {}
            if (
                isinstance(local_storage, dict)
                and local_storage.get("HasUserLogin") == "1"
            ):
                return True
            _, cookies = await browser_cookies(browser_context, self.cookie_urls)
            if cookies.get("LOGIN_STATUS") == "1":
                return True
        try:
            response = await self.get_self_profile()
        except Exception:
            return False
        if response.get("status_code") not in (0, "0"):
            return False
        data = response.get("data")
        profile = (
            response.get("user")
            or response.get("user_info")
            or (data.get("user") if isinstance(data, dict) else None)
            or (data.get("user_info") if isinstance(data, dict) else None)
            or data
        )
        return isinstance(profile, dict) and bool(
            profile.get("uid") or profile.get("sec_uid") or profile.get("sec_user_id")
        )

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
        headers = copy.copy(self.headers)
        headers["Referer"] = quote(referer, safe=":/")
        return await self.get("/aweme/v1/web/general/search/single/", params, headers)

    async def get_video(self, aweme_id: str) -> dict[str, Any]:
        headers = copy.copy(self.headers)
        headers.pop("Origin", None)
        response = await self.get(
            "/aweme/v1/web/aweme/detail/", {"aweme_id": aweme_id}, headers
        )
        detail = response.get("aweme_detail") or {}
        return detail if isinstance(detail, dict) else {}

    async def get_comments_page(
        self, aweme_id: str, cursor: int, keyword: str = ""
    ) -> dict[str, Any]:
        headers = copy.copy(self.headers)
        headers["Referer"] = quote(
            f"https://www.douyin.com/search/{keyword}?type=general", safe=":/"
        )
        return await self.get(
            "/aweme/v1/web/comment/list/",
            {"aweme_id": aweme_id, "cursor": cursor, "count": 20, "item_type": 0},
            headers,
        )

    async def get_sub_comments_page(
        self, aweme_id: str, comment_id: str, cursor: int, keyword: str = ""
    ) -> dict[str, Any]:
        headers = copy.copy(self.headers)
        headers["Referer"] = quote(
            f"https://www.douyin.com/search/{keyword}?type=general", safe=":/"
        )
        return await self.get(
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

    async def get_user_info(self, sec_user_id: str) -> dict[str, Any]:
        return await self.get(
            "/aweme/v1/web/user/profile/other/",
            {
                "sec_user_id": sec_user_id,
                "publish_video_strategy_type": 2,
                "personal_center_strategy": 1,
            },
        )

    async def get_self_profile(self) -> dict[str, Any]:
        headers = copy.copy(self.headers)
        headers["Referer"] = "https://www.douyin.com/user/self"
        return await self.get(
            "/aweme/v1/web/user/profile/self/", {"aid": "6383"}, headers
        )

    async def get_liked(
        self, sec_user_id: str, cursor: int | str, count: int
    ) -> dict[str, Any]:
        headers = copy.copy(self.headers)
        headers["Referer"] = "https://www.douyin.com/user/self?showTab=like"
        return await self.get(
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
        headers = copy.copy(self.headers)
        headers["Referer"] = (
            "https://www.douyin.com/user/self?showTab=favorite_collection"
        )
        headers["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8"
        return await self.post(
            "/aweme/v1/web/aweme/listcollection/",
            {"count": count, "cursor": cursor},
            headers,
            {"aid": "6383"},
        )

    async def get_user_posts(
        self, sec_user_id: str, cursor: str = ""
    ) -> dict[str, Any]:
        return await self.get(
            "/aweme/v1/web/aweme/post/",
            {
                "sec_user_id": sec_user_id,
                "count": 18,
                "max_cursor": cursor,
                "locate_query": "false",
                "publish_video_strategy_type": 2,
            },
        )

    async def resolve_short_url(self, short_url: str) -> str:
        try:
            response = await self.http.get(short_url, follow_redirects=True)
            response.raise_for_status()
            return str(response.url)
        except httpx.HTTPError as exc:
            raise DataFetchError(f"抖音短链解析失败: {type(exc).__name__}") from exc
