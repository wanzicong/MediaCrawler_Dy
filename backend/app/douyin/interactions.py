# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
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


@dataclass(frozen=True)
class InteractionExecutionResult:
    platform_id: str | None = None


class DouyinInteractionExecutor:
    """Perform explicitly confirmed write actions through an existing CDP profile."""

    index_url = "https://www.douyin.com"
    response_markers = ("/comment/publish", "/im/", "/message/")
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
        '[data-e2e="comment-input"] [contenteditable="true"]',
        '[data-e2e="comment-input"] textarea',
        'div[contenteditable="true"][data-placeholder*="评论"]',
        'div[contenteditable="true"][aria-label*="评论"]',
        'textarea[placeholder*="评论"]',
        'div[contenteditable="true"][data-placeholder*="回复"]',
        'textarea[placeholder*="回复"]',
    )
    comment_entry_selectors = (
        "#comment-input-container",
        ".comment-input-inner-container",
    )
    comment_submit_selectors = (
        "#comment-input-container .commentInput-right-ct > div > span:last-child",
        '#comment-input-container [data-e2e="comment-submit"]',
    )
    message_editor_selectors = (
        'div[contenteditable="true"][data-placeholder*="消息"]',
        'div[contenteditable="true"][aria-label*="消息"]',
        'textarea[placeholder*="消息"]',
        'textarea[placeholder*="发送"]',
    )

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
                "已通过 CDP 连接所选账号浏览器并打开抖音首页",
            )
            client = await DouyinClient.create(
                page=page,
                browser_context=browser.context,
                timeout=self.settings.DOUYIN_REQUEST_TIMEOUT,
                verify_ssl=self.settings.DOUYIN_REQUEST_SSL_VERIFY,
            )
            try:
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
                    return await self._reply_to_comment(page, request, step_callback)
                return await self._message_creator(
                    page, client, request, step_callback
                )
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
                await client.close()

    async def _comment_video(
        self,
        page: Page,
        request: InteractionExecutionRequest,
        step_callback: InteractionStepCallback | None,
    ) -> InteractionExecutionResult:
        await self._open_video(page, request.aweme_id)
        await self._trace(
            step_callback, page, "video_opened", "已打开目标视频页面"
        )
        editor = await self._open_comment_panel(page)
        if editor is None:
            raise InteractionExecutionError(
                "comment_not_available",
                "当前作品没有可用的评论输入框，可能已关闭评论",
            )
        await self._trace(
            step_callback,
            page,
            "comment_editor_ready",
            "评论区已展开并定位到评论输入框",
        )
        return await self._fill_and_submit(
            page, editor, request.content, step_callback
        )

    async def _reply_to_comment(
        self,
        page: Page,
        request: InteractionExecutionRequest,
        step_callback: InteractionStepCallback | None,
    ) -> InteractionExecutionResult:
        if not request.target_comment_content:
            raise InteractionExecutionError(
                "target_not_found", "目标评论不存在或内容不可用"
            )
        await self._open_video(page, request.aweme_id)
        await self._trace(
            step_callback, page, "video_opened", "已打开目标视频页面"
        )
        comment_editor = await self._open_comment_panel(page)
        if comment_editor is None:
            raise InteractionExecutionError(
                "comment_not_available",
                "评论区已完成加载，但当前作品没有可用的互动入口",
            )
        target = await self._find_comment_target(page, request)
        if target is None:
            raise InteractionExecutionError(
                "target_not_found",
                "目标评论未出现在当前作品中，可能已被删除或尚未加载",
            )
        await self._trace(
            step_callback,
            page,
            "reply_target_found",
            "已在评论区定位到目标评论",
        )
        reply_clicked = await self._click_reply(target)
        if not reply_clicked:
            raise InteractionExecutionError(
                "reply_not_available", "目标评论当前不允许回复"
            )
        editor = await self._find_visible(page, self.editor_selectors)
        if editor is None:
            raise InteractionExecutionError(
                "reply_not_available", "没有找到回复输入框"
            )
        await self._trace(
            step_callback,
            page,
            "reply_editor_ready",
            "已打开目标评论的回复输入框",
        )
        return await self._fill_and_submit(
            page, editor, request.content, step_callback
        )

    @staticmethod
    async def _find_comment_target(
        page: Page, request: InteractionExecutionRequest
    ) -> Locator | None:
        candidates: list[Locator] = []
        if request.target_comment_id and request.target_comment_id.isdigit():
            candidates.extend(
                [
                    page.locator(
                        f'[data-comment-id="{request.target_comment_id}"]'
                    ).first,
                    page.locator(f'[data-cid="{request.target_comment_id}"]').first,
                ]
            )
        assert request.target_comment_content is not None
        candidates.append(
            page.get_by_text(request.target_comment_content, exact=True).first
        )
        if len(request.target_comment_content) > 40:
            candidates.append(
                page.get_by_text(request.target_comment_content[:40], exact=False).first
            )
        for _ in range(16):
            for candidate in candidates:
                try:
                    if await candidate.count() and await candidate.is_visible():
                        return candidate
                except Exception:
                    continue
            await page.mouse.wheel(0, 900)
            await page.wait_for_timeout(350)
        return None

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
            raise InteractionExecutionError(
                "target_not_found", "无法从作品中解析作者"
            )
        # This raw identifier is deliberately kept in local memory only.
        sec_uid = str(
            author.get("sec_uid") or author.get("sec_user_id") or ""
        ).strip()
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
        message_button = await self._find_text_control(page, ("私信", "发消息"))
        if message_button is None:
            raise InteractionExecutionError(
                "message_not_allowed",
                "作者未开放私信，或当前账号不满足私信条件",
            )
        await message_button.click()
        editor = await self._find_visible(page, self.message_editor_selectors)
        if editor is None:
            raise InteractionExecutionError(
                "message_not_allowed",
                "私信窗口未能打开，可能需要互相关注或账号权限不足",
            )
        await self._trace(
            step_callback,
            page,
            "message_editor_ready",
            "私信窗口已打开并定位到消息输入框",
        )
        return await self._fill_and_submit(
            page, editor, request.content, step_callback
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

    async def _open_comment_panel(self, page: Page) -> Locator | None:
        controls = (
            '[data-e2e="feed-comment-icon"]',
            '[data-e2e="comment-icon"]',
            '[aria-label*="评论"]',
            'button:has-text("评论")',
        )
        deadline = (
            asyncio.get_running_loop().time()
            + self.settings.DOUYIN_INTERACTION_COMMENT_READY_TIMEOUT_SECONDS
        )
        control_clicked = False
        entry_seen = False
        next_entry_click_at = 0.0
        while asyncio.get_running_loop().time() < deadline:
            editor = await self._find_visible(
                page, self.editor_selectors, timeout=600
            )
            if editor is not None:
                return editor
            now = asyncio.get_running_loop().time()
            if now >= next_entry_click_at:
                entry = await self._find_visible(
                    page, self.comment_entry_selectors, timeout=400
                )
                if entry is not None:
                    entry_seen = True
                    try:
                        await entry.click(timeout=2_000)
                        next_entry_click_at = now + 3.0
                        continue
                    except Exception:
                        pass
            if not control_clicked and not entry_seen:
                control = await self._find_visible(page, controls, timeout=400)
                if control is not None:
                    try:
                        await control.click(timeout=2_000)
                        control_clicked = True
                        continue
                    except Exception:
                        pass
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining > 0:
                await page.wait_for_timeout(min(500, int(remaining * 1000)))
        return None

    @staticmethod
    async def _click_reply(target: Locator) -> bool:
        node = target
        for _ in range(8):
            reply = node.get_by_text("回复", exact=True).first
            if await reply.count() and await reply.is_visible():
                await reply.click()
                return True
            node = node.locator("xpath=..")
        return False

    async def _fill_and_submit(
        self,
        page: Page,
        editor: Locator,
        content: str,
        step_callback: InteractionStepCallback | None,
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

        submit = await self._find_submit_control(page, editor)
        submitted = False
        try:
            async with page.expect_response(
                lambda response: any(
                    marker in response.url for marker in self.response_markers
                ),
                timeout=12_000,
            ) as response_info:
                submitted = True
                if submit is not None:
                    await submit.click()
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
            status_code = payload.get("status_code")
            if status_code not in (None, 0, "0"):
                raise InteractionExecutionError(
                    "platform_rejected", "抖音未接受该互动请求"
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
            if submitted and await self._editor_is_empty(editor):
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
    def _result_id(payload: dict[str, Any]) -> str | None:
        comment = payload.get("comment")
        if isinstance(comment, dict):
            value = comment.get("cid") or comment.get("comment_id")
            return str(value) if value else None
        return None

    @staticmethod
    async def _editor_is_empty(editor: Locator) -> bool:
        value: str | None
        try:
            value = await editor.input_value()
        except Exception:
            try:
                value = await editor.text_content()
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
        page: Page, labels: tuple[str, ...]
    ) -> Locator | None:
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
        return None

    @staticmethod
    async def _find_submit_control(page: Page, editor: Locator) -> Locator | None:
        direct = await DouyinInteractionExecutor._find_visible(
            page,
            DouyinInteractionExecutor.comment_submit_selectors,
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
