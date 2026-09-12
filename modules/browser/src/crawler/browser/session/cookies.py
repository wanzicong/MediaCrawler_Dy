"""cookie 序列化与解析工具：浏览器上下文 cookie 与站点 cookie 字符串互转。

browser 模块的定位是「与浏览器相关的封装与操作」，使用方直接导入即可。
本模块与具体站点无关：需要收集哪些域名/URL 的 cookie 由调用方作为参数传入，
解析出的名值字典与 cookie 字符串不携带任何平台语义。
"""

from __future__ import annotations

from typing import Any

from playwright.async_api import BrowserContext


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


def parse_cookie_string(cookie_string: str) -> dict[str, str]:
    """将 ``name=value; ...`` 形式的 cookie 字符串解析为字典。

    忽略无等号或名称为空的片段。
    """
    result: dict[str, str] = {}
    for part in cookie_string.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name.strip():
            result[name.strip()] = value
    return result
