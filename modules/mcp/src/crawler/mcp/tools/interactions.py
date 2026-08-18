"""Authenticated MCP tools for this capability."""

from __future__ import annotations

from typing import Any, Literal

from crawler.mcp.runtime import api, mcp


@mcp.tool()
async def prepare_douyin_interaction(
    task_id: str,
    aweme_id: str,
    account_id: str,
    interaction_type: Literal["video_comment", "comment_reply", "creator_message"],
    content: str,
    target_comment_id: str | None = None,
) -> dict[str, Any]:
    """创建抖音互动草稿。只生成待确认任务，必须由用户在 Web 页面二次确认后才会发送。"""
    payload: dict[str, Any] = {
        "task_id": task_id,
        "aweme_id": aweme_id,
        "account_id": account_id,
        "interaction_type": interaction_type,
        "content": content,
    }
    if target_comment_id:
        payload["target_comment_id"] = target_comment_id
    checked = await api.request(
        "POST", "/douyin/interactions/preflight", json_body=payload
    )
    if not isinstance(checked, dict) or not checked.get("allowed"):
        return {
            "prepared": False,
            "preflight": checked,
            "message": "发送前检查未通过，没有创建互动任务",
        }
    result = await api.request("POST", "/douyin/interactions", json_body=payload)
    return {
        "prepared": True,
        "interaction": result,
        "message": "互动草稿已创建，请在 Web 页面确认发送",
    }


@mcp.tool()
async def list_douyin_interactions(
    task_id: str | None = None,
    track_id: str | None = None,
    aweme_id: str | None = None,
    interaction_type: Literal["video_comment", "comment_reply", "creator_message"]
    | None = None,
    status: Literal[
        "pending_confirmation",
        "queued",
        "running",
        "succeeded",
        "failed",
        "blocked",
        "needs_review",
        "cancelled",
    ]
    | None = None,
    limit: int = 100,
    skip: int = 0,
) -> dict[str, Any]:
    """查询互动任务及安全状态，不包含 Cookie、原始作者账号标识或完整发送内容。"""
    params: dict[str, Any] = {"limit": limit, "skip": skip}
    if task_id:
        params["task_id"] = task_id
    if track_id:
        params["track_id"] = track_id
    if aweme_id:
        params["aweme_id"] = aweme_id
    if interaction_type:
        params["interaction_type"] = interaction_type
    if status:
        params["status"] = status
    result = await api.request("GET", "/douyin/interactions", params=params)
    return dict(result)


@mcp.tool()
async def get_douyin_interaction(interaction_id: str) -> dict[str, Any]:
    """读取单个互动任务、状态历史和当前用户可见的发送内容。该工具不能确认发送。"""
    result = await api.request("GET", f"/douyin/interactions/{interaction_id}")
    return dict(result)


__all__ = [
    "prepare_douyin_interaction",
    "list_douyin_interactions",
    "get_douyin_interaction",
]
