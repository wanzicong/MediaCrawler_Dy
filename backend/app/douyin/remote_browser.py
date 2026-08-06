import asyncio
from urllib.parse import urlsplit, urlunsplit

import httpx
from playwright.async_api import Browser, Playwright

from app.douyin.exceptions import CDPConnectionError


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
        deadline = asyncio.get_running_loop().time() + self.timeout
        last_error: Exception | None = None
        async with httpx.AsyncClient(trust_env=False) as client:
            while asyncio.get_running_loop().time() < deadline:
                remaining = deadline - asyncio.get_running_loop().time()
                try:
                    response = await client.get(
                        self.http_endpoint,
                        # Chrome rejects Docker service names in the Host header.
                        headers={"Host": "localhost"},
                        timeout=max(0.1, min(5.0, remaining)),
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ValueError("CDP 响应不是对象")
                    websocket_url = str(payload.get("webSocketDebuggerUrl") or "")
                    parsed = urlsplit(websocket_url)
                    if parsed.scheme not in {"ws", "wss"} or not parsed.path.startswith(
                        "/devtools/browser/"
                    ):
                        raise ValueError("CDP 响应缺少有效的浏览器 WebSocket 地址")
                    host = f"[{self.host}]" if ":" in self.host else self.host
                    return urlunsplit(
                        (
                            parsed.scheme,
                            f"{host}:{self.port}",
                            parsed.path,
                            parsed.query,
                            "",
                        )
                    )
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    last_error = exc
                    await asyncio.sleep(min(0.5, max(0.0, remaining)))
        reason = type(last_error).__name__ if last_error else "timeout"
        raise CDPConnectionError(
            f"远程 CDP 不可用: {self.host}:{self.port} ({reason})"
        )

    async def connect(self, playwright: Playwright) -> Browser:
        websocket_url = await self.resolve_websocket_url()
        try:
            return await playwright.chromium.connect_over_cdp(
                websocket_url, timeout=int(self.timeout * 1000)
            )
        except Exception as exc:
            raise CDPConnectionError(
                f"远程 CDP 连接失败: {self.host}:{self.port} ({type(exc).__name__})"
            ) from exc
