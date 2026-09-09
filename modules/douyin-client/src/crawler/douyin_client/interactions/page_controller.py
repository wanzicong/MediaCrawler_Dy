# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音互动页面的 DOM 查询与点击集合（PageController）。

页面级查询/点击基元（可见元素查找、坐标点击、输入框判空、文案探测）已下沉到
``crawler.browser.runtime.dom``，由 browser 模块统一提供、本模块直接导入。
此处仅保留带抖音语义的操作：评论发布请求的触发与观测、发送控件查找、
页面是否停留在目标视频页的断言，以及互动页面的筛选。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from crawler.browser.runtime import dom
from crawler.douyin_client.base.errors import InteractionExecutionError
from crawler.douyin_client.interactions.response_inspector import ResponseInspector
from crawler.douyin_client.interactions.selectors import (
    COMMENT_SUBMIT_SELECTORS,
    MESSAGE_SUBMIT_SELECTORS,
)
from playwright.async_api import Locator, Page


class PageController:
    """抖音互动页面的 DOM 查询与点击集合。

    所有方法均为静态方法：只依赖传入的页面/定位器与 selectors 常量，
    不持有页面状态，便于跨协作类复用。通用基元经 ``dom.*`` 调用。
    """

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
                lambda: dom.click_control_center(page, control),
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
        direct = await dom.find_visible(
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
        return await dom.find_text_control(page, ("发送", "发布"))

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
