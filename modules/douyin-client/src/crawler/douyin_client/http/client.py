# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音 Web API 客户端主机会话与签名传输。

本文件保留 ``DouyinClient`` 的会话身份与传输引擎：cookie 同步、登录状态探测、
带 a_bogus 签名的 GET/POST/request。搜索、作品、评论、用户、短链等读接口已按业务
场景拆分到 ``http/scenarios/``，经组合属性访问（``client.search_api`` 等），本类
不再直接持有业务方法。
"""

import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from crawler.douyin_client.base.errors import DataFetchError
from crawler.douyin_client.base.signer import get_a_bogus, get_web_id
from crawler.douyin_client.http.request_log import (
    DouyinRequestLogEntry,
    RequestLogCallback,
    browser_cookies,
)
from crawler.douyin_client.http.scenarios.aweme import AwemeApi
from crawler.douyin_client.http.scenarios.comments import CommentsApi
from crawler.douyin_client.http.scenarios.resolver import ShortUrlApi
from crawler.douyin_client.http.scenarios.search import SearchApi
from crawler.douyin_client.http.scenarios.user import UserApi
from playwright.async_api import BrowserContext, Page
from playwright.async_api import Error as PlaywrightError

logger = logging.getLogger(__name__)

# 抖音下面的 Web API 客户端，持有浏览器 cookie、默认请求头与签名后的 httpx 会话，并提供登录态探测与 cookie 同步。
class DouyinClient:
    """抖音 Web API 客户端（主机会话 + 签名传输 + 场景客户端容器）。

    持有浏览器 cookie、默认请求头与签名后的 httpx 会话，并提供登录态探测与
    cookie 同步；搜索/作品/评论/用户/短链读接口挂在 ``search_api``/``aweme_api``/
    ``comments_api``/``user_api``/``resolver_api`` 组合属性上。
    """

    host = "https://www.douyin.com"  # 抖音 Web 主站地址
    cookie_urls = [  # 需要收集 cookie 的抖音相关域名
        "https://douyin.com",
        host,
        "https://creator.douyin.com",
        "https://douhot.douyin.com",
        "https://live.douyin.com",
    ]

    # 代码初始化客户端时，必须提供 Playwright 页面对象、默认请求头、cookie 字典、超时时间与 SSL 校验选项。  
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
        # 按业务场景拆分的读接口客户端（共享本会话的 cookie 与签名传输）。
        self.search_api = SearchApi(self)
        self.aweme_api = AwemeApi(self)
        self.comments_api = CommentsApi(self)
        self.user_api = UserApi(self)
        self.resolver_api = ShortUrlApi(self)

    # 通过现有浏览器会话创建客户端，自动收集 cookie 并读取 User-Agent 组装默认请求头。
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

    # 关闭底层 HTTP 连接。
    async def close(self) -> None:
        """关闭底层 HTTP 连接。"""
        await self.http.aclose()

    # 发送 HTTP 请求并校验响应为 JSON 对象。
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

    # 发送带公共参数与签名的 GET 请求。
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

    # 发送带公共参数与签名的 POST 请求。
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

    # 检测当前会话的抖音登录状态。
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
            response = await self.user_api.get_self_profile()
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


        # 从浏览器上下文重新收集 cookie，并同步到请求头与 cookie_dict。
    
    # 更新客户端的 cookie 信息，从浏览器上下文中重新收集 cookie，并同步到请求头和 cookie_dict 中。
    async def update_cookies(self, browser_context: BrowserContext) -> None:
        """从浏览器上下文重新收集 cookie，并同步到请求头与 cookie_dict。"""
        cookie_string, cookie_dict = await browser_cookies(
            browser_context, self.cookie_urls
        )
        self.headers["Cookie"] = cookie_string
        self.cookie_dict = cookie_dict
    
    # 在页面导航竞态下重试 evaluate，避免瞬时上下文销毁让整个任务失败。
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

    # 提取失败响应快照；正文预览在业务层落库前还会再次脱敏与限长。
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

    # 补全抖音 Web 端公共请求参数并计算 a_bogus 签名。
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

    # 记录请求日志回调；回调失败仅记日志，不影响爬取。
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
