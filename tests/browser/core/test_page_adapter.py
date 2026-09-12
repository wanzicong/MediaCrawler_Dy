"""页面适配层测试：标签页获取策略、只读端口句柄与会话能力适配器（含指纹推导）。"""

import asyncio
from collections.abc import Mapping
from unittest.mock import AsyncMock, MagicMock

import pytest
from crawler.browser.errors import CDPConnectionError
from crawler.browser.page.handle import PlaywrightPageHandle
from crawler.browser.session.context import BrowserSessionContext
from crawler.browser.session.environment import (
    DOUYIN_FINGERPRINT_KEYS,
    derive_browser_family,
)
from crawler.browser.session.policy import PageAcquisitionPolicy

_CHROME_WINDOWS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_READINGS: dict[str, object] = {
    "user_agent": _CHROME_WINDOWS_UA,
    "language": "zh-CN",
    "platform": "Win32",
    "hardware_concurrency": 16,
    "device_memory": 8,
    "on_line": True,
    "screen_width": 2560,
    "screen_height": 1440,
    "effective_type": "4g",
    "round_trip_time": 50,
}


def _handle(
    *, readings: object = None, storage: object = None
) -> tuple[PlaywrightPageHandle, MagicMock, MagicMock]:
    """构造一个页面句柄：page.evaluate 按表达式返回读数或 localStorage。"""

    def evaluate(expression: str) -> object:
        return storage if "localStorage" in expression else readings

    page = MagicMock()
    page.evaluate = AsyncMock(side_effect=evaluate)
    context = MagicMock()
    return PlaywrightPageHandle(page=page, context=context), page, context


# ---- PageAcquisitionPolicy：取页/归属/标记隔离 ----


def test_interaction_policy_reuses_and_preserves_existing_page() -> None:
    """验证复用策略取已存在页面、不新建、不拥有页面所有权。"""
    existing_page = MagicMock()
    existing_page.is_closed.return_value = False
    created_page = MagicMock()
    context = MagicMock()
    context.pages = [existing_page]
    context.new_page = AsyncMock(return_value=created_page)
    policy = PageAcquisitionPolicy(reuse_existing_page=True)

    asyncio.run(policy.acquire(context))

    assert policy.page is existing_page
    assert policy.owns_page is False
    context.new_page.assert_not_awaited()


def test_default_policy_owns_a_new_page() -> None:
    """验证默认策略新建页面并拥有所有权，关闭页面由会话负责。"""
    existing_page = MagicMock()
    existing_page.is_closed.return_value = False
    created_page = MagicMock()
    context = MagicMock()
    context.pages = [existing_page]
    context.new_page = AsyncMock(return_value=created_page)
    policy = PageAcquisitionPolicy()

    asyncio.run(policy.acquire(context))

    assert policy.page is created_page
    assert policy.owns_page is True


def test_marked_policy_ignores_unrelated_user_pages() -> None:
    """验证带标记的策略通过 window.name 识别自动化页面，忽略用户手工打开的页面。"""
    user_page = MagicMock()
    user_page.is_closed.return_value = False
    user_page.evaluate = AsyncMock(return_value="")
    automation_page = MagicMock()
    automation_page.is_closed.return_value = False
    automation_page.evaluate = AsyncMock(return_value="mediacrawler:interaction")
    context = MagicMock()
    context.pages = [user_page, automation_page]
    context.new_page = AsyncMock()
    policy = PageAcquisitionPolicy(page_marker="mediacrawler:interaction")

    asyncio.run(policy.acquire(context))

    assert policy.page is automation_page
    assert policy.unrelated_page_count == 1
    context.new_page.assert_not_awaited()


def test_marked_policy_creates_dedicated_page_without_hijacking_user_page() -> None:
    """验证无标记页面时新建专属自动化页面并写入标记，绝不劫持用户已有页面。"""
    user_page = MagicMock()
    user_page.is_closed.return_value = False
    user_page.evaluate = AsyncMock(return_value="")
    automation_page = MagicMock()
    automation_page.evaluate = AsyncMock()
    context = MagicMock()
    context.pages = [user_page]
    context.new_page = AsyncMock(return_value=automation_page)
    policy = PageAcquisitionPolicy(page_marker="mediacrawler:interaction")

    asyncio.run(policy.acquire(context))

    assert policy.page is automation_page
    assert policy.unrelated_page_count == 1
    automation_page.evaluate.assert_awaited_once_with(
        "marker => { window.name = marker; }", "mediacrawler:interaction"
    )


