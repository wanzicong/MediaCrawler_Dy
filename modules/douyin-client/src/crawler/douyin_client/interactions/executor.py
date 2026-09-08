# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音互动执行器：经 CDP 浏览器执行评论/回复/私信的流程编排。

本文件只保留编排：连接解析、三类互动流程入口、页面导航与步骤上报；
DOM 基元、目标定位、填写提交与响应解析分别下沉到同目录的协作类。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import cast
from urllib.parse import quote

from crawler.bootstrap.settings import Settings
from crawler.browser import CDPBrowserSession
from crawler.douyin_client.base.errors import InteractionExecutionError
from crawler.douyin_client.http.client import DouyinClient
from crawler.douyin_client.interactions.comment_locator import CommentLocator
from crawler.douyin_client.interactions.models import (
    InteractionBrowserConnection,
    InteractionExecutionRequest,
    InteractionExecutionResult,
    InteractionStepCallback,
    _LegacyInteractionAccount,
)
from crawler.douyin_client.interactions.page_controller import PageController
from crawler.douyin_client.interactions.selectors import (
    COMMENT_EDITOR_SELECTORS,
    COMMENT_ENTRY_SELECTORS,
    COMMENT_TAB_SELECTORS,
    CREATOR_PROFILE_READY_SELECTORS,
    VIDEO_PAGE_READY_SCRIPT,
)
from crawler.douyin_client.interactions.submit_flow import SubmitFlow
from playwright.async_api import Dialog, Locator, Page
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


class DouyinInteractionExecutor:
    """通过已有 CDP 浏览器 profile 执行用户明确确认的写操作（评论/回复/私信）。

    只负责编排：把三种互动流程映射到浏览器会话与页面导航；页面级细节委托给
    ``PageController`` / ``CommentLocator`` / ``SubmitFlow`` / ``ResponseInspector``。
    """

    index_url = "https://www.douyin.com"  # 抖音主站地址
    interaction_page_marker = "mediacrawler:interaction"  # 自动化专用标签页标记（隔离其他标签页）

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
        PageController._assert_video_page(active_page, request.aweme_id)
        await self._trace(
            step_callback,
            active_page,
            "comment_editor_ready",
            "评论区已展开并定位到评论输入框",
        )
        return await SubmitFlow._fill_and_submit(
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
        PageController._assert_video_page(active_page, request.aweme_id)
        if not await CommentLocator._ensure_comment_list_active(active_page):
            raise InteractionExecutionError(
                "comment_list_unavailable",
                "评论标签未能切换到可见评论列表，请稍后重试",
                retryable=True,
            )
        target = await CommentLocator._find_comment_target(active_page, request)
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
        reply_context, editor = await CommentLocator._open_reply_editor(
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
        return await SubmitFlow._fill_and_submit(
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
        profile_ready = await PageController._find_visible(
            page, CREATOR_PROFILE_READY_SELECTORS, timeout=30_000
        )
        message_button = await PageController._find_text_control(
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
        editor_page, editor = await CommentLocator._find_message_editor(
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
        return await SubmitFlow._fill_and_submit(
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
                    VIDEO_PAGE_READY_SCRIPT,
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
            candidates = PageController._interaction_pages(page, aweme_id=aweme_id)
            for candidate in candidates:
                editor = await PageController._find_visible(
                    candidate, COMMENT_EDITOR_SELECTORS, timeout=500
                )
                if editor is not None:
                    return candidate, editor

            now = asyncio.get_running_loop().time()
            for candidate in candidates:
                page_key = id(candidate)
                if page_key not in control_clicked_pages:
                    control = await PageController._find_visible(
                        candidate, COMMENT_TAB_SELECTORS, timeout=400
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
                entry = await PageController._find_visible(
                    candidate, COMMENT_ENTRY_SELECTORS, timeout=400
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
            lambda: PageController._click_control_center(page, control),
        )
        for activate in activators:
            try:
                await activate()
            except Exception:
                continue
            await page.wait_for_timeout(200)
            editor = await PageController._find_visible(
                page, COMMENT_EDITOR_SELECTORS, timeout=500
            )
            if editor is not None:
                return editor
            if not require_editor:
                entry = await PageController._find_visible(
                    page, COMMENT_ENTRY_SELECTORS, timeout=300
                )
                if entry is not None:
                    return None
        return None

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
