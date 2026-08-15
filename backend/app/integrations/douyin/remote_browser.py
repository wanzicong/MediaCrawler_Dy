import asyncio

import httpx
from playwright.async_api import Browser, Playwright

from app.framework.browser.cdp import (
    connect_over_cdp,
    discover_remote_websocket_url,
)
from app.integrations.douyin.exceptions import CDPConnectionError


class RemoteBrowserManager:
    """Discover and connect to a trusted, preconfigured remote CDP browser."""

    def __init__(self, *, host: str, port: int, timeout: float):
        self.host = host.strip()
        self.port = port
        self.timeout = timeout
        if not self.host or "://" in self.host or "/" in self.host:
            raise ValueError("DOUYIN_REMOTE_CDP_HOST 必须是主机名或 IP")
        if not 1 <= self.port <= 65535:
            raise ValueError("DOUYIN_REMOTE_CDP_PORT 必须在 1 到 65535 之间")

    @property
    def http_endpoint(self) -> str:
        return f"http://{self.host}:{self.port}/json/version"

    async def resolve_websocket_url(self) -> str:
        """Wait for Chrome and rewrite its container-local WebSocket address."""
        loop = asyncio.get_running_loop()
        return await discover_remote_websocket_url(
            endpoint=self.http_endpoint,
            host=self.host,
            port=self.port,
            timeout=self.timeout,
            client_factory=httpx.AsyncClient,
            error_factory=lambda reason: CDPConnectionError(
                f"远程 CDP 不可用: {self.host}:{self.port} ({reason})"
            ),
            clock=loop.time,
            sleep=asyncio.sleep,
        )

    async def connect(self, playwright: Playwright) -> Browser:
        websocket_url = await self.resolve_websocket_url()
        try:
            return await connect_over_cdp(
                playwright.chromium,
                websocket_url,
                timeout_ms=int(self.timeout * 1000),
            )
        except Exception as exc:
            raise CDPConnectionError(
                f"远程 CDP 连接失败: {self.host}:{self.port} ({type(exc).__name__})"
            ) from exc
