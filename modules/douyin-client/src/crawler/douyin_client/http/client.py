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
import math
import random
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

# 签名层重试次数与退避标称阶梯（第 n 次重试前等待 _RETRY_BACKOFF_SECONDS[n-1] 经
# _retry_wait() 抖动后的值）。标称值本身是确定阶梯。
_MAX_SIGNING_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS: tuple[float, ...] = (0.5, 1.5)

# 退避抖动的乘数区间（**单侧向上**）：抖动后的值 = 基准值 * uniform(low, high)，再由
# _retry_wait 的外层 min(上限, ...) 封顶。下界固定为 1.0——抖动只把等待**延长**、永不
# 缩短：本模块开头的注释已陈明「重试只会加重风控」，把任何一次重试提前塞回网关只会更糟
# （双侧抖动下首次签名退避最低会落到 0.5 倍标称值，比不加抖动还早回来）。上界 > 1 才是
# 抖动存在的意义：多任务并发时固定退避会让各任务的第 n 次重试在时间轴上同步对齐
# （thundering herd，重试风暴会二次压垮刚恢复的网关），乘上随机系数把等待打散——但这只
# 在基准值严格小于上限时有效，基准值顶格时外层 min() 会把分散整个吃掉（刻意取舍，见
# _retry_wait 的不变量 3）。_jitter_factor() 会用 max(1.0, low) 兜住下界，所以即使日后把
# 区间下界调到 1 以下，「只延长不缩短」依然在结构上成立。测试可 monkeypatch 本常量取得
# 确定性等待，见 tests/business/douyin/test_client.py。
_RETRY_BACKOFF_JITTER: tuple[float, float] = (1.0, 1.5)

# 传输层重试的退避步长：第 n 次重试前等待本值 * n 秒，同样经 _retry_wait() 抖动与封顶。
_TRANSPORT_BACKOFF_STEP_SECONDS = 0.25

# Retry-After 的等待上限（秒）。服务端给出异常大值时钳到本上限：重试是为了扛过瞬时
# 抖动，不能因为一个响应头把整个采集任务挂住（也不该被对端随意操纵等待时长）。
_RETRY_AFTER_MAX_SECONDS = 10.0


class _RetryableStatus(DataFetchError):
    """HTTP 502/503/504 瞬时状态失败，只允许由 ``request()`` 白名单构造。

    继承 ``DataFetchError`` 以保住既有 ``except DataFetchError`` 调用方的兼容性；
    它是唯一被 ``get()``/``post()`` 重试循环捕获的异常类型，而 403/429 与业务
    状态失败产生的是 ``DataFetchError`` 本身（非本类型），因此那些失败在类型层面
    就进不了重试分支。

    ``retry_after`` 是响应头 Retry-After 解析出的服务端建议等待秒数（已按
    ``_RETRY_AFTER_MAX_SECONDS`` 钳制）；``None`` 表示响应没有给出可解析的数值秒。
    """

    def __init__(self, status_code: int, retry_after: float | None = None) -> None:
        super().__init__(f"抖音请求返回可重试状态: status_code={status_code}")
        self.status_code = status_code
        self.retry_after = retry_after


def _jitter_factor() -> float:
    """取一个**单侧向上**的抖动系数：区间下界被钳在 1.0，故返回值恒 ``>= 1.0``。

    返回：
        ``_RETRY_BACKOFF_JITTER`` 区间上的随机系数，且不小于 1.0。
    """
    low, high = _RETRY_BACKOFF_JITTER
    return random.uniform(max(1.0, low), max(1.0, high))


