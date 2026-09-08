# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""评论区目标与私信编辑器的定位（CommentLocator）。

负责评论列表激活、按评论 id/内容定位目标评论、打开回复输入框以及私信会话
编辑器的查找；DOM 查询基元来自 ``page_controller``，选择器见 ``selectors``。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from crawler.douyin_client.interactions.models import InteractionExecutionRequest
from crawler.douyin_client.interactions.page_controller import PageController
from crawler.douyin_client.interactions.selectors import (
    COMMENT_EDITOR_SELECTORS,
    COMMENT_ITEM_SELECTORS,
    COMMENT_LIST_SELECTORS,
    COMMENT_TAB_SELECTORS,
    MESSAGE_EDITOR_SELECTORS,
)
from playwright.async_api import Locator, Page


class CommentLocator:
    """评论目标与私信编辑器的定位器。

    大部分方法为类方法：按需在页面内滚动/点击/核验，从 ``PageController``
    组合基础操作；本类自身不持有页面状态。
    """

    @classmethod
    async def _find_comment_target(
        cls, page: Page, request: InteractionExecutionRequest
    ) -> Locator | None:
        """在评论列表中按评论 ID 或内容定位目标评论。

        滚动加载评论列表直至找到唯一匹配项，或确认无法找到。

        返回：
            命中的评论节点定位器；未找到返回 None。
        """
        no_scroll_progress = 0
        for _ in range(48):
            comment_list = await PageController._find_visible(
                page, COMMENT_LIST_SELECTORS, timeout=250
            )
            roots: tuple[Page | Locator, ...] = (
                (comment_list,) if comment_list is not None else (page,)
            )
            for root in roots:
                candidates: list[tuple[Locator, bool]] = []
                if request.target_comment_id and request.target_comment_id.isdigit():
                    tooltip = root.locator(
                        f'[id="tooltip_{request.target_comment_id}"]'
                    )
                    candidates.extend(
                        [
                            (
                                tooltip.locator(
                                    "xpath=ancestor::*[@data-e2e='comment-item'][1]"
                                ),
                                False,
                            ),
                            (
                                root.locator(
                                    f'[data-comment-id="{request.target_comment_id}"]'
                                ),
                                False,
                            ),
                            (
                                root.locator(
                                    f'[data-cid="{request.target_comment_id}"]'
                                ),
                                False,
                            ),
                        ]
                    )
                assert request.target_comment_content is not None
                candidates.append(
                    (
                        root.get_by_text(request.target_comment_content, exact=True),
                        True,
                    )
                )
                if len(request.target_comment_content) > 40:
                    candidates.append(
                        (
                            root.get_by_text(
                                request.target_comment_content[:40], exact=False
                            ),
                            True,
                        )
                    )
                for candidates_locator, require_unique in candidates:
                    try:
                        count = await candidates_locator.count()
                        visible: list[Locator] = []
                        for index in range(count):
                            candidate = candidates_locator.nth(index)
                            if await candidate.is_visible():
                                if not require_unique:
                                    return candidate
                                visible.append(candidate)
                        if len(visible) == 1:
                            return visible[0]
                    except Exception:
                        continue
            if await cls._scroll_comment_list(page):
                no_scroll_progress = 0
            else:
                no_scroll_progress += 1
                if no_scroll_progress >= 8:
                    break
            await page.wait_for_timeout(600)
        return None

    @classmethod
    async def _scroll_comment_list(cls, page: Page) -> bool:
        """滚动抖音内部的路由级滚动容器（而非 window）。

        返回：
            是否产生了真实滚动位移。
        """
        scroll_anchor = await PageController._find_visible(
            page, COMMENT_LIST_SELECTORS, timeout=250
        )
        if scroll_anchor is None:
            # 旧版详情页只有评论节点、没有独立的评论列表标记；
            # 从可见评论节点出发，脚本仍能找到最近的真实滚动祖先容器。
            scroll_anchor = await PageController._find_visible(
                page, COMMENT_ITEM_SELECTORS, timeout=250
            )
        try:
            if scroll_anchor is None:
                await page.mouse.wheel(0, 1_000)
                return True
            return bool(
                await scroll_anchor.evaluate(
                    """element => {
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
                )
            )
        except Exception:
            await page.mouse.wheel(0, 1_000)
            return True

    @classmethod
    async def _ensure_comment_list_active(cls, page: Page) -> bool:
        """确保评论列表处于可见激活状态：必要时点击评论标签并逐方式验证。

        返回：
            评论列表已可见返回 True，否则 False。
        """
        if await cls._find_visible_comment_surface(page, timeout=300) is not None:
            return True
        control = await PageController._find_visible(
            page, COMMENT_TAB_SELECTORS, timeout=3_000
        )
        if control is None:
            return False
        activators: tuple[Callable[[], Awaitable[None]], ...] = (
            lambda: control.dispatch_event("click"),
            lambda: control.click(timeout=2_000),
            lambda: PageController._click_control_center(page, control),
        )
        for activate in activators:
            try:
                await activate()
            except Exception:
                continue
            if await cls._find_visible_comment_surface(page, timeout=1_500) is not None:
                return True
        return False

    @classmethod
    async def _find_visible_comment_surface(
        cls, page: Page, *, timeout: int
    ) -> Locator | None:
        """查找可见的评论列表容器；没有独立列表标记时退化为查找可见评论节点。"""
        comment_list = await PageController._find_visible(
            page, COMMENT_LIST_SELECTORS, timeout=timeout
        )
        if comment_list is not None:
            return comment_list
        return await PageController._find_visible(
            page, COMMENT_ITEM_SELECTORS, timeout=timeout
        )

    @classmethod
    async def _open_reply_editor(
        cls,
        page: Page,
        target: Locator,
        request: InteractionExecutionRequest,
    ) -> tuple[Locator | None, Locator | None]:
        """在目标评论卡片上点击「回复」，等待出现处于回复状态的输入框。

        返回：
            (评论卡片, 回复输入框) 二元组；任一步骤失败返回 (None, None)。
        """
        comment_card = target.locator(
            "xpath=ancestor-or-self::*[@data-e2e='comment-item'][1]"
        )
        try:
            if not await comment_card.count() or not await comment_card.is_visible():
                return None, None
        except Exception:
            return None, None
        node = target
        reply_control: Locator | None = None
        for _ in range(16):
            replies = node.get_by_text("回复", exact=True)
            visible_replies: list[Locator] = []
            for index in range(await replies.count()):
                reply = replies.nth(index)
                if await reply.is_visible():
                    visible_replies.append(reply)
            if len(visible_replies) == 1:
                reply_control = visible_replies[0]
                break
            if len(visible_replies) > 1:
                return None, None
            node = node.locator("xpath=..")
        if reply_control is None:
            return None, None

        activators: tuple[Callable[[], Awaitable[None]], ...] = (
            lambda: reply_control.dispatch_event("click"),
            lambda: reply_control.click(timeout=2_000),
            lambda: PageController._click_control_center(page, reply_control),
        )
        for activate in activators:
            try:
                await activate()
            except Exception:
                continue
            deadline = asyncio.get_running_loop().time() + 2.0
            while asyncio.get_running_loop().time() < deadline:
                editor = await PageController._find_visible(
                    page, COMMENT_EDITOR_SELECTORS, timeout=250
                )
                if editor is not None and await cls._reply_context_is_active(
                    comment_card, request.target_comment_id
                ):
                    return comment_card, editor
                await page.wait_for_timeout(150)
        return None, None

    @staticmethod
    async def _reply_context_is_active(
        comment_card: Locator, target_comment_id: str | None
    ) -> bool:
        """校验评论卡片是否处于对目标评论的「回复中」状态。"""
        try:
            if target_comment_id:
                matches_target = False
                for attribute in ("data-comment-id", "data-cid"):
                    if await comment_card.get_attribute(attribute) == target_comment_id:
                        matches_target = True
                        break
                selectors = (
                    f'[id="tooltip_{target_comment_id}"]',
                    f'[data-comment-id="{target_comment_id}"]',
                    f'[data-cid="{target_comment_id}"]',
                )
                for selector in selectors:
                    matches = comment_card.locator(selector)
                    for index in range(await matches.count()):
                        if await matches.nth(index).is_visible():
                            matches_target = True
                            break
                    if matches_target:
                        break
                if not matches_target:
                    return False
            active = comment_card.get_by_text("回复中", exact=True)
            for index in range(await active.count()):
                if await active.nth(index).is_visible():
                    return True
            return False
        except Exception:
            return False

    @classmethod
    async def _find_message_editor(
        cls,
        page: Page,
        *,
        timeout: int,
        baseline_pages: set[Page] | None = None,
    ) -> tuple[Page, Locator | None]:
        """在当前页或新打开的 CDP 标签页中查找私信会话输入框。

        返回：
            (输入框所在页面, 输入框定位器)；超时未找到时返回 (原页面, None)。
        """
        deadline = asyncio.get_running_loop().time() + timeout / 1000
        while True:
            candidates = [
                page,
                *[
                    item
                    for item in page.context.pages
                    if item != page
                    and not item.is_closed()
                    and (baseline_pages is None or item not in baseline_pages)
                ],
            ]
            for candidate in candidates:
                editor = await PageController._find_visible(
                    candidate, MESSAGE_EDITOR_SELECTORS, timeout=400
                )
                if editor is not None:
                    return candidate, editor
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return page, None
            await page.wait_for_timeout(min(250, int(remaining * 1000)))
