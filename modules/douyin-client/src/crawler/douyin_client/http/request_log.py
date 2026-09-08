# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音请求的公共辅助类型与 cookie 转换工具。

集中 ``DouyinRequestLogEntry`` / ``RequestLogCallback`` 等记录类型、请求间隔与
cookie 转换函数；``http/client.py`` 从本模块导入，保持客户端聚焦请求本身。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from playwright.async_api import BrowserContext

if TYPE_CHECKING:
    from crawler.douyin_client.http.client import DouyinClient

# 评论批次回调：参数为 aweme_id 与本批评论原始字典列表
CommentCallback = Callable[[str, list[dict[str, Any]]], Awaitable[None]]
# 请求间隔（秒）：可为固定数值，或返回数值的可调用对象
IntervalProvider = float | Callable[[], float]


@dataclass
class DouyinRequestLogEntry:
    """一次抖音接口调用的可观测记录。

    该对象仅在进程内短暂存在；上层落库前必须脱敏 Cookie、令牌、签名与账号标识。
    响应侧仅在失败时短暂携带返回快照；上层落库前必须继续脱敏并限长。
    """

    method: str  # HTTP 方法
    path: str  # 请求路径（不含查询串）
    url: str  # 完整请求地址
    query_params: dict[str, Any]  # 签名后的完整查询参数
    request_headers: dict[str, str]  # 实际发送的全部请求头
    request_body: dict[str, Any] | None  # POST 表单数据（签名后），GET 为 None
    response_status: int | None  # 响应状态码；网络异常时为 None
    duration_ms: int  # 请求耗时（毫秒）
    error: str | None  # 异常类型名；成功时为 None
    failure_detail: dict[str, Any] | None = None  # 失败响应快照；成功时为 None


# 抖音请求日志回调：由上层应用注册，每次抖音接口调用完成后触发
RequestLogCallback = Callable[["DouyinClient", DouyinRequestLogEntry], Awaitable[None]]


def _interval_seconds(interval: IntervalProvider) -> float:
    """将固定值或可调用形式的间隔配置统一解析为秒数。"""
    return interval() if callable(interval) else interval


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
