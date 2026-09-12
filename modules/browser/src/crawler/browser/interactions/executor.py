# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音互动执行器：经 CDP 浏览器执行评论/回复/私信的流程编排。

本文件只保留编排：会话建立与三条流程；页面导航、评论区/私信面板开启、目标核验、
DOM 定位、填写提交与响应解析分别下沉到同目录的 ``navigation`` / ``panel`` /
``verification`` / ``comment_locator`` / ``page_controller`` / ``submit_flow`` /
``response_inspector``。连接参数由 ``BrowserSessionSpec`` 承载（旧 ``account=`` 入参与
槽位 JSON 解析已删除，business 的 ``resolve_account_browser`` 是唯一真源）；抖音读写
能力全部经注入的 ``InteractionApiFactory`` 获得，本模块不 import ``crawler.douyin_client``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from crawler.bootstrap.settings import Settings
from crawler.browser.errors import CDPConnectionError, InteractionExecutionError
from crawler.browser.interactions import navigation, panel, verification
from crawler.browser.interactions.comment_locator import CommentLocator
from crawler.browser.interactions.models import (
    InteractionExecutionRequest,
    InteractionExecutionResult,
    InteractionStepCallback,
)
from crawler.browser.interactions.page_controller import PageController
from crawler.browser.interactions.reporting import report_step
from crawler.browser.interactions.submit_flow import SubmitFlow
from crawler.browser.page import primitives as dom
from crawler.browser.session.manager import CDPBrowserSession
from playwright.async_api import Dialog, Page

if TYPE_CHECKING:  # 门面协议与连接参数只作类型注解，运行时 import 会构成包环。
    from crawler.browser.facade.protocols import InteractionApi, InteractionApiFactory
    from crawler.browser.facade.spec import BrowserSessionSpec


