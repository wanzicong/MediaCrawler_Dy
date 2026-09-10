"""browser 门面能力的直测：会话连接参数、CDP 健康探测与页面截图。

这些能力从业务层下沉到 ``crawler.browser.facade``，与具体站点无关。
此处覆盖公开 API 的边界行为，不涉及抖音语义。
"""

import asyncio
import base64
from unittest.mock import AsyncMock

import httpx
import pytest
from crawler.browser.facade import (
    BrowserSessionSpec,
    capture_screenshot,
    probe_cdp_pages,
)


class FakeResponse:
    """模拟 CDP /json/list 的 HTTP 响应。"""

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        """模拟响应状态正常。"""
        return None

    def json(self) -> object:
        """返回预置负载。"""
        return self._payload


def test_browser_session_spec_defaults() -> None:
    """验证会话连接参数默认值为空，仅 browser_mode 必填。"""
    spec = BrowserSessionSpec(browser_mode="remote")
    assert spec.browser_mode == "remote"
    assert spec.remote_host is None
    assert spec.remote_port is None
    assert spec.viewer_url is None
    assert spec.user_data_dir is None
    assert spec.debug_port is None


def test_probe_cdp_pages_reports_unhealthy_on_bad_input() -> None:
    """验证主机为空或端口越界时返回离线，而不抛异常。"""
    assert probe_cdp_pages("", 9222)["cdp_healthy"] is False
    assert probe_cdp_pages("127.0.0.1", 0)["cdp_healthy"] is False
    assert probe_cdp_pages("127.0.0.1", 70000)["cdp_healthy"] is False


def test_probe_cdp_pages_parses_page_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证探测能解析页面列表并脱敏活动页 URL（去掉查询串与敏感片段）。"""

    def fake_get(*_args: object, **kwargs: object) -> FakeResponse:
        assert kwargs["headers"] == {"Host": "localhost"}
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return FakeResponse(
            [
                {
                    "type": "page",
                    "title": "抖音首页",
                    "url": "https://www.douyin.com/?sensitive=query",
                },
                {"type": "background_page"},
            ]
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    result = probe_cdp_pages("127.0.0.1", 9224)

    assert result["cdp_healthy"] is True
    assert result["page_count"] == 1
    assert result["active_page_title"] == "抖音首页"
    assert result["active_page_url"] == "https://www.douyin.com/"
    assert isinstance(result["latency_ms"], int)


def test_probe_cdp_pages_reports_unhealthy_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 HTTP 异常时返回离线而非向上抛出。"""

    def fake_get(*_args: object, **_kwargs: object) -> FakeResponse:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", fake_get)

    result = probe_cdp_pages("127.0.0.1", 9224)
    assert result["cdp_healthy"] is False
    assert result["page_count"] == 0
    assert result["latency_ms"] is None


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
