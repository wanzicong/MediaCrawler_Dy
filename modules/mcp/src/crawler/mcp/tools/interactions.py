"""抖音互动相关的 MCP 工具：互动草稿创建、查询与详情读取。

互动（评论、回复、私信）遵循「草稿 + 人工确认」安全模型：MCP 工具
只负责创建待确认任务，实际发送必须由用户在 Web 页面二次确认。
"""

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
    """创建抖音互动草稿。只生成待确认任务，必须由用户在 Web 页面二次确认后才会发送。

    先调用服务端发送前检查（preflight），未通过时不会创建互动任务。

    参数：
        task_id: 关联的采集任务 ID。
        aweme_id: 目标作品 ID。
        account_id: 执行互动的托管账号 ID。
        interaction_type: 互动类型：video_comment 评论作品、comment_reply
            回复评论、creator_message 私信作者。
        content: 要发送的文本内容。
        target_comment_id: interaction_type 为 comment_reply 时的目标评论 ID。

    返回：
        包含 prepared（是否已创建草稿）、interaction 或 preflight（检查
        详情）与 message（中文提示信息）的字典。
    """
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
    """查询互动任务及安全状态，不包含 Cookie、原始作者账号标识或完整发送内容。

    参数：
        task_id: 按采集任务 ID 过滤，为空不过滤。
        track_id: 按赛道 ID 过滤，为空不过滤。
        aweme_id: 按作品 ID 过滤，为空不过滤。
        interaction_type: 按互动类型过滤：video_comment 评论作品、
            comment_reply 回复评论、creator_message 私信作者。
        status: 按状态过滤：pending_confirmation 待确认、queued 排队中、
            running 执行中、succeeded 已成功、failed 已失败、blocked 被
            安全策略拦截、needs_review 需要人工复核、cancelled 已取消。
        limit: 单页返回的最大数量。
        skip: 分页偏移量（跳过的记录数）。

    返回：
        FastAPI 接口返回的分页互动任务列表 JSON。
    """
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
    """读取单个互动任务、状态历史和当前用户可见的发送内容。该工具不能确认发送。

    参数：
        interaction_id: 互动任务 ID。

    返回：
        FastAPI 接口返回的互动任务详情 JSON。
    """
    result = await api.request("GET", f"/douyin/interactions/{interaction_id}")
    return dict(result)


__all__ = [
    "prepare_douyin_interaction",
    "list_douyin_interactions",
    "get_douyin_interaction",
]
