"""Platform-neutral Chrome DevTools Protocol primitives."""

from app.framework.browser.cdp.connection import connect_over_cdp
from app.framework.browser.cdp.endpoint import (
    discover_local_websocket_url,
    discover_remote_websocket_url,
    rewrite_websocket_host,
)
from app.framework.browser.cdp.network import find_available_port, probe_tcp_port

__all__ = [
    "connect_over_cdp",
    "discover_local_websocket_url",
    "discover_remote_websocket_url",
    "find_available_port",
    "probe_tcp_port",
    "rewrite_websocket_host",
]
