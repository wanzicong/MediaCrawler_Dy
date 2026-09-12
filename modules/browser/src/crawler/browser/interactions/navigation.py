# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音页面导航：主站、视频页与作者主页（原 executor 的导航私有方法）。

导航失败策略与迁移前逐行一致：主站与作者主页只忽略「已 commit 后超时」，
视频页在配置的重试次数内自动刷新并以就绪脚本确认真正可交互，失败抛
``InteractionExecutionError``。
"""

from __future__ import annotations

from urllib.parse import quote

from crawler.bootstrap.settings import Settings
from crawler.browser.errors import InteractionExecutionError
from crawler.browser.interactions.selectors import VIDEO_PAGE_READY_SCRIPT
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

INDEX_URL = "https://www.douyin.com"  # 抖音主站地址
VIDEO_URL_TEMPLATE = "https://www.douyin.com/video/{aweme_id}"  # 视频页地址模板
CREATOR_URL_TEMPLATE = "https://www.douyin.com/user/{sec_uid}"  # 作者主页地址模板

_NAVIGATION_TIMEOUT_MS = 30_000  # 单次导航超时（毫秒）


def video_url(aweme_id: str) -> str:
    """按作品 ID 生成视频页地址。"""
    return VIDEO_URL_TEMPLATE.format(aweme_id=quote(aweme_id, safe=""))


def creator_url(sec_uid: str) -> str:
    """按作者 sec_uid 生成作者主页地址。"""
    return CREATOR_URL_TEMPLATE.format(sec_uid=quote(sec_uid, safe=""))


async def open_index(page: Page) -> None:
    """打开抖音主站；文档已 commit 时导航超时不算失败。"""
    try:
        await page.goto(
            INDEX_URL,
            wait_until="domcontentloaded",
            timeout=_NAVIGATION_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError:
        # 页面即使只加载了一部分，也已具备检测登录状态所需的会话信息。
        pass


async def open_creator_profile(page: Page, sec_uid: str) -> None:
    """打开作者主页；文档已 commit 时导航超时不算失败。"""
    try:
        await page.goto(
            creator_url(sec_uid),
            wait_until="domcontentloaded",
            timeout=_NAVIGATION_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError:
        pass


async def open_video(page: Page, aweme_id: str, *, settings: Settings) -> None:
    """打开目标视频页并等待进入可互动状态，失败时按配置次数自动重试。

    异常：
        InteractionExecutionError: 网络加载失败或页面持续未就绪时抛出。
    """
    target_url = video_url(aweme_id)
    attempts = settings.DOUYIN_INTERACTION_NAVIGATION_ATTEMPTS
    for attempt in range(attempts):
        try:
            await page.goto(
                target_url,
                wait_until="commit",
                timeout=_NAVIGATION_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError:
            # 文档已 commit 时，导航超时后页面仍会继续渲染。
            pass
        except PlaywrightError as exc:
            if attempt + 1 >= attempts:
                raise InteractionExecutionError(
                    "page_navigation_failed",
                    "目标视频页面网络加载失败，已自动重试仍未恢复",
                    retryable=True,
                    affects_account_health=True,
                ) from exc
            await page.wait_for_timeout((attempt + 1) * 1_000)
            continue

        try:
            await page.wait_for_function(
                VIDEO_PAGE_READY_SCRIPT,
                timeout=(settings.DOUYIN_INTERACTION_PAGE_READY_TIMEOUT_SECONDS * 1000),
            )
            return
        except PlaywrightTimeoutError as exc:
            if attempt + 1 >= attempts:
                raise InteractionExecutionError(
                    "page_load_timeout",
                    "目标视频页面持续加载，自动刷新后仍未进入可互动状态",
                    retryable=True,
                ) from exc

        # 重试目标 URL 前，先丢弃卡在抖音加载壳上的渲染进程。
        # 这样恢复动作始终限定在一次已确认的互动尝试内，且不会回退出 CDP 方案。
        try:
            await page.goto(
                "about:blank",
                wait_until="commit",
                timeout=5_000,
            )
        except PlaywrightError:
            pass
        await page.wait_for_timeout((attempt + 1) * 1_000)


__all__ = [
    "CREATOR_URL_TEMPLATE",
    "INDEX_URL",
    "VIDEO_URL_TEMPLATE",
    "creator_url",
    "open_creator_profile",
    "open_index",
    "open_video",
    "video_url",
]
