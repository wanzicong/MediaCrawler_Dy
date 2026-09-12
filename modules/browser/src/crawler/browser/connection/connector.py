"""本地 CDP 浏览器的探测、地址发现与附加连接。"""

from __future__ import annotations

import asyncio
import logging
import socket

import httpx
from crawler.browser.errors import CDPConnectionError
from playwright.async_api import Browser, Playwright

logger = logging.getLogger(__name__)

# 本地 /json/version 发现的重试参数。
_ATTEMPTS = 10
_REQUEST_TIMEOUT = 5.0
_RETRY_INTERVAL = 0.5
_PROBE_TIMEOUT = 0.5
_DIRECT_CONNECT_TIMEOUT_MS = 5_000


class LocalCdpConnector:
    """连接本机通过 CDP 暴露的浏览器：端口探测、WebSocket 发现与附加。

    支持两种路径：在配置允许附加既有浏览器时先直连固定 ws 端点，失败后回退
    到 /json/version 发现；否则仅走发现路径。
    """

    def __init__(self, *, host: str, connect_existing: bool) -> None:
        """初始化本地连接器。

        参数：
            host: 本地 CDP 主机地址。
            connect_existing: 是否允许先直连既有的 ws 端点。
        """
        self.host = host
        self.connect_existing = connect_existing

    async def probe(self, port: int) -> bool:
        """探测指定 CDP 端口是否可建立 TCP 连接。"""
        return await asyncio.to_thread(self._connect_probe, port)

    def _connect_probe(self, port: int) -> bool:
        try:
            with socket.create_connection((self.host, port), timeout=_PROBE_TIMEOUT):
                return True
        except OSError:
            return False

    async def websocket_url(self, port: int) -> str:
        """通过本地 /json/version 端点发现浏览器 WebSocket 地址（带重试）。"""
        endpoint = f"http://{self.host}:{port}/json/version"
        last_error: Exception | None = None
        async with httpx.AsyncClient(
            trust_env=False,
            timeout=_REQUEST_TIMEOUT,
        ) as client:
            for _ in range(_ATTEMPTS):
                try:
                    response = await client.get(endpoint)
                    response.raise_for_status()
                    payload: dict[str, object] = response.json()
                    url = str(payload.get("webSocketDebuggerUrl") or "")
                    if url:
                        return url
                except Exception as exc:
                    last_error = exc
                await asyncio.sleep(_RETRY_INTERVAL)
        reason = type(last_error).__name__
        raise CDPConnectionError(f"无法读取 CDP /json/version: {reason}")

    async def connect(self, playwright: Playwright, port: int) -> Browser:
        """连接本地 CDP 浏览器：可选直连 ws 端点，失败后回退 /json/version 发现。

        参数：
            playwright: 已启动的 Playwright 驱动实例。
            port: CDP 调试端口。

        返回：
            通过 CDP 附加得到的 Browser 对象。

        异常：
            CDPConnectionError: 直连与发现路径都失败时抛出。
        """
        if self.connect_existing:
            direct_url = f"ws://{self.host}:{port}/devtools/browser"
            try:
                return await playwright.chromium.connect_over_cdp(
                    direct_url,
                    timeout=_DIRECT_CONNECT_TIMEOUT_MS,
                )
            except Exception as direct_error:
                logger.info(
                    "CDP direct endpoint unavailable, trying /json/version: %s",
                    type(direct_error).__name__,
                )
        websocket_url = await self.websocket_url(port)
        try:
            return await playwright.chromium.connect_over_cdp(websocket_url)
        except Exception as exc:
            raise CDPConnectionError(f"CDP 连接失败: {type(exc).__name__}") from exc
