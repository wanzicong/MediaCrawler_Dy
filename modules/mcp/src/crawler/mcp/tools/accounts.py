"""账号管理相关的 MCP 工具：托管账号与账号池查询。

工具函数注册到共享 FastMCP 实例，代理到 FastAPI 的 /douyin/accounts 接口。
"""

from __future__ import annotations

from typing import Any

from crawler.mcp.runtime import api, mcp


@mcp.tool()
async def list_douyin_accounts(limit: int = 100, skip: int = 0) -> dict[str, Any]:
    """查询可供任务选择的托管账号及健康状态，不返回 Cookie 或平台原始账号 ID。

    参数：
        limit: 单页返回的最大账号数量。
        skip: 分页偏移量（跳过的记录数）。

    返回：
        FastAPI 接口返回的分页账号列表 JSON。
    """
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
