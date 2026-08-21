"""抖音客户端（DouyinClient）的测试：覆盖收藏接口的查询/表单参数分离、浏览器会话仅支持 CDP 模式以及 POST 请求体签名注入。"""

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from crawler.douyin_client.client import DouyinClient
from crawler.douyin_client.errors import DataFetchError
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page


def test_collected_keeps_query_and_form_body_separate() -> None:
    """验证收藏列表接口将分页参数放在查询串、aid 放在表单体，二者不混淆。"""
    client = DouyinClient(
        page=cast(Page, object()),
        headers={"User-Agent": "ua"},
        cookie_dict={},
        timeout=1,
        verify_ssl=True,
    )
    post = AsyncMock(return_value={"status_code": 0})
    client.post = post  # type: ignore[method-assign]

    result = asyncio.run(client.get_collected(cursor=20, count=10))
    asyncio.run(client.close())

    assert result["status_code"] == 0
    args = post.await_args.args
    assert args[1] == {"count": 10, "cursor": 20}
    assert args[3] == {"aid": "6383"}


def test_no_standard_playwright_launch_fallback() -> None:
    """验证浏览器会话实现中不存在标准 playwright 启动回退（仅允许 CDP 连接方式）。"""
    from crawler.browser import session as browser

    source = open(browser.__file__, encoding="utf-8").read()
    forbidden = [
        "chromium.launch(",
        "launch_persistent_context",
        "ENABLE_CDP_MODE",
        "fallback to standard",
    ]
    assert not [token for token in forbidden if token in source]


class FakePage:
    """模拟 playwright 页面：evaluate 固定返回 msToken 令牌。"""

    async def evaluate(self, _: str) -> dict[str, str]:
        """返回模拟的页面令牌。"""
        return {"xmst": "token"}


def test_post_without_query_sends_signed_body(monkeypatch: Any) -> None:
    """验证无查询串的 POST 请求会在表单体中注入 a_bogus 签名与 aid 后再发出。"""
    client = DouyinClient(
        page=cast(Page, FakePage()),
        headers={"User-Agent": "ua"},
        cookie_dict={},
        timeout=1,
        verify_ssl=True,
    )
    request = AsyncMock(return_value={"status_code": 0})
    client.request = request  # type: ignore[method-assign]
    monkeypatch.setattr(
        "crawler.douyin_client.client.get_a_bogus", lambda *_: "signature"
    )

    asyncio.run(client.post("/test", {"value": "1"}))
    asyncio.run(client.close())

    sent_body = request.await_args.kwargs["data"]
    assert sent_body["value"] == "1"
    assert sent_body["a_bogus"] == "signature"
    assert sent_body["aid"] == "6383"


def test_page_evaluate_retries_navigation_context_race() -> None:
    """验证页面正好导航时的上下文销毁会短暂重试，而不是让任务直接失败。"""

    class NavigatingPage:
        """第一次 evaluate 模拟导航竞态，第二次返回稳定结果。"""

        def __init__(self) -> None:
            self.attempts = 0

        async def evaluate(self, _: str) -> str:
            self.attempts += 1
            if self.attempts == 1:
                raise PlaywrightError("Execution context was destroyed")
            return "stable-user-agent"

        async def wait_for_load_state(self, *_: Any, **__: Any) -> None:
            return None

    page = NavigatingPage()
    result = asyncio.run(
        DouyinClient._evaluate_stable(cast(Page, page), "() => navigator.userAgent")
    )

    assert result == "stable-user-agent"
    assert page.attempts == 2


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
        client = DouyinClient(
            page=cast(Page, FakePage()),
            headers={"User-Agent": "ua"},
            cookie_dict={},
            timeout=1,
            verify_ssl=True,
        )
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
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
        client = DouyinClient(
            page=cast(Page, FakePage()),
            headers={"User-Agent": "ua"},
            cookie_dict={},
            timeout=1,
            verify_ssl=True,
        )
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
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
        client = DouyinClient(
            page=cast(Page, FakePage()),
            headers={"User-Agent": "ua"},
            cookie_dict={},
            timeout=1,
            verify_ssl=True,
        )
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

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
        client = DouyinClient(
            page=cast(Page, FakePage()),
            headers={"User-Agent": "ua"},
            cookie_dict={},
            timeout=1,
            verify_ssl=True,
        )
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

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