def _retry_wait(nominal: float, retry_after: float | None) -> float:
    """计算一次重试前的等待秒数：以 Retry-After 为下界、单侧向上抖动、且结构性封顶。

    记 ``floor = nominal if retry_after is None else max(nominal, retry_after)``、
    ``cap = _RETRY_AFTER_MAX_SECONDS``。下面三条不变量前两条**无条件**成立，第三条
    （分散性）**只在 ``floor < cap`` 时成立**：

    1. **等待 >= floor**（因而 Retry-After 存在时等待 ``>= retry_after``）：无条件成立。
       抖动系数恒 ``>= 1``（见 :func:`_jitter_factor`），故 ``floor * factor >= floor``；
       外层 ``min()`` 只在 ``floor * factor > cap`` 时起作用，而此时 ``cap >= floor``
       （两个入参本身都在上限以内），所以它最多砍掉抖动溢价，绝不会把等待压到 ``floor``
       之下。
    2. **等待 <= cap**：无条件成立。唯一收口是最外层 ``min(cap, ...)``，不依赖「标称值 /
       抖动上界恰好小于上限」这类常量巧合；日后调大抖动区间或标称阶梯，等待仍被同一个
       ``min()`` 钳住。
    3. **分散性是有条件的：仅当 ``floor < cap``**。抖动乘在**含 Retry-After 的基准值**
       上（而不是只乘本地标称退避再与 Retry-After 取 ``max``），所以并发任务收到同一个
       Retry-After 时各自落在 ``floor * uniform(low, high)`` 的不同取值上——但这只在基准值
       还没顶格时成立：``floor`` 越逼近 ``cap``，越多样本被 ``min()`` 压到 ``cap``、互异
       取值随之减少；**``floor >= cap`` 时等待恒等于 ``cap``，分散为 0**（入口有二：
       ``_parse_retry_after`` 把 Retry-After >= ``cap`` 的值钳到 ``cap``；或本地标称退避
       本身就顶到上限）。

       **这是刻意的取舍：上限优先于分散。** 此时服务端自己要求的等待（或本地标称退避）
       已经等于我们的安全上限，再向上分散必然越界；而 ``cap`` 正是为「不被对端随意操纵
       等待时长、不把整个采集任务挂住」设的硬边界（见常量定义处）。所以这里宁可让这几路
       重试同步回来，也不突破上限。**不要**把本条读成「Retry-After 存在时一定分散」——
       上一版实现正是在 Retry-After 分支上留下了一个为真的表面、为假的实质。

    反例留档（上一轮被证伪的写法）：``max(抖动标称, retry_after)`` 里抖动标称的上界只有
    ``1.5 * 1.5 = 2.25``，凡 Retry-After >= 3 都会把抖动整个吃掉——恰好在网关过载、最
    需要打散的场景退化成固定等待（当时实测 20 次重试的等待值集合恰为 ``{3.0}``）。现写法
    把抖动乘在含 Retry-After 的基准值上，把退化阈值从 2.25 推迟到了 ``cap``，但并没有
    消除它。

    参数：
        nominal: 本地标称退避秒数（签名层阶梯或传输层步长）。
        retry_after: 服务端 Retry-After 解析出的数值秒；``None`` 表示没有可解析的取值。

    返回：
        ``floor`` 经抖动与封顶后的等待秒数。值域为 ``[floor, min(cap, floor * f_max)]``，
        其中 ``f_max = max(1.0, _RETRY_BACKOFF_JITTER[1])`` 是抖动系数的上界，下界
        ``floor`` 在系数取到区间下界时达到。``floor >= cap`` 时该区间退化为**单点**
        ``cap``，不存在任何其他取值——例如 ``_retry_wait(100.0, None) == 10.0``（标称
        退避顶格）与 ``_retry_wait(0.5, 10.0) == 10.0``（Retry-After 顶格）。
    """
    floor = nominal if retry_after is None else max(nominal, retry_after)
    return min(_RETRY_AFTER_MAX_SECONDS, floor * _jitter_factor())


