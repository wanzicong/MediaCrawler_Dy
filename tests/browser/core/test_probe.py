"""CDP 端点健康探测（probe_cdp_pages）的测试：非法入参、页面列表解析与故障降级。"""

import httpx
import pytest
from crawler.browser.facade import probe_cdp_pages


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