class DouyinInteractionExecutor:
    """通过 CDP 浏览器执行用户明确确认的写操作（评论/回复/私信）。

    只负责编排：连接参数来自 ``BrowserSessionSpec``，登录态与抖音读写能力来自
    注入的 ``InteractionApiFactory``；页面级细节委托给各协作模块。
    """

    interaction_page_marker = "mediacrawler:interaction"  # 自动化专用标签页标记

    def __init__(self, settings: Settings) -> None:
        """初始化执行器（settings 提供超时、CDP 目录与导航重试次数等配置）。"""
        self.settings = settings

    async def execute(
        self,
        *,
        spec: BrowserSessionSpec,
        request: InteractionExecutionRequest,
        api_factory: InteractionApiFactory,
        step_callback: InteractionStepCallback | None = None,
    ) -> InteractionExecutionResult:
        """执行一次已确认的互动写操作（评论作品 / 回复评论 / 私信作者）。

        ``api_factory`` 只在主站导航成功之后调用：适配器在未导航的页面上取到的
        cookie/UA 是空值，会把「登录有效」静默判成「未登录」。

        异常：
            InteractionExecutionError: 浏览器不可用、未登录或执行失败时抛出。
        """
        browser = CDPBrowserSession.from_spec(
            self.settings,
            spec,
            reuse_existing_page=False,
            close_page_on_exit=False,
            page_marker=self.interaction_page_marker,
        )
        async with browser:
            page = self._interaction_page(browser)
            await page.bring_to_front()

            async def on_page_dialog_dismissed(dialog: Dialog) -> None:
                """对话框被自动关闭后上报步骤（异常由 auto_dismiss_dialogs 吞掉）。"""
                await report_step(
                    step_callback,
                    page,
                    "page_dialog_dismissed",
                    f"已自动关闭网页对话框（{dialog.type}）",
                )

            dialog_handler = dom.auto_dismiss_dialogs(
                page, on_dismiss=on_page_dialog_dismissed
            )
            api: InteractionApi | None = None
            try:
                await navigation.open_index(page)
                # 显式断言「导航先于建连」：适配器在未导航的页面上取到的 cookie/UA
                # 会是空值并被静默判为未登录，这里把该失败模式变成可观测的错误。
                self._assert_index_navigated(page)
                await report_step(
                    step_callback,
                    page,
                    "browser_connected",
                    (
                        "已通过 CDP 连接账号浏览器并打开自动化专用标签页；"
                        f"已隔离 {browser.unrelated_page_count} 个其他标签页"
                    ),
                )
                api = await api_factory(browser.browser_page)
                if not await api.verify_login(require_self_profile=True):
                    raise InteractionExecutionError(
                        "login_required",
                        "所选账号登录已失效，请先在账号管理中重新登录",
                        affects_account_health=True,
                    )
                await api.refresh_cookies()
                await report_step(
                    step_callback, page, "login_verified", "账号登录状态验证通过"
                )
                if request.interaction_type == "video_comment":
                    return await self._comment_video(page, request, step_callback)
                if request.interaction_type == "comment_reply":
                    return await self._reply_to_comment(
                        page, api, request, step_callback
                    )
                return await self._message_creator(page, api, request, step_callback)
            except Exception as exc:
                detail = (
                    f"执行失败：{exc}"
                    if isinstance(exc, InteractionExecutionError)
                    else "浏览器执行发生异常，已保留最后页面现场"
                )
                await report_step(step_callback, page, "execution_failed", detail)
                raise
            finally:
                page.remove_listener("dialog", dialog_handler)
                if api is not None:
                    await api.aclose()

    @staticmethod
    def _interaction_page(browser: CDPBrowserSession) -> Page:
        """取出本次互动专用的自动化页面，把「会话未就绪」翻译成互动错误。"""
        try:
            return browser.page_handle.page
        except CDPConnectionError as exc:
            raise InteractionExecutionError(
                "browser_unavailable",
                "CDP 浏览器页面不可用",
                retryable=True,
                affects_account_health=True,
            ) from exc

    @staticmethod
    def _assert_index_navigated(page: Page) -> None:
        """断言抖音主站已完成导航；未完成时中止，避免把空 cookie 误判为未登录。"""
        if not page.url.startswith(("http://", "https://")):
            raise InteractionExecutionError(
                "browser_unavailable",
                "抖音主站未完成导航，已中止互动以避免误判登录状态",
                retryable=True,
            )

    async def _comment_video(
        self,
        page: Page,
        request: InteractionExecutionRequest,
        step_callback: InteractionStepCallback | None,
    ) -> InteractionExecutionResult:
        """「评论作品」：打开视频页、展开评论区定位输入框后填写并提交。"""
        await navigation.open_video(page, request.aweme_id, settings=self.settings)
        await report_step(step_callback, page, "video_opened", "已打开目标视频页面")
        active_page, editor = await panel.open_comment_panel(
            page, aweme_id=request.aweme_id, settings=self.settings
        )
        if editor is None:
            raise InteractionExecutionError(
                "comment_not_available",
                "当前作品没有可用的评论输入框，可能已关闭评论",
            )
        PageController.assert_video_page(active_page, request.aweme_id)
        await report_step(
            step_callback,
            active_page,
            "comment_editor_ready",
            "评论区已展开并定位到评论输入框",
        )
        return await SubmitFlow.fill_and_submit(
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
        api: InteractionApi,
        request: InteractionExecutionRequest,
        step_callback: InteractionStepCallback | None,
    ) -> InteractionExecutionResult:
        """「回复评论」：定位目标评论（必要时经接口核验存在性）、打开回复框并提交。"""
        if not request.target_comment_content:
            raise InteractionExecutionError(
                "target_not_found", "目标评论不存在或内容不可用"
            )
        await navigation.open_video(page, request.aweme_id, settings=self.settings)
        await report_step(step_callback, page, "video_opened", "已打开目标视频页面")
        active_page, comment_editor = await panel.open_comment_panel(
            page, aweme_id=request.aweme_id, settings=self.settings
        )
        if comment_editor is None:
            raise InteractionExecutionError(
                "comment_not_available",
                "评论区已完成加载，但当前作品没有可用的互动入口",
            )
        PageController.assert_video_page(active_page, request.aweme_id)
        if not await CommentLocator.ensure_comment_list_active(active_page):
            raise InteractionExecutionError(
                "comment_list_unavailable",
                "评论标签未能切换到可见评论列表，请稍后重试",
                retryable=True,
            )
        target = await CommentLocator.find_comment_target(active_page, request)
        if target is None:
            # 页面未定位到目标：先经实时接口核验，才能区分「不存在」与「页面没加载出来」。
            await verification.lookup_target_comment(
                api, request, page=active_page, step_callback=step_callback
            )
            await report_step(
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
        await report_step(
            step_callback, active_page, "reply_target_found", "已在评论区定位到目标评论"
        )
        reply_context, editor = await CommentLocator.open_reply_editor(
            active_page, target, request
        )
        if editor is None or reply_context is None:
            raise InteractionExecutionError(
                "reply_not_available",
                "目标评论未能进入明确的回复状态，已停止发送，请重试",
                retryable=True,
            )
        await report_step(
            step_callback,
            active_page,
            "reply_editor_ready",
            "已打开目标评论的回复输入框",
        )
        return await SubmitFlow.fill_and_submit(
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

    async def _message_creator(
        self,
        page: Page,
        api: InteractionApi,
        request: InteractionExecutionRequest,
        step_callback: InteractionStepCallback | None,
    ) -> InteractionExecutionResult:
        """「私信作者」：解析作品作者、打开作者主页并进入私信会话后发送消息。"""
        # 该原始标识刻意只保留在本地内存中，不落盘、不上报。
        sec_uid = await api.resolve_video_author_sec_uid(request.aweme_id)
        if not sec_uid:
            raise InteractionExecutionError(
                "target_not_found", "无法从作品中解析出可私信的作者"
            )
        await navigation.open_creator_profile(page, sec_uid)
        await report_step(
            step_callback, page, "creator_profile_opened", "已打开目标视频作者主页"
        )
        editor_page, editor = await panel.open_message_panel(
            page, step_callback=step_callback
        )
        return await SubmitFlow.fill_and_submit(
            editor_page,
            editor,
            request.content,
            step_callback,
            require_explicit_submit=True,
        )


__all__ = ["DouyinInteractionExecutor"]
