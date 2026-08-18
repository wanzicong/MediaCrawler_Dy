"""CDP endpoint discovery and WebSocket address normalization."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, NoReturn
from urllib.parse import urlsplit, urlunsplit

import httpx

HttpClientFactory = Callable[..., Any]
ErrorFactory = Callable[[str], Exception]
Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[Any]]


def _raise_with(factory: ErrorFactory, reason: str) -> NoReturn:
    raise factory(reason)


def rewrite_websocket_host(
    websocket_url: str,
    *,
    host: str,
    port: int,
) -> str:
    """Validate a browser endpoint and replace its container-local authority."""
    parsed = urlsplit(websocket_url)
    if parsed.scheme not in {"ws", "wss"} or not parsed.path.startswith(
        "/devtools/browser/"
    ):
        raise ValueError("CDP 响应缺少有效的浏览器 WebSocket 地址")
    rewritten_host = f"[{host}]" if ":" in host else host
    return urlunsplit(
        (
            parsed.scheme,
            f"{rewritten_host}:{port}",
            parsed.path,
            parsed.query,
            "",
        )
    )


async def discover_remote_websocket_url(
    *,
    endpoint: str,
    host: str,
    port: int,
    timeout: float,
    client_factory: HttpClientFactory,
    error_factory: ErrorFactory,
    clock: Clock,
    sleep: Sleep,
) -> str:
    """Poll a trusted remote Chrome endpoint and normalize its WS authority."""
    deadline = clock() + timeout
    last_error: Exception | None = None
    async with client_factory(trust_env=False) as client:
        while clock() < deadline:
            remaining = deadline - clock()
            try:
                response = await client.get(
                    endpoint,
                    # Chrome rejects Docker service names in the Host header.
                    headers={"Host": "localhost"},
                    timeout=max(0.1, min(5.0, remaining)),
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("CDP 响应不是对象")
                websocket_url = str(payload.get("webSocketDebuggerUrl") or "")
                return rewrite_websocket_host(
                    websocket_url,
                    host=host,
                    port=port,
                )
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                last_error = exc
                await sleep(min(0.5, max(0.0, remaining)))
    reason = type(last_error).__name__ if last_error else "timeout"
    _raise_with(error_factory, reason)


async def discover_local_websocket_url(
    *,
    endpoint: str,
    client_factory: HttpClientFactory,
    error_factory: ErrorFactory,
    attempts: int = 10,
    request_timeout: float = 5,
    retry_interval: float = 0.5,
    sleep: Sleep = asyncio.sleep,
) -> str:
    """Read a local Chrome `/json/version` endpoint with bounded retries."""
    last_error: Exception | None = None
    async with client_factory(
        trust_env=False,
        timeout=request_timeout,
    ) as client:
        for _ in range(attempts):
            try:
                response = await client.get(endpoint)
                response.raise_for_status()
                payload: dict[str, Any] = json.loads(response.text)
                url = str(payload.get("webSocketDebuggerUrl") or "")
                if url:
                    return url
            except Exception as exc:
                last_error = exc
            await sleep(retry_interval)
    reason = type(last_error).__name__
    _raise_with(error_factory, reason)
