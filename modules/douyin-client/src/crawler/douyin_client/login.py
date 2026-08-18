# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音登录流程封装：cookie 登录与扫码登录（基于 Playwright 浏览器上下文）。"""

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
# 二维码更新回调：参数为二维码图片路径，None 表示二维码已清除
QRCodeCallback = Callable[[Path | None], Awaitable[None]]


def parse_cookie_string(cookie_string: str) -> dict[str, str]:
    """将 ``name=value; ...`` 形式的 cookie 字符串解析为字典，忽略无等号或名称为空的片段。"""
    result: dict[str, str] = {}
    for part in cookie_string.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name.strip():
            result[name.strip()] = value
    return result


class DouyinLogin:
    """抖音登录器，封装 cookie 登录与扫码登录两种流程。

    通过 Playwright 浏览器上下文写入 cookie 或引导用户扫码，
    登录成功后回写 DouyinClient 的 cookies。

    参数：
        browser_context: Playwright 浏览器上下文。
        page: 已打开抖音站点的页面。
        qrcode_path: 登录二维码图片的落盘路径。
        timeout: 扫码登录的等待超时时间（秒）。
        on_qrcode: 二维码更新回调，收到图片路径或 None（清除）。
    """

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
        """使用 cookie 字符串完成登录。

        清空 douyin.com 域的旧 cookie 后写入新 cookie，
        刷新页面并调用接口校验登录状态。

        参数：
            cookie_string: 抖音站点的 cookie 字符串。
            client: 用于同步 cookie 与校验登录状态的客户端。

        异常：
            LoginError: cookie 为空、无效或已过期时抛出。
        """
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
        """扫码登录：弹出登录框、持续抓取二维码并等待用户扫码完成。

        参数：
            client: 用于检测登录状态与回写 cookie 的客户端。
            require_self_profile: 是否要求通过本人资料接口校验登录状态。

        异常：
            LoginError: 超时仍未完成扫码登录时抛出。
        """
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
        """打开抖音登录弹窗；按候选控件依次尝试点击「登录」，全部失败时抛 LoginError。"""
        selector = "xpath=//div[@id='login-panel-new']"
        try:
            await self.page.wait_for_selector(selector, timeout=5_000)
            return
        except Exception:
            pass

        # 抖音当前版本的页头把「登录」文案包在 button 里。若直接选择第一个
        # 匹配的 <p>，可能命中隐藏的用户菜单节点，导致弹窗静默打不开，
        # 在有头的 Docker 浏览器中尤其明显。
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
        """等待并读取登录二维码图片的 src；超时或异常时返回空字符串。"""
        try:
            element = await self.page.wait_for_selector(selector, timeout=5_000)
            if element is None:
                return ""
            return str(await element.get_attribute("src") or "")
        except Exception:
            return ""

    async def _save_qrcode(self, source: str) -> None:
        """将二维码内容（data URL / http(s) 链接 / base64）解码保存到本地并触发回调。

        异常：
            LoginError: 无法解析二维码内容时抛出。
        """
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
        """清除二维码：通知回调（None）并删除本地二维码文件。"""
        await self.on_qrcode(None)
        if self.qrcode_path.exists():
            await asyncio.to_thread(self.qrcode_path.unlink, missing_ok=True)
