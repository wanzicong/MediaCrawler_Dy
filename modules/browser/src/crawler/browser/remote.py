"""远程 CDP 浏览器接入：端点校验、WebSocket 地址解析与连接建立。

属于浏览器集成层，用于连接预先配置好的可信远程 Chrome（如 Docker 容器中的浏览器）。
"""

import asyncio

import httpx
from crawler.browser.cdp import (
    connect_over_cdp,
    discover_remote_websocket_url,
)
from crawler.browser.errors import CDPConnectionError
from playwright.async_api import Browser, Playwright


class RemoteBrowserManager:
    """发现并连接一个可信的、预先配置的远程 CDP 浏览器。"""

    def __init__(self, *, host: str, port: int, timeout: float):
        """初始化远程浏览器管理器并校验主机与端口参数。

        参数：
            host: 远程 CDP 主机名或 IP，不允许包含协议前缀或路径。
            port: 远程 CDP 端口，取值范围 1~65535。
            timeout: 等待远程浏览器就绪及建立连接的超时时间（秒）。

        异常：
            ValueError: host 为空、包含协议/路径，或 port 超出合法范围时抛出。
        """
        self.host = host.strip()
        self.port = port
        self.timeout = timeout
        if not self.host or "://" in self.host or "/" in self.host:
            raise ValueError("DOUYIN_REMOTE_CDP_HOST 必须是主机名或 IP")
        if not 1 <= self.port <= 65535:
            raise ValueError("DOUYIN_REMOTE_CDP_PORT 必须在 1 到 65535 之间")

    @property
    def http_endpoint(self) -> str:
        """远程 Chrome 的 /json/version HTTP 端点地址。"""
        return f"http://{self.host}:{self.port}/json/version"

    async def resolve_websocket_url(self) -> str:
        """等待远程 Chrome 就绪，并将其容器内部的 WebSocket 地址重写为可访问地址。

        返回：
            重写主机与端口后的浏览器 WebSocket 地址。

        异常：
            CDPConnectionError: 超时内未获取到有效 WebSocket 地址时抛出。
        """
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
        """通过解析出的 WebSocket 地址连接远程浏览器。

        参数：
            playwright: 已启动的 Playwright 驱动实例。

        返回：
            通过 CDP 附加到远程浏览器得到的 Browser 对象。

        异常：
            CDPConnectionError: CDP 握手失败时抛出。
        """
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
