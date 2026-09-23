"""抖音客户端（DouyinClient）的测试：覆盖收藏接口的查询/表单参数分离、POST 请求体签名注入、5xx 重签名重试、指纹逐键来自注入会话、目标评论存在性核验与零浏览器依赖。"""

import asyncio
import logging
import random
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from crawler.douyin_client import DataFetchError, DouyinClient
from crawler.douyin_client.http import client as client_module
from crawler.douyin_client.http.client import _RetryableStatus

# 请求指纹键表：与 DouyinClient.FINGERPRINT_KEYS 一致（14 项）。
_FINGERPRINT_KEYS = {
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
}

# 本地硬编码的旧指纹常量：修复后不允许以任何形式重新出现在参数或源码里。
_LEGACY_FAKE_FINGERPRINT_VALUES = (
    "MacIntel",
    "Mac OS",
    "10.15.7",
    "125.0.0.0",
    "2560",
    "1440",
    "109.0",
)

# 源码里禁止出现的硬编码指纹字面量（R9：这三个键也必须随注入指纹变化）。
_FORBIDDEN_SOURCE_LITERALS = (
    "MacIntel",
    "Mac OS",
    "2560",
    "1440",
    "Chrome 125",
    '"zh-CN"',
    '"4g"',
    '"50"',
)

# 非指纹公共参数的键集：本次修复不应改变它（BROWSER_LANGUAGE / EFFECTIVE_TYPE /
# ROUND_TRIP_TIME 已改由指纹提供，因此不在本集合内）。
_STABLE_PUBLIC_PARAM_KEYS = {
    "device_platform",
    "aid",
    "channel",
    "version_code",
    "version_name",
    "update_version_code",
    "pc_client_type",
    "cookie_enabled",
    "browser_online",
    "platform",
    "webid",
    "msToken",
    # 与真实网页请求对齐后新增的固定公共参数（缺任一项都会被接口拒掉）
    "pc_libra_divert",
    "support_h265",
    "support_dash",
}

# 注入会话提供的指纹：取值刻意与旧硬编码常量全都不同，用于证明「逐键来自注入」。
_INJECTED_FINGERPRINT: dict[str, str] = {
    "browser_language": "fr-FR",
    "browser_platform": "Linux armv8l",
    "browser_name": "Firefox",
    "browser_version": "127.0",
    "engine_name": "Gecko",
    "os_name": "Linux",
    "cpu_core_num": "6",
    "device_memory": "4",
    "screen_width": "1234",
    "screen_height": "768",
    "effective_type": "3g",
    "round_trip_time": "77",
}


class FakeSession:
    """假会话上下文：实现 SessionContext 的 4 个原语方法并全部返回内建类型。"""

    def __init__(
        self,
        *,
        user_agent: str = "ua",
        local_storage: dict[str, Any] | None = None,
        cookies: tuple[str, dict[str, str]] = ("", {}),
        fingerprint: Mapping[str, str] | None = None,
    ) -> None:
        self._user_agent = user_agent
        self._local_storage = dict(local_storage or {})
        self._cookies = (cookies[0], dict(cookies[1]))
        self._fingerprint = dict(fingerprint or {})

    async def user_agent(self) -> str:
        """返回注入的 User-Agent。"""
        return self._user_agent

    async def local_storage(self) -> dict[str, Any]:
        """返回注入的 localStorage 快照。"""
        return dict(self._local_storage)

    async def cookies(self, urls: Sequence[str]) -> tuple[str, dict[str, str]]:
        """返回注入的 (cookie 字符串, 名值字典)。"""
        assert isinstance(urls, list)
        return (self._cookies[0], dict(self._cookies[1]))

    async def fingerprint(self) -> Mapping[str, str]:
        """返回注入的请求指纹映射。"""
        return dict(self._fingerprint)


def _client(session: FakeSession | None = None) -> DouyinClient:
    """用假会话构造客户端（测试内统一的装配方式）。"""
    return DouyinClient(
        session=session or FakeSession(),
        headers={"User-Agent": "ua"},
        cookie_dict={},
        timeout=1,
        verify_ssl=True,
    )


async def _client_with_transport(
    handler: Any, session: FakeSession | None = None
) -> DouyinClient:
    """构造使用 MockTransport 的客户端（同文件既有用例的装配方式）。"""
    client = _client(session)
    await client.http.aclose()
    client.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def _capture_sleeps(monkeypatch: Any) -> list[float]:
    """把 ``asyncio.sleep`` 换成记录实参的桩，返回收集到的等待秒数。

    重试退避现在是抖动的，无法断言精确值；本桩是唯一可靠的观测点，测试再配合
    monkeypatch ``_RETRY_BACKOFF_JITTER`` 固定抖动系数即可精确断言。
    """
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return sleeps


def test_collected_keeps_query_and_form_body_separate() -> None:
    """验证收藏列表接口将分页参数放在查询串、aid 放在表单体，二者不混淆。"""
    client = _client()
    post = AsyncMock(return_value={"status_code": 0})
    client.post = post  # type: ignore[method-assign]

    result = asyncio.run(client.user_api.get_collected(cursor=20, count=10))
    asyncio.run(client.close())

    assert result["status_code"] == 0
    args = post.await_args.args
    assert args[1] == {"count": 10, "cursor": 20}
    assert args[3] == {"aid": "6383"}


class PageSession(FakeSession):
    """支持页面上下文取数的假会话：记录 evaluate 调用并返回预置响应。"""

    def __init__(self, *, response_text: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._response_text = response_text
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def evaluate(self, expression: str, argument: Any = None) -> Any:
        """记录调用参数并返回一段伪造的页面取数结果。"""
        self.calls.append((expression, dict(argument or {})))
        return {"status": 200, "text": self._response_text}


def test_get_recovers_in_page_when_body_is_empty() -> None:
    """验证直连被拒（200 + 空 body）时改由页面上下文取数。

    抖音「喜欢列表」要求请求带页面内安全 SDK 生成的签名，直连只会拿到空 body；
    页面里的 fetch 会被 SDK 自动补签名，因此这是唯一稳定通道。
    """
    import json

    payload = {"status_code": 0, "aweme_list": [{"aweme_id": "7300000000000000001"}]}
    session = PageSession(response_text=json.dumps(payload))

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"", headers={"content-type": "text/plain; charset=utf-8"}
        )

    async def scenario() -> dict[str, Any]:
        client = await _client_with_transport(handler, session)
        try:
            return await client.user_api.get_liked("MS4wLjABAAAA", 0, 18)
        finally:
            await client.close()

    result = asyncio.run(scenario())

    assert result["aweme_list"][0]["aweme_id"] == "7300000000000000001"
    assert session.calls, "应当走页面上下文取数"
    _, argument = session.calls[0]
    assert argument["uri"] == "/aweme/v1/web/aweme/favorite/"
    # 页面内由 SDK 重新签名，因此只传业务参数，不带我们计算的 a_bogus
    assert "a_bogus" not in argument["params"]
    assert argument["params"]["sec_user_id"] == "MS4wLjABAAAA"


def test_get_keeps_original_error_when_page_recovery_unavailable() -> None:
    """验证会话不支持页面取数时，空响应仍然按原样报错（不掩盖原因）。"""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"", headers={"content-type": "text/plain"})

    async def scenario() -> None:
        client = await _client_with_transport(handler, FakeSession())
        try:
            await client.user_api.get_liked("MS4wLjABAAAA", 0, 18)
        finally:
            await client.close()

    with pytest.raises(DataFetchError, match="body=empty"):
        asyncio.run(scenario())


