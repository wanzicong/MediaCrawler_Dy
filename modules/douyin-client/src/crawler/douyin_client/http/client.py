# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音 Web API 客户端主机会话与签名传输。

本文件保留 ``DouyinClient`` 的会话身份与传输引擎：cookie 同步、登录状态探测、
带 a_bogus 签名的 GET/POST/request。搜索、作品、评论、用户、短链等读接口已按业务
场景拆分到 ``http/scenarios/``，经组合属性访问（``client.search_api`` 等），本类
不再直接持有业务方法。

浏览器依赖已完全外置：会话能力（UA / localStorage / cookie / 请求指纹）由构造时
注入的 :class:`crawler.douyin_client.session.context.SessionContext` 提供；本模块
不 import 任何浏览器实现，``import crawler.douyin_client`` 不会加载 playwright。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from crawler.douyin_client.errors.family import DataFetchError
from crawler.douyin_client.http.request_log import (
    DouyinRequestLogEntry,
    RequestLogCallback,
)
from crawler.douyin_client.http.scenarios.aweme import AwemeApi
from crawler.douyin_client.http.scenarios.comments import CommentsApi
from crawler.douyin_client.http.scenarios.resolver import ShortUrlApi
from crawler.douyin_client.http.scenarios.search import SearchApi
from crawler.douyin_client.http.scenarios.user import UserApi
from crawler.douyin_client.session.context import SessionContext
from crawler.douyin_client.signing.a_bogus import get_a_bogus
from crawler.douyin_client.signing.web_id import get_web_id

logger = logging.getLogger(__name__)

# 只有网关侧的瞬时不可用才值得重签名重试；403（风控拦截）与 429（限流）
# 重试只会加重风控，状态判定按白名单写在 request() 内（见 _RetryableStatus）。
_RETRYABLE_STATUS_CODES = frozenset({502, 503, 504})

# 签名层重试次数与固定退避阶梯（第 n 次重试前等待 _RETRY_BACKOFF_SECONDS[n-1]）。
_MAX_SIGNING_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS: tuple[float, ...] = (0.5, 1.5)


class _RetryableStatus(DataFetchError):
    """HTTP 502/503/504 瞬时状态失败，只允许由 ``request()`` 白名单构造。

    继承 ``DataFetchError`` 以保住既有 ``except DataFetchError`` 调用方的兼容性；
    它是唯一被 ``get()``/``post()`` 重试循环捕获的异常类型，而 403/429 与业务
    状态失败产生的是 ``DataFetchError`` 本身（非本类型），因此那些失败在类型层面
    就进不了重试分支。
    """

    def __init__(self, status_code: int) -> None:
        super().__init__(f"抖音请求返回可重试状态: status_code={status_code}")
        self.status_code = status_code


