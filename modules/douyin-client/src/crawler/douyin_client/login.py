# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

import asyncio
import base64
import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from crawler.douyin_client.client import DouyinClient
from crawler.douyin_client.errors import LoginError
from playwright.async_api import BrowserContext, Page

logger = logging.getLogger(__name__)
QRCodeCallback = Callable[[Path | None], Awaitable[None]]


def parse_cookie_string(cookie_string: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in cookie_string.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name.strip():
            result[name.strip()] = value
    return result


class DouyinLogin:
    def __init__(
        self,
        *,
        browser_context: BrowserContext,
        page: Page,
        qrcode_path: Path,
        timeout: float,
        on_qrcode: QRCodeCallback,
    ):
        self.browser_context = browser_context
        self.page = page
        self.qrcode_path = qrcode_path
        self.timeout = timeout
        self.on_qrcode = on_qrcode

    async def login_with_cookie(self, cookie_string: str, client: DouyinClient) -> None:
        cookie_items = parse_cookie_string(cookie_string)
        if not cookie_items:
            raise LoginError("cookie 登录需要非空 cookies")
        await self.browser_context.clear_cookies(
            domain=re.compile(r"(^|\.)douyin\.com$")
        )
        await self.browser_context.add_cookies(
            [
                {"name": key, "value": value, "domain": ".douyin.com", "path": "/"}
                for key, value in cookie_items.items()
            ]
        )
        await self.page.reload(wait_until="domcontentloaded")
        await client.update_cookies(self.browser_context)
        if not await client.pong(self.browser_context):
            raise LoginError("提供的抖音 cookies 无效或已过期")

    async def login_with_qrcode(
        self, client: DouyinClient, *, require_self_profile: bool
    ) -> None:
        await self._popup_login_dialog()
        selector = "xpath=//div[@id='animate_qrcode_container']//img"
        last_source = ""
        deadline = asyncio.get_running_loop().time() + self.timeout
        while asyncio.get_running_loop().time() < deadline:
            if await client.pong(
                self.browser_context, require_self_profile=require_self_profile
            ):
                await client.update_cookies(self.browser_context)
                await self._clear_qrcode()
                return
            source = await self._qrcode_source(selector)
            if source and source != last_source:
                await self._save_qrcode(source)
                last_source = source
            await asyncio.sleep(1)
        await self._clear_qrcode()
        raise LoginError("等待抖音扫码登录超时")

    async def _popup_login_dialog(self) -> None:
        selector = "xpath=//div[@id='login-panel-new']"
        try:
            await self.page.wait_for_selector(selector, timeout=5_000)
            return
        except Exception:
            pass

        # Douyin's current header wraps the login text in a button. Selecting
        # the first matching <p> can hit a hidden user-menu node and silently
        # leave the dialog closed, especially in the headed Docker browser.
        candidates = [
            self.page.get_by_role("button", name="登录", exact=True).first,
            self.page.locator("#douyin-header button").filter(has_text="登录").first,
            self.page.locator("xpath=//p[normalize-space()='登录']").first,
        ]
        last_error: Exception | None = None
        for button in candidates:
            try:
                await button.click(timeout=5_000)
            except Exception as click_error:
                last_error = click_error
                try:
                    await button.dispatch_event("click")
                except Exception as dispatch_error:
                    last_error = dispatch_error
                    continue
            try:
                await self.page.wait_for_selector(selector, timeout=10_000)
                return
            except Exception as dialog_error:
                last_error = dialog_error

        raise LoginError("无法打开抖音登录窗口") from last_error

    async def _qrcode_source(self, selector: str) -> str:
        try:
            element = await self.page.wait_for_selector(selector, timeout=5_000)
            if element is None:
                return ""
            return str(await element.get_attribute("src") or "")
        except Exception:
            return ""

    async def _save_qrcode(self, source: str) -> None:
        if source.startswith("data:"):
            encoded = source.split(",", 1)[1]
            content = base64.b64decode(encoded)
        elif source.startswith(("http://", "https://")):
            async with httpx.AsyncClient(
                trust_env=False, follow_redirects=True
            ) as client:
                response = await client.get(source)
                response.raise_for_status()
                content = response.content
        else:
            try:
                content = base64.b64decode(source)
            except ValueError as exc:
                raise LoginError("无法解析抖音登录二维码") from exc
        self.qrcode_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self.qrcode_path.write_bytes, content)
        await self.on_qrcode(self.qrcode_path)
        logger.info("Douyin login QR code updated: %s", self.qrcode_path)

    async def _clear_qrcode(self) -> None:
        await self.on_qrcode(None)
        if self.qrcode_path.exists():
            await asyncio.to_thread(self.qrcode_path.unlink, missing_ok=True)