def test_create_reads_user_agent_and_cookies_from_session() -> None:
    """验证 create() 的 UA 与 cookie 全部来自注入会话，不再接收 page/browser_context。"""

    async def scenario() -> DouyinClient:
        session = FakeSession(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/127.0",
            cookies=("a=b; LOGIN_STATUS=1", {"a": "b", "LOGIN_STATUS": "1"}),
        )
        return await DouyinClient.create(session=session, timeout=1, verify_ssl=True)

    client = asyncio.run(scenario())
    try:
        assert client.headers["User-Agent"] == (
            "Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/127.0"
        )
        assert client.headers["Cookie"] == "a=b; LOGIN_STATUS=1"
        assert client.cookie_dict == {"a": "b", "LOGIN_STATUS": "1"}
    finally:
        asyncio.run(client.close())


def test_post_without_query_sends_signed_body(monkeypatch: Any) -> None:
    """验证无查询串的 POST 请求会在表单体中注入 a_bogus 签名与 aid 后再发出。"""
    client = _client(FakeSession(local_storage={"xmst": "token"}))
    request = AsyncMock(return_value={"status_code": 0})
    client.request = request  # type: ignore[method-assign]
    monkeypatch.setattr(
        "crawler.douyin_client.http.client.get_a_bogus", lambda *_: "signature"
    )

    asyncio.run(client.post("/test", {"value": "1"}))
    asyncio.run(client.close())

    sent_body = request.await_args.kwargs["data"]
    assert sent_body["value"] == "1"
    assert sent_body["a_bogus"] == "signature"
    assert sent_body["aid"] == "6383"


def test_request_retries_transient_remote_protocol_error() -> None:
    """验证对端瞬时断连会有限重试，评论任务不再因一次连接抖动整体失败。"""
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.RemoteProtocolError("peer closed", request=request)
        return httpx.Response(200, json={"status_code": 0, "data": []})

    async def scenario() -> dict[str, Any]:
        client = await _client_with_transport(handler)
        try:
            return await client.request("GET", "https://www.douyin.com/test")
        finally:
            await client.close()

    payload = asyncio.run(scenario())

    assert payload["status_code"] == 0
    assert attempts == 2


def test_request_rejects_nonzero_douyin_business_status() -> None:
    """验证 HTTP 200 但抖音业务状态失败时不会被误记为采集成功。"""

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status_code": 4, "data": []})

    async def scenario() -> None:
        client = await _client_with_transport(handler)
        try:
            with pytest.raises(DataFetchError, match="status_code=4"):
                await client.request("GET", "https://www.douyin.com/test")
        finally:
            await client.close()

    asyncio.run(scenario())


def test_request_log_captures_failed_business_response() -> None:
    """验证业务失败时日志回调能取得返回信息，而成功响应不保存正文。"""
    captured: list[Any] = []

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status_code": 4,
                "status_msg": "请求过于频繁",
                "search_nil_info": {"search_nil_type": "verify_check"},
            },
        )

    async def scenario() -> None:
        client = await _client_with_transport(handler)

        async def capture(_: DouyinClient, entry: Any) -> None:
            captured.append(entry)

        client.request_logger = capture
        try:
            with pytest.raises(DataFetchError, match="status_code=4"):
                await client.request("GET", "https://www.douyin.com/test")
        finally:
            await client.close()

    asyncio.run(scenario())

    assert len(captured) == 1
    detail = captured[0].failure_detail
    assert detail["http_status"] == 200
    assert detail["body"]["status_msg"] == "请求过于频繁"
    assert detail["body"]["search_nil_info"]["search_nil_type"] == "verify_check"


def test_request_log_captures_http_error_body() -> None:
    """验证 HTTP 错误页面也会记录正文预览与内容类型。"""
    captured: list[Any] = []

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            text="risk verification required",
            headers={"content-type": "text/plain; charset=utf-8"},
        )

    async def scenario() -> None:
        client = await _client_with_transport(handler)

        async def capture(_: DouyinClient, entry: Any) -> None:
            captured.append(entry)

        client.request_logger = capture
        try:
            with pytest.raises(DataFetchError, match="HTTPStatusError"):
                await client.request("GET", "https://www.douyin.com/test")
        finally:
            await client.close()

    asyncio.run(scenario())

    assert len(captured) == 1
    assert captured[0].response_status == 403
    assert captured[0].failure_detail["body"] == "risk verification required"


def test_request_retries_5xx_and_resigns(monkeypatch: Any) -> None:
    """验证 502/503/504 会重签名重试，且每次尝试的 a_bogus 都重新计算、只出现一次。"""
    monkeypatch.setattr(
        "crawler.douyin_client.http.client._RETRY_BACKOFF_SECONDS", (0.0, 0.0)
    )
    signatures = 0

    def fake_bogus(*_: Any) -> str:
        nonlocal signatures
        signatures += 1
        return f"sig-{signatures}"

    monkeypatch.setattr("crawler.douyin_client.http.client.get_a_bogus", fake_bogus)

    queries: list[httpx.QueryParams] = []
    statuses = [503, 200]

    async def handler(request: httpx.Request) -> httpx.Response:
        queries.append(request.url.params)
        status = statuses[len(queries) - 1]
        if status != 200:
            return httpx.Response(status, text="gateway unavailable")
        return httpx.Response(200, json={"status_code": 0, "data": []})

    logged: list[Any] = []

    async def scenario() -> dict[str, Any]:
        client = await _client_with_transport(handler)

        async def capture(_: DouyinClient, entry: Any) -> None:
            logged.append(entry)

        client.request_logger = capture
        try:
            return await client.get("/test", {"value": "1"})
        finally:
            await client.close()

    payload = asyncio.run(scenario())

    assert payload["status_code"] == 0
    assert len(queries) == 2
    # 每次尝试都重新签名：签名值逐次递增，且重试请求体里没有叠加出第二个 a_bogus。
    assert queries[0].get_list("a_bogus") == ["sig-1"]
    assert queries[1].get_list("a_bogus") == ["sig-2"]
    assert queries[1].get("value") == "1"
    # 每次尝试各落一条 request_log，重试对上层可见。
    assert [entry.response_status for entry in logged] == [503, 200]
    assert logged[0].error == "RetryableStatus:503"


def test_request_gives_up_after_three_retryable_statuses(monkeypatch: Any) -> None:
    """验证 5xx 有限重试：连续三次 502/503/504 后抛出 DataFetchError，不再继续请求。"""
    monkeypatch.setattr(
        "crawler.douyin_client.http.client._RETRY_BACKOFF_SECONDS", (0.0, 0.0)
    )
    monkeypatch.setattr(
        "crawler.douyin_client.http.client.get_a_bogus", lambda *_: "signature"
    )
    attempts = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(504, text="gateway timeout")

    async def scenario() -> None:
        client = await _client_with_transport(handler)
        try:
            with pytest.raises(DataFetchError, match="status_code=504"):
                await client.get("/test", {"value": "1"})
        finally:
            await client.close()

    asyncio.run(scenario())

    assert attempts == 3


