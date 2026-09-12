"""与具体站点无关的页面 DOM 查询/点击基元与浏览器自动化辅助函数。

browser 模块的定位是「与浏览器相关的封装与操作」，使用方直接导入即可。
本模块承载不依赖任何站点语义的 Playwright 页面基元：可见元素查询、按文案
找控件、真实坐标点击、输入框状态判断、可见文案探测、滚动容器滚底、页面
evaluate 导航竞态重试与页面对话框自动关闭。站点专属的选择器/文案一律由
调用方作为参数传入，本模块不持有任何平台语义。

异常约定：本模块只抛出 browser 集成层的中立异常（``crawler.browser.errors``），
绝不抛出业务/领域层的异常类型。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from crawler.browser.errors import BrowserAutomationError
from playwright.async_api import Dialog, Locator, Page

# 滚动容器滚底脚本：从锚点沿祖先链找到最近的真实可滚动容器并滚到底。
# 找不到可滚动容器时返回 False，由调用方决定兜底策略。
_SCROLL_TO_BOTTOM_SCRIPT = """element => {
    let node = element;
    while (node) {
        const style = getComputedStyle(node);
        const scrollable = ['auto', 'scroll'].includes(
            style.overflowY
        ) && node.scrollHeight > node.clientHeight;
        if (scrollable) {
            const before = node.scrollTop;
            node.scrollTo(0, node.scrollHeight);
            return node.scrollTop > before;
        }
        node = node.parentElement;
    }
    return false;
}"""


async def find_visible(
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


async def find_text_control(
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


async def click_control_center(page: Page, control: Locator) -> None:
    """用真实 CDP 鼠标事件点击控件中心（针对经过变换的 React 控件）。"""
    await control.scroll_into_view_if_needed()
    box = await control.bounding_box()
    if box is None:
        raise BrowserAutomationError("control has no bounding box")
    await page.mouse.click(
        box["x"] + box["width"] / 2,
        box["y"] + box["height"] / 2,
    )


async def editor_is_empty(editor: Locator) -> bool:
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


async def visible_page_message(page: Page, messages: tuple[str, ...]) -> str | None:
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


async def wait_editor_empty(editor: Locator, *, timeout_ms: int = 5_000) -> bool:
    """等待输入框内容清空（视为发送完成的 UI 信号），超时返回 False。"""
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    while True:
        if await editor_is_empty(editor):
            return True
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return False
        try:
            await editor.page.wait_for_timeout(min(200, int(remaining * 1000)))
        except Exception:
            await asyncio.sleep(min(0.2, remaining))


async def scroll_container_to_bottom(page: Page, anchor: Locator | None) -> bool:
    """把锚点所在最近的真实可滚动容器滚到底。

    锚点为 None 或 evaluate 失败时，退化为对页面窗口滚动。

    返回：
        是否产生了真实滚动位移。
    """
    try:
        if anchor is None:
            await page.mouse.wheel(0, 1_000)
            return True
        return bool(await anchor.evaluate(_SCROLL_TO_BOTTOM_SCRIPT))
    except Exception:
        await page.mouse.wheel(0, 1_000)
        return True


async def evaluate_stable(page: Page, expression: str) -> Any:
    """在页面导航竞态下重试 evaluate，避免瞬时上下文销毁让整个任务失败。"""
    for attempt in range(3):
        try:
            return await page.evaluate(expression)
        except BrowserAutomationError as exc:
            if "Execution context was destroyed" not in str(exc) or attempt == 2:
                raise
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=3_000)
            except BrowserAutomationError:
                pass
            await asyncio.sleep(0.1 * (attempt + 1))
    raise RuntimeError("页面执行上下文不可用")


def auto_dismiss_dialogs(
    page: Page,
    *,
    on_dismiss: Callable[[Dialog], Awaitable[None]] | None = None,
) -> Callable[[Dialog], Awaitable[None]]:
    """自动关闭页面弹出的对话框并返回已注册的 handler 供调用方移除监听。

    参数：
        on_dismiss: 对话框被关闭后触发的回调；其异常被吞掉，不影响主流程。

    返回：
        已注册到 ``page.on("dialog", ...)`` 的 handler，用于 ``remove_listener``。
    """

    async def handler(dialog: Dialog) -> None:
        try:
            await dialog.dismiss()
        except Exception:
            # 关闭对话框期间页面可能已发生跳转。
            return
        if on_dismiss is not None:
            try:
                await on_dismiss(dialog)
            except Exception:
                return

    page.on("dialog", handler)
    return handler
