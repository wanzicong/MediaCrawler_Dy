# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""页面 DOM 查询与点击基元（PageController）。

提供「找可见元素 / 按文案找控件 / 触发点击 / 判空 / 探测页面文案」等不区分
互动类型的基础操作，被 executor 的页面导航与 comment_locator / submit_flow 复用。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from crawler.douyin_client.base.errors import InteractionExecutionError
from crawler.douyin_client.interactions.response_inspector import ResponseInspector
from crawler.douyin_client.interactions.selectors import (
    COMMENT_SUBMIT_SELECTORS,
    MESSAGE_SUBMIT_SELECTORS,
)
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page


class PageController:
    """抖音互动页面的 DOM 查询与点击基元集合。

    所有方法均为静态方法：只依赖传入的页面/定位器与 selectors 常量，
    不持有页面状态，便于跨协作类复用。
    """

    @staticmethod
    async def _find_visible(
        page: Page,
        selectors: tuple[str, ...],
        *,
        timeout: int = 4_000,
    ) -> Locator | None:
        """按候选选择器查找第一个可见元素，超时返回 None。"""
        per_selector = max(timeout // max(len(selectors), 1), 50)
        for selector in selectors:
            locator = page.locator(selector)
            deadline = asyncio.get_running_loop().time() + per_selector / 1000
            while True:
                try:
                    count = await locator.count()
                    for index in range(count):
                        candidate = locator.nth(index)
                        if await candidate.is_visible():
                            return candidate
                except Exception:
                    break
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                await page.wait_for_timeout(min(100, int(remaining * 1000)))
        return None

    @staticmethod
    async def _find_text_control(
        page: Page,
        labels: tuple[str, ...],
        *,
        timeout: int = 4_000,
    ) -> Locator | None:
        """按文案查找可见按钮/文本控件，超时返回 None。"""
        deadline = asyncio.get_running_loop().time() + timeout / 1000
        while True:
            for label in labels:
                for locator in (
                    page.get_by_role("button", name=label, exact=True).first,
                    page.get_by_text(label, exact=True).first,
                ):
                    try:
                        if await locator.count() and await locator.is_visible():
                            return locator
                    except Exception:
                        continue
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return None
            await page.wait_for_timeout(min(150, int(remaining * 1000)))

    @staticmethod
    async def _click_control_center(page: Page, control: Locator) -> None:
        """用真实 CDP 鼠标事件点击控件中心（针对变换后的 React 发送控件）。"""
        await control.scroll_into_view_if_needed()
        box = await control.bounding_box()
        if box is None:
            raise PlaywrightError("comment submit control has no bounding box")
        await page.mouse.click(
            box["x"] + box["width"] / 2,
            box["y"] + box["height"] / 2,
        )

    @staticmethod
    async def _editor_is_empty(editor: Locator) -> bool:
        """判断输入框是否为空（兼容 input 与 contenteditable 元素）。"""
        try:
            if await editor.count() == 0:
                return True
        except Exception:
            pass
        value: str | None
        try:
            value = await editor.input_value(timeout=300)
        except Exception:
            try:
                value = await editor.text_content(timeout=300)
            except Exception:
                return False
        return not (value or "").strip()

    @staticmethod
    async def _visible_page_message(
        page: Page, messages: tuple[str, ...]
    ) -> str | None:
        """在页面可见文本中查找指定提示文案，命中返回该文案，否则返回 None。"""
        for message in messages:
            matches = page.get_by_text(message, exact=False)
            try:
                for index in range(min(await matches.count(), 5)):
                    if await matches.nth(index).is_visible():
                        return message
            except Exception:
                continue
        return None

    @staticmethod
    async def _wait_editor_empty(editor: Locator, *, timeout_ms: int = 5_000) -> bool:
        """等待输入框内容清空（视为发送完成的 UI 信号），超时返回 False。"""
        deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
        while True:
            if await PageController._editor_is_empty(editor):
                return True
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            try:
                await editor.page.wait_for_timeout(min(200, int(remaining * 1000)))
            except Exception:
                await asyncio.sleep(min(0.2, remaining))

    @staticmethod
    async def _dispatch_comment_submit(page: Page, control: Locator) -> bool:
        """对抖音变换后的评论发送控件执行且仅执行一次激活。

        返回：
            是否观测到了评论发布请求。
        """
        publish_requested = asyncio.Event()

        def observe_request(request: Any) -> None:
            """监听网络请求，命中评论发布接口时置位事件。"""
            if ResponseInspector._is_comment_publish_request(request):
                publish_requested.set()

        page.on("request", observe_request)
        try:
            # 抖音经过变换的评论编辑器可能接受组件级点击；而 Playwright 报告
            # 坐标点击成功时，文档实际可能没有收到任何 click 事件。因此先在
            # 组件可见时触发 React 组件点击，再以可信的 CDP 坐标点击兜底。
            activators: tuple[Callable[[], Awaitable[None]], ...] = (
                lambda: control.dispatch_event("click"),
                lambda: control.click(timeout=5_000),
                lambda: PageController._click_control_center(page, control),
            )
            last_error: Exception | None = None
            activated = False
            for activate in activators:
                if publish_requested.is_set():
                    return True
                try:
                    await activate()
                    activated = True
                except Exception as exc:
                    last_error = exc
                    continue
                try:
                    await asyncio.wait_for(publish_requested.wait(), timeout=1.5)
                    return True
                except TimeoutError:
                    continue
            if not activated and last_error is not None:
                raise last_error
            return publish_requested.is_set()
        finally:
            page.remove_listener("request", observe_request)

    @staticmethod
    async def _find_submit_control(page: Page, editor: Locator) -> Locator | None:
        """查找发送按钮：先按选择器直查，再从输入框向上找「发送/发布」按钮，最后全页兜底。"""
        direct = await PageController._find_visible(
            page,
            (
                *COMMENT_SUBMIT_SELECTORS,
                *MESSAGE_SUBMIT_SELECTORS,
            ),
            timeout=1_500,
        )
        if direct is not None:
            return direct
        node = editor
        for _ in range(6):
            for label in ("发送", "发布"):
                control = node.get_by_role("button", name=label, exact=True).first
                try:
                    if await control.count() and await control.is_visible():
                        return control
                except Exception:
                    continue
            node = node.locator("xpath=..")
        return await PageController._find_text_control(page, ("发送", "发布"))

    @staticmethod
    def _assert_video_page(page: Page, aweme_id: str) -> None:
        """断言页面仍停留在目标视频页，否则抛 page_interrupted 安全终止发送。"""
        if page.is_closed() or aweme_id not in page.url:
            raise InteractionExecutionError(
                "page_interrupted",
                "自动化专用标签页被关闭或切换，发送前已安全终止；请重试任务",
                retryable=True,
            )

    @staticmethod
    def _interaction_pages(page: Page, *, aweme_id: str | None) -> list[Page]:
        """筛选允许参与互动的页面，绝不让无关的用户标签页参与互动。"""
        if page.is_closed():
            return []
        if aweme_id and aweme_id not in page.url:
            return []
        return [page]