def test_post_retry_resigns_body_without_duplicate_signature(monkeypatch: Any) -> None:
    """验证 POST 重试使用请求体副本重新签名，a_bogus 不会被二次签名叠加两份。"""
    monkeypatch.setattr(
        "crawler.douyin_client.http.client._RETRY_BACKOFF_SECONDS", (0.0, 0.0)
    )
    signatures = 0

    def fake_bogus(*_: Any) -> str:
        nonlocal signatures
        signatures += 1
        return f"sig-{signatures}"

    monkeypatch.setattr("crawler.douyin_client.http.client.get_a_bogus", fake_bogus)

    bodies: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content.decode())
        if len(bodies) == 1:
            return httpx.Response(502, text="bad gateway")
        return httpx.Response(200, json={"status_code": 0, "data": []})

    async def scenario() -> dict[str, Any]:
        client = await _client_with_transport(handler)
        try:
            return await client.post("/test", {"value": "1"})
        finally:
            await client.close()

    payload = asyncio.run(scenario())

    assert payload["status_code"] == 0
    assert len(bodies) == 2
    assert bodies[0].count("a_bogus=") == 1
    assert bodies[1].count("a_bogus=") == 1
    assert "sig-1" in bodies[0]
    assert "sig-2" in bodies[1]
    assert "value=1" in bodies[1]


@pytest.mark.parametrize(
    ("status", "retry_after"),
    [(403, None), (429, None), (429, "3")],
)
def test_request_never_retries_forbidden_or_rate_limited(
    status: int, retry_after: str | None, monkeypatch: Any
) -> None:
    """验证 403/429 只发一次请求：风控拦截与限流在结构上不可能进入重试分支。

    最后一组专门盯住「429 还带了 Retry-After」——服务端明确建议稍后重试，最容易被
    写成「那就照它说的重试一次」，而本模块的判断是限流重试只会加重风控。
    """
    monkeypatch.setattr(
        "crawler.douyin_client.http.client._RETRY_BACKOFF_SECONDS", (0.0, 0.0)
    )
    monkeypatch.setattr(
        "crawler.douyin_client.http.client.get_a_bogus", lambda *_: "signature"
    )
    attempts = 0
    headers = {} if retry_after is None else {"Retry-After": retry_after}

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status, text="risk control", headers=headers)

    async def scenario() -> None:
        client = await _client_with_transport(handler)
        try:
            with pytest.raises(DataFetchError) as excinfo:
                await client.get("/test", {"value": "1"})
            assert not isinstance(excinfo.value, _RetryableStatus)
        finally:
            await client.close()

    asyncio.run(scenario())

    assert attempts == 1


# --- 重试退避：单侧向上抖动、Retry-After 下界与结构封顶（OI-2） ---


def _sequenced_handler(
    statuses: Sequence[int], headers: Mapping[str, str] | None = None
) -> tuple[Any, list[int]]:
    """构造按序返回给定状态码的 handler，并返回「已应答状态码」列表。

    超出序列长度的请求按最后一个状态码应答，便于写「连续 5xx」场景。
    """
    seen: list[int] = []

    async def handler(_: httpx.Request) -> httpx.Response:
        status = statuses[min(len(seen), len(statuses) - 1)]
        seen.append(status)
        if status == 200:
            return httpx.Response(200, json={"status_code": 0, "data": []})
        return httpx.Response(status, text="transient", headers=headers or {})

    return handler, seen


async def _run_get(handler: Any) -> dict[str, Any]:
    """在 MockTransport 客户端上发一次 ``client.get``（新用例统一的装配方式）。"""
    client = await _client_with_transport(handler)
    try:
        return await client.get("/test", {"value": "1"})
    finally:
        await client.close()


def test_signing_retry_sleep_is_jittered_nominal_backoff(monkeypatch: Any) -> None:
    """验证签名层等待 = 标称退避 * 单侧向上抖动系数（系数固定为定值后可精确断言）。"""
    monkeypatch.setattr(client_module, "_RETRY_BACKOFF_SECONDS", (2.0, 2.0))
    monkeypatch.setattr(client_module, "_RETRY_BACKOFF_JITTER", (1.25, 1.25))
    monkeypatch.setattr(client_module, "get_a_bogus", lambda *_: "signature")
    sleeps = _capture_sleeps(monkeypatch)
    handler, seen = _sequenced_handler([503, 504, 200])

    payload = asyncio.run(_run_get(handler))

    assert payload["status_code"] == 0
    assert seen == [503, 504, 200]
    # 两次重试的标称退避 2.0 都被抖动系数 1.25 缩放 → 2.5（不再等于标称值本身）。
    assert sleeps == [2.5, 2.5]


def test_retry_backoff_jitter_spreads_within_declared_range() -> None:
    """验证抖动确实随机（并发重试不会同步对齐），且只向上延长、不短于标称退避。"""
    low, high = client_module._RETRY_BACKOFF_JITTER

    samples = {client_module._retry_wait(2.0, None) for _ in range(64)}

    assert len(samples) > 1
    # 单侧向上：抖动是乘数，下界 1.0，因此任何一次都不会把等待压到标称值以下。
    assert low >= 1.0
    assert min(samples) >= 2.0
    assert max(samples) <= 2.0 * high


def test_jitter_never_shortens_even_if_range_lower_bound_is_lowered(
    monkeypatch: Any,
) -> None:
    """验证「只延长不缩短」是结构保证：把区间下界调到 1 以下也不会出现更短的等待。"""
    monkeypatch.setattr(client_module, "_RETRY_BACKOFF_JITTER", (0.1, 0.5))
    samples = [client_module._retry_wait(2.0, None) for _ in range(64)]

    # _jitter_factor() 用 max(1.0, low) 兜住下界，故区间整体落在 1 以下时退化为原值。
    assert min(samples) >= 2.0
    assert max(samples) <= 2.0


def test_transport_retry_sleep_is_jittered_too(monkeypatch: Any) -> None:
    """验证传输层（httpx.TransportError）重试退避同样加抖动，且不早于标称步长。"""
    monkeypatch.setattr(client_module, "_TRANSPORT_BACKOFF_STEP_SECONDS", 1.0)
    monkeypatch.setattr(client_module, "_RETRY_BACKOFF_JITTER", (1.5, 1.5))
    sleeps = _capture_sleeps(monkeypatch)
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.RemoteProtocolError("peer closed", request=request)
        return httpx.Response(200, json={"status_code": 0, "data": []})

    payload = asyncio.run(_run_get(handler))

    assert payload["status_code"] == 0
    assert attempts == 2
    # 第 1 次重试：标称 1.0 * 1 * 抖动系数 1.5（单侧向上，不会低于标称的 1.0）。
    assert sleeps == [1.5]


def test_retry_wait_is_structurally_capped(monkeypatch: Any) -> None:
    """验证上限由外层 min() 结构保证，而不是靠「常量恰好小于上限」的巧合。

    把标称退避与抖动区间都调到远超上限，等待仍被钳在 ``_RETRY_AFTER_MAX_SECONDS``：
    日后有人调大 ``_RETRY_BACKOFF_JITTER`` 或 ``_RETRY_BACKOFF_SECONDS``，也不会出现
    把采集任务挂住的超长等待。
    """
    monkeypatch.setattr(client_module, "_RETRY_BACKOFF_JITTER", (1.0, 1_000.0))
    # 标称值本身就超过上限（模拟日后调大阶梯）：min() 仍然收口。
    # 这正是 _retry_wait 的返回值域退化成单点的场景（floor >= cap → 恒等于 cap），
    # 该退化是刻意取舍，由 test_waits_degenerate_to_cap_once_floor_reaches_cap 承重。
    assert (
        client_module._retry_wait(100.0, None) == client_module._RETRY_AFTER_MAX_SECONDS
    )
    # 抖动上界再放大两个数量级，结论不变。
    monkeypatch.setattr(client_module, "_RETRY_BACKOFF_JITTER", (1.0, 100_000.0))
    assert (
        client_module._retry_wait(100.0, None) == client_module._RETRY_AFTER_MAX_SECONDS
    )
    # 封顶后依然不短于 Retry-After：Retry-After 自身已由 _parse_retry_after 钳在上限内。
    assert (
        client_module._retry_wait(100.0, 4.0) == client_module._RETRY_AFTER_MAX_SECONDS
    )


