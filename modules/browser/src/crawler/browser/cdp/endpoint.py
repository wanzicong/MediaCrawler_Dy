"""CDP 端点发现与 WebSocket 地址规范化。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, NoReturn
from urllib.parse import urlsplit, urlunsplit

import httpx

HttpClientFactory = Callable[
    ..., Any
]  # 构造异步 HTTP 客户端（上下文管理器）的工厂，便于测试注入
ErrorFactory = Callable[[str], Exception]  # 依据失败原因构造领域异常的工厂
Clock = Callable[[], float]  # 单调时钟函数，用于计算轮询截止时间
Sleep = Callable[[float], Awaitable[Any]]  # 异步睡眠函数，便于测试注入


def _raise_with(factory: ErrorFactory, reason: str) -> NoReturn:
    """通过工厂构造领域异常并抛出，保持调用栈干净。"""
    raise factory(reason)


def rewrite_websocket_host(
    websocket_url: str,
    *,
    host: str,
    port: int,
) -> str:
    """校验浏览器端点地址，并将其容器内部的 authority 替换为可访问的主机与端口。

    参数：
        websocket_url: Chrome 返回的原始浏览器 WebSocket 地址。
        host: 目标主机名或 IP（IPv6 地址会自动加方括号）。
        port: 目标端口。

    返回：
        替换 authority 后的 WebSocket 地址。

    异常：
        ValueError: 协议不是 ws/wss 或路径不是 /devtools/browser/ 前缀时抛出。
    """
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
    """轮询可信的远程 Chrome 端点，并将其返回的 WebSocket authority 规范化。

    在超时时间内反复请求 /json/version，直到拿到有效的浏览器 WebSocket 地址，
    并将其中容器内部的主机与端口重写为外部可访问的地址。

    参数：
        endpoint: 远程 Chrome 的 /json/version HTTP 端点。
        host: 重写 WebSocket 地址时使用的目标主机。
        port: 重写 WebSocket 地址时使用的目标端口。
        timeout: 整体轮询超时时间（秒）。
        client_factory: 异步 HTTP 客户端工厂。
        error_factory: 超时后依据失败原因构造领域异常的工厂。
        clock: 单调时钟函数。
        sleep: 异步睡眠函数。

    返回：
        规范化后的浏览器 WebSocket 地址。

    异常：
        超时后通过 error_factory 抛出的领域异常。
    """
    deadline = clock() + timeout
    last_error: Exception | None = None
    async with client_factory(trust_env=False) as client:
        while clock() < deadline:
            remaining = deadline - clock()
            try:
                response = await client.get(
                    endpoint,
                    # Chrome 会拒绝 Host 头为 Docker 服务名的请求。
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
    """以有界重试读取本地 Chrome 的 /json/version 端点。

    参数：
        endpoint: 本地 Chrome 的 /json/version HTTP 端点。
        client_factory: 异步 HTTP 客户端工厂。
        error_factory: 重试耗尽后依据失败原因构造领域异常的工厂。
        attempts: 最大尝试次数。
        request_timeout: 单次请求超时时间（秒）。
        retry_interval: 两次尝试之间的间隔（秒）。
        sleep: 异步睡眠函数。

    返回：
        浏览器 WebSocket 地址（webSocketDebuggerUrl）。

    异常：
        重试耗尽后通过 error_factory 抛出的领域异常。
    """
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
