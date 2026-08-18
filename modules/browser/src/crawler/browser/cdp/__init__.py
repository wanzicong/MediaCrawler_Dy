"""平台无关的 Chrome DevTools Protocol (CDP) 基础原语。

聚合 CDP 连接、端点发现与网络探测能力，供上层会话封装统一引用。
"""

from crawler.browser.cdp.connection import connect_over_cdp
from crawler.browser.cdp.endpoint import (
    discover_local_websocket_url,
    discover_remote_websocket_url,
    rewrite_websocket_host,
)
from crawler.browser.cdp.network import find_available_port, probe_tcp_port

__all__ = [
    "connect_over_cdp",
    "discover_local_websocket_url",
    "discover_remote_websocket_url",
    "find_available_port",
    "probe_tcp_port",
    "rewrite_websocket_host",
]