def test_retry_after_zero_waits_exactly_like_absent(monkeypatch: Any) -> None:
    """承重事实：``_retry_wait(n, 0.0)`` 与 ``_retry_wait(n, None)`` 得到**相同**等待。

    本用例是「HTTP-date 已过期 → 返回 ``None`` 而非 0 秒」这条选择的**真实理由**的回归
    护栏。``floor = nominal if retry_after is None else max(nominal, retry_after)``，标称
    退避非负时 ``max(nominal, 0.0) == nominal``，因此 ``0.0`` 与 ``None`` 都退回标称退避，
    唯一可观测的差别是「记不记 WARNING」。旧文档曾声称返回 0 秒会把重试**无退避**地塞回
    网关，那在本仓库是假的（``Retry-After: 0`` 本就是合法响应头，实测同样等于标称退避）。
    谁日后把那条理由写回文档、或误以为改报 0 秒会取消退避，本用例的等值断言就会在行为
    真正改变的那一刻失败并指向这里。
    """
    cap = client_module._RETRY_AFTER_MAX_SECONDS
    monkeypatch.setattr(client_module, "_RETRY_BACKOFF_JITTER", (1.0, 1.0))

    # nominal <= cap：0.0 与 None 都等于标称退避本身（0.0 绝不把等待压成 0）。
    for nominal in (0.0, 0.25, 0.5, 0.75, 1.5, 2.0, 10.0):
        with_zero = client_module._retry_wait(nominal, 0.0)
        without = client_module._retry_wait(nominal, None)
        assert with_zero == without == min(cap, nominal), (
            f"nominal={nominal} 时 0.0 与 None 的等待不再相等，"
            "「0 秒会取消标称退避」的旧理由不能复活"
        )
    # floor >= cap 的退化区间同样相等（都恒为上限）。
    assert (
        client_module._retry_wait(100.0, 0.0)
        == client_module._retry_wait(100.0, None)
        == cap
    )
    # 抖动不钉死时也相等：floor 相同 → _jitter_factor 消费同一次随机抽样 → 结果逐位相同。
    random.seed(20260913)
    with_zero = client_module._retry_wait(0.5, 0.0)
    random.seed(20260913)
    without = client_module._retry_wait(0.5, None)
    assert with_zero == without != 0.0


def test_request_honours_retry_after_as_wait_lower_bound(monkeypatch: Any) -> None:
    """验证 502 带 Retry-After: 3 时实际等待不短于 3 秒，且不超过上限。"""
    monkeypatch.setattr(client_module, "get_a_bogus", lambda *_: "signature")
    sleeps = _capture_sleeps(monkeypatch)
    handler, seen = _sequenced_handler([502, 200], headers={"Retry-After": "3"})

    payload = asyncio.run(_run_get(handler))

    assert payload["status_code"] == 0
    assert seen == [502, 200]
    assert len(sleeps) == 1
    # 服务端要求等 3 秒 → 抖动只能把它推高，绝不能把它压到 3 秒以下。
    assert sleeps[0] >= 3.0
    assert sleeps[0] <= client_module._RETRY_AFTER_MAX_SECONDS


def test_retry_after_present_still_spreads_waits_across_retries(
    monkeypatch: Any,
) -> None:
    """承重回归：带 Retry-After 时同一任务内多次重试的等待值必须互异。

    旧实现 ``max(_jittered(标称), retry_after)`` 里，抖动后的标称上界只有
    1.5 * 1.5 = 2.25，凡 Retry-After >= 3 都被 ``max()`` 吃掉——上一轮实测 20 次重试
    的等待值集合恰为 {3.0}，抖动在最需要它打散的场景（网关过载并发出 Retry-After）
    被完全抵消，thundering herd 原样保留。本用例在同一个客户端上连做两次 5xx 重试，
    直接断言两个等待值互异，在旧实现上必然失败。
    """
    monkeypatch.setattr(client_module, "get_a_bogus", lambda *_: "signature")
    monkeypatch.setattr(client_module, "_RETRY_BACKOFF_SECONDS", (0.5, 1.5))
    sleeps = _capture_sleeps(monkeypatch)
    handler, seen = _sequenced_handler([502, 503, 200], headers={"Retry-After": "3"})

    payload = asyncio.run(_run_get(handler))

    assert payload["status_code"] == 0
    assert seen == [502, 503, 200]
    assert len(sleeps) == 2
    assert len(set(sleeps)) == len(sleeps), (
        f"等待值重复，抖动被 Retry-After 吃掉: {sleeps}"
    )
    assert all(s >= 3.0 for s in sleeps)
    assert all(s <= client_module._RETRY_AFTER_MAX_SECONDS for s in sleeps)


def test_concurrent_retry_after_waits_do_not_align(monkeypatch: Any) -> None:
    """承重回归：并发任务收到同一个 Retry-After 时，等待值不得整队对齐到同一秒。

    这是 thundering herd 的直接对抗：上一个实现里 8 个并发任务会得到 8 个一模一样的
    3.0 秒等待，然后同时回来二次压垮网关。旧实现上断言 ``len(set(sleeps)) == 8`` 必失败。
    """
    monkeypatch.setattr(client_module, "get_a_bogus", lambda *_: "signature")
    sleeps = _capture_sleeps(monkeypatch)

    async def scenario() -> None:
        tasks = []
        for _ in range(8):
            handler, _ = _sequenced_handler([502, 200], headers={"Retry-After": "3"})
            tasks.append(_run_get(handler))
        await asyncio.gather(*tasks)

    asyncio.run(scenario())

    assert len(sleeps) == 8
    assert len(set(sleeps)) == len(sleeps), f"并发等待值对齐了: {sleeps}"
    assert all(s >= 3.0 for s in sleeps)
    assert all(s <= client_module._RETRY_AFTER_MAX_SECONDS for s in sleeps)


