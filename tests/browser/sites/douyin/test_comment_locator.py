"""评论目标定位与互动面板开启测试（CommentLocator + interactions.panel）。

覆盖评论列表激活/滚动、按评论 ID 或文本定位目标评论、回复编辑器与私信会话开启；
通用 DOM 基元来自 ``crawler.browser.page.primitives``，故相关 monkeypatch 指向它。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from crawler.bootstrap.settings import settings
from crawler.browser.errors import InteractionExecutionError
from crawler.browser.interactions import panel
from crawler.browser.interactions.comment_locator import CommentLocator
from crawler.browser.interactions.models import InteractionExecutionRequest
from crawler.browser.interactions.selectors import (
    COMMENT_EDITOR_SELECTORS,
    COMMENT_ITEM_SELECTORS,
    COMMENT_SUBMIT_SELECTORS,
    COMMENT_TAB_SELECTORS,
)
from crawler.browser.page import primitives as dom


def _reply_request(**overrides: object) -> InteractionExecutionRequest:
    """构造一个回复评论请求。"""
    payload: dict[str, object] = {
        "interaction_type": "comment_reply",
        "aweme_id": "123",
        "content": "回复",
        "target_comment_id": "456",
        "target_comment_content": "目标评论",
        "target_parent_comment_id": None,
    }
    payload.update(overrides)
    return InteractionExecutionRequest(
        interaction_type=str(payload["interaction_type"]),
        aweme_id=str(payload["aweme_id"]),
        content=str(payload["content"]),
        target_comment_id=payload["target_comment_id"],  # type: ignore[arg-type]
        target_comment_content=payload["target_comment_content"],  # type: ignore[arg-type]
        target_parent_comment_id=payload["target_parent_comment_id"],  # type: ignore[arg-type]
    )


# ---- panel：评论区展开 ----
#
# 本文件同时承载 interactions.panel 的单测（评论区/私信会话面板开启），
# 因为这两个面板都属于「抖音互动面」的定位与展开，测试用例不再新建文件。


def test_open_comment_panel_expands_real_douyin_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证打开评论面板时能通过真实抖音占位容器选择器激活出编辑器。"""
    entry = AsyncMock()
    editor = AsyncMock()
    find_visible = AsyncMock(side_effect=[None, None, entry])
    monkeypatch.setattr(dom, "find_visible", find_visible)
    activate = AsyncMock(return_value=editor)
    monkeypatch.setattr(
        "crawler.browser.interactions.panel.activate_comment_control", activate
    )

    page = MagicMock()
    page.context.pages = [page]
    page.is_closed.return_value = False
    page.url = "https://www.douyin.com/note/123"
    page.wait_for_timeout = AsyncMock()
    active_page, result = asyncio.run(
        panel.open_comment_panel(page, aweme_id="123", settings=settings)
    )

    assert active_page is page
    assert result is editor
    activate.assert_awaited_once_with(page, entry, require_editor=True)
    assert find_visible.await_args_list[2].args[1] == (
        ".comment-input-inner-container",
        "#comment-input-container",
    )


def test_comment_control_uses_real_click_when_dispatch_does_not_open_editor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 dispatch_event 点击未能展开编辑器时回退为真实鼠标点击。"""
    entry = AsyncMock()
    editor = AsyncMock()
    find_visible = AsyncMock(side_effect=[None, editor])
    monkeypatch.setattr(dom, "find_visible", find_visible)
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()

    result = asyncio.run(
        panel.activate_comment_control(page, entry, require_editor=True)
    )

    assert result is editor
    entry.dispatch_event.assert_awaited_once_with("click")
    entry.click.assert_awaited_once_with(timeout=2_000)


def test_open_comment_panel_activates_note_comment_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证图文笔记页打开评论面板时会先激活评论 Tab 再定位编辑器。"""
    tab = AsyncMock()
    editor = AsyncMock()
    find_visible = AsyncMock(side_effect=[None, tab])
    monkeypatch.setattr(dom, "find_visible", find_visible)
    activate = AsyncMock(return_value=editor)
    monkeypatch.setattr(
        "crawler.browser.interactions.panel.activate_comment_control", activate
    )
    page = MagicMock()
    page.context.pages = [page]
    page.is_closed.return_value = False
    page.url = "https://www.douyin.com/note/123"
    page.wait_for_timeout = AsyncMock()

    active_page, result = asyncio.run(
        panel.open_comment_panel(page, aweme_id="123", settings=settings)
    )

    assert active_page is page
    assert result is editor
    activate.assert_awaited_once_with(page, tab)


def test_comment_selectors_cover_note_page_class_container() -> None:
    """验证评论相关选择器集合覆盖图文笔记页的类容器写法（编辑器/发送按钮/评论 Tab）。"""
    assert (
        '.comment-input-container [contenteditable="true"][role="combobox"]'
        in COMMENT_EDITOR_SELECTORS
    )
    assert (
        '.comment-input-container .commentInput-right-ct span:has(path[fill="#fff"])'
        in COMMENT_SUBMIT_SELECTORS
    )
    assert "div.X9EiuBV4:nth-of-type(2)" in COMMENT_TAB_SELECTORS


