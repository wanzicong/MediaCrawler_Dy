"""抖音登录流程测试（``crawler.browser.login.flow``）。

重点是 ``is_logged_in`` 的**顺序契约**（规格 §4.7）：非 ``require_self_profile``
时先读 ``localStorage.HasUserLogin``、再读 cookie ``LOGIN_STATUS``，命中即 True，
两者都未命中才回调 ``api.verify_login``。扫码轮询走这条路，若顺序退化就会从
「每秒一次本地判断」变成「每秒一次高风控资料接口调用」。
"""

import asyncio
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from crawler.browser.errors import LoginError
from crawler.browser.login.flow import DOUYIN_COOKIE_URLS, DouyinLogin
from crawler.browser.session.cookies import parse_cookie_string
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


class FakeLoginApi:
    """``LoginApi`` 替身：记录登录校验入参与调用顺序。"""

    def __init__(
        self, *, logged_in: bool = True, events: list[str] | None = None
    ) -> None:
        """预置登录结论；events 用于断言调用顺序。"""
        self.logged_in = logged_in
        self.events = events if events is not None else []
        self.login_checks: list[bool] = []

    async def verify_login(self, *, require_self_profile: bool = False) -> bool:
        """记录校验入参并返回预置结论。"""
        self.events.append("verify_login")
        self.login_checks.append(require_self_profile)
        return self.logged_in

    async def get_self_profile(self) -> dict[str, Any] | None:
        """本文件不覆盖资料读取。"""
        return None

    async def refresh_cookies(self) -> None:
        """记录 cookie 同步调用。"""
        self.events.append("refresh_cookies")


def _fake_handle(
    *,
    storage: dict[str, Any] | None = None,
    cookies: dict[str, str] | None = None,
    events: list[str] | None = None,
) -> MagicMock:
    """构造只读页面句柄替身，记录 local_storage/cookies 的读取顺序。"""
    handle = MagicMock()
    handle.page = MagicMock()

    async def local_storage() -> dict[str, Any]:
        """返回预置 localStorage 快照。"""
        if events is not None:
            events.append("local_storage")
        return dict(storage or {})

    async def read_cookies(_urls: Sequence[str]) -> tuple[str, dict[str, str]]:
        """返回预置 cookie 字符串与名值字典。"""
        if events is not None:
            events.append("cookies")
        jar = dict(cookies or {})
        return "; ".join(f"{name}={value}" for name, value in jar.items()), jar

    handle.local_storage = AsyncMock(side_effect=local_storage)
    handle.cookies = AsyncMock(side_effect=read_cookies)
    handle.clear_domain_cookies = AsyncMock()
    handle.set_cookies = AsyncMock()
    handle.reload = AsyncMock()
    handle.wait_for_selector = AsyncMock(return_value=MagicMock())
    return handle


def _login(
    handle: MagicMock,
    *,
    qrcode_path: Path,
    timeout: float = 5.0,
) -> tuple[DouyinLogin, AsyncMock]:
    """经 ``from_session`` 构造登录器（返回登录器与二维码回调替身）。"""
    on_qrcode = AsyncMock()
    session = MagicMock()
    session.page_handle = handle
    login = DouyinLogin.from_session(
        session, qrcode_path=qrcode_path, timeout=timeout, on_qrcode=on_qrcode
    )
    return login, on_qrcode


def test_from_session_takes_the_page_handle_from_the_session(tmp_path: Path) -> None:
    """``from_session`` 从会话取句柄，其余参数原样落到登录器上。"""
    handle = _fake_handle()
    on_qrcode = AsyncMock()
    session = MagicMock()
    session.page_handle = handle
    qrcode_path = tmp_path / "qrcode.png"

    login = DouyinLogin.from_session(
        session, qrcode_path=qrcode_path, timeout=3.5, on_qrcode=on_qrcode
    )

    assert login._page_handle is handle
    assert login._page is handle.page
    assert login.qrcode_path == qrcode_path
    assert login.timeout == 3.5
    assert login.on_qrcode is on_qrcode


# ---- is_logged_in 的顺序契约（规格 §4.7） ----


