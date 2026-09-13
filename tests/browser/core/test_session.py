"""CDP 会话门面的测试：模式枚举语义、异常边界、页面归属、反检测脚本路径与新公开面。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from crawler.bootstrap.settings import settings
from crawler.browser import (
    BrowserAutomationError,
    BrowserAutomationTimeoutError,
    BrowserSessionContext,
    BrowserSessionSpec,
    CDPBrowserSession,
    CDPConnectionError,
)
from crawler.browser.session.manager import STEALTH_SCRIPT_PATH
from crawler.browser.session.mode import BrowserMode
from crawler.business.douyin.accounts.models import DouyinBrowserMode
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


def _session_with_page() -> tuple[CDPBrowserSession, MagicMock, MagicMock]:
    """构造一个手工装配了 page/context 的会话（不启动真实浏览器）。

    返回 (会话, 页面替身, 上下文替身)。会话能力适配器仍按真实装配路径建立，
    因此 ``session_context()`` / ``page_handle`` 可直测。原生 Playwright 对象
    已不再对外暴露（``page`` / ``context`` 属性在 S5b 删除），故此处直接写入
    私有字段——等价于 ``start()`` 内部 ``_acquire_page()`` 的装配结果。
    """
    page = MagicMock()
    page.goto = AsyncMock()
    context = MagicMock()
    session = CDPBrowserSession(settings)
    session._page = page
    session._context = context
    session._page_handle = None
    session._session_context = BrowserSessionContext(page=page, context=context)
    return session, page, context


def test_browser_mode_keeps_historical_enum_value_semantics() -> None:
    """验证浏览器模式枚举的取值语义：默认取配置值、字符串形式稳定、显式传参原样保留。"""
    configured = CDPBrowserSession(settings)
    supplied_mode = DouyinBrowserMode.remote
    supplied = CDPBrowserSession(settings, browser_mode=supplied_mode)

    assert configured.browser_mode.value == settings.DOUYIN_BROWSER_MODE  # type: ignore[attr-defined]
    assert isinstance(configured.browser_mode, BrowserMode)
    assert str(configured.browser_mode) == f"BrowserMode.{settings.DOUYIN_BROWSER_MODE}"
    assert supplied.browser_mode is supplied_mode


def test_browser_exception_boundary_preserves_playwright_identity() -> None:
    """验证浏览器自动化异常边界类型就是 playwright 原生异常（保持上层捕获兼容）。"""
    assert BrowserAutomationError is PlaywrightError
    assert BrowserAutomationTimeoutError is PlaywrightTimeoutError


def test_browser_session_spec_defaults() -> None:
    """验证会话连接参数默认值为空，仅 browser_mode 必填。"""
    spec = BrowserSessionSpec(browser_mode="remote")
    assert spec.browser_mode == "remote"
    assert spec.remote_host is None
    assert spec.remote_port is None
    assert spec.viewer_url is None
    assert spec.user_data_dir is None
    assert spec.debug_port is None


def test_browser_session_from_spec_carries_connection_parameters() -> None:
    """验证 from_spec 把连接参数逐项搬到会话构造参数上。"""
    spec = BrowserSessionSpec(
        browser_mode="remote",
        remote_host="douyin-browser",
        remote_port=9333,
    )

    session = CDPBrowserSession.from_spec(
        settings,
        spec,
        reuse_existing_page=True,
        close_page_on_exit=False,
        page_marker="mediacrawler:interaction",
    )

    assert session.browser_mode == BrowserMode.remote
    assert session.remote_host == "douyin-browser"
    assert session.remote_port == 9333
    assert session.reuse_existing_page is True
    assert session.close_page_on_exit is False
    assert session.page_marker == "mediacrawler:interaction"


def test_owned_page_is_closed_for_default_session() -> None:
    """验证默认会话拥有页面所有权，关闭会话时页面随之关闭。"""
    page = MagicMock()
    page.close = AsyncMock()
    session = CDPBrowserSession(settings)
    session._page = page
    session.owns_page = True

    asyncio.run(session.close())

    page.close.assert_awaited_once()


def test_session_is_usable_tracks_browser_and_page_state() -> None:
    """验证 is_usable 能识别「窗口已关闭」的失效会话，且探测异常按不可用处理。"""
    session = CDPBrowserSession(settings)
    # 未启动的会话不可用
    assert session.is_usable() is False

    browser = MagicMock()
    page = MagicMock()
    session.playwright = MagicMock()
    session.browser = browser
    session._page = page
    browser.is_connected.return_value = True
    page.is_closed.return_value = False
    assert session.is_usable() is True

    # 用户关掉页面/窗口
    page.is_closed.return_value = True
    assert session.is_usable() is False

    # CDP 连接断开（浏览器进程退出）
    page.is_closed.return_value = False
    browser.is_connected.return_value = False
    assert session.is_usable() is False

    # 驱动已被回收：探测本身抛错也必须按不可用处理
    browser.is_connected.side_effect = RuntimeError("driver already stopped")
    assert session.is_usable() is False


def test_browser_session_exposes_stealth_script_path() -> None:
    """反检测脚本路径必须真实存在（非 mock 断言）。

    ``session/manager.py`` 处于模块第 2 层，``Path(__file__).resolve().parents[1]``
    必须解析到 ``crawler/browser/``；模块一旦下沉或上浮一层，stealth.js 会静默失效
    （单测里 context 是 mock，路径错了不会红），进而变成真实风控回归。
    """
    assert STEALTH_SCRIPT_PATH.exists(), f"反检测脚本不存在：{STEALTH_SCRIPT_PATH}"
    assert STEALTH_SCRIPT_PATH.is_file()
    assert STEALTH_SCRIPT_PATH.stat().st_size > 0
    # 深度自检：manager.py -> session/ -> browser/ -> resources/stealth.js
    assert STEALTH_SCRIPT_PATH.parents[1].name == "browser"
    assert STEALTH_SCRIPT_PATH.parents[0].name == "resources"
    assert STEALTH_SCRIPT_PATH.name == "stealth.js"


def test_stealth_script_path_expression_stays_at_module_second_level() -> None:
    """验证注入点用的是本模块第 2 层的路径表达式，不会随重构换深度。

    真实调用点是 ``start()`` 里的 ``add_init_script``，其单测需要真实浏览器；
    这里用源码文本断言把「路径由 ``parents[1]`` 解析」这一事实钉住。
    """
    source = (
        STEALTH_SCRIPT_PATH.parents[1]
        .joinpath("session", "manager.py")
        .read_text(encoding="utf-8")
    )

    assert 'parents[1] / "resources" / "stealth.js"' in source
    assert "add_init_script(path=STEALTH_SCRIPT_PATH)" in source


def test_session_context_and_page_handle_require_a_started_session() -> None:
    """验证未 start() 时取会话上下文/页面句柄/导航都抛 CDPConnectionError。"""
    session = CDPBrowserSession(settings)

    with pytest.raises(CDPConnectionError):
        session.session_context()
    with pytest.raises(CDPConnectionError):
        _ = session.page_handle
    with pytest.raises(CDPConnectionError):
        _ = session.browser_page
    with pytest.raises(CDPConnectionError):
        asyncio.run(session.open("https://www.douyin.com"))


def test_open_delegates_to_page_goto_with_wait_until_and_timeout() -> None:
    """验证 open() 与 page.goto 同语义：等待状态与超时毫秒原样透传。"""
    session, page, _ = _session_with_page()

    asyncio.run(session.open("https://www.douyin.com", timeout_ms=1_234))

    page.goto.assert_awaited_once_with(
        "https://www.douyin.com", wait_until="domcontentloaded", timeout=1_234
    )


def test_browser_page_and_session_context_share_one_fingerprint_cache() -> None:
    """验证页面句柄与会话上下文共用同一个会话能力适配器（指纹只采集一次）。"""
    session, _, _ = _session_with_page()

    assert session.page_handle is session.page_handle
    assert session.browser_page is session.page_handle
    assert session.page_handle._session_context is session.session_context()


def test_session_context_is_invalidated_on_close() -> None:
    """验证 close() 之后会话上下文被置空并拒绝服务（避免读到上个页面残留读数）。"""
    session, _, _ = _session_with_page()
    context = session.session_context()

    asyncio.run(session.close())

    with pytest.raises(CDPConnectionError):
        session.session_context()
    with pytest.raises(CDPConnectionError):
        asyncio.run(context.user_agent())