# ---- panel：私信会话开启 ----


def test_open_message_panel_clicks_entry_and_returns_message_editor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证私信会话开启会等待主页就绪、点击私信入口并返回消息输入框。"""
    page = MagicMock()
    page.context.pages = [page]
    profile = AsyncMock()
    button = AsyncMock()
    editor = AsyncMock()
    monkeypatch.setattr(dom, "find_visible", AsyncMock(return_value=profile))
    monkeypatch.setattr(dom, "find_text_control", AsyncMock(return_value=button))
    monkeypatch.setattr(
        CommentLocator, "find_message_editor", AsyncMock(return_value=(page, editor))
    )
    callback = AsyncMock()

    editor_page, result = asyncio.run(
        panel.open_message_panel(page, step_callback=callback)
    )

    assert editor_page is page
    assert result is editor
    button.click.assert_awaited_once_with(timeout=5_000)
    assert [call.args[1] for call in callback.await_args_list] == [
        "message_entry_opened",
        "message_editor_ready",
    ]


def test_open_message_panel_reports_retryable_page_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证主页控件一直加载不出来时报告可重试的 page_load_timeout。"""
    monkeypatch.setattr(dom, "find_visible", AsyncMock(return_value=None))
    monkeypatch.setattr(dom, "find_text_control", AsyncMock(return_value=None))

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(panel.open_message_panel(MagicMock()))

    assert captured.value.code == "page_load_timeout"
    assert captured.value.retryable is True


def test_open_message_panel_reports_closed_dm_when_entry_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """作者主页已就绪但没有私信入口时判为 message_not_allowed（终态）。"""
    monkeypatch.setattr(dom, "find_visible", AsyncMock(return_value=AsyncMock()))
    monkeypatch.setattr(dom, "find_text_control", AsyncMock(return_value=None))

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(panel.open_message_panel(MagicMock()))

    assert captured.value.code == "message_not_allowed"
    assert captured.value.retryable is False


def test_open_message_panel_reports_retryable_entry_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """私信入口存在但点击失败时报可重试的 message_entry_unavailable。"""
    page = MagicMock()
    page.context.pages = [page]
    button = AsyncMock()
    button.click.side_effect = RuntimeError("detached")
    monkeypatch.setattr(dom, "find_visible", AsyncMock(return_value=AsyncMock()))
    monkeypatch.setattr(dom, "find_text_control", AsyncMock(return_value=button))

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(panel.open_message_panel(page))

    assert captured.value.code == "message_entry_unavailable"
    assert captured.value.retryable is True


# ---- CommentLocator：回复编辑器与评论面 ----


def test_open_reply_editor_walks_to_card_and_verifies_reply_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证打开回复编辑器会向上回溯到评论卡片、点击可见回复按钮并核验回复上下文已激活。"""
    nodes = [MagicMock() for _ in range(12)]
    reply_controls: list[MagicMock] = []
    for index, node in enumerate(nodes):
        replies = MagicMock()
        reply = MagicMock()
        reply.is_visible = AsyncMock(return_value=index == 10)
        reply.dispatch_event = AsyncMock()
        replies.count = AsyncMock(return_value=1 if index == 10 else 0)
        replies.nth.return_value = reply
        node.get_by_text.return_value = replies
        reply_controls.append(reply)
        if index + 1 < len(nodes):
            node.locator.return_value = nodes[index + 1]
    comment_card = MagicMock()
    comment_card.count = AsyncMock(return_value=1)
    comment_card.is_visible = AsyncMock(return_value=True)
    nodes[0].locator.side_effect = lambda selector: (
        comment_card if "ancestor-or-self" in selector else nodes[1]
    )
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    editor = AsyncMock()
    monkeypatch.setattr(dom, "find_visible", AsyncMock(return_value=editor))
    monkeypatch.setattr(
        CommentLocator, "reply_context_is_active", AsyncMock(return_value=True)
    )

    context, result = asyncio.run(
        CommentLocator.open_reply_editor(page, nodes[0], _reply_request())
    )

    assert context is comment_card
    assert result is editor
    reply_controls[10].dispatch_event.assert_awaited_once_with("click")


def test_open_reply_editor_stops_before_ambiguous_comment_list() -> None:
    """验证匹配到多个可见回复按钮（歧义）时不做任何点击，直接返回空上下文与空编辑器。"""
    target = MagicMock()
    comment_card = MagicMock()
    comment_card.count = AsyncMock(return_value=1)
    comment_card.is_visible = AsyncMock(return_value=True)
    target.locator.return_value = comment_card
    replies = MagicMock()
    first = MagicMock()
    second = MagicMock()
    first.is_visible = AsyncMock(return_value=True)
    second.is_visible = AsyncMock(return_value=True)
    first.dispatch_event = AsyncMock()
    second.dispatch_event = AsyncMock()
    replies.count = AsyncMock(return_value=2)
    replies.nth.side_effect = [first, second]
    target.get_by_text.return_value = replies

    context, editor = asyncio.run(
        CommentLocator.open_reply_editor(AsyncMock(), target, _reply_request())
    )

    assert context is None
    assert editor is None
    first.dispatch_event.assert_not_awaited()
    second.dispatch_event.assert_not_awaited()


def test_reply_context_accepts_legacy_comment_id_attribute() -> None:
    """验证回复上下文激活判断兼容旧版 data-cid 属性标识的评论卡片。"""
    comment_card = MagicMock()
    comment_card.get_attribute = AsyncMock(
        side_effect=lambda attribute: "456" if attribute == "data-cid" else None
    )
    empty = MagicMock()
    empty.count = AsyncMock(return_value=0)
    comment_card.locator.return_value = empty
    active = MagicMock()
    active.count = AsyncMock(return_value=1)
    active_node = AsyncMock()
    active_node.is_visible.return_value = True
    active.nth.return_value = active_node
    comment_card.get_by_text.return_value = active

    assert (
        asyncio.run(CommentLocator.reply_context_is_active(comment_card, "456")) is True
    )


def test_comment_scroller_uses_visible_internal_route_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证评论列表滚动优先使用可见的内部路由容器（JS 滚动而非鼠标滚轮）。"""
    page = MagicMock()
    comment_list = AsyncMock()
    comment_list.evaluate.return_value = True
    find_visible = AsyncMock(return_value=comment_list)
    monkeypatch.setattr(dom, "find_visible", find_visible)

    result = asyncio.run(CommentLocator.scroll_comment_list(page))

    assert result is True
    comment_list.evaluate.assert_awaited_once()
    assert "let node = element" in comment_list.evaluate.await_args.args[0]
    page.mouse.wheel.assert_not_called()


