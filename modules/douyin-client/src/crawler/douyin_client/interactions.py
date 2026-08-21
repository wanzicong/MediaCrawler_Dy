# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音互动执行器：通过 CDP 浏览器执行用户明确确认的写操作。

支持评论作品、回复评论、私信作者三类互动；全程在账号已有的 CDP
浏览器 profile 中进行，并通过步骤回调上报进展。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import parse_qs, quote

from crawler.bootstrap.settings import Settings
from crawler.browser.session import CDPBrowserSession
from crawler.douyin_client.client import DouyinClient
from playwright.async_api import Dialog, Locator, Page
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

# 互动步骤回调：参数为当前页面、步骤标识与步骤说明
InteractionStepCallback = Callable[[Page, str, str], Awaitable[None]]


class _LegacyAccountId(Protocol):
    """旧版账号 ID 的结构化协议（仅要求 int 属性）。"""

    int: int  # 账号整数 ID


class _LegacyInteractionAccount(Protocol):
    """旧版互动账号对象的结构化协议，仅声明本模块需要的属性。"""

    id: _LegacyAccountId  # 账号 ID
    browser_mode: object  # 浏览器模式（枚举或其原始值）
    profile_key: str  # 本地 profile 目录名
    remote_slot: str | None  # 远程浏览器槽位名，None 表示使用默认远程配置


class InteractionExecutionError(RuntimeError):
    """互动执行失败错误，携带错误码与处置标记。

    属性：
        code: 机器可读的错误码。
        retryable: 是否可安全重试。
        ambiguous: 结果是否不明确（可能已发出，需人工核对）。
        affects_account_health: 是否影响账号健康状态。
    """

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
    """互动执行请求参数。

    属性：
        interaction_type: 互动类型：video_comment（评论作品）/ comment_reply（回复评论）/ 其他为私信作者。
        aweme_id: 目标作品 ID。
        content: 互动文本内容。
        target_comment_id: 目标评论 ID（comment_reply 时使用）。
        target_comment_content: 目标评论内容，用于页面内定位。
        target_parent_comment_id: 目标评论的父评论 ID（回复二级评论时使用）。
    """

    interaction_type: str  # 互动类型：video_comment / comment_reply / 私信作者
    aweme_id: str  # 目标作品 ID
    content: str  # 互动文本内容
    target_comment_id: str | None = None  # 目标评论 ID
    target_comment_content: str | None = None  # 目标评论内容，用于页面内定位
    target_parent_comment_id: str | None = None  # 目标评论的父评论 ID


@dataclass(frozen=True)
class InteractionExecutionResult:
    """互动执行结果。

    属性：
        platform_id: 平台侧返回的评论 ID 等标识，未能解析时为 None。
    """

    platform_id: str | None = None  # 平台侧返回的评论 ID 等标识


@dataclass(frozen=True)
class InteractionBrowserConnection:
    """由应用层解析好的 CDP 连接参数（纯基础设施数据）。"""

    browser_mode: str  # 浏览器模式：local（本地 profile）或 remote（远程 CDP）
    remote_host: str | None = None  # 远程 CDP 主机
    remote_port: int | None = None  # 远程 CDP 端口
    user_data_dir: Path | None = None  # 本地浏览器用户数据目录
    debug_port: int | None = None  # 本地浏览器 CDP 调试端口


