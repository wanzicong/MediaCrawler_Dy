"""抖音客户端（DouyinClient）的测试：覆盖收藏接口的查询/表单参数分离、POST 请求体签名注入、5xx 重签名重试、指纹逐键来自注入会话、目标评论存在性核验与零浏览器依赖。"""

import asyncio
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from crawler.douyin_client import DataFetchError, DouyinClient
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


@pytest.mark.parametrize("status", [403, 429])
def test_request_never_retries_forbidden_or_rate_limited(
    status: int, monkeypatch: Any
) -> None:
    """验证 403/429 只发一次请求：风控拦截与限流在结构上不可能进入重试分支。"""
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
        return httpx.Response(status, text="risk control")

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
    from crawler.douyin_client.http import client as client_module

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