def test_waits_degenerate_to_cap_once_floor_reaches_cap(monkeypatch: Any) -> None:
    """承重用例：基准值顶到上限后，等待**恒定退化**为上限值、分散为 0（已知且刻意）。

    本用例把 ``_retry_wait`` 不变量 3 的后半段（``floor >= cap`` → 等待恒等于 ``cap``）
    钉成**可见行为**。这是取舍，不是缺陷：``cap`` 是为「不被对端随意操纵等待时长、不把整个
    采集任务挂住」设的硬边界，服务端要求的等待已经顶到该边界时再向上抖动必然越界，所以
    **上限优先于分散**。写成断言的目的有二：

    1. 谁将来把外层 ``min()`` 换成「无论如何都要分散」的写法，本用例立刻失败并指向
       ``_retry_wait`` 文档里的取舍说明，而不是让这个已知退化被当成「抖动失灵」误修；
    2. 它同时是「``Retry-After`` 存在时**不一定**分散」这一精确陈述的回归护栏——上一版
       docstring 的无条件措辞正是在这里被实测证伪（``Retry-After: 10`` 时 8 个并发任务
       拿到 8 个相同的 10.0）。

    两条到达 ``floor == cap`` 的入口都覆盖：① 响应头 ``Retry-After: 3600``（及 10）被
    ``_parse_retry_after`` 钳到上限；② 本地标称退避本身超过上限（模拟日后调大
    ``_RETRY_BACKOFF_SECONDS``）。断言值**恰好**是 ``cap``：不低于（不变量 1 的单侧向上
    结构，且基准值已是 ``cap``），也不高于（不变量 2 的外层 ``min()`` 收口）。
    """
    monkeypatch.setattr(client_module, "get_a_bogus", lambda *_: "signature")
    cap = client_module._RETRY_AFTER_MAX_SECONDS
    monkeypatch.setattr(client_module, "_RETRY_BACKOFF_SECONDS", (0.5, 1.5))

    # 入口 ①：Retry-After 超上限。同一任务内连做两次 5xx 重试，等待值两次都恒为 cap。
    sleeps = _capture_sleeps(monkeypatch)
    handler, seen = _sequenced_handler([502, 503, 200], headers={"Retry-After": "3600"})

    payload = asyncio.run(_run_get(handler))

    assert payload["status_code"] == 0
    assert seen == [502, 503, 200]
    assert sleeps == [cap, cap]
    assert len(set(sleeps)) == 1, f"顶格后不应再有分散: {sleeps}"

    # 入口 ①（并发面）：8 个并发任务收到同一个超上限 Retry-After，等待值**全部相同**。
    # 这里刻意期望 distinct == 1：它宣告「此场景下分散为 0」是已知的，而非意外。
    concurrent_sleeps = _capture_sleeps(monkeypatch)

    async def scenario() -> None:
        tasks = []
        for _ in range(8):
            per_task, _ = _sequenced_handler([502, 200], headers={"Retry-After": "10"})
            tasks.append(_run_get(per_task))
        await asyncio.gather(*tasks)

    asyncio.run(scenario())

    assert concurrent_sleeps == [cap] * 8
    assert len(set(concurrent_sleeps)) == 1, f"顶格后不应再有分散: {concurrent_sleeps}"

    # 入口 ②：标称退避本身超过上限，抖动区间再宽也无法把它分散开。
    monkeypatch.setattr(client_module, "_RETRY_BACKOFF_JITTER", (1.0, 1.5))
    assert {client_module._retry_wait(100.0, None) for _ in range(64)} == {cap}

    # 边界对照：floor 严格小于 cap 时分散仍在（说明退化是「顶格」触发的，不是恒常行为）。
    spread = {client_module._retry_wait(0.5, 3.0) for _ in range(64)}
    assert len(spread) == 64
    assert all(3.0 <= wait <= cap for wait in spread)


def test_clamped_fraction_rises_as_floor_approaches_cap() -> None:
    """验证「分散随基准值逼近上限而**单调退化**」的渐进过程，而非二元开关。

    ``_retry_wait`` 不变量 3 只承诺「``floor < cap`` 时分散、``floor >= cap`` 时恒为
    ``cap``」，容易被误读成中间没有过渡带。实测三档几何给出过渡带的形状：抖动区间上端是
    ``floor * 1.5``，凡越过 ``cap = 10`` 的样本都被 ``min()`` 压平，压顶比例为
    ``(floor * 1.5 - cap) / (floor * 1.5 - floor)``——``floor = 3``（上端 4.5）为 0%、
    ``floor = 8``（上端 12）为 50%、``floor = cap`` 为 100%。三档单调上升即钉住了
    「阈值就是 ``cap``、退化是渐进的」这一文档表述。
    """
    cap = client_module._RETRY_AFTER_MAX_SECONDS
    samples = 2000

    def at_cap_ratio(floor: float) -> float:
        waits = [client_module._retry_wait(0.5, floor) for _ in range(samples)]
        return sum(1 for wait in waits if wait == cap) / samples

    far = at_cap_ratio(3.0)  # 抖动区间整体在上限以内：完全不压顶。
    near = at_cap_ratio(8.0)  # 上端 12 越过上限：约一半样本被压平。
    topped = at_cap_ratio(cap)  # 基准值顶格：全部压平，分散为 0。

    # 2000 次采样下 8.0 档的二项分布标准差约 0.011，±0.1 的容差留足余量。
    assert far == 0.0
    assert near == pytest.approx(0.5, abs=0.1)
    assert topped == 1.0
    assert far < near < topped


