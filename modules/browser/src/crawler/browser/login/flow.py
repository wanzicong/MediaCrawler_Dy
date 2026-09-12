# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音登录流程封装：cookie 登录与扫码登录（基于 CDP 浏览器会话）。

登录器只操作浏览器侧：清空 douyin.com 域旧 cookie、写入新 cookie、刷新页面、
抓取并落盘二维码。登录态的判定与 cookie 同步全部委托给注入的 ``LoginApi``，
因此本模块不依赖 ``crawler.douyin_client``。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from crawler.browser.errors import LoginError
from crawler.browser.page.handle import PlaywrightPageHandle
from crawler.browser.session.cookies import parse_cookie_string
from playwright.async_api import Page

if TYPE_CHECKING:  # 门面协议与会话只作类型注解，运行时 import 会构成包环。
    from crawler.browser.facade.protocols import LoginApi
    from crawler.browser.session.manager import CDPBrowserSession

logger = logging.getLogger(__name__)

# 二维码更新回调：参数为二维码图片路径，None 表示二维码已清除
QRCodeCallback = Callable[[Path | None], Awaitable[None]]

_DOUYIN_COOKIE_DOMAIN = re.compile(r"(^|\.)douyin\.com$")

# 读取登录态所需 cookie 的抖音作用域。browser 不得反向 import douyin_client，
# 故此处自带一份（与 ``DouyinClient.cookie_urls`` 同源，键名唯一真源仍是 cookie 名）。
DOUYIN_COOKIE_URLS = (
    "https://douyin.com",
    "https://www.douyin.com",
    "https://creator.douyin.com",
    "https://douhot.douyin.com",
    "https://live.douyin.com",
)

_LOGIN_DIALOG_SELECTOR = "xpath=//div[@id='login-panel-new']"
_QRCODE_SELECTOR = "xpath=//div[@id='animate_qrcode_container']//img"


class DouyinLogin:
    """抖音登录器，封装 cookie 登录与扫码登录两种流程。

    参数：
        page_handle: 自动化标签页的页面句柄（写 cookie/刷新/读 localStorage 用）。
        qrcode_path: 登录二维码图片的落盘路径。
        timeout: 扫码登录的等待超时时间（秒）。
        on_qrcode: 二维码更新回调，收到图片路径或 None（清除）。
    """

    def __init__(
        self,
        *,
        page_handle: PlaywrightPageHandle,
        qrcode_path: Path,
        timeout: float,
        on_qrcode: QRCodeCallback,
    ) -> None:
        self._page_handle = page_handle
        self.qrcode_path = qrcode_path
        self.timeout = timeout
        self.on_qrcode = on_qrcode

    @classmethod
    def from_session(
        cls,
        session: CDPBrowserSession,
        *,
        qrcode_path: Path,
        timeout: float,
        on_qrcode: QRCodeCallback,
    ) -> DouyinLogin:
        """用浏览器会话构造登录器（上层唯一入口；句柄由会话提供）。"""
        return cls(
            page_handle=session.page_handle,
            qrcode_path=qrcode_path,
            timeout=timeout,
            on_qrcode=on_qrcode,
        )

    @property
    def _page(self) -> Page:
        """当前自动化标签页（仅本模块内部使用，不出门面）。"""
        return self._page_handle.page

    async def login_with_cookie(self, cookie_string: str, api: LoginApi) -> None:
        """使用 cookie 字符串完成登录。

        清空 douyin.com 域的旧 cookie 后写入新 cookie，刷新页面并校验登录状态。

        异常：
            LoginError: cookie 为空、无效或已过期时抛出。
        """
        cookie_items = parse_cookie_string(cookie_string)
        if not cookie_items:
            raise LoginError("cookie 登录需要非空 cookies")
        await self._page_handle.clear_domain_cookies(_DOUYIN_COOKIE_DOMAIN)
        await self._page_handle.set_cookies(
            [
                {"name": key, "value": value, "domain": ".douyin.com", "path": "/"}
                for key, value in cookie_items.items()
            ]
        )
        await self._page_handle.reload(wait_until="domcontentloaded")
        await api.refresh_cookies()
        if not await api.verify_login():
            raise LoginError("提供的抖音 cookies 无效或已过期")

    async def is_logged_in(
        self, api: LoginApi, *, require_self_profile: bool = False
    ) -> bool:
        """检测当前会话的抖音登录状态。

        **顺序契约（规格 §4.7，不得调整）**：``require_self_profile`` 为 False 时
        先读 ``localStorage`` 的 ``HasUserLogin``、再读 cookie 的 ``LOGIN_STATUS``，
        任一命中即返回 True；两者都未命中才回调 ``api.verify_login``。这样扫码轮询
        是「每秒一次本地判断」，不会退化成「每秒一次高风控资料接口调用」。

        参数：
            api: 登录能力端口。
            require_self_profile: 为 True 时跳过本地快速判断，直接用资料接口校验。

        返回：
            已登录返回 True，否则 False。
        """
        if not require_self_profile:
            local_storage = await self._page_handle.local_storage()
            if local_storage.get("HasUserLogin") == "1":
                return True
            _, cookies = await self._page_handle.cookies(DOUYIN_COOKIE_URLS)
            if cookies.get("LOGIN_STATUS") == "1":
                return True
        return await api.verify_login(require_self_profile=require_self_profile)

    async def login_with_qrcode(
        self, api: LoginApi, *, require_self_profile: bool
    ) -> None:
        """扫码登录：弹出登录框、持续抓取二维码并等待用户扫码完成。

        异常：
            LoginError: 超时仍未完成扫码登录时抛出。
        """
        await self._popup_login_dialog()
        last_source = ""
        deadline = asyncio.get_running_loop().time() + self.timeout
        while asyncio.get_running_loop().time() < deadline:
            if await self.is_logged_in(api, require_self_profile=require_self_profile):
                await api.refresh_cookies()
                await self._clear_qrcode()
                return
            source = await self._qrcode_source(_QRCODE_SELECTOR)
            if source and source != last_source:
                await self._save_qrcode(source)
                last_source = source
            await asyncio.sleep(1)
        await self._clear_qrcode()
        raise LoginError("等待抖音扫码登录超时")

    async def _popup_login_dialog(self) -> None:
        """打开抖音登录弹窗；按候选控件依次尝试点击「登录」，全部失败时抛 LoginError。"""
        try:
            await self._page_handle.wait_for_selector(
                _LOGIN_DIALOG_SELECTOR, timeout_ms=5_000
            )
            return
        except Exception:
            pass

        # 抖音当前版本的页头把「登录」文案包在 button 里。若直接选择第一个
        # 匹配的 <p>，可能命中隐藏的用户菜单节点，导致弹窗静默打不开，
        # 在有头的 Docker 浏览器中尤其明显。
        page = self._page
        candidates = [
            page.get_by_role("button", name="登录", exact=True).first,
            page.locator("#douyin-header button").filter(has_text="登录").first,
            page.locator("xpath=//p[normalize-space()='登录']").first,
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
                await self._page_handle.wait_for_selector(
                    _LOGIN_DIALOG_SELECTOR, timeout_ms=10_000
                )
                return
            except Exception as dialog_error:
                last_error = dialog_error

        raise LoginError("无法打开抖音登录窗口") from last_error

    async def _qrcode_source(self, selector: str) -> str:
        """等待并读取登录二维码图片的 src；超时或异常时返回空字符串。"""
        try:
            element = await self._page_handle.wait_for_selector(
                selector, timeout_ms=5_000
            )
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


__all__ = ["DOUYIN_COOKIE_URLS", "DouyinLogin", "QRCodeCallback"]
