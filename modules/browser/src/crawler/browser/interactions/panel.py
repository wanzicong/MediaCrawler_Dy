# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音互动面板的开启：评论区展开与私信会话建立。

抖音的评论输入框可能藏在「评论」标签或评论入口容器之后，两种入口的激活都要求
「点击后必须观测到编辑器出现」才算成功，避免把静默失败的点击当成进展。私信会话
同理：作者主页就绪、私信入口可点、输入框出现三步缺一不可。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from crawler.bootstrap.settings import Settings
from crawler.browser.errors import InteractionExecutionError
from crawler.browser.interactions.comment_locator import CommentLocator
from crawler.browser.interactions.models import InteractionStepCallback
from crawler.browser.interactions.page_controller import PageController
from crawler.browser.interactions.reporting import report_step
from crawler.browser.interactions.selectors import (
    COMMENT_EDITOR_SELECTORS,
    COMMENT_ENTRY_SELECTORS,
    COMMENT_TAB_SELECTORS,
    CREATOR_PROFILE_READY_SELECTORS,
)
from crawler.browser.page import primitives as dom
from playwright.async_api import Locator, Page

_MESSAGE_ENTRY_READY_TIMEOUT_MS = 30_000  # 作者主页与私信窗口的等待上限（毫秒）


async def activate_comment_control(
    page: Page,
    control: Locator,
    *,
    require_editor: bool = False,
) -> Locator | None:
    """激活控件并验证抖音已切换到可编辑状态。

    require_editor 为 False 时，评论区入口展开（但未出现输入框）也视为
    阶段性成功并返回 None。
    """
    activators: tuple[Callable[[], Awaitable[None]], ...] = (
        lambda: control.dispatch_event("click"),
        lambda: control.click(timeout=2_000),
        lambda: dom.click_control_center(page, control),
    )
    for activate in activators:
        try:
            await activate()
        except Exception:
            continue
        await page.wait_for_timeout(200)
        editor = await dom.find_visible(page, COMMENT_EDITOR_SELECTORS, timeout=500)
        if editor is not None:
            return editor
        if not require_editor:
            entry = await dom.find_visible(page, COMMENT_ENTRY_SELECTORS, timeout=300)
            if entry is not None:
                return None
    return None


async def open_comment_panel(
    page: Page, *, aweme_id: str | None = None, settings: Settings
) -> tuple[Page, Locator | None]:
    """在自动化标签页内展开评论区并定位评论输入框。

    返回：
        (输入框所在页面, 输入框定位器)；超时未找到时返回 (原页面, None)。
    """
    deadline = (
        asyncio.get_running_loop().time()
        + settings.DOUYIN_INTERACTION_COMMENT_READY_TIMEOUT_SECONDS
    )
    control_clicked_pages: set[int] = set()
    next_entry_click_at: dict[int, float] = {}
    while asyncio.get_running_loop().time() < deadline:
        candidates = PageController.interaction_pages(page, aweme_id=aweme_id)
        for candidate in candidates:
            editor = await dom.find_visible(
                candidate, COMMENT_EDITOR_SELECTORS, timeout=500
            )
            if editor is not None:
                return candidate, editor

        now = asyncio.get_running_loop().time()
        for candidate in candidates:
            page_key = id(candidate)
            if page_key not in control_clicked_pages:
                control = await dom.find_visible(
                    candidate, COMMENT_TAB_SELECTORS, timeout=400
                )
                if control is not None:
                    editor = await activate_comment_control(candidate, control)
                    control_clicked_pages.add(page_key)
                    if editor is not None:
                        return candidate, editor

            if now < next_entry_click_at.get(page_key, 0.0):
                continue
            entry = await dom.find_visible(
                candidate, COMMENT_ENTRY_SELECTORS, timeout=400
            )
            if entry is not None:
                editor = await activate_comment_control(
                    candidate, entry, require_editor=True
                )
                if editor is not None:
                    return candidate, editor
                next_entry_click_at[page_key] = now + 2.0

        remaining = deadline - asyncio.get_running_loop().time()
        if remaining > 0:
            await page.wait_for_timeout(min(500, int(remaining * 1000)))
    return page, None


async def open_message_panel(
    page: Page,
    *,
    timeout: int = _MESSAGE_ENTRY_READY_TIMEOUT_MS,
    step_callback: InteractionStepCallback | None = None,
) -> tuple[Page, Locator]:
    """在作者主页上进入私信会话并定位消息输入框。

    返回：
        (输入框所在页面, 输入框定位器)；本函数每条返回路径都保证定位器非 None，
        打不开私信窗口时以 ``message_not_allowed`` 抛出，因此标注不放开 ``| None``。

    异常：
        InteractionExecutionError: 主页未就绪（page_load_timeout，可重试）、
        私信未开放或会话窗口打不开（message_not_allowed）、私信入口不可点
        （message_entry_unavailable，可重试）时抛出。
    """
    profile_ready = await dom.find_visible(
        page, CREATOR_PROFILE_READY_SELECTORS, timeout=timeout
    )
    message_button: Locator | None = await dom.find_text_control(
        page, ("私信", "发消息"), timeout=2_000
    )
    if profile_ready is None and message_button is None:
        raise InteractionExecutionError(
            "page_load_timeout",
            "作者主页没有在限定时间内加载完成，请稍后重试",
            retryable=True,
        )
    if message_button is None:
        raise InteractionExecutionError(
            "message_not_allowed",
            "作者未开放私信，或当前账号不满足私信条件",
        )
    baseline_pages = set(page.context.pages)
    try:
        await message_button.click(timeout=5_000)
    except Exception as exc:
        raise InteractionExecutionError(
            "message_entry_unavailable",
            "私信入口暂时不可操作，请稍后重试",
            retryable=True,
        ) from exc
    await report_step(
        step_callback,
        page,
        "message_entry_opened",
        "已点击作者私信入口，正在等待会话窗口",
    )
    editor_page, editor = await CommentLocator.find_message_editor(
        page, timeout=timeout, baseline_pages=baseline_pages
    )
    if editor is None:
        raise InteractionExecutionError(
            "message_not_allowed",
            "私信窗口未能打开；该作者可能要求互相关注，或当前账号没有私信权限",
        )
    await report_step(
        step_callback,
        editor_page,
        "message_editor_ready",
        "私信窗口已打开并定位到消息输入框",
    )
    return editor_page, editor


__all__ = ["activate_comment_control", "open_comment_panel", "open_message_panel"]
