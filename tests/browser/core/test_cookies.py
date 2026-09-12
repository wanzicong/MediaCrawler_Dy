"""browser 模块 cookie 工具的直测。

这些工具与站点无关：Playwright cookie 字典 ↔ cookie 字符串 ↔ 名值字典。
此处只覆盖纯函数边界与上下文读取。
"""

import asyncio
from unittest.mock import AsyncMock

from crawler.browser.session.cookies import (
    browser_cookies,
    convert_cookies,
    parse_cookie_string,
)


def test_convert_cookies_builds_string_and_dict() -> None:
    """验证 cookie 字典列表转出 cookie 字符串与名值字典。"""
    cookies = [
        {"name": "sid", "value": "abc", "domain": ".douyin.com"},
        {"name": "ttwid", "value": "xyz", "domain": ".douyin.com"},
    ]

    cookie_string, cookie_dict = convert_cookies(cookies)

    assert cookie_string == "sid=abc;ttwid=xyz"
    assert cookie_dict == {"sid": "abc", "ttwid": "xyz"}


def test_convert_cookies_skips_missing_name() -> None:
    """验证无 name 的 cookie 条目不会污染结果。"""
    cookies: list[dict[str, object]] = [
        {"value": "orphan", "domain": ".douyin.com"},
        {"name": "sid", "value": "abc"},
    ]

    cookie_string, cookie_dict = convert_cookies(cookies)  # type: ignore[arg-type]

    assert cookie_string == "sid=abc"
    assert cookie_dict == {"sid": "abc"}


def test_convert_cookies_empty_input() -> None:
    """验证空输入返回空字符串与空字典。"""
    assert convert_cookies([]) == ("", {})


def test_browser_cookies_reads_context_for_urls() -> None:
    """验证从浏览器上下文读取指定 URL 的 cookie 并完成序列化。"""
    context = AsyncMock()
    context.cookies.return_value = [{"name": "sid", "value": "abc"}]

    cookie_string, cookie_dict = asyncio.run(
        browser_cookies(context, ["https://www.douyin.com/"])
    )

    context.cookies.assert_awaited_once_with(urls=["https://www.douyin.com/"])
    assert cookie_string == "sid=abc"
    assert cookie_dict == {"sid": "abc"}


def test_parse_cookie_string_round_trips() -> None:
    """验证 cookie 字符串能完整解析回名值字典（段首尾空白被清理）。"""
    parsed = parse_cookie_string(" sid=v1;  ttwid=v2 ")

    assert parsed == {"sid": "v1", "ttwid": "v2"}


def test_parse_cookie_string_keeps_embedded_equals() -> None:
    """验证值内部的等号只按第一个分割符切分，其余保留。"""
    parsed = parse_cookie_string("token=a=b=c")

    assert parsed == {"token": "a=b=c"}


def test_parse_cookie_string_ignores_malformed_segments() -> None:
    """验证无等号或名称为空的片段被忽略。"""
    parsed = parse_cookie_string("=orphan; bare; sid=abc")

    assert parsed == {"sid": "abc"}


def test_parse_cookie_string_empty_input() -> None:
    """验证空字符串解析为空字典。"""
    assert parse_cookie_string("") == {}
    assert parse_cookie_string(";; ;") == {}