class DouyinInteractionExecutor:
    """通过已有 CDP 浏览器 profile 执行用户明确确认的写操作（评论/回复/私信）。"""

    index_url = "https://www.douyin.com"  # 抖音主站地址
    response_markers = ("/im/", "/message/")  # 私信发送响应的 URL 匹配标记
    # 视频页就绪检测脚本：页面不再处于“视频数据加载中”，且存在 video 元素或互动 UI
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
    editor_selectors = (  # 评论/回复输入框候选选择器（兼容多种页面版本）
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
    comment_entry_selectors = (  # 评论区入口容器选择器
        ".comment-input-inner-container",
        "#comment-input-container",
    )
    comment_tab_selectors = (  # 评论标签按钮选择器
        (
            "xpath=//*[self::div or self::span][not(*) and "
            "(normalize-space(.)='评论' or "
            "starts-with(normalize-space(.), '评论('))]"
        ),
        '[data-e2e="feed-comment-icon"]',
        '[data-e2e="comment-icon"]',
        '[aria-label*="评论"]',
        'button:has-text("评论")',
        # 针对旧版图文详情页的兜底选择器。上面的语义化选择器必须放在前面，
        # 因为这个自动生成的类名也会出现在无关的推荐控件上。
        "div.X9EiuBV4:nth-of-type(2)",
    )
    comment_list_selectors = ('[data-e2e="comment-list"]',)  # 评论列表容器选择器
    comment_item_selectors = ('[data-e2e="comment-item"]',)  # 单条评论节点选择器
    comment_submit_selectors = (  # 评论发送按钮候选选择器
        '#comment-input-container .commentInput-right-ct span:has(path[fill="#fff"])',
        "#comment-input-container .commentInput-right-ct > div > span:last-child",
        '.comment-input-container .commentInput-right-ct span:has(path[fill="#fff"])',
        ".comment-input-container .commentInput-right-ct > div > span:last-child",
        ".comment-input-inner-container .commentInput-right-ct > div > span:last-child",
        '#comment-input-container [data-e2e="comment-submit"]',
    )
    comment_failure_messages = (  # 评论失败的页面提示文案
        "发布评论失败",
        "评论发布失败",
        "评论发送失败",
        "操作频繁",
        "请求太频繁",
    )
    comment_success_messages = (  # 评论成功的页面提示文案
        "已发布",
        "评论成功",
        "发布成功",
    )
    comment_risk_messages = (  # 触发风控/安全验证的页面提示文案
        "接收短信验证码",
        "为确保是本人操作抖音账号",
        "使用原设备扫码",
        "安全验证",
    )
    message_editor_selectors = (  # 私信输入框候选选择器
        '[data-e2e="im-input"] [contenteditable="true"]',
        '[data-e2e="message-input"] [contenteditable="true"]',
        'div[contenteditable="true"][data-placeholder*="消息"]',
        'div[contenteditable="true"][aria-label*="消息"]',
        'div[contenteditable="true"][role="textbox"]',
        'textarea[placeholder*="消息"]',
        'textarea[placeholder*="发送"]',
    )
    message_submit_selectors = (  # 私信发送按钮候选选择器
        "svg.e2e-send-msg-btn",
        "svg.messageMsgInputpublishRedBtn",
        ".messageMsgInputpublishRedBtn.e2e-send-msg-btn",
    )
    creator_profile_ready_selectors = (  # 作者主页加载完成的标志元素选择器
        '[data-e2e="user-detail"]',
        '[data-e2e="user-info"]',
    )
    interaction_page_marker = (
        "mediacrawler:interaction"  # 自动化专用标签页标记（用于隔离用户其他标签页）
    )

    def __init__(self, settings: Settings) -> None:
        """初始化执行器。

        参数：
            settings: 全局配置（超时、CDP 目录、远程槽位等）。
        """
        self.settings = settings

    async def execute(
        self,
        *,
        account: object | None = None,
        connection: InteractionBrowserConnection | None = None,
        request: InteractionExecutionRequest,
        step_callback: InteractionStepCallback | None = None,
    ) -> InteractionExecutionResult:
        """执行一次已确认的互动写操作（评论作品 / 回复评论 / 私信作者）。

        通过 CDP 连接账号浏览器、校验登录状态后，按互动类型分发执行；
        全程通过 step_callback 上报步骤进展。

        参数：
            account: 旧版账号对象（与 connection 二选一）。
            connection: 已解析的 CDP 连接参数（与 account 二选一）。
            request: 互动执行请求。
            step_callback: 步骤回调，可为 None。

        返回：
            互动执行结果。

        异常：
            InteractionExecutionError: 浏览器不可用、未登录或执行失败时抛出。
        """
        connection = self._execution_connection(
            account=account,
            connection=connection,
        )
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
                """自动关闭页面弹出的对话框并上报步骤。"""
                try:
                    await dialog.dismiss()
                    await self._trace(
                        step_callback,
                        page,
                        "page_dialog_dismissed",
                        f"已自动关闭网页对话框（{dialog.type}）",
                    )
                except Exception:
                    # 关闭对话框期间页面可能已发生跳转。
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
                    # 页面即使只加载了一部分，也已具备检测登录状态所需的会话信息。
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
                if request.interaction_type == "video_comment":
                    return await self._comment_video(page, request, step_callback)
                if request.interaction_type == "comment_reply":
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

    def _execution_connection(
        self,
        *,
        account: object | None,
        connection: InteractionBrowserConnection | None,
    ) -> InteractionBrowserConnection:
        """兼容历史 account 入参与中立的 connection DTO，解析出 CDP 连接参数。

        account 分支刻意使用结构化属性访问，使集成层不会重新引入
        对 ORM/应用层的依赖。

        异常：
            TypeError: account 与 connection 同时提供或同时缺失时抛出。
        """
        if connection is not None and account is not None:
            raise TypeError("account 和 connection 不能同时提供")
        if connection is not None:
            return connection
        if account is None:
            raise TypeError("必须提供 account 或 connection")
        return self._connection_from_legacy_account(account)

    def _connection_from_legacy_account(
        self, account: object
    ) -> InteractionBrowserConnection:
        """将旧版账号对象解析为 CDP 连接参数。

        local 模式按 profile_key 推导用户数据目录与调试端口；
        remote 模式读取槽位配置（缺省使用全局远程 CDP 地址）。

        异常：
            ValueError: 浏览器模式或槽位配置非法时抛出。
        """
        legacy_account = cast(_LegacyInteractionAccount, account)
        raw_mode = legacy_account.browser_mode
        mode = str(getattr(raw_mode, "value", raw_mode))
        if mode == "local":
            profile_root = (
                self.settings.DOUYIN_CDP_USER_DATA_DIR.resolve().parent / "accounts"
            )
            return InteractionBrowserConnection(
                browser_mode=mode,
                user_data_dir=profile_root / str(legacy_account.profile_key),
                debug_port=self.settings.DOUYIN_CDP_PORT
                + (int(legacy_account.id.int) % 500),
            )
        if mode != "remote":
            raise ValueError(f"{mode!r} is not a valid DouyinBrowserMode")

        remote_slot = legacy_account.remote_slot
        if not remote_slot:
            return InteractionBrowserConnection(
                browser_mode=mode,
                remote_host=self.settings.DOUYIN_REMOTE_CDP_HOST,
                remote_port=self.settings.DOUYIN_REMOTE_CDP_PORT,
            )
        slots = self._legacy_remote_slots()
        slot = slots.get(str(remote_slot))
        if slot is None:
            raise ValueError(f"远程浏览器槽位 {remote_slot} 未配置")
        host = str(slot.get("host") or "").strip()
        try:
            port = int(str(slot.get("port") or 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("远程浏览器槽位端口无效") from exc
        if not host or not 1 <= port <= 65535:
            raise ValueError("远程浏览器槽位主机或端口无效")
        return InteractionBrowserConnection(
            browser_mode=mode,
            remote_host=host,
            remote_port=port,
        )

    def _legacy_remote_slots(self) -> dict[str, dict[str, object]]:
        """解析 DOUYIN_REMOTE_CDP_SLOTS（JSON 对象）为槽位名到连接配置的映射。

        异常：
            ValueError: 配置不是有效 JSON 或格式非法时抛出。
        """
        raw = self.settings.DOUYIN_REMOTE_CDP_SLOTS.strip()
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("DOUYIN_REMOTE_CDP_SLOTS 不是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("DOUYIN_REMOTE_CDP_SLOTS 必须是对象")
        result: dict[str, dict[str, object]] = {}
        for name, value in payload.items():
            if (
                not isinstance(name, str)
                or not name.strip()
                or not isinstance(value, dict)
            ):
                raise ValueError("远程浏览器槽位配置格式无效")
            result[name] = value
        return result

    async def _comment_video(
        self,
        page: Page,
        request: InteractionExecutionRequest,
        step_callback: InteractionStepCallback | None,
    ) -> InteractionExecutionResult:
        """执行「评论作品」：打开视频页、展开评论区并定位输入框后填写并提交。"""
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
        """执行「回复评论」：定位目标评论（必要时用接口核验存在性）、打开回复框并提交。

        异常：
            InteractionExecutionError: 目标评论不存在、无法定位或回复框不可用时抛出。
        """
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
        """在评论列表中按评论 ID 或内容定位目标评论。

        滚动加载评论列表直至找到唯一匹配项，或确认无法找到。

        返回：
            命中的评论节点定位器；未找到返回 None。
        """
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
        """滚动抖音内部的路由级滚动容器（而非 window）。

        返回：
            是否产生了真实滚动位移。
        """
        scroll_anchor = await cls._find_visible(
            page, cls.comment_list_selectors, timeout=250
        )
        if scroll_anchor is None:
            # 旧版详情页只有评论节点、没有独立的评论列表标记；
            # 从可见评论节点出发，脚本仍能找到最近的真实滚动祖先容器。
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
        """确保评论列表处于可见激活状态：必要时点击评论标签并逐方式验证。

        返回：
            评论列表已可见返回 True，否则 False。
        """
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
            if (
                await self._find_visible_comment_surface(page, timeout=1_500)
                is not None
            ):
                return True
        return False

    async def _find_visible_comment_surface(
        self, page: Page, *, timeout: int
    ) -> Locator | None:
        """查找可见的评论列表容器；没有独立列表标记时退化为查找可见评论节点。"""
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
        """通过实时评论接口翻页核验目标评论。

        返回：
            present（目标存在）/ unavailable（已完整翻页确认不存在）/ inconclusive（无法定论）。
        """
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
            # 抖音业务状态码非零、或响应缺少分页契约字段，都不能证明评论已消失；
            # 统一按 inconclusive 处理，保证任务可安全重试。
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

    async def _message_creator(
        self,
        page: Page,
        client: DouyinClient,
        request: InteractionExecutionRequest,
        step_callback: InteractionStepCallback | None,
    ) -> InteractionExecutionResult:
        """执行「私信作者」：解析作品作者、打开作者主页并进入私信会话后发送消息。

        异常：
            InteractionExecutionError: 作者解析失败、私信未开放或会话窗口打不开时抛出。
        """
        detail = await client.get_video(request.aweme_id)
        author = detail.get("author")
        if not isinstance(author, dict):
            raise InteractionExecutionError("target_not_found", "无法从作品中解析作者")
        # 该原始标识刻意只保留在本地内存中，不落盘、不上报。
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
        """打开目标视频页并等待进入可互动状态，失败时按配置次数自动重试。

        异常：
            InteractionExecutionError: 网络加载失败或页面持续未就绪时抛出。
        """
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

    async def _open_comment_panel(
        self, page: Page, *, aweme_id: str | None = None
    ) -> tuple[Page, Locator | None]:
        """在自动化标签页内展开评论区并定位评论输入框。

        返回：
            (输入框所在页面, 输入框定位器)；超时未找到时返回 (原页面, None)。
        """
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
        """筛选允许参与互动的页面，绝不让无关的用户标签页参与互动。"""
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
        """激活控件并验证抖音已切换到可编辑状态。

        require_editor 为 False 时，评论区入口展开（但未出现输入框）也视为
        阶段性成功并返回 None。
        """
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
        """断言页面仍停留在目标视频页，否则抛 page_interrupted 安全终止发送。"""
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
        """填写内容并触发发送，等待抖音接口确认结果。

        参数：
            page: 当前页面。
            editor: 输入框定位器。
            content: 互动文本内容。
            step_callback: 步骤回调。
            response_markers: 响应 URL 匹配标记，缺省使用类默认的私信标记。
            require_explicit_submit: 为 True 时找不到发送按钮则直接失败（不用快捷键兜底）。
            require_comment_confirmation: 为 True 时必须观测到评论发布请求并得到平台确认。
            expected_aweme_id: 期望的作品 ID，发送前校验页面未跳走。
            expected_reply_context: 期望的回复评论卡片，发送前校验回复状态仍有效。
            expected_reply_comment_id: 期望回复的目标评论 ID，用于核验发布请求的绑定关系。
            expected_parent_comment_id: 期望的父评论 ID。

        返回：
            互动执行结果。

        异常：
            InteractionExecutionError: 各阶段失败时抛出，携带 retryable/ambiguous 等处置标记。
        """
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
                # 只有观测到发布请求之后，结果才可能不明确；
                # 若只是 UI 激活失败且内容仍在输入框中，则可以安全重试。
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
        """若提供了步骤回调，则上报一个执行步骤。"""
        if callback is not None:
            await callback(page, step, detail)

    @staticmethod
    async def _safe_json(response: Any) -> dict[str, Any]:
        """尽力解析响应 JSON，解析失败或非对象时返回空字典。"""
        try:
            payload = await response.json()
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _is_comment_publish_response(response: Any) -> bool:
        """判断响应是否来自抖音（新旧版）评论发布接口。"""
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
        """核验评论发布请求确实绑定到了已确认的目标评论（含二级回复场景）。"""
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
        """判断请求是否为评论发布请求（POST 且路径含 comment 与 publish/create/post）。"""
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
        """从平台响应中提取评论 ID（cid/comment_id，兼容多层包裹），未找到返回 None。"""
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
        """从（新旧版包裹的）响应中读取抖音业务状态码，找不到返回 None。"""
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
        """从响应中提取平台错误文案并拼接前缀，未找到时仅返回前缀。"""
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
        """等待输入框内容清空（视为发送完成的 UI 信号），超时返回 False。"""
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
        """等待抖音页面给出 UI 层面的判定（发布失败的响应也可能是 HTTP 200）。

        异常：
            InteractionExecutionError: 命中风控/失败提示，或超时仍无法判定时抛出。
        """
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
    async def _dispatch_comment_submit(page: Page, control: Locator) -> bool:
        """对抖音变换后的评论发送控件执行且仅执行一次激活。

        返回：
            是否观测到了评论发布请求。
        """
        publish_requested = asyncio.Event()

        def observe_request(request: Any) -> None:
            """监听网络请求，命中评论发布接口时置位事件。"""
            if DouyinInteractionExecutor._is_comment_publish_request(request):
                publish_requested.set()

        page.on("request", observe_request)
        try:
            # 抖音经过变换的评论编辑器可能接受组件级点击；而 Playwright 报告
            # 坐标点击成功时，文档实际可能没有收到任何 click 事件。因此先在
            # 组件可见时触发 React 组件点击，再以可信的 CDP 坐标点击兜底。
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

    async def _find_message_editor(
        self,
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
        """查找发送按钮：先按选择器直查，再从输入框向上找「发送/发布」按钮，最后全页兜底。"""
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
