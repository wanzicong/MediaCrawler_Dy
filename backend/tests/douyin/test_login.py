import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from app.douyin.login import DouyinLogin


def test_popup_login_dialog_prefers_visible_login_button() -> None:
    page = MagicMock()
    page.wait_for_selector = AsyncMock(
        side_effect=[TimeoutError("not open"), MagicMock()]
    )
    button = MagicMock()
    button.click = AsyncMock()
    page.get_by_role.return_value.first = button

    login = DouyinLogin(
        browser_context=MagicMock(),
        page=page,
        qrcode_path=Path("unused.png"),
        timeout=1,
        on_qrcode=AsyncMock(),
    )

    asyncio.run(login._popup_login_dialog())

    page.get_by_role.assert_called_once_with(
        "button", name="登录", exact=True
    )
    button.click.assert_awaited_once_with(timeout=5_000)
    assert page.wait_for_selector.await_count == 2
