# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, quote

from playwright.async_api import Dialog, Locator, Page
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.core.config import Settings
from app.douyin.browser import CDPBrowserSession
from app.douyin.client import DouyinClient
from app.models import DouyinAccount, DouyinInteractionType
from app.services.douyin_accounts import resolve_account_browser

InteractionStepCallback = Callable[[Page, str, str], Awaitable[None]]


class InteractionExecutionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        ambiguous: bool = False,
        affects_account_health: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.ambiguous = ambiguous
        self.affects_account_health = affects_account_health


@dataclass(frozen=True)
class InteractionExecutionRequest:
    interaction_type: DouyinInteractionType
    aweme_id: str
    content: str
    target_comment_id: str | None = None
    target_comment_content: str | None = None
    target_parent_comment_id: str | None = None


@dataclass(frozen=True)
class InteractionExecutionResult:
    platform_id: str | None = None


class DouyinInteractionExecutor:
    """Perform explicitly confirmed write actions through an existing CDP profile."""

    index_url = "https://www.douyin.com"
    response_markers = ("/im/", "/message/")
    video_page_ready_script = """() => {
        const bodyText = document.body?.innerText || '';
        const stillLoading = bodyText.includes('视频数据加载中');
        const hasVideo = document.querySelectorAll('video').length > 0;
        const hasInteractionUi = Boolean(document.querySelector(
            '#comment-input-container, .comment-input-inner-container, '
            + '[data-e2e="feed-comment-icon"], [data-e2e="comment-icon"]'
        ));
        return !stillLoading
            && (hasVideo || hasInteractionUi);
    }"""
    editor_selectors = (
        '#comment-input-container [contenteditable="true"][role="combobox"]',
        '#comment-input-container .public-DraftEditor-content[contenteditable="true"]',
        '.comment-input-container [contenteditable="true"][role="combobox"]',
        '.comment-input-container .public-DraftEditor-content[contenteditable="true"]',
        '.comment-input-inner-container [contenteditable="true"]',
        '[data-e2e="comment-input"] [contenteditable="true"]',
        '[data-e2e="comment-input"] textarea',
        'div[contenteditable="true"][data-placeholder*="评论"]',
        'div[contenteditable="true"][aria-label*="评论"]',
        'textarea[placeholder*="评论"]',
        'div[contenteditable="true"][data-placeholder*="回复"]',
        'textarea[placeholder*="回复"]',
    )
    comment_entry_selectors = (
        ".comment-input-inner-container",
        "#comment-input-container",
    )
    comment_tab_selectors = (
        (
            "xpath=//*[self::div or self::span][not(*) and "
            "(normalize-space(.)='评论' or "
            "starts-with(normalize-space(.), '评论('))]"
        ),
        '[data-e2e="feed-comment-icon"]',
        '[data-e2e="comment-icon"]',
        '[aria-label*="评论"]',
        'button:has-text("评论")',
        # Last-resort fallback for older note-detail builds. Keep the semantic
        # selectors above first because this generated class also appears in
        # unrelated recommendation controls.
        "div.X9EiuBV4:nth-of-type(2)",
    )
    comment_list_selectors = ('[data-e2e="comment-list"]',)
    comment_item_selectors = ('[data-e2e="comment-item"]',)
    comment_submit_selectors = (
        '#comment-input-container .commentInput-right-ct span:has(path[fill="#fff"])',
        "#comment-input-container .commentInput-right-ct > div > span:last-child",
        '.comment-input-container .commentInput-right-ct span:has(path[fill="#fff"])',
        ".comment-input-container .commentInput-right-ct > div > span:last-child",
        ".comment-input-inner-container .commentInput-right-ct > div > span:last-child",
        '#comment-input-container [data-e2e="comment-submit"]',
    )
    comment_failure_messages = (
        "发布评论失败",
        "评论发布失败",
        "评论发送失败",
        "操作频繁",
        "请求太频繁",
    )
    comment_success_messages = (
        "已发布",
        "评论成功",
        "发布成功",
    )
    comment_risk_messages = (
        "接收短信验证码",
        "为确保是本人操作抖音账号",
        "使用原设备扫码",
        "安全验证",
    )
    message_editor_selectors = (
        '[data-e2e="im-input"] [contenteditable="true"]',
        '[data-e2e="message-input"] [contenteditable="true"]',
        'div[contenteditable="true"][data-placeholder*="消息"]',
        'div[contenteditable="true"][aria-label*="消息"]',
        'div[contenteditable="true"][role="textbox"]',
        'textarea[placeholder*="消息"]',
        'textarea[placeholder*="发送"]',
    )
    message_submit_selectors = (
        "svg.e2e-send-msg-btn",
        "svg.messageMsgInputpublishRedBtn",
        ".messageMsgInputpublishRedBtn.e2e-send-msg-btn",
    )
    creator_profile_ready_selectors = (
        '[data-e2e="user-detail"]',
        '[data-e2e="user-info"]',
    )
    interaction_page_marker = "mediacrawler:interaction"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def execute(
        self,
        *,
        account: DouyinAccount,
        request: InteractionExecutionRequest,
        step_callback: InteractionStepCallback | None = None,
    ) -> InteractionExecutionResult:
        connection = resolve_account_browser(account)
        browser = CDPBrowserSession(
            self.settings,
            browser_mode=connection.browser_mode,
            remote_host=connection.remote_host,
            remote_port=connection.remote_port,
            user_data_dir=connection.user_data_dir,
            debug_port=connection.debug_port,
            reuse_existing_page=False,
            close_page_on_exit=False,
            page_marker=self.interaction_page_marker,
        )
        async with browser:
            if browser.page is None or browser.context is None:
                raise InteractionExecutionError(
                    "browser_unavailable",
                    "CDP 浏览器页面不可用",
                    retryable=True,
                    affects_account_health=True,
                )
            page = browser.page
            await page.bring_to_front()

            async def dismiss_page_dialog(dialog: Dialog) -> None:
                try:
                    await dialog.dismiss()
                    await self._trace(
                        step_callback,
                        page,
                        "page_dialog_dismissed",
                        f"已自动关闭网页对话框（{dialog.type}）",
                    )
                except Exception:
                    # The document may have navigated while the dialog was dismissed.
                    return

            page.on("dialog", dismiss_page_dialog)
            client: DouyinClient | None = None
            try:
                try:
                    await page.goto(
                        self.index_url,
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                except PlaywrightTimeoutError:
                    # A partially loaded page still has enough session state for pong.
                    pass
                await self._trace(
                    step_callback,
                    page,
                    "browser_connected",
                    (
                        "已通过 CDP 连接账号浏览器并打开自动化专用标签页；"
                        f"已隔离 {browser.unrelated_page_count} 个其他标签页"
                    ),
                )
                client = await DouyinClient.create(
                    page=page,
                    browser_context=browser.context,
                    timeout=self.settings.DOUYIN_REQUEST_TIMEOUT,
                    verify_ssl=self.settings.DOUYIN_REQUEST_SSL_VERIFY,
                )
                if not await client.pong(browser.context, require_self_profile=True):
                    raise InteractionExecutionError(
                        "login_required",
                        "所选账号登录已失效，请先在账号管理中重新登录",
                        affects_account_health=True,
                    )
                await client.update_cookies(browser.context)
                await self._trace(
                    step_callback,
                    page,
                    "login_verified",
                    "账号登录状态验证通过",
                )
                if request.interaction_type == DouyinInteractionType.video_comment:
                    return await self._comment_video(page, request, step_callback)
                if request.interaction_type == DouyinInteractionType.comment_reply:
                    return await self._reply_to_comment(
                        page, client, request, step_callback
                    )
                return await self._message_creator(page, client, request, step_callback)
            except Exception as exc:
                detail = (
                    f"执行失败：{exc}"
                    if isinstance(exc, InteractionExecutionError)
                    else "浏览器执行发生异常，已保留最后页面现场"
                )
                await self._trace(
                    step_callback,
                    page,
                    "execution_failed",
                    detail,
                )
                raise
            finally:
                page.remove_listener("dialog", dismiss_page_dialog)
                if client is not None:
                    await client.close()

    async def _comment_video(
        self,
        page: Page,
        request: InteractionExecutionRequest,
        step_callback: InteractionStepCallback | None,
    ) -> InteractionExecutionResult:
        await self._open_video(page, request.aweme_id)
        await self._trace(step_callback, page, "video_opened", "已打开目标视频页面")
        active_page, editor = await self._open_comment_panel(
            page, aweme_id=request.aweme_id
        )
        if editor is None:
            raise InteractionExecutionError(
                "comment_not_available",
                "当前作品没有可用的评论输入框，可能已关闭评论",
            )
        self._assert_video_page(active_page, request.aweme_id)
        await self._trace(
            step_callback,
            active_page,
            "comment_editor_ready",
            "评论区已展开并定位到评论输入框",
        )
        return await self._fill_and_submit(
            active_page,
            editor,
            request.content,
            step_callback,
            require_explicit_submit=True,
            require_comment_confirmation=True,
            expected_aweme_id=request.aweme_id,
        )

    async def _reply_to_comment(
        self,
        page: Page,
        client: DouyinClient,
        request: InteractionExecutionRequest,
        step_callback: InteractionStepCallback | None,
    ) -> InteractionExecutionResult:
        if not request.target_comment_content:
            raise InteractionExecutionError(
                "target_not_found", "目标评论不存在或内容不可用"
            )
        await self._open_video(page, request.aweme_id)
        await self._trace(step_callback, page, "video_opened", "已打开目标视频页面")
        active_page, comment_editor = await self._open_comment_panel(
            page, aweme_id=request.aweme_id
        )
        if comment_editor is None:
            raise InteractionExecutionError(
                "comment_not_available",
                "评论区已完成加载，但当前作品没有可用的互动入口",
            )
        self._assert_video_page(active_page, request.aweme_id)
        if not await self._ensure_comment_list_active(active_page):
            raise InteractionExecutionError(
                "comment_list_unavailable",
                "评论标签未能切换到可见评论列表，请稍后重试",
                retryable=True,
            )
        target = await self._find_comment_target(active_page, request)
        if target is None:
            target_state = await self._lookup_target_comment(client, request)
            if target_state == "unavailable":
                await self._trace(
                    step_callback,
                    active_page,
                    "reply_target_unavailable",
                    "真实评论接口已完整翻页，目标评论当前不可见",
                )
                raise InteractionExecutionError(
                    "target_unavailable",
                    "真实评论列表已完整核验：目标评论不存在或当前账号不可见",
                )
            if target_state == "present":
                await self._trace(
                    step_callback,
                    active_page,
                    "reply_target_api_verified",
                    "真实评论接口已确认目标存在，但页面未能完成定位",
                )
                raise InteractionExecutionError(
                    "target_dom_not_found",
                    "目标评论仍然存在，但当前页面未能加载到对应节点，请重试",
                    retryable=True,
                )
            raise InteractionExecutionError(
                "target_lookup_inconclusive",
                "页面未定位到目标评论，实时接口核验也未能完整结束，请重试",
                retryable=True,
            )
        await self._trace(
            step_callback,
            active_page,
            "reply_target_found",
            "已在评论区定位到目标评论",
        )
        reply_context, editor = await self._open_reply_editor(
            active_page, target, request
        )
        if editor is None or reply_context is None:
            raise InteractionExecutionError(
                "reply_not_available",
                "目标评论未能进入明确的回复状态，已停止发送，请重试",
                retryable=True,
            )
        await self._trace(
            step_callback,
            active_page,
            "reply_editor_ready",
            "已打开目标评论的回复输入框",
        )
        return await self._fill_and_submit(
            active_page,
            editor,
            request.content,
            step_callback,
            require_explicit_submit=True,
            require_comment_confirmation=True,
            expected_aweme_id=request.aweme_id,
            expected_reply_context=reply_context,
            expected_reply_comment_id=request.target_comment_id,
            expected_parent_comment_id=request.target_parent_comment_id,
        )

    @classmethod
    async def _find_comment_target(
        cls, page: Page, request: InteractionExecutionRequest
    ) -> Locator | None:
        no_scroll_progress = 0
        for _ in range(48):
            comment_list = await cls._find_visible(
                page, cls.comment_list_selectors, timeout=250
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
        """Advance Douyin's internal route scroller instead of the window."""
        scroll_anchor = await cls._find_visible(
            page, cls.comment_list_selectors, timeout=250
        )
        if scroll_anchor is None:
            # Older detail-page builds expose comment items but not a dedicated
            # comment-list marker. Starting at a visible item still lets the
            # script locate its nearest real scrolling ancestor.
            scroll_anchor = await cls._find_visible(
                page, cls.comment_item_selectors, timeout=250
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

    async def _ensure_comment_list_active(self, page: Page) -> bool:
        if await self._find_visible_comment_surface(page, timeout=300) is not None:
            return True
        control = await self._find_visible(
            page, self.comment_tab_selectors, timeout=3_000
        )
        if control is None:
            return False
        activators: tuple[Callable[[], Awaitable[None]], ...] = (
            lambda: control.dispatch_event("click"),
            lambda: control.click(timeout=2_000),
            lambda: self._click_control_center(page, control),
        )
        for activate in activators:
            try:
                await activate()
            except Exception:
                continue
            if await self._find_visible_comment_surface(page, timeout=1_500) is not None:
                return True
        return False

    async def _find_visible_comment_surface(
        self, page: Page, *, timeout: int
    ) -> Locator | None:
        comment_list = await self._find_visible(
            page, self.comment_list_selectors, timeout=timeout
        )
        if comment_list is not None:
            return comment_list
        return await self._find_visible(
            page, self.comment_item_selectors, timeout=timeout
        )

    @staticmethod
    async def _lookup_target_comment(
        client: DouyinClient, request: InteractionExecutionRequest
    ) -> str:
        """Return present, unavailable, or inconclusive from live comment APIs."""
        if not request.target_comment_id:
            return "inconclusive"
        cursor = 0
        total = 0
        seen_cursors: set[int] = set()
        for _ in range(50):
            try:
                parent_comment_id = request.target_parent_comment_id
                if parent_comment_id not in {None, "", "0"}:
                    assert parent_comment_id is not None
                    payload = await client.get_sub_comments_page(
                        request.aweme_id,
                        parent_comment_id,
                        cursor,
                    )
                else:
                    payload = await client.get_comments_page(request.aweme_id, cursor)
            except Exception:
                return "inconclusive"
            # A non-zero Douyin business status, or a response that omits the
            # pagination contract, is not proof that a comment disappeared.
            # Treat it as inconclusive so the task stays safely retryable.
            if payload.get("status_code") not in (0, "0"):
                return "inconclusive"
            if "comments" not in payload or "has_more" not in payload:
                return "inconclusive"
            comments = payload["comments"]
            if not isinstance(comments, list):
                return "inconclusive"
            for comment in comments:
                if str(comment.get("cid") or "") == request.target_comment_id:
                    return "present"
            total += len(comments)
            has_more = payload.get("has_more")
            if has_more in (False, 0, "0"):
                return "unavailable"
            if has_more not in (True, 1, "1"):
                return "inconclusive"
            if not comments or total >= 1_000:
                return "inconclusive"
            try:
                next_cursor = int(payload.get("cursor") or 0)
            except (TypeError, ValueError):
                return "inconclusive"
            if next_cursor == cursor or next_cursor in seen_cursors:
                return "inconclusive"
            seen_cursors.add(cursor)
            cursor = next_cursor
            await asyncio.sleep(0.2)
        return "inconclusive"

    async def _open_reply_editor(
        self,
        page: Page,
        target: Locator,
        request: InteractionExecutionRequest,
    ) -> tuple[Locator | None, Locator | None]:
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
            lambda: self._click_control_center(page, reply_control),
        )
        for activate in activators:
            try:
                await activate()
            except Exception:
                continue
            deadline = asyncio.get_running_loop().time() + 2.0
            while asyncio.get_running_loop().time() < deadline:
                editor = await self._find_visible(
                    page, self.editor_selectors, timeout=250
                )
                if editor is not None and await self._reply_context_is_active(
                    comment_card, request.target_comment_id
                ):
                    return comment_card, editor
                await page.wait_for_timeout(150)
        return None, None

    @staticmethod
    async def _reply_context_is_active(
        comment_card: Locator, target_comment_id: str | None
    ) -> bool:
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

    async def _message_creator(
        self,
        page: Page,
        client: DouyinClient,
        request: InteractionExecutionRequest,
        step_callback: InteractionStepCallback | None,
    ) -> InteractionExecutionResult:
        detail = await client.get_video(request.aweme_id)
        author = detail.get("author")
        if not isinstance(author, dict):
            raise InteractionExecutionError("target_not_found", "无法从作品中解析作者")
        # This raw identifier is deliberately kept in local memory only.
        sec_uid = str(author.get("sec_uid") or author.get("sec_user_id") or "").strip()
        if not sec_uid:
            raise InteractionExecutionError(
                "target_not_found", "作品作者没有可用的私信目标"
            )
        try:
            await page.goto(
                f"{self.index_url}/user/{quote(sec_uid, safe='')}",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
        except PlaywrightTimeoutError:
            pass
        await self._trace(
            step_callback,
            page,
            "creator_profile_opened",
            "已打开目标视频作者主页",
        )
        profile_ready = await self._find_visible(
            page, self.creator_profile_ready_selectors, timeout=30_000
        )
        message_button = await self._find_text_control(
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
        await self._trace(
            step_callback,
            page,
            "message_entry_opened",
            "已点击作者私信入口，正在等待会话窗口",
        )
        editor_page, editor = await self._find_message_editor(
            page, timeout=30_000, baseline_pages=baseline_pages
        )
        if editor is None:
            raise InteractionExecutionError(
                "message_not_allowed",
                "私信窗口未能打开；该作者可能要求互相关注，或当前账号没有私信权限",
            )
        await self._trace(
            step_callback,
            editor_page,
            "message_editor_ready",
            "私信窗口已打开并定位到消息输入框",
        )
        return await self._fill_and_submit(
            editor_page,
            editor,
            request.content,
            step_callback,
            require_explicit_submit=True,
        )

    async def _open_video(self, page: Page, aweme_id: str) -> None:
        target_url = f"https://www.douyin.com/video/{quote(aweme_id, safe='')}"
        attempts = self.settings.DOUYIN_INTERACTION_NAVIGATION_ATTEMPTS
        for attempt in range(attempts):
            try:
                await page.goto(
                    target_url,
                    wait_until="commit",
                    timeout=30_000,
                )
            except PlaywrightTimeoutError:
                # A committed document can continue rendering after navigation times out.
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
                    self.video_page_ready_script,
                    timeout=(
                        self.settings.DOUYIN_INTERACTION_PAGE_READY_TIMEOUT_SECONDS
                        * 1000
                    ),
                )
                return
            except PlaywrightTimeoutError as exc:
                if attempt + 1 >= attempts:
                    raise InteractionExecutionError(
                        "page_load_timeout",
                        "目标视频页面持续加载，自动刷新后仍未进入可互动状态",
                        retryable=True,
                    ) from exc

            # Discard a renderer that is stuck on Douyin's loading shell before
            # retrying the target URL. This keeps recovery inside one confirmed
            # interaction attempt and never falls back from CDP.
            try:
                await page.goto(
                    "about:blank",
                    wait_until="commit",
                    timeout=5_000,
                )
            except PlaywrightError:
                pass
            await page.wait_for_timeout((attempt + 1) * 1_000)

    async def _open_comment_panel(
        self, page: Page, *, aweme_id: str | None = None
    ) -> tuple[Page, Locator | None]:
        deadline = (
            asyncio.get_running_loop().time()
            + self.settings.DOUYIN_INTERACTION_COMMENT_READY_TIMEOUT_SECONDS
        )
        control_clicked_pages: set[int] = set()
        next_entry_click_at: dict[int, float] = {}
        while asyncio.get_running_loop().time() < deadline:
            candidates = self._interaction_pages(page, aweme_id=aweme_id)
            for candidate in candidates:
                editor = await self._find_visible(
                    candidate, self.editor_selectors, timeout=500
                )
                if editor is not None:
                    return candidate, editor

            now = asyncio.get_running_loop().time()
            for candidate in candidates:
                page_key = id(candidate)
                if page_key not in control_clicked_pages:
                    control = await self._find_visible(
                        candidate, self.comment_tab_selectors, timeout=400
                    )
                    if control is not None:
                        editor = await self._activate_comment_control(
                            candidate, control
                        )
                        control_clicked_pages.add(page_key)
                        if editor is not None:
                            return candidate, editor

                if now < next_entry_click_at.get(page_key, 0.0):
                    continue
                entry = await self._find_visible(
                    candidate, self.comment_entry_selectors, timeout=400
                )
                if entry is not None:
                    editor = await self._activate_comment_control(
                        candidate, entry, require_editor=True
                    )
                    if editor is not None:
                        return candidate, editor
                    next_entry_click_at[page_key] = now + 2.0

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining > 0:
                await page.wait_for_timeout(min(500, int(remaining * 1000)))
        return page, None

    @staticmethod
    def _interaction_pages(page: Page, *, aweme_id: str | None) -> list[Page]:
        """Never let unrelated user tabs participate in an interaction."""
        if page.is_closed():
            return []
        if aweme_id and aweme_id not in page.url:
            return []
        return [page]

    async def _activate_comment_control(
        self,
        page: Page,
        control: Locator,
        *,
        require_editor: bool = False,
    ) -> Locator | None:
        """Activate a control and verify that Douyin changed to an editable state."""
        activators: tuple[Callable[[], Awaitable[None]], ...] = (
            lambda: control.dispatch_event("click"),
            lambda: control.click(timeout=2_000),
            lambda: self._click_control_center(page, control),
        )
        for activate in activators:
            try:
                await activate()
            except Exception:
                continue
            await page.wait_for_timeout(200)
            editor = await self._find_visible(page, self.editor_selectors, timeout=500)
            if editor is not None:
                return editor
            if not require_editor:
                entry = await self._find_visible(
                    page, self.comment_entry_selectors, timeout=300
                )
                if entry is not None:
                    return None
        return None

    @staticmethod
    def _assert_video_page(page: Page, aweme_id: str) -> None:
        if page.is_closed() or aweme_id not in page.url:
            raise InteractionExecutionError(
                "page_interrupted",
                "自动化专用标签页被关闭或切换，发送前已安全终止；请重试任务",
                retryable=True,
            )

    async def _fill_and_submit(
        self,
        page: Page,
        editor: Locator,
        content: str,
        step_callback: InteractionStepCallback | None,
        *,
        response_markers: tuple[str, ...] | None = None,
        require_explicit_submit: bool = False,
        require_comment_confirmation: bool = False,
        expected_aweme_id: str | None = None,
        expected_reply_context: Locator | None = None,
        expected_reply_comment_id: str | None = None,
        expected_parent_comment_id: str | None = None,
    ) -> InteractionExecutionResult:
        try:
            await editor.click()
            await editor.fill(content)
        except Exception as exc:
            raise InteractionExecutionError(
                "editor_unavailable", "互动输入框不可用", retryable=True
            ) from exc
        await self._trace(
            step_callback,
            page,
            "content_filled",
            "互动内容已填写，准备触发发送",
        )
        if expected_aweme_id:
            self._assert_video_page(page, expected_aweme_id)
        if (
            expected_reply_context is not None
            and not await self._reply_context_is_active(
                expected_reply_context, expected_reply_comment_id
            )
        ):
            raise InteractionExecutionError(
                "reply_context_lost",
                "回复目标状态在发送前丢失，已停止发送，请重试",
                retryable=True,
            )

        submit = await self._find_submit_control(page, editor)
        if require_explicit_submit and submit is None:
            raise InteractionExecutionError(
                "submit_not_available",
                "互动内容已填写，但没有找到可点击的发送按钮，未执行发送",
                retryable=True,
            )
        markers = response_markers or self.response_markers
        submitted = False
        try:
            if require_comment_confirmation:
                # A send is ambiguous only after a publish request is observed.
                # Failed UI activation with a still-filled editor is safe to retry.
                assert submit is not None
                async with page.expect_response(
                    lambda response: (self._is_comment_publish_response(response)),
                    timeout=12_000,
                ) as response_info:
                    await submit.scroll_into_view_if_needed()
                    submitted = await self._dispatch_comment_submit(page, submit)
                    if not submitted:
                        raise InteractionExecutionError(
                            "submit_not_triggered",
                            "发送按钮没有触发评论发布请求，内容仍在输入框中，确认未发送",
                            retryable=True,
                        )
                    await self._trace(
                        step_callback,
                        page,
                        "submit_triggered",
                        "已触发发送，正在等待抖音确认",
                    )
                response = await response_info.value
                if expected_reply_comment_id and not self._request_targets_reply(
                    response.request,
                    target_comment_id=expected_reply_comment_id,
                    parent_comment_id=expected_parent_comment_id,
                ):
                    raise InteractionExecutionError(
                        "reply_target_mismatch",
                        "回复发布请求没有绑定到预期评论，结果需要人工核对",
                        ambiguous=True,
                    )
                if not response.ok:
                    code = (
                        "risk_controlled"
                        if response.status in {403, 429}
                        else "platform_rejected"
                    )
                    raise InteractionExecutionError(
                        code,
                        f"抖音拒绝了评论请求（HTTP {response.status}）",
                        affects_account_health=response.status in {403, 429},
                    )
                payload = await self._safe_json(response)
                status_code = self._platform_status_code(payload)
                if status_code not in (None, 0, "0"):
                    raise InteractionExecutionError(
                        "platform_rejected",
                        self._platform_error_message(
                            payload, prefix="抖音未接受评论请求"
                        ),
                        affects_account_health=True,
                    )
                platform_id = self._result_id(payload)
                if status_code in (0, "0") or platform_id is not None:
                    await self._trace(
                        step_callback,
                        page,
                        "platform_accepted",
                        "抖音评论发布接口已返回成功",
                    )
                    return InteractionExecutionResult(platform_id=platform_id)
                await self._wait_comment_submission(page, request_content=content)
                if not await self._wait_editor_empty(editor):
                    raise InteractionExecutionError(
                        "ambiguous_result",
                        "已经触发评论发布请求，但评论仍停留在输入框中，不能判定成功",
                        ambiguous=True,
                    )
                await self._trace(
                    step_callback,
                    page,
                    "platform_accepted",
                    "评论发布请求已触发且输入框已清空",
                )
                return InteractionExecutionResult(platform_id=platform_id)

            async with page.expect_response(
                lambda response: any(marker in response.url for marker in markers),
                timeout=12_000,
            ) as response_info:
                submitted = True
                if submit is not None:
                    await submit.scroll_into_view_if_needed()
                    await submit.click(timeout=5_000)
                else:
                    await editor.press("Control+Enter")
                await self._trace(
                    step_callback,
                    page,
                    "submit_triggered",
                    "已触发发送，正在等待抖音确认",
                )
            response = await response_info.value
            if not response.ok:
                code = (
                    "risk_controlled"
                    if response.status in {403, 429}
                    else "platform_rejected"
                )
                raise InteractionExecutionError(
                    code,
                    f"抖音拒绝了互动请求（HTTP {response.status}）",
                    affects_account_health=response.status in {403, 429},
                )
            payload = await self._safe_json(response)
            status_code = self._platform_status_code(payload)
            if status_code not in (None, 0, "0"):
                raise InteractionExecutionError(
                    "platform_rejected",
                    self._platform_error_message(
                        payload, prefix="抖音未接受该互动请求"
                    ),
                )
            platform_id = self._result_id(payload)
            await self._trace(
                step_callback,
                page,
                "platform_accepted",
                "抖音已接受互动请求",
            )
            return InteractionExecutionResult(platform_id=platform_id)
        except PlaywrightTimeoutError as exc:
            if require_comment_confirmation:
                risk_message = await self._visible_page_message(
                    page, self.comment_risk_messages
                )
                if risk_message:
                    raise InteractionExecutionError(
                        "risk_controlled",
                        "抖音要求完成短信或扫码安全验证，请先在对应账号浏览器中完成验证",
                        affects_account_health=True,
                    ) from exc
                failure_message = await self._visible_page_message(
                    page, self.comment_failure_messages
                )
                if failure_message:
                    raise InteractionExecutionError(
                        "platform_rejected",
                        f"抖音页面提示：{failure_message}",
                        affects_account_health=True,
                    ) from exc
            if (
                submitted
                and not require_comment_confirmation
                and await self._editor_is_empty(editor)
            ):
                return InteractionExecutionResult()
            raise InteractionExecutionError(
                "ambiguous_result",
                "发送后未收到明确结果，请人工检查抖音页面后再决定是否重试",
                ambiguous=submitted,
                retryable=not submitted,
                affects_account_health=not submitted,
            ) from exc

        except InteractionExecutionError:
            raise
        except Exception as exc:
            raise InteractionExecutionError(
                "ambiguous_result" if submitted else "network_error",
                (
                    "发送结果不明确，请人工检查后再决定是否重试"
                    if submitted
                    else "发送前发生网络或页面错误"
                ),
                ambiguous=submitted,
                retryable=not submitted,
                affects_account_health=True,
            ) from exc

    @staticmethod
    async def _trace(
        callback: InteractionStepCallback | None,
        page: Page,
        step: str,
        detail: str,
    ) -> None:
        if callback is not None:
            await callback(page, step, detail)

    @staticmethod
    async def _safe_json(response: Any) -> dict[str, Any]:
        try:
            payload = await response.json()
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _is_comment_publish_response(response: Any) -> bool:
        """Match current and legacy Douyin comment-publish endpoints."""
        try:
            return DouyinInteractionExecutor._is_comment_publish_request(
                response.request
            )
        except Exception:
            return False

    @staticmethod
    def _request_targets_reply(
        request: Any,
        *,
        target_comment_id: str,
        parent_comment_id: str | None,
    ) -> bool:
        """Verify that a publish request is bound to the confirmed comment."""
        try:
            post_data = str(request.post_data or "")
            fields: dict[str, list[str]] = parse_qs(post_data, keep_blank_values=True)
        except Exception:
            return False
        reply_id = (fields.get("reply_id") or [""])[0]
        reply_to_reply_id = (fields.get("reply_to_reply_id") or [""])[0]
        if parent_comment_id not in {None, "", "0"}:
            return (
                reply_id == parent_comment_id and reply_to_reply_id == target_comment_id
            )
        return reply_id == target_comment_id and reply_to_reply_id in {"", "0"}

    @staticmethod
    def _is_comment_publish_request(request: Any) -> bool:
        try:
            if request.method != "POST":
                return False
            path = request.url.split("?", 1)[0].lower()
        except Exception:
            return False
        return "comment" in path and any(
            marker in path for marker in ("publish", "create", "post")
        )

    @staticmethod
    def _result_id(payload: dict[str, Any]) -> str | None:
        for candidate in (payload, payload.get("data"), payload.get("result")):
            if not isinstance(candidate, dict):
                continue
            nested = candidate.get("comment")
            if isinstance(nested, dict):
                value = nested.get("cid") or nested.get("comment_id")
                if value:
                    return str(value)
            value = candidate.get("cid") or candidate.get("comment_id")
            if value:
                return str(value)
        return None

    @staticmethod
    def _platform_status_code(payload: dict[str, Any]) -> object | None:
        """Read Douyin business status from current and legacy wrappers."""
        for candidate in (
            payload,
            payload.get("data"),
            payload.get("result"),
        ):
            if isinstance(candidate, dict) and "status_code" in candidate:
                return candidate.get("status_code")
        return None

    @staticmethod
    def _platform_error_message(payload: dict[str, Any], *, prefix: str) -> str:
        for candidate in (payload, payload.get("data"), payload.get("result")):
            if not isinstance(candidate, dict):
                continue
            for key in ("status_msg", "message", "description"):
                value = candidate.get(key)
                if isinstance(value, str) and value.strip():
                    return f"{prefix}：{value.strip()}"
        return prefix

    @staticmethod
    async def _wait_editor_empty(editor: Locator, *, timeout_ms: int = 5_000) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
        while True:
            if await DouyinInteractionExecutor._editor_is_empty(editor):
                return True
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            try:
                await editor.page.wait_for_timeout(min(200, int(remaining * 1000)))
            except Exception:
                await asyncio.sleep(min(0.2, remaining))

    async def _wait_comment_submission(
        self,
        page: Page,
        *,
        request_content: str,
        timeout_ms: int = 5_000,
    ) -> None:
        """Wait for Douyin's UI verdict; its failed publish response can still be HTTP 200."""
        deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
        stable_editor = page.locator(
            "#comment-input-container .public-DraftEditor-content"
        ).first
        while True:
            success_message = await self._visible_page_message(
                page, self.comment_success_messages
            )
            if success_message:
                return
            risk_message = await self._visible_page_message(
                page, self.comment_risk_messages
            )
            if risk_message:
                raise InteractionExecutionError(
                    "risk_controlled",
                    "抖音要求完成短信或扫码安全验证，请先在对应账号浏览器中完成验证",
                    affects_account_health=True,
                )
            failure_message = await self._visible_page_message(
                page, self.comment_failure_messages
            )
            if failure_message:
                raise InteractionExecutionError(
                    "platform_rejected",
                    f"抖音页面提示：{failure_message}",
                    affects_account_health=True,
                )
            try:
                if await stable_editor.count():
                    value = (
                        await stable_editor.text_content(timeout=300) or ""
                    ).strip()
                    if not value:
                        return
                else:
                    root = page.locator("#comment-input-container").first
                    root_text = (
                        await root.text_content(timeout=300) or ""
                        if await root.count()
                        else ""
                    )
                    if request_content.strip() not in root_text.strip():
                        return
            except InteractionExecutionError:
                raise
            except Exception:
                pass
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise InteractionExecutionError(
                    "ambiguous_result",
                    "评论发布请求已完成，但内容仍停留在输入框中，不能判定发送成功",
                    ambiguous=True,
                )
            await page.wait_for_timeout(min(200, int(remaining * 1000)))

    @staticmethod
    async def _visible_page_message(
        page: Page, messages: tuple[str, ...]
    ) -> str | None:
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
    async def _dispatch_comment_submit(page: Page, control: Locator) -> bool:
        """Activate Douyin's transformed comment submit control exactly once."""
        publish_requested = asyncio.Event()

        def observe_request(request: Any) -> None:
            if DouyinInteractionExecutor._is_comment_publish_request(request):
                publish_requested.set()

        page.on("request", observe_request)
        try:
            # Douyin's transformed comment composer can accept a component click
            # while Playwright reports a successful coordinate click without the
            # document receiving any click event. Trigger the React component while
            # it is still visible, then keep trusted CDP clicks as fallbacks.
            activators: tuple[Callable[[], Awaitable[None]], ...] = (
                lambda: control.dispatch_event("click"),
                lambda: control.click(timeout=5_000),
                lambda: DouyinInteractionExecutor._click_control_center(page, control),
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
    async def _click_control_center(page: Page, control: Locator) -> None:
        """Use a real CDP mouse event for transformed React submit controls."""
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
    async def _find_visible(
        page: Page,
        selectors: tuple[str, ...],
        *,
        timeout: int = 4_000,
    ) -> Locator | None:
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

    async def _find_message_editor(
        self,
        page: Page,
        *,
        timeout: int,
        baseline_pages: set[Page] | None = None,
    ) -> tuple[Page, Locator | None]:
        """Find the conversation editor on the current or newly opened CDP page."""
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
                editor = await self._find_visible(
                    candidate, self.message_editor_selectors, timeout=400
                )
                if editor is not None:
                    return candidate, editor
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return page, None
            await page.wait_for_timeout(min(250, int(remaining * 1000)))

    @staticmethod
    async def _find_submit_control(page: Page, editor: Locator) -> Locator | None:
        direct = await DouyinInteractionExecutor._find_visible(
            page,
            (
                *DouyinInteractionExecutor.comment_submit_selectors,
                *DouyinInteractionExecutor.message_submit_selectors,
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
        return await DouyinInteractionExecutor._find_text_control(
            page, ("发送", "发布")
        )
