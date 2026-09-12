"""抖音页面导航测试：主站/作者主页的容错导航与视频页的就绪重试。"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from crawler.bootstrap.settings import settings
from crawler.browser.errors import InteractionExecutionError
from crawler.browser.interactions.navigation import (
    CREATOR_URL_TEMPLATE,
    INDEX_URL,
    VIDEO_URL_TEMPLATE,
    creator_url,
    open_creator_profile,
    open_index,
    open_video,
    video_url,
)
from crawler.browser.interactions.selectors import VIDEO_PAGE_READY_SCRIPT
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


def test_url_templates_encode_the_dynamic_segments() -> None:
    """URL 模板按路径段转义拼接：作品 ID 与作者 sec_uid 都不会逃出路径。"""
    assert INDEX_URL == "https://www.douyin.com"
    assert VIDEO_URL_TEMPLATE == "https://www.douyin.com/video/{aweme_id}"
    assert CREATOR_URL_TEMPLATE == "https://www.douyin.com/user/{sec_uid}"
    assert video_url("123") == "https://www.douyin.com/video/123"
    assert creator_url("sec/uid") == "https://www.douyin.com/user/sec%2Fuid"


def test_open_index_ignores_commit_timeout() -> None:
    """主站导航超时被忽略（已 commit 的页面仍具备检测登录状态所需的信息）。"""
    page = AsyncMock()
    page.goto.side_effect = PlaywrightTimeoutError("timeout")

    asyncio.run(open_index(page))

    page.goto.assert_awaited_once_with(
        "https://www.douyin.com", wait_until="domcontentloaded", timeout=30_000
    )


def test_open_creator_profile_uses_template_and_ignores_commit_timeout() -> None:
    """作者主页导航按 sec_uid 拼接地址，超时同样视为可继续。"""
    page = AsyncMock()
    page.goto.side_effect = PlaywrightTimeoutError("timeout")

    asyncio.run(open_creator_profile(page, "author-sec-id"))

    page.goto.assert_awaited_once_with(
        "https://www.douyin.com/user/author-sec-id",
        wait_until="domcontentloaded",
        timeout=30_000,
    )


def test_open_video_waits_until_page_is_really_interactive() -> None:
    """打开视频页后等待页面就绪脚本通过（真正可交互）而非仅等待导航完成。"""
    page = AsyncMock()

    asyncio.run(open_video(page, "123", settings=settings))

    page.goto.assert_awaited_once()
    page.wait_for_function.assert_awaited_once_with(
        VIDEO_PAGE_READY_SCRIPT,
        timeout=settings.DOUYIN_INTERACTION_PAGE_READY_TIMEOUT_SECONDS * 1000,
    )


def test_open_video_reports_page_load_timeout() -> None:
    """视频页持续加载不出来时按配置次数重试后报告可重试的 page_load_timeout。"""
    page = AsyncMock()
    page.wait_for_function.side_effect = PlaywrightTimeoutError("timeout")

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(open_video(page, "123", settings=settings))

    assert captured.value.code == "page_load_timeout"
    assert captured.value.retryable is True
    assert page.wait_for_function.await_count == (
        settings.DOUYIN_INTERACTION_NAVIGATION_ATTEMPTS
    )
    target_calls = [
        call
        for call in page.goto.await_args_list
        if call.args[0] == "https://www.douyin.com/video/123"
    ]
    assert len(target_calls) == settings.DOUYIN_INTERACTION_NAVIGATION_ATTEMPTS


def test_open_video_recovers_from_stuck_loading_shell() -> None:
    """页面卡在加载壳时通过 about:blank 重置导航后恢复加载。"""
    page = AsyncMock()
    page.wait_for_function.side_effect = [PlaywrightTimeoutError("timeout"), None]

    asyncio.run(open_video(page, "123", settings=settings))

    assert [call.args[0] for call in page.goto.await_args_list] == [
        "https://www.douyin.com/video/123",
        "about:blank",
        "https://www.douyin.com/video/123",
    ]
    page.wait_for_timeout.assert_awaited_once_with(1_000)
    assert page.wait_for_function.await_count == 2


def test_open_video_retries_transient_navigation_errors() -> None:
    """瞬时导航错误（如临时 SSL 错误）会重试一次后成功。"""
    page = AsyncMock()
    page.goto.side_effect = [PlaywrightError("temporary ssl error"), None]

    asyncio.run(open_video(page, "123", settings=settings))

    assert page.goto.await_count == 2
    page.wait_for_timeout.assert_awaited_once_with(1_000)
    page.wait_for_function.assert_awaited_once()
