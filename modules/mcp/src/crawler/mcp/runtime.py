"""MCP 共享运行时：FastMCP 实例与带鉴权的 FastAPI 代理客户端。

本模块创建全局唯一的 FastMCP 服务实例和 AuthenticatedApiClient，
crawler.mcp.tools 下的所有工具函数都注册到该实例，并经由 api 客户端
转发到规范的 FastAPI 服务，避免在 MCP 层重复实现业务逻辑。
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from crawler.bootstrap.logging import configure_sensitive_transport_logging
from crawler.bootstrap.settings import settings
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp.server.fastmcp import FastMCP

configure_sensitive_transport_logging()

mcp = FastMCP("Douyin Crawler API")


class AuthenticatedApiClient:
    """带鉴权的 FastAPI 代理客户端。

    首次请求时自动调用 /login/access-token 登录并缓存 access_token，
    请求遇到 401/403 时清空缓存重新登录并重试一次。
    用户名与密码取自 MCP_API_USERNAME / MCP_API_PASSWORD 配置，
    未配置时回退到 FIRST_SUPERUSER 超级管理员账号。
    """

    def __init__(self) -> None:
        self._token = ""
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        """FastAPI 服务基础地址（去掉末尾斜杠），取自 MCP_API_BASE_URL 配置。"""
        return settings.MCP_API_BASE_URL.rstrip("/")

    async def _login(self) -> str:
        """登录 FastAPI 服务并缓存 access_token；并发调用通过 asyncio 锁去重。

        返回：
            有效的 access_token 字符串。

        异常：
            httpx.HTTPStatusError: 登录接口返回错误状态码。
            RuntimeError: 登录响应中缺少有效的 access_token。
        """
        async with self._lock:
            if self._token:
                return self._token
            username = str(settings.MCP_API_USERNAME or settings.FIRST_SUPERUSER)
            configured_password = settings.MCP_API_PASSWORD
            password = (
                configured_password.get_secret_value()
                if configured_password
                else settings.FIRST_SUPERUSER_PASSWORD
            )
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                response = await client.post(
                    f"{self.base_url}/login/access-token",
                    data={"username": username, "password": password},
                )
            response.raise_for_status()
            payload = response.json()
            token = payload.get("access_token") if isinstance(payload, dict) else None
            if not isinstance(token, str) or not token:
                raise RuntimeError("FastAPI 登录响应缺少 access_token")
            self._token = token
            return token

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        """向 FastAPI 服务发起带 Bearer 鉴权的请求。

        首次调用会自动登录；响应为 401/403 时清空 token 重新登录并重试一次，
        之后仍失败则按错误处理。

        参数：
            method: HTTP 方法（GET/POST 等）。
            path: 以 / 开头的接口路径，会与 base_url 拼接。
            params: URL 查询参数。
            json_body: JSON 请求体。

        返回：
            接口响应解析后的 JSON 数据。

        异常：
            httpx.HTTPStatusError: 接口返回非鉴权类错误状态码，或重登录后仍返回 401/403。
            RuntimeError: 连续两次尝试后鉴权仍未通过（正常流程不可达，作为兜底）。
        """
        token = await self._login()
        for attempt in range(2):
            async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    params=params,
                    json=json_body,
                    headers={"Authorization": f"Bearer {token}"},
                )
            if response.status_code not in {401, 403} or attempt:
                response.raise_for_status()
                return response.json()
            self._token = ""
            token = await self._login()
        raise RuntimeError("FastAPI 鉴权失败")


api = AuthenticatedApiClient()


@mcp.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]
async def health_check(_request: Request) -> JSONResponse:
    """MCP 服务的健康检查端点，返回服务名与 ok 状态。"""
    return JSONResponse({"status": "ok", "service": "Douyin Crawler MCP"})


__all__ = ["AuthenticatedApiClient", "api", "health_check", "mcp"]