def test_is_logged_in_checks_local_storage_then_cookie_before_the_api(
    tmp_path: Path,
) -> None:
    """本地信号全未命中时：先 localStorage、再 cookie、最后才回调资料接口。"""
    events: list[str] = []
    handle = _fake_handle(events=events)
    api = FakeLoginApi(logged_in=False, events=events)
    login, _ = _login(handle, qrcode_path=tmp_path / "qrcode.png")

    assert asyncio.run(login.is_logged_in(api)) is False

    assert events == ["local_storage", "cookies", "verify_login"]
    assert api.login_checks == [False]
    handle.cookies.assert_awaited_once_with(DOUYIN_COOKIE_URLS)


def test_local_storage_hit_short_circuits_cookie_and_api(tmp_path: Path) -> None:
    """``HasUserLogin == "1"`` 命中即 True：不读 cookie，更不调用资料接口。"""
    events: list[str] = []
    handle = _fake_handle(storage={"HasUserLogin": "1"}, events=events)
    api = FakeLoginApi(logged_in=False, events=events)
    login, _ = _login(handle, qrcode_path=tmp_path / "qrcode.png")

    assert asyncio.run(login.is_logged_in(api)) is True

    assert events == ["local_storage"]
    assert api.login_checks == []
    handle.cookies.assert_not_awaited()


def test_cookie_hit_short_circuits_the_api(tmp_path: Path) -> None:
    """``LOGIN_STATUS == "1"`` 命中即 True：在 localStorage 之后判定，不调用资料接口。"""
    events: list[str] = []
    handle = _fake_handle(
        storage={"HasUserLogin": "0"}, cookies={"LOGIN_STATUS": "1"}, events=events
    )
    api = FakeLoginApi(logged_in=False, events=events)
    login, _ = _login(handle, qrcode_path=tmp_path / "qrcode.png")

    assert asyncio.run(login.is_logged_in(api)) is True

    assert events == ["local_storage", "cookies"]
    assert api.login_checks == []


def test_require_self_profile_skips_local_and_goes_straight_to_the_api(
    tmp_path: Path,
) -> None:
    """``require_self_profile=True`` 时跳过本地快速判断，直接走资料接口。"""
    events: list[str] = []
    handle = _fake_handle(storage={"HasUserLogin": "1"}, events=events)
    api = FakeLoginApi(logged_in=True, events=events)
    login, _ = _login(handle, qrcode_path=tmp_path / "qrcode.png")

    assert asyncio.run(login.is_logged_in(api, require_self_profile=True)) is True

    assert events == ["verify_login"]
    assert api.login_checks == [True]
    handle.local_storage.assert_not_awaited()
    handle.cookies.assert_not_awaited()


def test_non_one_local_signals_do_not_count_as_logged_in(tmp_path: Path) -> None:
    """本地信号必须是字符串 "1"：``0``/缺失都不算已登录，仍要回调资料接口。"""
    events: list[str] = []
    handle = _fake_handle(
        storage={"HasUserLogin": "0"}, cookies={"LOGIN_STATUS": "0"}, events=events
    )
    api = FakeLoginApi(logged_in=True, events=events)
    login, _ = _login(handle, qrcode_path=tmp_path / "qrcode.png")

    assert asyncio.run(login.is_logged_in(api)) is True

    assert events == ["local_storage", "cookies", "verify_login"]


# ---- cookie 登录 ----


def test_login_with_cookie_writes_cookies_refreshes_and_verifies(
    tmp_path: Path,
) -> None:
    """cookie 登录：清域内旧 cookie → 写入新 cookie → 刷新 → 同步 cookie → 校验。"""
    handle = _fake_handle()
    api = FakeLoginApi(events=[])
    login, _ = _login(handle, qrcode_path=tmp_path / "qrcode.png")

    assert asyncio.run(login.login_with_cookie("sessionid=abc; ttwid=xyz", api)) is None

    domain = handle.clear_domain_cookies.await_args.args[0]
    assert isinstance(domain, re.Pattern)
    assert domain.search("www.douyin.com") is not None
    assert domain.search(".douyin.com") is not None
    assert domain.search("notdouyin.com") is None
    written = handle.set_cookies.await_args.args[0]
    assert written == [
        {"name": "sessionid", "value": "abc", "domain": ".douyin.com", "path": "/"},
        {"name": "ttwid", "value": "xyz", "domain": ".douyin.com", "path": "/"},
    ]
    handle.reload.assert_awaited_once_with(wait_until="domcontentloaded")
    assert api.events == ["refresh_cookies", "verify_login"]


