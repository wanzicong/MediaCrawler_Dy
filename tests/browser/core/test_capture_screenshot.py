"""站点无关截图能力（capture_screenshot）的测试：CDP 采集、解码与故障分支。"""

import asyncio
import base64
from unittest.mock import AsyncMock

import pytest
from crawler.browser.facade import capture_screenshot


def test_capture_screenshot_decodes_base64() -> None:
    """验证截图经 CDP 采集后解码为原始字节并正确分离会话。"""
    page = AsyncMock()
    screenshot = b"fake-jpeg-browser-evidence"
    cdp = AsyncMock()
    cdp.send.return_value = {"data": base64.b64encode(screenshot).decode()}
    page.context.new_cdp_session.return_value = cdp

    result = asyncio.run(capture_screenshot(page, quality=80, timeout=5))

    assert result == screenshot
    page.context.new_cdp_session.assert_awaited_once_with(page)
    cdp.send.assert_awaited_once_with(
        "Page.captureScreenshot",
        {
            "format": "jpeg",
            "quality": 80,
            "fromSurface": True,
            "captureBeyondViewport": False,
        },
    )
    cdp.detach.assert_awaited_once()


def test_capture_screenshot_raises_on_missing_data() -> None:
    """验证 CDP 未返回图像数据时抛出 RuntimeError。"""
    page = AsyncMock()
    cdp = AsyncMock()
    cdp.send.return_value = {}
    page.context.new_cdp_session.return_value = cdp

    with pytest.raises(RuntimeError, match="no image data"):
        asyncio.run(capture_screenshot(page, quality=80, timeout=5))
    cdp.detach.assert_awaited_once()