# 抖音下面的 Web API 客户端，持有会话 cookie、默认请求头与签名后的 httpx 会话，并提供登录态探测与 cookie 同步。
class DouyinClient:
    """抖音 Web API 客户端（主机会话 + 签名传输 + 场景客户端容器）。

    持有会话 cookie、默认请求头与签名后的 httpx 会话，并提供登录态探测与
    cookie 同步；搜索/作品/评论/用户/短链读接口挂在 ``search_api``/``aweme_api``/
    ``comments_api``/``user_api``/``resolver_api`` 组合属性上。

    浏览器侧的全部输入经构造参数 ``session`` 注入（结构化满足 ``SessionContext``）：
    本类不持有页面对象、也不 import 浏览器实现。
    """

    host = "https://www.douyin.com"  # 抖音 Web 主站地址
    cookie_urls = [  # 需要收集 cookie 的抖音相关域名
        "https://douyin.com",
        host,
        "https://creator.douyin.com",
        "https://douhot.douyin.com",
        "https://live.douyin.com",
    ]

    # 抖音请求指纹的键表；与 ``crawler.browser.session.environment.DOUYIN_FINGERPRINT_KEYS``
    # 集合相等（门禁 G15）。它只声明「可写入哪些键」的能力，不承诺每个键都有值：
    # ``session.fingerprint()`` 缺哪个键就不写哪个键，绝不回退伪造常量。
    FINGERPRINT_KEYS: tuple[str, ...] = (
        "browser_language",
        "browser_platform",
        "browser_name",
        "browser_version",
        "engine_name",
        "engine_version",
        "os_name",
        "os_version",
        "cpu_core_num",
        "device_memory",
        "screen_width",
        "screen_height",
        "effective_type",
        "round_trip_time",
    )

    def __init__(
        self,
        *,
        session: SessionContext,
        headers: dict[str, str],
        cookie_dict: dict[str, str],
        timeout: float,
        verify_ssl: bool,
    ) -> None:
        """初始化客户端。

        参数：
            session: 浏览器会话能力（UA / localStorage / cookie / 请求指纹的唯一来源）。
            headers: 默认请求头（含 User-Agent 与 Cookie）。
            cookie_dict: cookie 名值字典。
            timeout: HTTP 请求超时时间（秒）。
            verify_ssl: 是否校验 SSL 证书。
        """
        self.session = session
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

    # 通过注入的会话上下文创建客户端，UA 与 cookie 全部由会话提供。
    @classmethod
    async def create(
        cls,
        *,
        session: SessionContext,
        timeout: float,
        verify_ssl: bool,
    ) -> DouyinClient:
        """基于注入的浏览器会话能力创建客户端。

        User-Agent 取 ``session.user_agent()``，Cookie 取
        ``session.cookies(cls.cookie_urls)``；请求指纹不在此处采集，而是由
        ``_process_params()`` 在每次发送尝试时经 ``session.fingerprint()`` 读取
        （实现方负责会话内缓存，因此重复读取不产生额外采集）。

        参数：
            session: 浏览器会话能力。
            timeout: HTTP 请求超时时间（秒）。
            verify_ssl: 是否校验 SSL 证书。

        返回：
            初始化完成的 DouyinClient。
        """
        cookie_string, cookie_dict = await session.cookies(cls.cookie_urls)
        user_agent = await session.user_agent()
        return cls(
            session=session,
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
            _RetryableStatus: 独有信号，仅当状态码命中 ``_RETRYABLE_STATUS_CODES``
                白名单（502/503/504）时抛出，由 ``get()``/``post()`` 重签名重试；
                它是 ``DataFetchError`` 子类，非重试调用方无需感知。
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
                        if response.status_code in _RETRYABLE_STATUS_CODES:
                            # 只在这里、只对白名单状态码构造可重试信号：模型层
                            # 重试的是「网关瞬时不可用」，而不是任何 4xx/业务失败。
                            entry.error = f"RetryableStatus:{response.status_code}"
                            entry.failure_detail = self._failure_detail_from_response(
                                response
                            )
                            raise _RetryableStatus(response.status_code)
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

        异常：
            DataFetchError: 三次签名尝试后仍失败，或遇到结构与业务失败时抛出。
        """
        request_headers = headers or self.headers
        base_params = dict(params or {})

        async def send() -> dict[str, Any]:
            # 每次尝试都从 base_params 的副本重新走一遍公共参数补全与签名。
            signed_params = await self._process_params(
                uri, dict(base_params), request_headers
            )
            return await self.request(
                "GET",
                f"{self.host}{uri}",
                params=signed_params,
                headers=request_headers,
            )

        return await self._send_with_resign(send)

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

        异常：
            DataFetchError: 三次签名尝试后仍失败，或遇到结构与业务失败时抛出。
        """
        request_headers = headers or self.headers
        # 每次尝试的签名输入与请求体都取自这两份副本，避免 a_bogus 在同一个
        # 字典上被二次签名叠成两个。
        base_signing = dict(params if params is not None else data)
        base_body = dict(data)

        async def send() -> dict[str, Any]:
            signed_params = await self._process_params(
                uri, dict(base_signing), request_headers
            )
            request_kwargs: dict[str, Any] = {
                "data": signed_params if params is None else dict(base_body),
                "headers": request_headers,
            }
            if params is not None:
                request_kwargs["params"] = signed_params
            return await self.request("POST", f"{self.host}{uri}", **request_kwargs)

        return await self._send_with_resign(send)

    # 重签名重试循环：只对 _RetryableStatus（502/503/504）重试。
    @staticmethod
    async def _send_with_resign(
        send: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        """执行 ``send``，仅在抛出 ``_RetryableStatus`` 时重签名重试。

        ``send`` 每次被调用都自带一次完整的公共参数补全与 a_bogus 重算，因此
        重试不会复用上一次的签名。除 ``_RetryableStatus`` 以外的任何异常都不在
        捕获范围内：403/429 与业务状态失败在 ``request()`` 里产生的是
        ``DataFetchError`` 本身，类型上不可能进入本循环的重试分支。

        参数：
            send: 无参协程工厂，一次「签名 + 请求」尝试。

        返回：
            成功响应的 JSON 字典。

        异常：
            _RetryableStatus: 连续 ``_MAX_SIGNING_ATTEMPTS`` 次仍是 5xx 时抛出。
        """
        attempt = 0
        while True:
            try:
                return await send()
            except _RetryableStatus:
                if attempt >= _MAX_SIGNING_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS[attempt])
                attempt += 1

    # 检测当前会话的抖音登录状态。
    async def pong(self, require_self_profile: bool = False) -> bool:
        """检测当前会话的抖音登录状态。

        require_self_profile 为 False 时，先查会话 localStorage 的 HasUserLogin
        与 cookie 的 LOGIN_STATUS 做快速判断，未命中再调用本人资料接口兜底；
        为 True 时跳过本地快速检查，直接调用接口校验。

        参数：
            require_self_profile: 是否强制通过本人资料接口校验登录状态。

        返回：
            已登录返回 True，否则 False。
        """
        if not require_self_profile:
            try:
                local_storage: object = await self.session.local_storage()
            except Exception:
                local_storage = {}
            if (
                isinstance(local_storage, dict)
                and local_storage.get("HasUserLogin") == "1"
            ):
                return True
            _, cookies = await self.session.cookies(self.cookie_urls)
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

    # 更新客户端的 cookie 信息，从会话上下文重新收集 cookie，并同步到请求头和 cookie_dict 中。
    async def update_cookies(self) -> None:
        """从会话上下文重新收集 cookie，并同步到请求头与 cookie_dict。"""
        cookie_string, cookie_dict = await self.session.cookies(self.cookie_urls)
        self.headers["Cookie"] = cookie_string
        self.cookie_dict = cookie_dict

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

        msToken 取会话 localStorage 的 xmst；除指纹类外的公共参数键集与取值保持
        稳定；``FINGERPRINT_KEYS`` 的 14 个键由 ``session.fingerprint()`` 提供，
        **逐键写入、缺键不写入**，绝不回退伪造常量。除综合搜索接口外，均调用签名
        脚本计算 a_bogus。

        参数：
            uri: 请求路径。
            params: 业务请求参数（会被原地补充公共参数与签名）。
            headers: 请求头（签名需要其中的 User-Agent）。

        返回：
            补全后的请求参数。
        """
        local_storage = await self.session.local_storage()
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
                "browser_online": "true",
                "platform": "PC",
                "webid": get_web_id(),
                "msToken": local_storage.get("xmst"),
            }
        )
        # 指纹键逐键写入：取值全部来自真实浏览器读数的同源结果，缺哪个键就不写
        # 哪个键——绝不回退任何本地硬编码的伪造指纹常量（历史实现里的平台名、
        # 屏幕分辨率、浏览器版本与语言/网络类型常量一律不得在本文件复活）。
        fingerprint = await self.session.fingerprint()
        missing_keys: list[str] = []
        for key in self.FINGERPRINT_KEYS:
            value = fingerprint.get(key)
            if value:
                params[key] = str(value)
            else:
                missing_keys.append(key)
        if missing_keys:
            logger.warning(
                "会话指纹缺少以下键，本次请求不写入这些公共参数: %s",
                ", ".join(missing_keys),
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
