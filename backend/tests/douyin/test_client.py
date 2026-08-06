import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock

from playwright.async_api import Page

from app.douyin.client import DouyinClient


def test_collected_keeps_query_and_form_body_separate() -> None:
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
    from app.douyin import browser

    source = open(browser.__file__, encoding="utf-8").read()
    forbidden = [
        "chromium.launch(",
        "launch_persistent_context",
        "ENABLE_CDP_MODE",
        "fallback to standard",
    ]
    assert not [token for token in forbidden if token in source]


class FakePage:
    async def evaluate(self, _: str) -> dict[str, str]:
        return {"xmst": "token"}


def test_post_without_query_sends_signed_body(monkeypatch: Any) -> None:
    client = DouyinClient(
        page=cast(Page, FakePage()),
        headers={"User-Agent": "ua"},
        cookie_dict={},
        timeout=1,
        verify_ssl=True,
    )
    request = AsyncMock(return_value={"status_code": 0})
    client.request = request  # type: ignore[method-assign]
    monkeypatch.setattr("app.douyin.client.get_a_bogus", lambda *_: "signature")

    asyncio.run(client.post("/test", {"value": "1"}))
    asyncio.run(client.close())

    sent_body = request.await_args.kwargs["data"]
    assert sent_body["value"] == "1"
    assert sent_body["a_bogus"] == "signature"
    assert sent_body["aid"] == "6383"
