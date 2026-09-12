# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""互动内容填写与提交确认（SubmitFlow）。

负责把内容写入输入框、触发发送并等待抖音的明确确认；组合 ``PageController``
（发送控件/点击/清空判定）、``CommentLocator``（回复上下文核验）与
``ResponseInspector``（发布响应解析）。不感知浏览器连接等编排细节。
方法已全部去掉下划线：它们是本包与 ``tests/browser/`` 的协作面，不是私有实现。
"""

from __future__ import annotations

import asyncio

from crawler.browser.errors import InteractionExecutionError
from crawler.browser.interactions.comment_locator import CommentLocator
from crawler.browser.interactions.models import (
    InteractionExecutionResult,
    InteractionStepCallback,
)
from crawler.browser.interactions.page_controller import PageController
from crawler.browser.interactions.reporting import report_step
from crawler.browser.interactions.response_inspector import ResponseInspector
from crawler.browser.interactions.selectors import (
    COMMENT_FAILURE_MESSAGES,
    COMMENT_RISK_MESSAGES,
    COMMENT_SUCCESS_MESSAGES,
    MESSAGE_RESPONSE_MARKERS,
)
from crawler.browser.page import primitives as dom
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


class SubmitFlow:
    """互动内容填写与提交确认。

    两个入口方法（``fill_and_submit`` / ``wait_comment_submission``）为类方法，
    通过协作类组合发送流程；不持有浏览器状态。
    """

    @classmethod
    async def fill_and_submit(
        cls,
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
            response_markers: 响应 URL 匹配标记，缺省使用私信标记。
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
        await report_step(
            step_callback,
            page,
            "content_filled",
            "互动内容已填写，准备触发发送",
        )
        if expected_aweme_id:
            PageController.assert_video_page(page, expected_aweme_id)
        if (
            expected_reply_context is not None
            and not await CommentLocator.reply_context_is_active(
                expected_reply_context, expected_reply_comment_id
            )
        ):
            raise InteractionExecutionError(
                "reply_context_lost",
                "回复目标状态在发送前丢失，已停止发送，请重试",
                retryable=True,
            )

        submit = await PageController.find_submit_control(page, editor)
        if require_explicit_submit and submit is None:
            raise InteractionExecutionError(
                "submit_not_available",
                "互动内容已填写，但没有找到可点击的发送按钮，未执行发送",
                retryable=True,
            )
        markers = response_markers or MESSAGE_RESPONSE_MARKERS
        submitted = False
        try:
            if require_comment_confirmation:
                # 只有观测到发布请求之后，结果才可能不明确；
                # 若只是 UI 激活失败且内容仍在输入框中，则可以安全重试。
                assert submit is not None
                async with page.expect_response(
                    lambda response: ResponseInspector.is_comment_publish_response(
                        response
                    ),
                    timeout=12_000,
                ) as response_info:
                    await submit.scroll_into_view_if_needed()
                    submitted = await PageController.dispatch_comment_submit(
                        page, submit
                    )
                    if not submitted:
                        raise InteractionExecutionError(
                            "submit_not_triggered",
                            "发送按钮没有触发评论发布请求，内容仍在输入框中，确认未发送",
                            retryable=True,
                        )
                    await report_step(
                        step_callback,
                        page,
                        "submit_triggered",
                        "已触发发送，正在等待抖音确认",
                    )
                response = await response_info.value
                if (
                    expected_reply_comment_id
                    and not ResponseInspector.request_targets_reply(
                        response.request,
                        target_comment_id=expected_reply_comment_id,
                        parent_comment_id=expected_parent_comment_id,
                    )
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
                payload = await ResponseInspector.safe_json(response)
                status_code = ResponseInspector.platform_status_code(payload)
                if status_code not in (None, 0, "0"):
                    raise InteractionExecutionError(
                        "platform_rejected",
                        ResponseInspector.platform_error_message(
                            payload, prefix="抖音未接受评论请求"
                        ),
                        affects_account_health=True,
                    )
                platform_id = ResponseInspector.result_id(payload)
                if status_code in (0, "0") or platform_id is not None:
                    await report_step(
                        step_callback,
                        page,
                        "platform_accepted",
                        "抖音评论发布接口已返回成功",
                    )
                    return InteractionExecutionResult(platform_id=platform_id)
                await cls.wait_comment_submission(page, request_content=content)
                if not await dom.wait_editor_empty(editor):
                    raise InteractionExecutionError(
                        "ambiguous_result",
                        "已经触发评论发布请求，但评论仍停留在输入框中，不能判定成功",
                        ambiguous=True,
                    )
                await report_step(
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
                await report_step(
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
            payload = await ResponseInspector.safe_json(response)
            status_code = ResponseInspector.platform_status_code(payload)
            if status_code not in (None, 0, "0"):
                raise InteractionExecutionError(
                    "platform_rejected",
                    ResponseInspector.platform_error_message(
                        payload, prefix="抖音未接受该互动请求"
                    ),
                )
            platform_id = ResponseInspector.result_id(payload)
            await report_step(
                step_callback,
                page,
                "platform_accepted",
                "抖音已接受互动请求",
            )
            return InteractionExecutionResult(platform_id=platform_id)
        except PlaywrightTimeoutError as exc:
            if require_comment_confirmation:
                risk_message = await dom.visible_page_message(
                    page, COMMENT_RISK_MESSAGES
                )
                if risk_message:
                    raise InteractionExecutionError(
                        "risk_controlled",
                        "抖音要求完成短信或扫码安全验证，请先在对应账号浏览器中完成验证",
                        affects_account_health=True,
                    ) from exc
                failure_message = await dom.visible_page_message(
                    page, COMMENT_FAILURE_MESSAGES
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
                and await dom.editor_is_empty(editor)
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

    @classmethod
    async def wait_comment_submission(
        cls,
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
            success_message = await dom.visible_page_message(
                page, COMMENT_SUCCESS_MESSAGES
            )
            if success_message:
                return
            risk_message = await dom.visible_page_message(page, COMMENT_RISK_MESSAGES)
            if risk_message:
                raise InteractionExecutionError(
                    "risk_controlled",
                    "抖音要求完成短信或扫码安全验证，请先在对应账号浏览器中完成验证",
                    affects_account_health=True,
                )
            failure_message = await dom.visible_page_message(
                page, COMMENT_FAILURE_MESSAGES
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


__all__ = ["SubmitFlow"]