def _parse_retry_after(response: httpx.Response) -> float | None:
    """解析 Retry-After 响应头的**数值秒**形式，作为重试等待的下界。

    只认 ``Retry-After: 3`` / ``Retry-After: 3.5`` 这类数值秒；HTTP-date 形式
    （如 ``Wed, 21 Oct 2015 07:28:00 GMT``）与任何解析不出的取值一律忽略
    （返回 ``None``），退化为本地抖动的标称退避——**这是一个已知缺口**，不是「非法
    输入」：HTTP-date 是 RFC 9110 的合法形式，忽略它意味着对端要求等 30 秒而我们
    只等不足 2 秒，服务端可能因此升级风控。响应**带了这个头却用不上**时必须留痕，
    所以三种失败路径（非数值、非有限/负数、超上限）各记一条 WARNING，让运行期能看出
    「Retry-After 被忽略了」，而不是静默退化成标称退避。超过
    ``_RETRY_AFTER_MAX_SECONDS`` 时钳到上限并记一条 WARNING。

    参数：
        response: 状态码命中 ``_RETRYABLE_STATUS_CODES`` 的响应。

    返回：
        服务端建议的等待秒数（已钳制），无法解析时为 ``None``。
    """
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        logger.warning(
            "抖音返回的 Retry-After=%r 不是可解析的数值秒（HTTP-date 形式尚未支持），"
            "本次重试退化为本地抖动的标称退避",
            raw,
        )
        return None
    if not math.isfinite(seconds) or seconds < 0:
        logger.warning(
            "抖音返回的 Retry-After=%r 不是有限的非负秒数，本次重试退化为本地抖动的标称退避",
            raw,
        )
        return None
    if seconds > _RETRY_AFTER_MAX_SECONDS:
        logger.warning(
            "抖音返回的 Retry-After=%.1f 秒超过上限 %.1f 秒，已钳到上限等待",
            seconds,
            _RETRY_AFTER_MAX_SECONDS,
        )
        return _RETRY_AFTER_MAX_SECONDS
    return seconds


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
                它是 ``DataFetchError`` 子类，非重试调用方无需感知。抛出时一并带出
                响应头里可解析的 Retry-After（数值秒，已按上限钳制）作为重试等待下界。
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
                            raise _RetryableStatus(
                                response.status_code,
                                _parse_retry_after(response),
                            )
                        response.raise_for_status()
                        break
                    except httpx.TransportError:
                        if attempt == 2:
                            raise
                        await asyncio.sleep(
                            _retry_wait(
                                _TRANSPORT_BACKOFF_STEP_SECONDS * (attempt + 1), None
                            )
                        )
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

        等待时长取 ``_retry_wait(_RETRY_BACKOFF_SECONDS[attempt], exc.retry_after)``。
        **无条件**成立的两条约束是：等待 ``>= max(标称退避, 服务端 Retry-After)``
        （无 Retry-After 时下界即标称退避）且等待 ``<= _RETRY_AFTER_MAX_SECONDS``；
        Retry-After 已由 ``_parse_retry_after`` 钳在上限内，故两条约束不冲突——基准值
        本身在上限内，外层 ``min()`` 只砍抖动溢价、不会把等待压到基准值之下。

        抖动系数恒 ``>= 1``（单侧向上，只延长不缩短，与本模块「重试只会加重风控」的
        判断一致）且乘在**含 Retry-After 的基准值**上，因此「避免并发任务重试同步对齐」
        是**有条件的**：仅当基准值 ``max(标称退避, retry_after)`` 严格小于上限时，各任务
        才落在 ``基准值 * uniform(low, high)`` 的互异取值上。对端给出
        Retry-After >= 上限（或标称退避本身顶格）时，基准值先被钳到上限，等待恒等于
        ``_RETRY_AFTER_MAX_SECONDS``、分散为 0——这是「上限优先于分散」的刻意取舍，
        完整表述与理由见 :func:`_retry_wait` 的不变量 3。

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
            except _RetryableStatus as exc:
                if attempt >= _MAX_SIGNING_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(
                    _retry_wait(_RETRY_BACKOFF_SECONDS[attempt], exc.retry_after)
                )
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