def test_login_with_cookie_rejects_empty_input(tmp_path: Path) -> None:
    """空 cookie 直接拒绝，且不触碰浏览器 cookie。"""
    handle = _fake_handle()
    api = FakeLoginApi()
    login, _ = _login(handle, qrcode_path=tmp_path / "qrcode.png")

    with pytest.raises(LoginError, match="非空 cookies"):
        asyncio.run(login.login_with_cookie("  ", api))

    assert parse_cookie_string("  ") == {}
    handle.clear_domain_cookies.assert_not_awaited()
    assert api.events == []


def test_login_with_cookie_raises_when_the_api_rejects_them(tmp_path: Path) -> None:
    """写 cookie 后接口仍判未登录时抛 LoginError（先同步 cookie 再校验）。"""
    handle = _fake_handle()
    api = FakeLoginApi(logged_in=False, events=[])
    login, _ = _login(handle, qrcode_path=tmp_path / "qrcode.png")

    with pytest.raises(LoginError, match="无效或已过期"):
        asyncio.run(login.login_with_cookie("sessionid=expired", api))

    assert api.events == ["refresh_cookies", "verify_login"]


# ---- 扫码登录 ----


def test_login_with_qrcode_polls_local_signals_without_the_profile_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """扫码轮询期间靠本地判断收尾：只同步一次 cookie，绝不调用资料接口。"""
    events: list[str] = []
    handle = _fake_handle(storage={"HasUserLogin": "1"}, events=events)
    api = FakeLoginApi(logged_in=False, events=events)
    login, on_qrcode = _login(handle, qrcode_path=tmp_path / "qrcode.png", timeout=5.0)
    monkeypatch.setattr(login, "_popup_login_dialog", AsyncMock())

    asyncio.run(login.login_with_qrcode(api, require_self_profile=False))

    assert events == ["local_storage", "refresh_cookies"]
    assert api.login_checks == []
    on_qrcode.assert_awaited_once_with(None)


def test_login_with_qrcode_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """超时未完成扫码时抛 LoginError，并清除本地二维码（回调收到 None）。"""
    handle = _fake_handle()
    api = FakeLoginApi(logged_in=False)
    login, on_qrcode = _login(handle, qrcode_path=tmp_path / "qrcode.png", timeout=0.0)
    monkeypatch.setattr(login, "_popup_login_dialog", AsyncMock())

    with pytest.raises(LoginError, match="超时"):
        asyncio.run(login.login_with_qrcode(api, require_self_profile=True))

    on_qrcode.assert_awaited_once_with(None)


def test_popup_login_dialog_falls_back_to_the_login_button(tmp_path: Path) -> None:
    """登录弹窗未自动出现时，依次尝试点击页头「登录」按钮并等待弹窗。"""
    handle = _fake_handle()
    handle.wait_for_selector = AsyncMock(
        side_effect=[PlaywrightTimeoutError("no dialog"), MagicMock()]
    )
    button = MagicMock()
    button.click = AsyncMock()
    handle.page.get_by_role.return_value.first = button
    login, _ = _login(handle, qrcode_path=tmp_path / "qrcode.png")

    asyncio.run(login._popup_login_dialog())

    handle.page.get_by_role.assert_called_once_with("button", name="登录", exact=True)
    button.click.assert_awaited_once_with(timeout=5_000)
    assert handle.wait_for_selector.await_count == 2


def test_popup_login_dialog_skips_clicking_when_it_is_already_open(
    tmp_path: Path,
) -> None:
    """弹窗已在页面上时不点击任何控件（按选择器等待成功即返回）。"""
    handle = _fake_handle()
    login, _ = _login(handle, qrcode_path=tmp_path / "qrcode.png")

    asyncio.run(login._popup_login_dialog())

    handle.wait_for_selector.assert_awaited_once()
    handle.page.get_by_role.assert_not_called()
