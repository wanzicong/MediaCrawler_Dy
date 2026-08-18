"""CDP 附加之前使用的小型 TCP 与本地端口探测原语。"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable
from typing import Any

ConnectionFactory = Callable[..., Any]
SocketFactory = Callable[[], Any]


async def probe_tcp_port(
    host: str,
    port: int,
    *,
    timeout: float,
    connection_factory: ConnectionFactory = socket.create_connection,
) -> bool:
    """检测目标 TCP 端口是否在超时时间内接受连接。

    参数：
        host: 目标主机。
        port: 目标端口。
        timeout: 连接超时时间（秒）。
        connection_factory: 创建阻塞式连接的工厂，默认 socket.create_connection。

    返回：
        能在超时内建立连接返回 True，否则返回 False。
    """

    def connect() -> bool:
        try:
            with connection_factory((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    return await asyncio.to_thread(connect)


def find_available_port(
    start: int,
    *,
    span: int = 100,
    bind_host: str = "127.0.0.1",
    socket_factory: SocketFactory = socket.socket,
) -> int | None:
    """在有界范围内找到第一个可绑定的 TCP 端口。

    参数：
        start: 扫描起始端口。
        span: 向后扫描的端口跨度。
        bind_host: 绑定的本机地址。
        socket_factory: 创建 socket 的工厂，便于测试注入。

    返回：
        第一个可绑定端口；范围内全部不可用时返回 None。
    """
    for port in range(start, min(start + span, 65536)):
        with socket_factory() as candidate:
            try:
                candidate.bind((bind_host, port))
            except OSError:
                continue
            return port
    return None
