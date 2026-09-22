"""``BrowserPage`` 的唯一实现：包住 Playwright 页面并收窄上层可见的能力。

只读的四个原语（UA / localStorage / cookie / 指纹）与截图是**出门面**的能力，
直接委托给 ``BrowserSessionContext`` 与站点无关的截图能力；导航、cookie 写入、
选择器等待等**写操作**只作为本句柄的内部方法存在，不上门面、不出 browser，
由 ``crawler.browser`` 内部的会话编排与站点流程调用。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from crawler.browser.session.context import BrowserSessionContext
from playwright._impl._api_structures import SetCookieParam
from playwright.async_api import BrowserContext, ElementHandle, Page

_DEFAULT_NAVIGATION_TIMEOUT_MS = 30_000

# Playwright 期望的加载状态字面量联合。公开签名（会话 open() / 本句柄方法）按
# 规格冻结为 str，仅在调用 Playwright 的边界处收窄。
PlaywrightWaitUntil = Literal["commit", "domcontentloaded", "load", "networkidle"]


class PlaywrightPageHandle:
    """BrowserPage 的唯一实现，内部附带写操作与 Playwright 原生对象。

    上层（business/api/mcp）只能把它当作 ``BrowserPage`` 使用：``goto`` /
    ``set_cookies`` / ``page`` / ``context`` 这些名字禁止出现在 browser 之外。
    """

    def __init__(
        self,
        *,
        page: Page,
        context: BrowserContext,
        session_context: BrowserSessionContext | None = None,
    ) -> None:
        """初始化句柄。

        参数：
            page: 会话当前使用的 Playwright 页面。
            context: 页面所属的浏览器上下文。
            session_context: 共享的会话能力适配器；为 None 时本句柄自建一个，
                调用方（``CDPBrowserSession``）传入可保证与 ``session_context()``
                返回同一份指纹缓存。
        """
        self._page = page
        self._context = context
        self._session_context = (
            session_context
            if session_context is not None
            else BrowserSessionContext(page=page, context=context)
        )

    # ---- BrowserPage：上层唯一可用的只读能力面 ----

    async def user_agent(self) -> str:
        """返回当前浏览器会话的真实 User-Agent；取不到时返回空字符串。"""
        return await self._session_context.user_agent()

    async def local_storage(self) -> dict[str, Any]:
        """返回当前页面的 window.localStorage 快照；取不到时返回 {}。"""
        return await self._session_context.local_storage()

    async def cookies(self, urls: Sequence[str]) -> tuple[str, dict[str, str]]:
        """读取指定 URL 的 cookie，返回 (cookie 字符串, 名值字典)。"""
        return await self._session_context.cookies(urls)

    async def fingerprint(self) -> Mapping[str, str]:
        """返回与真实浏览器一致的请求指纹参数；缺失的键不写入。"""
        return await self._session_context.fingerprint()

    async def evaluate(self, expression: str, argument: Any = None) -> Any:
        """在页面上下文执行 JS（供调用方借页面内安全 SDK 发请求）。"""
        return await self._session_context.evaluate(expression, argument)

    async def capture_screenshot(self, *, quality: int, timeout: float) -> bytes:
        """通过 CDP 截取当前页面 JPEG 图像并返回原始字节。

        实现复用站点无关的 ``facade.capabilities.capture_screenshot``。此处延迟
        import：``facade`` 包会反向 import ``session.manager``，模块级 import 会
        构成 ``page.handle -> facade -> session.manager -> page.handle`` 的环。
        """
        from crawler.browser.facade.capabilities import (
            capture_screenshot as _capture_screenshot,
        )

        return await _capture_screenshot(self._page, quality=quality, timeout=timeout)

    # ---- browser 内部专用：不出门面，business/api/mcp 禁止出现这些名字 ----

    @property
    def page(self) -> Page:
        """原始 Playwright 页面（仅供 browser 内部编排使用）。"""
        return self._page

    @property
    def context(self) -> BrowserContext:
        """原始浏览器上下文（仅供 browser 内部编排使用）。"""
        return self._context

    async def goto(
        self,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        timeout_ms: int = _DEFAULT_NAVIGATION_TIMEOUT_MS,
    ) -> None:
        """导航到指定 URL；与 ``page.goto`` 同语义（超时/失败按 Playwright 异常抛出）。"""
        await self._page.goto(
            url,
            wait_until=cast("PlaywrightWaitUntil", wait_until),
            timeout=timeout_ms,
        )

    async def reload(
        self,
        *,
        wait_until: str = "domcontentloaded",
        timeout_ms: int = _DEFAULT_NAVIGATION_TIMEOUT_MS,
    ) -> None:
        """重新加载当前页面，等待到指定的加载状态。"""
        await self._page.reload(
            wait_until=cast("PlaywrightWaitUntil", wait_until),
            timeout=timeout_ms,
        )

    def current_url(self) -> str:
        """返回页面当前地址。"""
        return self._page.url

    async def set_cookies(self, cookies: Sequence[SetCookieParam]) -> None:
        """向浏览器上下文写入 cookie（登录流程回写 cookie 用）。"""
        await self._context.add_cookies(list(cookies))

    async def clear_domain_cookies(self, domain: str | re.Pattern[str]) -> None:
        """清空匹配 domain 的 cookie；domain 可为字符串或正则。"""
        await self._context.clear_cookies(domain=domain)

    async def wait_for_selector(
        self, selector: str, *, timeout_ms: int = 5_000
    ) -> ElementHandle | None:
        """等待选择器出现，返回匹配到的元素句柄（超时抛 Playwright 异常）。"""
        return await self._page.wait_for_selector(selector, timeout=timeout_ms)


__all__ = ["PlaywrightPageHandle"]
