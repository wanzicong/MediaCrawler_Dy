"""抖音扫码登录流程的测试：覆盖登录弹窗唤起等 DouyinLogin 交互逻辑。"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from crawler.douyin_client.login import DouyinLogin


def test_popup_login_dialog_prefers_visible_login_button() -> None:
    """验证唤起登录弹窗时优先点击可见的「登录」按钮，并在首方案失败后回退重试。"""
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

    page.get_by_role.assert_called_once_with("button", name="登录", exact=True)
    button.click.assert_awaited_once_with(timeout=5_000)
    assert page.wait_for_selector.await_count == 2
