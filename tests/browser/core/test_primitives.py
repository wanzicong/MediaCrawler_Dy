"""browser 模块通用 DOM 基元的直测。

这些基元与站点无关。此处只覆盖各函数自身的边界行为（坐标点击、输入框判空、
可见文案探测、滚动兜底、evaluate 重试与对话框自动关闭），不带任何抖音语义。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from crawler.browser import BrowserAutomationError
from crawler.browser.page import primitives
from playwright.async_api import Error as PlaywrightError


def test_click_control_center_clicks_geometry_center() -> None:
    """验证坐标点击落在控件包围盒的中心。"""
    control = AsyncMock()
    control.bounding_box.return_value = {"x": 10, "y": 20, "width": 100, "height": 50}
    page = MagicMock()
    page.mouse.click = AsyncMock()

    asyncio.run(primitives.click_control_center(page, control))

    control.scroll_into_view_if_needed.assert_awaited_once()
    page.mouse.click.assert_awaited_once_with(60, 45)


def test_click_control_center_raises_when_no_bounding_box() -> None:
    """验证控件不可见/无包围盒时抛出中立的 browser 异常。"""
    control = AsyncMock()
    control.bounding_box.return_value = None
    page = MagicMock()

    with pytest.raises(BrowserAutomationError, match="no bounding box"):
        asyncio.run(primitives.click_control_center(page, control))
    page.mouse.click.assert_not_called()


def test_editor_is_empty_falls_back_to_text_content() -> None:
    """验证 contenteditable（input_value 抛错）元素按文本内容判空。"""
    editor = AsyncMock()
    editor.input_value.side_effect = PlaywrightError("not an input")
    editor.text_content.return_value = "   "

    assert asyncio.run(primitives.editor_is_empty(editor)) is True
    editor.text_content.assert_awaited()


def test_editor_is_empty_reports_nonempty_and_empty_editor() -> None:
    """验证普通 input 输入框按 value 判空。"""
    filled = AsyncMock()
    filled.input_value.return_value = "评论内容"
    empty = AsyncMock()
    empty.input_value.return_value = ""

    assert asyncio.run(primitives.editor_is_empty(filled)) is False
    assert asyncio.run(primitives.editor_is_empty(empty)) is True


def test_editor_is_empty_when_editor_missing() -> None:
    """验证编辑器节点消失视为空（避免误判未发送）。"""
    editor = AsyncMock()
    editor.count.return_value = 0

    assert asyncio.run(primitives.editor_is_empty(editor)) is True


def test_wait_editor_empty_polls_until_clear() -> None:
    """验证等待输入框清空会持续轮询直到命中空态。"""
    editor = MagicMock()
    editor.page = MagicMock()
    editor.page.wait_for_timeout = AsyncMock()
    empty = AsyncMock(side_effect=[False, True])
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(primitives, "editor_is_empty", empty)
    try:
        result = asyncio.run(primitives.wait_editor_empty(editor, timeout_ms=1_000))
    finally:
        monkeypatch.undo()

    assert result is True
    assert empty.await_count == 2


def test_visible_page_message_returns_first_visible_match() -> None:
    """验证只命中真正可见的提示文案，隐藏的重复文案被跳过。"""
    page = MagicMock()
    hidden = AsyncMock()
    hidden.is_visible.return_value = False
    visible = AsyncMock()
    visible.is_visible.return_value = True

    def matches_for(message: str, **_kwargs: object) -> MagicMock:
        matches = MagicMock()
        matches.count = AsyncMock(return_value=1)
        matches.nth.return_value = hidden if message == "发送失败" else visible
        return matches

    page.get_by_text.side_effect = matches_for

    result = asyncio.run(
        primitives.visible_page_message(page, ("发送失败", "评论已发送"))
    )

    assert result == "评论已发送"


def test_scroll_container_to_bottom_uses_anchor_evaluate() -> None:
    """验证优先用锚点祖先链的 JS 滚动（返回真实位移）。"""
    page = MagicMock()
    anchor = AsyncMock()
    anchor.evaluate.return_value = True

    result = asyncio.run(primitives.scroll_container_to_bottom(page, anchor))

    assert result is True
    assert "let node = element" in anchor.evaluate.await_args.args[0]
    page.mouse.wheel.assert_not_called()


def test_scroll_container_to_bottom_wheel_fallback_on_failure() -> None:
    """验证 evaluate 抛错时退化为鼠标滚轮并仍视为产生位移。"""
    page = MagicMock()
    page.mouse.wheel = AsyncMock()
    anchor = AsyncMock()
    anchor.evaluate.side_effect = PlaywrightError("Execution context was destroyed")

    result = asyncio.run(primitives.scroll_container_to_bottom(page, anchor))

    assert result is True
    page.mouse.wheel.assert_awaited_once_with(0, 1_000)


def test_scroll_container_to_bottom_wheel_fallback_without_anchor() -> None:
    """验证无锚点（找不到滚动容器）时直接对窗口滚轮滚动。"""
    page = MagicMock()
    page.mouse.wheel = AsyncMock()

    result = asyncio.run(primitives.scroll_container_to_bottom(page, None))

    assert result is True
    page.mouse.wheel.assert_awaited_once_with(0, 1_000)


def test_evaluate_stable_succeeds_on_first_try() -> None:
    """验证普通页面 evaluate 直接返回结果。"""
    page = MagicMock()
    page.evaluate = AsyncMock(return_value="stable")

    assert asyncio.run(primitives.evaluate_stable(page, "1 + 1")) == "stable"
    page.evaluate.assert_awaited_once_with("1 + 1")


def test_evaluate_stable_reraises_unrelated_error() -> None:
    """验证非导航竞态的错误立即抛出，不做无谓重试。"""
    page = AsyncMock()
    page.evaluate.side_effect = PlaywrightError("some other failure")

    with pytest.raises(PlaywrightError, match="some other failure"):
        asyncio.run(primitives.evaluate_stable(page, "1 + 1"))
    page.evaluate.assert_awaited_once()


def test_auto_dismiss_dialogs_registers_and_returns_handler() -> None:
    """验证注册对话框自动关闭并返回 handler 供调用方移除监听。"""
    page = MagicMock()
    dialog = AsyncMock()

    handler = primitives.auto_dismiss_dialogs(page)
    asyncio.run(handler(dialog))

    dialog.dismiss.assert_awaited_once()
    page.on.assert_called_once_with("dialog", handler)


def test_auto_dismiss_dialogs_runs_on_dismiss_callback() -> None:
    """验证对话框关闭后触发 on_dismiss 回调。"""
    page = MagicMock()
    dialog = AsyncMock()
    on_dismiss = AsyncMock()

    handler = primitives.auto_dismiss_dialogs(page, on_dismiss=on_dismiss)
    asyncio.run(handler(dialog))

    dialog.dismiss.assert_awaited_once()
    on_dismiss.assert_awaited_once_with(dialog)


def test_auto_dismiss_dialogs_swallows_handler_errors() -> None:
    """验证 dismiss 或 on_dismiss 抛错都被吞掉，不影响主流程。"""
    page = MagicMock()
    dialog = AsyncMock()
    dialog.dismiss.side_effect = PlaywrightError("page navigated")
    on_dismiss = AsyncMock(side_effect=ValueError("boom"))

    handler = primitives.auto_dismiss_dialogs(page, on_dismiss=on_dismiss)
    asyncio.run(handler(dialog))

    dialog.dismiss.assert_awaited_once()
    on_dismiss.assert_not_called()
