"""Authenticated MCP tools for this capability."""

from __future__ import annotations

from typing import Any

from crawler.mcp.runtime import api, mcp


@mcp.tool()
async def list_douyin_accounts(limit: int = 100, skip: int = 0) -> dict[str, Any]:
    """查询可供任务选择的托管账号及健康状态，不返回 Cookie 或平台原始账号 ID。"""
    result = await api.request(
        "GET", "/douyin/accounts", params={"limit": limit, "skip": skip}
    )
    return dict(result)


@mcp.tool()
async def list_douyin_account_pools() -> dict[str, Any]:
    """查询账号池、调度策略和池内账号的安全状态。"""
    result = await api.request("GET", "/douyin/accounts/pools")
    return dict(result)


__all__ = [
    "list_douyin_accounts",
    "list_douyin_account_pools",
]
