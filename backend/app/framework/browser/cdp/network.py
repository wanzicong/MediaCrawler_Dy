"""Small TCP and local-port primitives used before CDP attachment."""

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
    """Return whether a TCP listener accepts a connection within the timeout."""

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
    """Find the first bindable TCP port in the same bounded range as before."""
    for port in range(start, min(start + span, 65536)):
        with socket_factory() as candidate:
            try:
                candidate.bind((bind_host, port))
            except OSError:
                continue
            return port
    return None
