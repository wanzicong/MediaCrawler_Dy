# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""互动内容填写与提交确认（SubmitFlow）。

负责把内容写入输入框、触发发送并等待抖音的明确确认；组合 ``PageController``
（发送控件/点击/清空判定）、``CommentLocator``（回复上下文核验）与
``ResponseInspector``（发布响应解析）。不感知浏览器连接等编排细节。
方法已全部去掉下划线：它们是本包与 ``tests/browser/`` 的协作面，不是私有实现。
"""

from __future__ import annotations

import asyncio
from typing import cast

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

# 「本次没有发出、且尚未从平台侧拿到任何判定」的错误码。
#
# 这类失败的 code 是我们按页面条件自己归的类，而同一时刻页面上可能正显示着比内部
# 归类更权威的平台判定：验证蒙层会拦掉点击、限流会让按钮点不动，于是「控件点不动」
# 与「点了没反应」的真实原因恰恰是风控或平台限流。因此它们必须在抛出前再查一次
# 页面文案（``page_message_verdict``）：命中风控要按风控计入账号健康，否则业务侧
# ``account_healthy = not exc.affects_account_health`` 会被判为 True，
# ``release_account(success=True)`` 就会把 failure_streak 归零、清空 last_error，
# 连续被风控也永远攒不到 unhealthy/blocked 的阈值。
#
# 归类以 **code** 为单位、由本集合与匹配的排除表共同穷尽（新增错误码若两处都没有，
# tests/browser/sites/douyin/test_submit_flow.py 的 AST 穷尽性用例会红灯）。逐类说明：
#   * risk_controlled / platform_rejected：已经是平台对本次请求的直接判定（HTTP 状态码
#     或平台业务状态码），页面文案只是同一判定的另一种呈现；再查一遍带不来新信息，
#     反而可能把「平台已明确拒绝」覆盖成另一类结论。二者都已按平台语义设置好
#     affects_account_health，不查也不会漏掉账号健康信号。
#   * reply_target_mismatch：要表达的是「发布请求绑定错了评论」，这只有请求本身能证明，
#     页面文案提供不了；该分支已标 ambiguous 交人工核对，不能改判成风控/拒绝。
#   * ambiguous_result：发布请求已经观测到，结果本身不明确（超时后无信号、内容仍残留），
#     构造点已自行决定是否计入账号健康；它不属于「未发出」，页面文案无法给出更确定的结论。
#   * 该集合按 code 归类，因此 ``PageController.dispatch_comment_submit`` 内部构造的
#     同名 submit_not_activated 一并覆盖，无需重复声明。
PAGE_VERDICT_CODES: frozenset[str] = frozenset(
    {
        # 发送控件存在但已脱离可点击状态：本次连点击都没有发出。
        "submit_not_activated",
        # 三种激活方式都执行完成，却没有观测到任何发布请求。
        "submit_not_triggered",
    }
)


async def page_message_verdict(page: Page) -> InteractionExecutionError | None:
    """把页面上可见的风控/失败提示转成对应异常，没有提示时返回 ``None``。

    页面文案是抖音对本次发送最直接的判定，优先于任何内部异常类型：命中风控必须
    计入账号健康，命中失败提示按平台拒绝处理。调用方只在「要求平台确认」的模式下
    使用它——该模式下页面文案才与本次发送一一对应。

    本函数的读数是**防御式**的：``dom.visible_page_message`` 自身吞掉页面/浏览器
    不可用的异常（``await matches.count()`` / ``is_visible()`` 都在它内部的 try 里，
    失败即 ``continue`` 并最终返回 ``None``），因此本函数在页面不可用时返回 ``None``
    而不是抛异常；调用方据此沿用原有归类。保护在 primitives 那一层，这里再包一层
    只会把本区域内未来引入的真实异常一并吞成一条 warning，排障时看不见。
    """
    risk_message = await dom.visible_page_message(page, COMMENT_RISK_MESSAGES)
    if risk_message:
        return InteractionExecutionError(
            "risk_controlled",
            "抖音要求完成短信或扫码安全验证，请先在对应账号浏览器中完成验证",
            affects_account_health=True,
        )
    failure_message = await dom.visible_page_message(page, COMMENT_FAILURE_MESSAGES)
    if failure_message:
        return InteractionExecutionError(
            "platform_rejected",
            f"抖音页面提示：{failure_message}",
            affects_account_health=True,
        )
    return None


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
        if submit is None and (require_explicit_submit or require_comment_confirmation):
            # 发送控件是「要求显式提交」与「要求平台确认」两种模式的硬前置条件：
            # 页面上没有发送入口是确定性的页面缺失，既不是网络故障，也不说明账号
            # 不健康，因此必须在 try 之外以类型化异常抛出。若改为 assert，它会被
            # 下面的兜底 except 吞掉并误标成 network_error / 影响账号健康。
            raise InteractionExecutionError(
                "submit_not_available",
                "互动内容已填写，但没有找到可点击的发送按钮，未执行发送",
                retryable=True,
            )
        markers = response_markers or MESSAGE_RESPONSE_MARKERS
        submitted = False
        try:
            if require_comment_confirmation:
                # 上面的前置检查已保证该模式下发送控件存在；这里显式声明该不变量
                # （mypy 无法从 bool 参数推断出联合类型中非 None 的那一支）。
                submit_control = cast(Locator, submit)
                # 只有观测到发布请求之后，结果才可能不明确；
                # 若只是 UI 激活失败且内容仍在输入框中，则可以安全重试。
                async with page.expect_response(
                    lambda response: ResponseInspector.is_comment_publish_response(
                        response
                    ),
                    timeout=12_000,
                ) as response_info:
                    # 控件可能在「查找到」与「点击」之间脱离 DOM（评论区是虚拟列表，
                    # 滚动会重建节点）。这一步失败说明本次连点击都没有发出，是确定性
                    # 页面条件，必须类型化抛出，不能被下面的兜底 except 标成
                    # network_error 并牵连账号健康。
                    try:
                        await submit_control.scroll_into_view_if_needed()
                    except Exception as exc:
                        raise InteractionExecutionError(
                            "submit_not_activated",
                            "发送控件存在，但已脱离可点击状态，已确认未发送，请重试",
                            retryable=True,
                        ) from exc
                    submitted = await PageController.dispatch_comment_submit(
                        page, submit_control
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
                # HTTP 状态是平台对**本次请求**的权威判定，与请求绑定到哪条评论无关，
                # 因此必须先判：否则 403/429 撞上「未绑定到预期评论」时会被归类成
                # reply_target_mismatch（ambiguous 且不计账号健康），风控信号丢失一次。
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
                    # 滚动先于点击：滚动失败即证明本次点击没有发出，因此可以
                    # 明确判为「未发送」（可重试、非歧义、不影响账号健康），而
                    # 不是让兜底 except 把 submitted 当成「可能已发送」。
                    # 点击本身的失败仍按原语义交给兜底分支：点击可能已经落点，
                    # 结果确实不明确。
                    try:
                        await submit.scroll_into_view_if_needed()
                    except Exception as exc:
                        raise InteractionExecutionError(
                            "submit_not_activated",
                            "发送控件存在，但已脱离可点击状态，已确认未发送，请重试",
                            retryable=True,
                        ) from exc
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
                verdict = await page_message_verdict(page)
                if verdict is not None:
                    raise verdict from exc
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

        except InteractionExecutionError as exc:
            # 「未发出、且尚未观测到平台判定」的失败（见 PAGE_VERDICT_CODES）也可能
            # 正是因为页面上弹出了风控或失败提示（验证蒙层会拦截点击、限流会让按钮
            # 点不动）。页面文案比内部异常类型更贴近事实，因此先按文案判定：命中风控
            # 必须计入账号健康，不能因为异常已经是类型化的页面条件就被降级。文案缺失
            # 时才保留原有归类。判定绑在「这类失败」上而不是绑在某个具体 code 上，
            # 是为了让下一个新增的同类错误码自动获得同一条页面判定，而不是靠人记得补。
            if exc.code in PAGE_VERDICT_CODES and require_comment_confirmation:
                verdict = await page_message_verdict(page)
                if verdict is not None:
                    raise verdict from exc
            raise
        except Exception as exc:
            # 账号健康标记与超时分支（``affects_account_health=not submitted``，即上面
            # 的 PlaywrightTimeoutError 分支）对齐，不再恒定取 True：
            #   * submitted=False：本次发送被未知异常挡在门外（浏览器/命令通道断开等），
            #     结果未知，保守计入账号健康——与 browser_unavailable / network_error
            #     的既有取向一致，这一支**刻意**保持 True。
            #   * submitted=True：请求已经观测到，异常发生在提交之后（解析响应、读取
            #     页面、上报步骤回调……），既可能是我们自己的缺陷或业务侧故障（数据库
            #     写入失败、回调抛错），也可能是平台风控。恒定 True 会让一次提交后端的
            #     自家故障在连续 3 次后把好账号置为 unhealthy、此后拒绝其一切互动
            #     （release_account 的 failure_streak>=3 分支），因此按「提交后结果不明」
            #     处理：不计账号健康，交由 needs_review（ambiguous）走人工核对。
            #
            # 平台判定没有被这条分支削弱：本次请求的直接判定走 HTTP 403/429（计入账号
            # 健康）或响应体业务状态码（platform_rejected），页面文案则由超时分支在
            # ``require_comment_confirmation`` 时调 ``page_message_verdict`` 兜底。
            #
            # ⚠ 但私信模式（``require_comment_confirmation=False``，executor 的私信路径
            # 就是这么调的）下**没有页面文案通道**：``page_message_verdict`` 的两个调用点
            # 都以该 flag 为前置。私信被风控时页面只弹文案、不抛异常，只能靠 403/429
            # 落地。这是既有缺口（超时分支是同一套 ``not submitted`` 取向，同样拿不到
            # 页面信号），本分支与它同构、没有额外削弱保护；缺口本身是有意设计，见
            # docs/refactor/03-open-issues.md 的 OI-7。
            raise InteractionExecutionError(
                "ambiguous_result" if submitted else "network_error",
                (
                    "发送结果不明确，请人工检查后再决定是否重试"
                    if submitted
                    else "发送前发生网络或页面错误"
                ),
                ambiguous=submitted,
                retryable=not submitted,
                affects_account_health=not submitted,
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


__all__ = ["PAGE_VERDICT_CODES", "SubmitFlow", "page_message_verdict"]
