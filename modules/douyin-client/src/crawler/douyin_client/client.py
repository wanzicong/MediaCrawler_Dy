# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音 Web API 客户端封装。

提供带 a_bogus 签名的 GET/POST 请求、cookie 同步，
以及搜索、作品详情、评论、用户资料等业务接口的调用。
"""

import asyncio
import copy
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx
from crawler.douyin_client.errors import DataFetchError
from crawler.douyin_client.signer import get_a_bogus, get_web_id
from crawler.douyin_client.types import (
    PublishTimeType,
    SearchChannelType,
    SearchSortType,
)
from playwright.async_api import BrowserContext, Page
from playwright.async_api import Error as PlaywrightError

logger = logging.getLogger(__name__)
# 评论批次回调：参数为 aweme_id 与本批评论原始字典列表
CommentCallback = Callable[[str, list[dict[str, Any]]], Awaitable[None]]
# 请求间隔（秒）：可为固定数值，或返回数值的可调用对象
IntervalProvider = float | Callable[[], float]


@dataclass
class DouyinRequestLogEntry:
    """一次抖音接口调用的可观测记录。

    该对象仅在进程内短暂存在；上层落库前必须脱敏 Cookie、令牌、签名与账号标识。
    响应侧仅在失败时短暂携带返回快照；上层落库前必须继续脱敏并限长。
    """

    method: str  # HTTP 方法
    path: str  # 请求路径（不含查询串）
    url: str  # 完整请求地址
    query_params: dict[str, Any]  # 签名后的完整查询参数
    request_headers: dict[str, str]  # 实际发送的全部请求头
    request_body: dict[str, Any] | None  # POST 表单数据（签名后），GET 为 None
    response_status: int | None  # 响应状态码；网络异常时为 None
    duration_ms: int  # 请求耗时（毫秒）
    error: str | None  # 异常类型名；成功时为 None
    failure_detail: dict[str, Any] | None = None  # 失败响应快照；成功时为 None


# 抖音请求日志回调：由上层应用注册，每次抖音接口调用完成后触发
RequestLogCallback = Callable[["DouyinClient", DouyinRequestLogEntry], Awaitable[None]]


def _interval_seconds(interval: IntervalProvider) -> float:
    """将固定值或可调用形式的间隔配置统一解析为秒数。"""
    return interval() if callable(interval) else interval


def convert_cookies(cookies: list[dict[str, Any]]) -> tuple[str, dict[str, str]]:
    """将 Playwright cookie 字典列表转换为 cookie 字符串与名值字典。

    参数：
        cookies: Playwright 导出的 cookie 字典列表。

    返回：
        (cookie 字符串, cookie 名值字典) 二元组。
    """
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
    """读取浏览器上下文中指定 URL 的 cookie，返回 cookie 字符串与名值字典。"""
    cookies = await browser_context.cookies(urls=urls)
    return convert_cookies(cookies)  # type: ignore[arg-type]


class DouyinClient:
    """抖音 Web API 客户端。

    封装带签名的请求、cookie 同步以及搜索、作品、评论、用户等接口调用；
    通过类方法 create 基于现有浏览器会话构造。
    """

    host = "https://www.douyin.com"  # 抖音 Web 主站地址
    cookie_urls = [  # 需要收集 cookie 的抖音相关域名
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
        """初始化客户端。

        参数：
            page: Playwright 页面（用于读取 localStorage 中的 msToken 等信息）。
            headers: 默认请求头（含 User-Agent 与 Cookie）。
            cookie_dict: cookie 名值字典。
            timeout: HTTP 请求超时时间（秒）。
            verify_ssl: 是否校验 SSL 证书。
        """
        self.page = page
        self.headers = headers
        self.cookie_dict = cookie_dict
        self.http = httpx.AsyncClient(
            timeout=timeout,
            verify=verify_ssl,
            trust_env=False,
            follow_redirects=False,
        )
        # 抖音请求日志回调（可选）：注册后每次接口调用完成都会触发
        self.request_logger: RequestLogCallback | None = None

    @classmethod
    async def create(
        cls,
        *,
        page: Page,
        browser_context: BrowserContext,
        timeout: float,
        verify_ssl: bool,
    ) -> "DouyinClient":
        """基于现有浏览器会话创建客户端。

        从浏览器上下文收集 cookie，从页面读取真实 User-Agent 组装默认请求头。

        参数：
            page: 已打开抖音站点的 Playwright 页面。
            browser_context: 浏览器上下文。
            timeout: HTTP 请求超时时间（秒）。
            verify_ssl: 是否校验 SSL 证书。

        返回：
            初始化完成的 DouyinClient。
        """
        cookie_string, cookie_dict = await browser_cookies(
            browser_context, cls.cookie_urls
        )
        user_agent = str(await cls._evaluate_stable(page, "() => navigator.userAgent"))
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

    @staticmethod
    async def _evaluate_stable(page: Page, expression: str) -> Any:
        """在页面导航竞态下重试 evaluate，避免瞬时上下文销毁让整个任务失败。"""
        for attempt in range(3):
            try:
                return await page.evaluate(expression)
            except PlaywrightError as exc:
                if "Execution context was destroyed" not in str(exc) or attempt == 2:
                    raise
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=3_000)
                except PlaywrightError:
                    pass
                await asyncio.sleep(0.1 * (attempt + 1))
        raise RuntimeError("页面执行上下文不可用")  # pragma: no cover

    async def close(self) -> None:
        """关闭底层 HTTP 连接。"""
        await self.http.aclose()

    @staticmethod
    def _failure_detail_from_response(response: httpx.Response) -> dict[str, Any]:
        """提取失败响应快照；正文预览在业务层落库前还会再次脱敏与限长。"""
        detail: dict[str, Any] = {
            "http_status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
        }
        if not response.content:
            detail["body"] = ""
            return detail
        try:
            detail["body"] = response.json()
        except ValueError:
            body = response.text
            detail["body"] = body[:8192]
            detail["truncated"] = len(body) > 8192
        return detail

    async def _process_params(
        self,
        uri: str,
        params: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """补全抖音 Web 端公共请求参数并计算 a_bogus 签名。

        从页面 localStorage 读取 msToken（xmst），拼装模拟浏览器环境的公共参数；
        除综合搜索接口外，均调用签名脚本计算 a_bogus。

        参数：
            uri: 请求路径。
            params: 业务请求参数（会被原地补充公共参数与签名）。
            headers: 请求头（签名需要其中的 User-Agent）。

        返回：
            补全后的请求参数。
        """
        local_storage = await self._evaluate_stable(
            self.page, "() => window.localStorage"
        )
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
        """发送 HTTP 请求并校验响应为 JSON 对象。

        参数：
            method: HTTP 方法。
            url: 完整请求地址。

        返回：
            响应 JSON（保证为 dict）。

        异常：
            DataFetchError: 网络错误、响应为空/被拦截、或响应不是 JSON 对象时抛出。
        """
        started = time.monotonic()
        entry = DouyinRequestLogEntry(
            method=method,
            path=urlsplit(url).path,
            url=url,
            query_params=(
                dict(kwargs["params"]) if isinstance(kwargs.get("params"), dict) else {}
            ),
            request_headers=dict(
                kwargs.get("headers") or getattr(self, "headers", None) or {}
            ),
            request_body=(
                dict(kwargs["data"]) if isinstance(kwargs.get("data"), dict) else None
            ),
            response_status=None,
            duration_ms=0,
            error=None,
        )
        try:
            try:
                response: httpx.Response | None = None
                for attempt in range(3):
                    try:
                        response = await self.http.request(method, url, **kwargs)
                        entry.response_status = response.status_code
                        response.raise_for_status()
                        break
                    except httpx.TransportError:
                        if attempt == 2:
                            raise
                        await asyncio.sleep(0.25 * (attempt + 1))
                if response is None:  # pragma: no cover - 防御性保护
                    raise httpx.RequestError("抖音请求未返回响应")
            except httpx.HTTPError as exc:
                # HTTPX 异常会保留完整签名后的请求 URL。此处切断异常链，
                # 确保 msToken/a_bogus 永远不会进入 traceback 日志。
                entry.error = type(exc).__name__
                if isinstance(exc, httpx.HTTPStatusError):
                    entry.failure_detail = self._failure_detail_from_response(
                        exc.response
                    )
                else:
                    entry.failure_detail = {
                        "kind": "transport_error",
                        "exception_type": type(exc).__name__,
                        "message": "网络请求未收到 HTTP 响应",
                    }
                raise DataFetchError(f"抖音请求失败: {type(exc).__name__}") from None
            body = response.text
            if not body or body == "blocked":
                entry.error = "blocked" if body == "blocked" else "empty"
                entry.failure_detail = self._failure_detail_from_response(response)
                raise DataFetchError(
                    f"抖音请求被拒绝: status={response.status_code}, body={'empty' if not body else 'blocked'}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                entry.error = "non-json"
                entry.failure_detail = self._failure_detail_from_response(response)
                raise DataFetchError(
                    f"抖音响应不是 JSON: status={response.status_code}, length={len(response.content)}"
                ) from exc
            if not isinstance(payload, dict):
                entry.error = "non-object"
                entry.failure_detail = self._failure_detail_from_response(response)
                raise DataFetchError("抖音响应 JSON 顶层不是对象")
            business_status = payload.get("status_code")
            if business_status not in (None, 0, "0"):
                normalized_status = str(business_status)[:32]
                entry.error = f"DouyinBusinessError:{normalized_status}"
                entry.failure_detail = self._failure_detail_from_response(response)
                raise DataFetchError(
                    f"抖音接口业务状态失败: status_code={normalized_status}"
                )
            return payload
        finally:
            entry.duration_ms = int((time.monotonic() - started) * 1000)
            await self._emit_request_log(entry)

    async def _emit_request_log(self, entry: DouyinRequestLogEntry) -> None:
        """把请求记录交给上层注册的回调；回调失败仅记日志，不影响爬取。"""
        request_logger: RequestLogCallback | None = getattr(
            self, "request_logger", None
        )
        if request_logger is None:
            return
        try:
            await request_logger(self, entry)
        except Exception:
            logger.exception("抖音请求日志回调失败")

    async def get(
        self,
        uri: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """发送带公共参数与签名的 GET 请求。

        参数：
            uri: 接口路径（自动拼接主站 host）。
            params: 查询参数。
            headers: 自定义请求头，缺省使用客户端默认请求头。

        返回：
            响应 JSON 字典。
        """
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
        """发送带公共参数与签名的 POST 请求。

        参数：
            uri: 接口路径（自动拼接主站 host）。
            data: 表单请求体；params 为 None 时同时作为签名依据。
            headers: 自定义请求头，缺省使用客户端默认请求头。
            params: 查询参数；提供时仅对它做签名，data 原样作为请求体。

        返回：
            响应 JSON 字典。
        """
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
        """从浏览器上下文重新收集 cookie，并同步到请求头与 cookie_dict。"""
        cookie_string, cookie_dict = await browser_cookies(
            browser_context, self.cookie_urls
        )
        self.headers["Cookie"] = cookie_string
        self.cookie_dict = cookie_dict

    async def pong(
        self, browser_context: BrowserContext, require_self_profile: bool = False
    ) -> bool:
        """检测当前会话的抖音登录状态。

        require_self_profile 为 False 时，先查页面 localStorage 的 HasUserLogin
        与 cookie 的 LOGIN_STATUS 做快速判断，未命中再调用本人资料接口兜底；
        为 True 时跳过本地快速检查，直接调用接口校验。

        参数：
            browser_context: 浏览器上下文。
            require_self_profile: 是否强制通过本人资料接口校验登录状态。

        返回：
            已登录返回 True，否则 False。
        """
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
        headers = copy.copy(self.headers)
        headers["Referer"] = quote(referer, safe=":/")
        return await self.get("/aweme/v1/web/general/search/single/", params, headers)

    async def get_video(self, aweme_id: str) -> dict[str, Any]:
        """获取作品详情（/aweme/v1/web/aweme/detail/）。

        参数：
            aweme_id: 作品 ID。

        返回：
            作品详情字典（aweme_detail），缺失或类型不符时返回空字典。
        """
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
        """获取作品一级评论分页（/aweme/v1/web/comment/list/）。

        参数：
            aweme_id: 作品 ID。
            cursor: 分页游标。
            keyword: 来源搜索关键词，仅用于构造 Referer。

        返回：
            评论接口原始响应 JSON（含 comments、cursor、has_more）。
        """
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
        """获取某条评论的子评论（回复）分页（/aweme/v1/web/comment/list/reply/）。

        参数：
            aweme_id: 作品 ID。
            comment_id: 一级评论 ID。
            cursor: 分页游标。
            keyword: 来源搜索关键词，仅用于构造 Referer。

        返回：
            子评论接口原始响应 JSON。
        """
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

    async def get_user_info(self, sec_user_id: str) -> dict[str, Any]:
        """获取其他用户的公开资料（/aweme/v1/web/user/profile/other/）。

        参数：
            sec_user_id: 目标用户的 sec_user_id。

        返回：
            用户资料接口原始响应 JSON。
        """
        return await self.get(
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
        headers = copy.copy(self.headers)
        headers["Referer"] = "https://www.douyin.com/user/self"
        return await self.get(
            "/aweme/v1/web/user/profile/self/", {"aid": "6383"}, headers
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
        """获取当前登录账号收藏的作品列表（/aweme/v1/web/aweme/listcollection/，POST）。

        参数：
            cursor: 分页游标。
            count: 每页数量。

        返回：
            收藏列表接口原始响应 JSON。
        """
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
        """获取用户发布的作品列表（/aweme/v1/web/aweme/post/）。

        参数：
            sec_user_id: 目标用户的 sec_user_id。
            cursor: 分页游标。

        返回：
            作品列表接口原始响应 JSON。
        """
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
            request_headers=dict(getattr(self, "headers", None) or {}),
            request_body=None,
            response_status=None,
            duration_ms=0,
            error=None,
        )
        try:
            response = await self.http.get(short_url, follow_redirects=True)
            entry.response_status = response.status_code
            response.raise_for_status()
            return str(response.url)
        except httpx.HTTPError as exc:
            entry.error = type(exc).__name__
            if isinstance(exc, httpx.HTTPStatusError):
                entry.failure_detail = self._failure_detail_from_response(exc.response)
            else:
                entry.failure_detail = {
                    "kind": "transport_error",
                    "exception_type": type(exc).__name__,
                    "message": "网络请求未收到 HTTP 响应",
                }
            raise DataFetchError(f"抖音短链解析失败: {type(exc).__name__}") from exc
        finally:
            entry.duration_ms = int((time.monotonic() - started) * 1000)
            await self._emit_request_log(entry)