# ---- PlaywrightPageHandle：只读端口 + 内部写操作 ----


def test_page_handle_delegates_read_only_primitives() -> None:
    """验证 BrowserPage 的四个原语直接委托给会话能力适配器（同源读数）。"""
    handle, _, context = _handle(readings=_READINGS)
    context.cookies = AsyncMock(return_value=[{"name": "sid", "value": "abc"}])

    assert asyncio.run(handle.user_agent()) == _CHROME_WINDOWS_UA
    assert asyncio.run(handle.local_storage()) == {}
    cookie_string, cookie_dict = asyncio.run(
        handle.cookies(["https://www.douyin.com/"])
    )

    assert cookie_string == "sid=abc"
    assert cookie_dict == {"sid": "abc"}
    context.cookies.assert_awaited_once_with(urls=["https://www.douyin.com/"])
    assert set(asyncio.run(handle.fingerprint())) == set(DOUYIN_FINGERPRINT_KEYS) - {
        "engine_version"
    }


def test_page_handle_capture_screenshot_uses_site_agnostic_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证句柄截图复用 facade 的站点无关截图能力，并把原始 page 传给它。"""
    handle, page, _ = _handle()
    screenshot = b"captured-bytes"
    seen: dict[str, object] = {}

    async def fake_capture(target: object, *, quality: int, timeout: float) -> bytes:
        seen.update(page=target, quality=quality, timeout=timeout)
        return screenshot

    monkeypatch.setattr(
        "crawler.browser.facade.capabilities.capture_screenshot", fake_capture
    )

    result = asyncio.run(handle.capture_screenshot(quality=80, timeout=5))

    assert result == screenshot
    assert seen == {"page": page, "quality": 80, "timeout": 5}


def test_page_handle_keeps_write_operations_off_the_port() -> None:
    """验证写操作（cookie 写入/清空、导航、重载、选择器等待）落在原生对象上。"""
    handle, page, context = _handle()
    context.add_cookies = AsyncMock()
    context.clear_cookies = AsyncMock()
    page.reload = AsyncMock()
    page.wait_for_selector = AsyncMock(return_value="element")
    page.url = "https://www.douyin.com/"

    asyncio.run(handle.set_cookies([{"name": "sid", "value": "abc"}]))
    asyncio.run(handle.clear_domain_cookies(".douyin.com"))
    asyncio.run(handle.reload())
    assert asyncio.run(handle.wait_for_selector("#login-panel", timeout_ms=1_005)) == (
        "element"
    )
    assert handle.current_url() == "https://www.douyin.com/"

    context.add_cookies.assert_awaited_once_with([{"name": "sid", "value": "abc"}])
    context.clear_cookies.assert_awaited_once_with(domain=".douyin.com")
    page.reload.assert_awaited_once_with(wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_selector.assert_awaited_once_with("#login-panel", timeout=1_005)


# ---- BrowserSessionContext：会话能力适配器 ----


def test_session_context_maps_real_readings_to_fingerprint_keys() -> None:
    """验证指纹逐键来自真实读数与同源 UA，且不含伪造常量。"""
    handle, _, _ = _handle(readings=_READINGS)

    fingerprint = asyncio.run(handle.fingerprint())

    assert isinstance(fingerprint, Mapping)
    assert fingerprint["browser_language"] == "zh-CN"
    assert fingerprint["browser_platform"] == "Win32"
    assert fingerprint["browser_name"] == "Chrome"
    assert fingerprint["browser_version"] == "126.0.0.0"
    assert fingerprint["engine_name"] == "Blink"
    assert fingerprint["os_name"] == "Windows"
    assert fingerprint["os_version"] == "10.0"
    assert fingerprint["cpu_core_num"] == "16"
    assert fingerprint["device_memory"] == "8"
    assert fingerprint["screen_width"] == "2560"
    assert fingerprint["screen_height"] == "1440"
    assert fingerprint["effective_type"] == "4g"
    assert fingerprint["round_trip_time"] == "50"
    # Blink/Gecko 的 UA 只带冻结的兼容标记，推不出真实内核版本 → 不写入该键。
    assert "engine_version" not in fingerprint


def test_session_context_never_invents_missing_fingerprint_values() -> None:
    """缺键即不写入：读不到任何读数时指纹为空，绝不回退伪造常量。"""
    handle, _, _ = _handle(readings={})

    assert asyncio.run(handle.fingerprint()) == {}


def test_session_context_caches_fingerprint_within_session() -> None:
    """验证指纹在同一会话内幂等：首次采集后缓存。"""
    handle, page, _ = _handle(readings=_READINGS)
    context = BrowserSessionContext(page=page, context=MagicMock())

    first = asyncio.run(context.fingerprint())
    second = asyncio.run(context.fingerprint())

    assert first == second
    assert page.evaluate.await_count == 1


def test_session_context_local_storage_is_empty_when_unreadable() -> None:
    """验证 localStorage 读不到时返回 {} 而不是抛异常（pong 语义不变）。"""
    handle, page, _ = _handle(storage={"HasUserLogin": "1"})
    assert asyncio.run(handle.local_storage()) == {"HasUserLogin": "1"}

    page.evaluate = AsyncMock(side_effect=ValueError("SecurityError"))
    assert asyncio.run(handle.local_storage()) == {}


def test_session_context_rejects_reads_after_close() -> None:
    """验证 close() 后任何读取都抛 CDPConnectionError。"""
    context = BrowserSessionContext(page=MagicMock(), context=MagicMock())
    context.close()

    with pytest.raises(CDPConnectionError):
        asyncio.run(context.fingerprint())
    with pytest.raises(CDPConnectionError):
        asyncio.run(context.local_storage())


# ---- derive_browser_family：UA 正则推导 ----


def test_derive_browser_family_prefers_derived_browsers_over_chrome() -> None:
    """验证 Edg/OPR 等衍生浏览器不会被其 UA 里的 Chrome 标记抢先命中。"""
    edge_ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.2592.87"
    )

    derived = derive_browser_family(edge_ua)

    assert derived["browser_name"] == "Edge"
    assert derived["browser_version"] == "126.0.2592.87"
    assert derived["engine_name"] == "Blink"


def test_derive_browser_family_reads_webkit_engine_version_from_ua() -> None:
    """验证 Safari 的内核版本取 UA 里真实存在的 AppleWebKit 标记。"""
    safari_ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    )

    derived = derive_browser_family(safari_ua)

    assert derived["browser_name"] == "Safari"
    assert derived["browser_version"] == "17.5"
    assert derived["engine_name"] == "WebKit"
    assert derived["engine_version"] == "605.1.15"
    assert derived["os_name"] == "Mac OS"
    assert derived["os_version"] == "10.15.7"


def test_derive_browser_family_maps_mobile_and_linux_systems() -> None:
    """验证 Android / iOS / Linux 的系统名与版本推导（Linux 版本诚实省略）。"""
    android_ua = (
        "Mozilla/5.0 (Linux; Android 13; SM-S9110) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
    )
    iphone_ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 "
        "Safari/604.1"
    )
    linux_ua = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )

    assert derive_browser_family(android_ua)["os_name"] == "Android"
    assert derive_browser_family(android_ua)["os_version"] == "13"
    assert derive_browser_family(iphone_ua)["os_name"] == "iOS"
    assert derive_browser_family(iphone_ua)["os_version"] == "16.5"
    linux = derive_browser_family(linux_ua)
    assert linux["os_name"] == "Linux"
    assert "os_version" not in linux


def test_derive_browser_family_omits_everything_for_unparsable_ua() -> None:
    """验证无法解析的 UA 不产生任何键（不放默认值）。"""
    assert derive_browser_family("") == {}
    assert derive_browser_family("curl/8.4.0") == {}
