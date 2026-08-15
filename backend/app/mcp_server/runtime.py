"""Shared MCP runtime and authenticated FastAPI client."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.bootstrap.settings import settings
from app.framework.logging import configure_sensitive_transport_logging

configure_sensitive_transport_logging()

mcp = FastMCP("Douyin Crawler API")


class AuthenticatedApiClient:
    """Authenticate once and proxy MCP tools to the canonical FastAPI service."""

    def __init__(self) -> None:
        self._token = ""
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        return settings.MCP_API_BASE_URL.rstrip("/")

    async def _login(self) -> str:
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
    return JSONResponse({"status": "ok", "service": "Douyin Crawler MCP"})


__all__ = ["AuthenticatedApiClient", "api", "health_check", "mcp"]