def test_request_clamps_oversized_retry_after_and_warns(
    monkeypatch: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """验证异常大的 Retry-After 被钳到上限并记一条 WARNING，不会把任务挂死。

    这里的 ``sleeps == [10.0]`` 是**刻意钉住的取舍值**，不是「分散不重要」：``Retry-After``
    >= 上限时，服务端自己要求的等待已经顶到我们的安全上限，再向上抖动就会越界，所以
    ``_retry_wait`` 让**上限优先于分散**，等待恒等于上限（退化过程与阈值由
    ``test_waits_degenerate_to_cap_once_floor_reaches_cap`` 单独承重）。本用例只负责
    「超上限 → 钳到上限 + 留 WARNING 痕」，不要把这条断言误读成抖动失效的回归。
    """
    monkeypatch.setattr(client_module, "get_a_bogus", lambda *_: "signature")
    sleeps = _capture_sleeps(monkeypatch)
    handler, _ = _sequenced_handler([503, 200], headers={"Retry-After": "3600"})

    with caplog.at_level(logging.WARNING, logger="crawler.douyin_client.http.client"):
        payload = asyncio.run(_run_get(handler))

    assert payload["status_code"] == 0
    assert sleeps == [client_module._RETRY_AFTER_MAX_SECONDS]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Retry-After" in r.getMessage() for r in warnings)


# --- Retry-After 的 HTTP-date 形式（OI-9） ---

# 固定的「当前时间」与配套的三个 HTTP-date 取值：换算「距现在多少秒」必须有个可注入的
# 被减数，否则断言会随运行时刻漂移。_FROZEN_NOW 取一个平凡时刻，三个日期分别是
# 「晚 5 秒」（生效）「早 15 年」（已过期）「晚 60 秒」（超上限被钳）。
_FROZEN_NOW = datetime(2030, 10, 21, 7, 27, 55, tzinfo=timezone.utc)
_FROZEN_NOW_HTTP_DATE = "Mon, 21 Oct 2030 07:28:00 GMT"
_FROZEN_EXPIRED_HTTP_DATE = "Wed, 21 Oct 2015 07:28:00 GMT"
_FROZEN_FAR_FUTURE_HTTP_DATE = "Mon, 21 Oct 2030 07:28:55 GMT"


def _freeze_utcnow(monkeypatch: Any, now: datetime = _FROZEN_NOW) -> None:
    """把 client 模块的时钟钉在 ``now``，让 HTTP-date 换算完全脱离真实时钟。

    替换的是模块级函数 ``_utcnow()`` 而不是 ``datetime``——这正是它被抽成模块级函数
    的原因（可注入、可 monkeypatch）。全程不 sleep：等待时长由 ``_capture_sleeps``
    的桩观测。
    """
    monkeypatch.setattr(client_module, "_utcnow", lambda: now)


def test_parse_retry_after_converts_http_date_to_seconds_from_now(
    monkeypatch: Any,
) -> None:
    """验证 HTTP-date 形式被换算成「距当前 UTC 时间还有多少秒」的确定性数值。"""
    _freeze_utcnow(monkeypatch)

    assert client_module._parse_retry_after(
        httpx.Response(503, headers={"Retry-After": _FROZEN_NOW_HTTP_DATE})
    ) == pytest.approx(5.0)


def test_http_date_without_timezone_is_read_as_utc(monkeypatch: Any) -> None:
    """验证缺时区的 HTTP-date 按 UTC 解释，不随运行机器的本地时区漂移。"""
    _freeze_utcnow(monkeypatch)

    # parsedate_to_datetime 对无时区后缀的日期返回 naive datetime，本实现按 UTC 补齐。
    assert client_module._parse_retry_after(
        httpx.Response(503, headers={"Retry-After": "Mon, 21 Oct 2030 07:28:00"})
    ) == pytest.approx(5.0)


def test_http_date_retry_after_is_honoured_as_wait_lower_bound(
    monkeypatch: Any,
) -> None:
    """验证未来 5 秒的 HTTP-date 生效：实际等待不短于 5 秒，且不超过上限。"""
    _freeze_utcnow(monkeypatch)
    monkeypatch.setattr(client_module, "get_a_bogus", lambda *_: "signature")
    sleeps = _capture_sleeps(monkeypatch)
    handler, seen = _sequenced_handler(
        [502, 200], headers={"Retry-After": _FROZEN_NOW_HTTP_DATE}
    )

    payload = asyncio.run(_run_get(handler))

    assert payload["status_code"] == 0
    assert seen == [502, 200]
    assert len(sleeps) == 1
    # 换算出的 5 秒进入 _retry_wait 的下界（floor）：抖动只能向上推，外层 min() 封顶。
    assert sleeps[0] >= 5.0
    assert sleeps[0] <= client_module._RETRY_AFTER_MAX_SECONDS


def test_http_date_retry_after_already_expired_degrades_to_nominal_backoff(
    monkeypatch: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """验证**已过期**的 HTTP-date 退化为标称退避——刻意不是「等待 0 秒」。

    语义选择：负秒数与数值秒形式里的 ``-1`` 是同一条语义（两者同属「对端给出的等待值
    不可用」，而不是「要求立刻重试」），既有实现已把它归入「无法解析 → 退化为本地标称
    退避」。选 ``None`` 而不是换算出的 0 秒**不是**因为 0 秒会取消退避：等待时长由
    ``_retry_wait`` 的 ``floor = nominal if retry_after is None else max(nominal,
    retry_after)`` 决定，标称退避非负时 ``max(nominal, 0.0) == nominal``，故 ``0.0`` 与
    ``None`` 得到的等待**完全相同**（都由标称退避托底，可由
    ``test_retry_after_zero_waits_exactly_like_absent`` 直接核实）。两者唯一的可观测差别
    是**有没有那条 WARNING**：返回 ``None`` 会留痕说明「对端给了个过去的时间」，换报 0 秒
    则把这句抹掉、让过去的绝对时间伪装成合法取值（与真发 ``Retry-After: 0`` 无法区分）。
    崩溃更不可接受。所以这里断言 ``sleeps == [0.5]``（标称退避）而不是 ``[0.0]``。

    时钟已由 ``_freeze_utcnow`` 钉死（``_FROZEN_EXPIRED_HTTP_DATE`` 相对 ``_FROZEN_NOW``
    恒定过期 15 年），断言不随运行时刻漂移；等待时长由 ``_capture_sleeps`` 观测，全程无 sleep。
    """
    _freeze_utcnow(monkeypatch)
    monkeypatch.setattr(client_module, "get_a_bogus", lambda *_: "signature")
    monkeypatch.setattr(client_module, "_RETRY_BACKOFF_SECONDS", (0.5, 1.5))
    monkeypatch.setattr(client_module, "_RETRY_BACKOFF_JITTER", (1.0, 1.0))
    sleeps = _capture_sleeps(monkeypatch)
    handler, seen = _sequenced_handler(
        [502, 200], headers={"Retry-After": _FROZEN_EXPIRED_HTTP_DATE}
    )

    with caplog.at_level(logging.WARNING, logger="crawler.douyin_client.http.client"):
        payload = asyncio.run(_run_get(handler))
        warnings = [
            r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
        ]

    assert payload["status_code"] == 0
    assert seen == [502, 200]
    assert sleeps == [0.5]
    assert any("Retry-After" in message for message in warnings), warnings
    # 直接盯住解析层：过期日期与数值秒负数一样返回 None。
    assert (
        client_module._parse_retry_after(
            httpx.Response(502, headers={"Retry-After": _FROZEN_EXPIRED_HTTP_DATE})
        )
        is None
    )


def test_http_date_retry_after_beyond_cap_is_clamped_and_warns(
    monkeypatch: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """验证 HTTP-date 换算出的秒数超过上限时钳到上限等待，并记一条 WARNING。

    换算出的 60 秒先被钳到 ``_RETRY_AFTER_MAX_SECONDS``，再进入既有的抖动/封顶路径；
    ``floor == cap`` 时等待恒为上限（取舍见 ``_retry_wait`` 不变量 3），故断言恰好等于
    上限而不是「不超过上限」。
    """
    _freeze_utcnow(monkeypatch)
    monkeypatch.setattr(client_module, "get_a_bogus", lambda *_: "signature")
    sleeps = _capture_sleeps(monkeypatch)
    handler, seen = _sequenced_handler(
        [503, 200], headers={"Retry-After": _FROZEN_FAR_FUTURE_HTTP_DATE}
    )

    with caplog.at_level(logging.WARNING, logger="crawler.douyin_client.http.client"):
        payload = asyncio.run(_run_get(handler))
        warnings = [
            r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
        ]

    assert payload["status_code"] == 0
    assert seen == [503, 200]
    assert sleeps == [client_module._RETRY_AFTER_MAX_SECONDS]
    assert any("Retry-After" in message for message in warnings), warnings
    assert (
        client_module._parse_retry_after(
            httpx.Response(503, headers={"Retry-After": _FROZEN_FAR_FUTURE_HTTP_DATE})
        )
        == client_module._RETRY_AFTER_MAX_SECONDS
    )


@pytest.mark.parametrize(
    "retry_after",
    [None, "", "soon", "Wed, 32 Oct 2015 07:28:00 GMT", "-1"],
)
def test_request_ignores_unparseable_retry_after(
    retry_after: str | None, monkeypatch: Any
) -> None:
    """未支持/不可用的 Retry-After 取值退化为「标称退避 * 抖动」。

    参数表只剩**真正拿不到可用秒数**的形式：``None`` 表示响应根本没带这个头（正常
    路径）、空串、垃圾串、``32 Oct``（长相像 HTTP-date 但日字段越界，
    ``parsedate_to_datetime`` 直接抛 ValueError）、``-1``（数值秒里的「负数 = 无法
    解析」，与已过期的 HTTP-date 同语义）。**HTTP-date 已从本表移除**：RFC 9110 的
    合法日期形式现在会被解析成秒数，其「生效 / 已过期 / 超上限」三条分支分别由
    ``test_http_date_retry_after_is_honoured_as_wait_lower_bound``、
    ``test_http_date_retry_after_already_expired_degrades_to_nominal_backoff``、
    ``test_http_date_retry_after_beyond_cap_is_clamped_and_warns`` 承重。

    表里的 ``32 Oct`` 虽在 ``parsedate_to_datetime`` 抛 ValueError 之后才轮到时钟，但仍
    冻结时钟：这样本文件里**凡出现 HTTP-date 形状的断言都不可达真实时间**，日后若有人把
    解析顺序改到时钟之后，本用例的确定性也不会随之漂移。
    """
    monkeypatch.setattr(client_module, "get_a_bogus", lambda *_: "signature")
    _freeze_utcnow(monkeypatch)
    monkeypatch.setattr(client_module, "_RETRY_BACKOFF_SECONDS", (0.5, 1.5))
    monkeypatch.setattr(client_module, "_RETRY_BACKOFF_JITTER", (1.0, 1.0))
    sleeps = _capture_sleeps(monkeypatch)
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    handler, seen = _sequenced_handler([502, 200], headers=headers)

    payload = asyncio.run(_run_get(handler))

    assert payload["status_code"] == 0
    assert seen == [502, 200]
    # 解析不出就用「标称退避 * 抖动」，不引入任何额外等待。
    assert sleeps == [0.5]


@pytest.mark.parametrize(
    "retry_after",
    ["", "soon", _FROZEN_EXPIRED_HTTP_DATE, "-1", "nan", "inf"],
)
def test_unusable_retry_after_is_logged_as_warning(
    retry_after: str, monkeypatch: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """验证「响应带了 Retry-After 却用不上」会留一条 WARNING，而不是静默忽略。

    参数表里的 ``_FROZEN_EXPIRED_HTTP_DATE``（``Wed, 21 Oct 2015 07:28:00 GMT``）自 OI-9
    起走的是「HTTP-date 可解析、但换算结果已过期 → 视为无法解析」这条路径（同样 WARNING +
    退化为标称退避），不再是「格式不合法」；该路径的专测见
    ``test_http_date_retry_after_already_expired_degrades_to_nominal_backoff``。

    本用例**必须**冻结时钟：表里有一个活 HTTP-date，只有相对 ``_FROZEN_NOW`` 求值才能让
    「已过期」这一性质确定（否则它依赖运行机器的真实当前时间，方向虽单调、却让断言随
    到期语义的改动无声漂移）。``_freeze_utcnow`` 把被减数钉死，其余参数与时钟无关，一并
    获得确定性。等待时长由 ``_capture_sleeps`` 观测，全程无 sleep；``nan`` / ``inf`` 走的是
    数值秒分支里那道 ``math.isfinite`` 检查（该检查对 HTTP-date 分支不可达，见
    ``_parse_retry_after`` 实现处的注释）。
    """
    monkeypatch.setattr(client_module, "get_a_bogus", lambda *_: "signature")
    _freeze_utcnow(monkeypatch)
    _capture_sleeps(monkeypatch)
    handler, seen = _sequenced_handler([502, 200], headers={"Retry-After": retry_after})

    with caplog.at_level(logging.WARNING, logger="crawler.douyin_client.http.client"):
        payload = asyncio.run(_run_get(handler))

    assert payload["status_code"] == 0
    assert seen == [502, 200]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Retry-After" in r.getMessage() for r in warnings), caplog.text


def test_absent_retry_after_logs_no_warning(
    monkeypatch: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """验证响应没有 Retry-After 头（正常路径）时不会记 Retry-After 相关的 WARNING。

    只筛 Retry-After 相关的记录：空指纹的 FakeSession 另有一条与本题无关的指纹缺键
    WARNING，不该被本用例的断言牵连。
    """
    monkeypatch.setattr(client_module, "get_a_bogus", lambda *_: "signature")
    _capture_sleeps(monkeypatch)
    handler, seen = _sequenced_handler([502, 200])

    with caplog.at_level(logging.WARNING, logger="crawler.douyin_client.http.client"):
        payload = asyncio.run(_run_get(handler))

    assert payload["status_code"] == 0
    assert seen == [502, 200]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("Retry-After" in message for message in warnings), warnings


def test_request_carries_retry_after_on_retryable_status(monkeypatch: Any) -> None:
    """验证 Retry-After 随 _RetryableStatus 带出，且单参构造与继承关系仍然兼容。"""
    monkeypatch.setattr(client_module, "get_a_bogus", lambda *_: "signature")
    handler, _ = _sequenced_handler([502], headers={"Retry-After": "3"})

    async def scenario() -> _RetryableStatus:
        client = await _client_with_transport(handler)
        try:
            with pytest.raises(_RetryableStatus) as excinfo:
                await client.request("GET", "https://www.douyin.com/test")
            return excinfo.value
        finally:
            await client.close()

    exc = asyncio.run(scenario())

    # 既有 except DataFetchError 调用方不受影响。
    assert isinstance(exc, DataFetchError)
    assert exc.status_code == 502
    assert exc.retry_after == pytest.approx(3.0)
    # 既有单参构造签名仍可用，retry_after 缺省为 None。
    legacy = _RetryableStatus(503)
    assert legacy.retry_after is None
    assert isinstance(legacy, DataFetchError)


def test_douyin_client_fingerprint_params_come_from_session(monkeypatch: Any) -> None:
    """验证指纹参数逐键来自注入会话的指纹，且非指纹公共参数的键集不变。"""
    monkeypatch.setattr(
        "crawler.douyin_client.http.client.get_a_bogus", lambda *_: "signature"
    )
    session = FakeSession(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.6367.91 Safari/537.36"
        ),
        local_storage={"xmst": "token"},
        fingerprint=_INJECTED_FINGERPRINT,
    )

    async def scenario() -> dict[str, Any]:
        client = await DouyinClient.create(session=session, timeout=1, verify_ssl=True)
        try:
            return await client._process_params("/test", {}, client.headers)
        finally:
            await client.close()

    params = asyncio.run(scenario())

    # 注入指纹里的每个键都逐字写入（值来自会话，不是任何本地常量）。
    for key, value in _INJECTED_FINGERPRINT.items():
        assert params[key] == value
    # 键表声明了 engine_version 但会话没有提供 → 该键不写入（缺键不伪造）。
    assert "engine_version" in DouyinClient.FINGERPRINT_KEYS
    assert "engine_version" not in params
    # 旧的硬编码指纹不得以任何形式重现。
    for legacy in _LEGACY_FAKE_FINGERPRINT_VALUES:
        assert legacy not in params.values()
    # 非指纹公共参数的键集与取值保持原样。
    assert set(params) - _FINGERPRINT_KEYS == _STABLE_PUBLIC_PARAM_KEYS | {"a_bogus"}
    assert params["device_platform"] == "webapp"
    assert params["aid"] == "6383"
    assert params["platform"] == "PC"
    assert params["msToken"] == "token"
    assert params["a_bogus"] == "signature"


def test_fingerprint_keys_are_not_written_when_session_has_none(
    monkeypatch: Any,
) -> None:
    """验证会话拿不到任何指纹时不写入指纹键，也绝不回退伪造常量。"""
    monkeypatch.setattr(
        "crawler.douyin_client.http.client.get_a_bogus", lambda *_: "signature"
    )

    async def scenario() -> dict[str, Any]:
        client = _client(FakeSession(local_storage={"xmst": "token"}))
        try:
            return await client._process_params("/test", {}, client.headers)
        finally:
            await client.close()

    params = asyncio.run(scenario())

    assert set(params) & _FINGERPRINT_KEYS == set()
    assert set(params) == _STABLE_PUBLIC_PARAM_KEYS | {"a_bogus"}
    for legacy in _LEGACY_FAKE_FINGERPRINT_VALUES:
        assert legacy not in params.values()


def test_client_source_has_no_hardcoded_fingerprint_literals() -> None:
    """验证指纹完全外置：源码中不再出现任何硬编码指纹字面量（R9 的三个键在内）。"""
    source = Path(cast(str, client_module.__file__)).read_text(encoding="utf-8")
    present = [token for token in _FORBIDDEN_SOURCE_LITERALS if token in source]
    assert present == []


def test_pong_and_update_cookies_read_only_the_injected_session() -> None:
    """验证 pong / update_cookies 是无浏览器入参的纯 API 方法（R1 兼容参数已删除）。

    S5b 已彻底删除 ``browser_context`` 形参：二者只读注入会话，签名里不再有任何
    浏览器对象，因此 business 侧也不再有可传的原生上下文。
    """
    session = FakeSession(
        local_storage={"HasUserLogin": "1"},
        cookies=("LOGIN_STATUS=1", {"LOGIN_STATUS": "1"}),
    )
    client = _client(session)

    async def scenario() -> tuple[bool, bool]:
        logged_in = await client.pong()
        await client.update_cookies()
        return logged_in, await client.pong(require_self_profile=False)

    try:
        logged_in, logged_in_again = asyncio.run(scenario())
    finally:
        asyncio.run(client.close())

    assert logged_in is True
    assert logged_in_again is True
    assert client.headers["Cookie"] == "LOGIN_STATUS=1"
    assert client.cookie_dict == {"LOGIN_STATUS": "1"}


def test_pong_and_update_cookies_reject_browser_context_argument() -> None:
    """验证 R1 的临时兼容入参已从签名删除：再传浏览器上下文是 TypeError。"""
    import inspect

    client = _client()
    try:
        for method in (client.pong, client.update_cookies):
            parameters = inspect.signature(method).parameters
            assert "browser_context" not in parameters
    finally:
        asyncio.run(client.close())


def test_douyin_client_has_no_browser_dependency() -> None:
    """验证纯 API 层零浏览器依赖：导入本包不得把 playwright 拉进 sys.modules。

    必须另起解释器：pytest 会话的 conftest 顶层 import ``crawler.api.main``，
    进程内早已加载 playwright，无法用它判断本包自身的 import 图。
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import crawler.douyin_client, sys; "
                "assert 'playwright' not in sys.modules, "
                "sorted(m for m in sys.modules if m.startswith('playwright'))"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# --- CommentsApi.find_comment：目标评论存在性核验（纯 API 层可测试性收益） ---


def test_find_comment_returns_present_when_target_on_first_page(
    monkeypatch: Any,
) -> None:
    """验证目标评论出现在首页时立即返回 present，且只请求一次。"""
    monkeypatch.setattr(
        "crawler.douyin_client.http.client.get_a_bogus", lambda *_: "signature"
    )
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "status_code": 0,
                "comments": [{"cid": "other"}, {"cid": "target"}],
                "has_more": 1,
                "cursor": 20,
            },
        )

    async def scenario() -> str:
        client = await _client_with_transport(handler)
        try:
            return await client.comments_api.find_comment(
                aweme_id="123", comment_id="target"
            )
        finally:
            await client.close()

    assert asyncio.run(scenario()) == "present"
    assert len(requests) == 1


def test_find_comment_returns_unavailable_after_full_pagination(
    monkeypatch: Any,
) -> None:
    """验证翻完所有页且目标未出现时返回 unavailable（has_more 为 0）。"""
    monkeypatch.setattr(
        "crawler.douyin_client.http.client.get_a_bogus", lambda *_: "signature"
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status_code": 0,
                "comments": [{"cid": "other"}],
                "has_more": 0,
                "cursor": 20,
            },
        )

    async def scenario() -> str:
        client = await _client_with_transport(handler)
        try:
            return await client.comments_api.find_comment(
                aweme_id="123", comment_id="target"
            )
        finally:
            await client.close()

    assert asyncio.run(scenario()) == "unavailable"


@pytest.mark.parametrize(
    "payload",
    [
        # 业务状态失败：不能证明评论已消失。
        {"status_code": 4, "comments": [], "has_more": 0},
        # 缺少分页契约字段。
        {"status_code": 0, "comments": []},
        # has_more 类型不可判定。
        {"status_code": 0, "comments": [{"cid": "other"}], "has_more": "maybe"},
        # comments 不是列表。
        {"status_code": 0, "comments": {"cid": "other"}, "has_more": 1},
        # 游标原地踏步（has_more 仍为真）。
        {"status_code": 0, "comments": [{"cid": "other"}], "has_more": 1, "cursor": 0},
    ],
)
def test_find_comment_returns_inconclusive_for_unprovable_responses(
    payload: dict[str, Any], monkeypatch: Any
) -> None:
    """验证任何无法定论的响应都返回 inconclusive，保证任务可安全重试。"""
    monkeypatch.setattr(
        "crawler.douyin_client.http.client.get_a_bogus", lambda *_: "signature"
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async def scenario() -> str:
        client = await _client_with_transport(handler)
        try:
            return await client.comments_api.find_comment(
                aweme_id="123", comment_id="target"
            )
        finally:
            await client.close()

    assert asyncio.run(scenario()) == "inconclusive"


def test_find_comment_returns_inconclusive_on_api_failure(monkeypatch: Any) -> None:
    """验证接口抛错时返回 inconclusive，而不是把异常抛给任务层。"""
    monkeypatch.setattr(
        "crawler.douyin_client.http.client.get_a_bogus", lambda *_: "signature"
    )
    monkeypatch.setattr(
        "crawler.douyin_client.http.client._RETRY_BACKOFF_SECONDS", (0.0, 0.0)
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="gateway unavailable")

    async def scenario() -> str:
        client = await _client_with_transport(handler)
        try:
            return await client.comments_api.find_comment(
                aweme_id="123", comment_id="target"
            )
        finally:
            await client.close()

    assert asyncio.run(scenario()) == "inconclusive"


def test_find_comment_without_target_id_does_not_call_api() -> None:
    """验证未给出目标评论 ID 时直接返回 inconclusive，不发任何请求。"""
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"status_code": 0})

    async def scenario() -> str:
        client = await _client_with_transport(handler)
        try:
            return await client.comments_api.find_comment(aweme_id="123", comment_id="")
        finally:
            await client.close()

    assert asyncio.run(scenario()) == "inconclusive"
    assert calls == 0


def test_find_comment_uses_sub_comment_page_for_reply_targets(
    monkeypatch: Any,
) -> None:
    """验证带父评论 ID 时改翻子评论页，并沿用其判定结果。"""
    monkeypatch.setattr(
        "crawler.douyin_client.http.client.get_a_bogus", lambda *_: "signature"
    )
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "status_code": 0,
                "comments": [{"cid": "target"}],
                "has_more": 0,
            },
        )

    async def scenario() -> str:
        client = await _client_with_transport(handler)
        try:
            return await client.comments_api.find_comment(
                aweme_id="123",
                comment_id="target",
                parent_comment_id="parent-1",
            )
        finally:
            await client.close()

    assert asyncio.run(scenario()) == "present"
    assert paths == ["/aweme/v1/web/comment/list/reply/"]


def test_find_comment_stops_at_page_and_comment_limits(monkeypatch: Any) -> None:
    """验证翻页/条数上限被遵守：超出上限仍未定论时返回 inconclusive。"""
    monkeypatch.setattr(
        "crawler.douyin_client.http.client.get_a_bogus", lambda *_: "signature"
    )
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "status_code": 0,
                "comments": [{"cid": "other"}],
                "has_more": 1,
                "cursor": calls * 10,
            },
        )

    async def scenario() -> tuple[str, str, int]:
        client = await _client_with_transport(handler)
        try:
            by_pages = await client.comments_api.find_comment(
                aweme_id="123", comment_id="target", max_pages=1
            )
            by_comments = await client.comments_api.find_comment(
                aweme_id="123", comment_id="target", max_comments=1
            )
            return by_pages, by_comments, calls
        finally:
            await client.close()

    by_pages, by_comments, calls = asyncio.run(scenario())

    assert by_pages == "inconclusive"
    assert by_comments == "inconclusive"
    # 两条用例各只发一次请求：页数上限与条数上限都在首轮即生效。
    assert calls == 2
