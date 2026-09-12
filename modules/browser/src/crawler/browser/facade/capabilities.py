"""站点无关的浏览器能力：CDP 端点健康探测与页面截图。

本模块承载从业务层下沉的、与具体站点无关的浏览器能力。探测与截图都
只依赖 Playwright / httpx 与 CDP 协议，不引用任何站点选择器或文案。
"""

from __future__ import annotations

import asyncio
import base64
import time
from urllib.parse import urlsplit, urlunsplit

import httpx
from playwright.async_api import Page


def probe_cdp_pages(host: str, port: int, *, timeout: float = 1.5) -> dict[str, object]:
    """探测一个 CDP 端点（``/json/list``）并返回页面健康信息。

    返回字典的键与业务层槽位公共字段一一对应，便于调用方直接展开合并；
    任何解析失败都返回 ``cdp_healthy=False``，绝不向上抛出异常。

    参数：
        host: CDP 主机名或 IP（不含协议前缀）。
        port: CDP 端口。
        timeout: 单次 HTTP 探测超时时间（秒）。

    返回：
        含 ``cdp_healthy`` / ``page_count`` / ``active_page_title`` /
        ``active_page_url`` / ``latency_ms`` 的健康信息字典。
    """
    host = host.strip()
    if not host or not 1 <= port <= 65535:
        return {
            "cdp_healthy": False,
            "page_count": 0,
            "active_page_title": None,
            "active_page_url": None,
            "latency_ms": None,
        }
    started = time.perf_counter()
    try:
        response = httpx.get(
            f"http://{host}:{port}/json/list",
            headers={"Host": "localhost"},
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        )
        response.raise_for_status()
        payload = response.json()
        pages = (
            [
                item
                for item in payload
                if isinstance(item, dict) and item.get("type") == "page"
            ]
            if isinstance(payload, list)
            else []
        )
        active = pages[0] if pages else None
        raw_url = str(active.get("url") or "") if active else ""
        parsed = urlsplit(raw_url)
        safe_url = (
            urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
            if parsed.scheme in {"http", "https"}
            else None
        )
        return {
            "cdp_healthy": True,
            "page_count": len(pages),
            "active_page_title": (
                str(active.get("title") or "").strip()[:200] or None if active else None
            ),
            "active_page_url": safe_url,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    except (httpx.HTTPError, ValueError, TypeError):
        return {
            "cdp_healthy": False,
            "page_count": 0,
            "active_page_title": None,
            "active_page_url": None,
            "latency_ms": None,
        }


async def capture_screenshot(page: Page, *, quality: int, timeout: float) -> bytes:
    """通过 CDP 截取当前页面 JPEG 图像并返回原始字节。

    参数：
        page: Playwright 页面对象。
        quality: JPEG 压缩质量（0~100）。
        timeout: 截图整体超时时间（秒）。

    返回：
        截图的原始 JPEG 字节。

    异常：
        RuntimeError: CDP 未返回有效图像数据时抛出。
    """

    async def _capture() -> bytes:
        cdp = await page.context.new_cdp_session(page)
        try:
            payload = await cdp.send(
                "Page.captureScreenshot",
                {
                    "format": "jpeg",
                    "quality": quality,
                    "fromSurface": True,
                    "captureBeyondViewport": False,
                },
            )
        finally:
            await cdp.detach()
        encoded = payload.get("data")
        if not isinstance(encoded, str) or not encoded:
            raise RuntimeError("CDP screenshot returned no image data")
        return base64.b64decode(encoded, validate=True)

    return await asyncio.wait_for(_capture(), timeout=timeout)


__all__ = ["capture_screenshot", "probe_cdp_pages"]