def test_comment_scroller_falls_back_to_visible_comment_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证找不到路由容器时回退为在可见评论条目上向上查找可滚动祖先执行 JS 滚动。"""
    page = MagicMock()
    comment_item = AsyncMock()
    comment_item.evaluate.return_value = True
    find_visible = AsyncMock(side_effect=[None, comment_item])
    monkeypatch.setattr(dom, "find_visible", find_visible)

    result = asyncio.run(CommentLocator.scroll_comment_list(page))

    assert result is True
    comment_item.evaluate.assert_awaited_once()
    assert (
        "node.scrollTo(0, node.scrollHeight)"
        in (comment_item.evaluate.await_args.args[0])
    )
    page.mouse.wheel.assert_not_called()


def test_comment_surface_falls_back_to_visible_comment_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证评论区域定位在容器选择器未命中时回退到可见评论条目选择器。"""
    comment_item = AsyncMock()
    find_visible = AsyncMock(side_effect=[None, comment_item])
    monkeypatch.setattr(dom, "find_visible", find_visible)

    result = asyncio.run(
        CommentLocator.find_visible_comment_surface(MagicMock(), timeout=300)
    )

    assert result is comment_item
    assert find_visible.await_args_list[1].args[1] == COMMENT_ITEM_SELECTORS


def test_find_comment_target_skips_hidden_duplicate_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证按文本定位目标评论时跳过隐藏的重复文本节点，返回可见节点。"""
    comment_list = MagicMock()
    tooltip = MagicMock()
    empty = MagicMock()
    empty.count = AsyncMock(return_value=0)
    tooltip.locator.return_value = empty
    comment_list.locator.side_effect = lambda selector: (
        tooltip if selector.startswith('[id="tooltip_') else empty
    )
    hidden = AsyncMock()
    hidden.is_visible.return_value = False
    visible = AsyncMock()
    visible.is_visible.return_value = True
    text_matches = MagicMock()
    text_matches.count = AsyncMock(return_value=2)
    text_matches.nth.side_effect = [hidden, visible]
    comment_list.get_by_text.return_value = text_matches
    monkeypatch.setattr(
        dom,
        "find_visible",
        AsyncMock(return_value=comment_list),
    )

    result = asyncio.run(
        CommentLocator.find_comment_target(
            MagicMock(), _reply_request(target_comment_content="重复评论文本")
        )
    )

    assert result is visible


def test_find_comment_target_prefers_stable_tooltip_comment_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证目标评论定位优先使用 tooltip 中稳定的评论 id（不依赖可能过期的评论文本）。"""
    comment_list = MagicMock()
    tooltip = MagicMock()
    card = MagicMock()
    card.count = AsyncMock(return_value=1)
    visible_card = AsyncMock()
    visible_card.is_visible = AsyncMock(return_value=True)
    card.nth.return_value = visible_card
    tooltip.locator.return_value = card
    empty = MagicMock()
    empty.count = AsyncMock(return_value=0)
    comment_list.locator.side_effect = lambda selector: (
        tooltip if selector.startswith('[id="tooltip_') else empty
    )
    comment_list.get_by_text.return_value = empty
    monkeypatch.setattr(
        dom,
        "find_visible",
        AsyncMock(return_value=comment_list),
    )

    result = asyncio.run(
        CommentLocator.find_comment_target(
            MagicMock(), _reply_request(target_comment_content="数据库里的旧文本")
        )
    )

    assert result is visible_card
