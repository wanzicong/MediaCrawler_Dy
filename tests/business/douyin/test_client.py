"""抖音客户端（DouyinClient）的测试：覆盖收藏接口的查询/表单参数分离、浏览器会话仅支持 CDP 模式以及 POST 请求体签名注入。"""

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock

from crawler.douyin_client.client import DouyinClient
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
