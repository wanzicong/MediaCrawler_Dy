"""Authenticated MCP tools for this capability."""

from __future__ import annotations

from typing import Any, Literal

from app.mcp_server.runtime import api, mcp


@mcp.tool()
async def create_douyin_task(
    crawl_type: Literal["search", "detail", "creator", "liked", "collected"],
    targets: list[str] | None = None,
    track_id: str | None = None,
    browser_mode: Literal["local", "remote"] | None = None,
    max_awemes: int = 10,
    fetch_comments: bool = True,
    request_delay_level: Literal["fast", "steady", "ultra_steady"] = "steady",
    download_media: bool = False,
    media_storage: Literal["local", "minio"] | None = None,
    translate_subtitles: bool = False,
    media_processing_mode: Literal["immediate", "batch"] = "immediate",
    transcription_language: str = "auto",
    account_id: str | None = None,
    account_ids: list[str] | None = None,
    account_pool_id: str | None = None,
    account_strategy: Literal[
        "least_loaded", "round_robin", "weighted_round_robin"
    ] = "least_loaded",
) -> dict[str, Any]:
    """创建抖音任务，可使用临时 CDP、托管账号或账号池并行分片。"""
    values = targets or []
    payload: dict[str, Any] = {
        "crawl_type": crawl_type,
        "login_type": "qrcode",
        "max_awemes": max_awemes,
        "fetch_comments": fetch_comments,
        "request_delay_level": request_delay_level,
        "download_media": download_media or translate_subtitles,
        "translate_subtitles": translate_subtitles,
        "media_processing_mode": (
            media_processing_mode if download_media or translate_subtitles else "none"
        ),
        "transcription_language": transcription_language,
        "account_strategy": account_strategy,
    }
    if track_id:
        payload["track_id"] = track_id
    if browser_mode is not None:
        payload["browser_mode"] = browser_mode
    if media_storage is not None:
        payload["media_storage"] = media_storage
    if account_id:
        payload["account_id"] = account_id
    elif account_ids:
        payload["account_ids"] = account_ids
    elif account_pool_id:
        payload["account_pool_id"] = account_pool_id
    if crawl_type == "search":
        payload["keywords"] = values
    elif crawl_type == "detail":
        payload["video_ids"] = values
    elif crawl_type == "creator":
        payload["creator_ids"] = values
    result = await api.request("POST", "/douyin/tasks", json_body=payload)
    return dict(result)


@mcp.tool()
async def list_douyin_tasks(
    limit: int = 20,
    skip: int = 0,
    track_id: str | None = None,
) -> dict[str, Any]:
    """分页查询当前 MCP 服务账号可见的抖音任务。"""
    params: dict[str, Any] = {"limit": limit, "skip": skip}
    if track_id:
        params["track_id"] = track_id
    result = await api.request("GET", "/douyin/tasks", params=params)
    return dict(result)


@mcp.tool()
async def get_douyin_task(task_id: str) -> dict[str, Any]:
    """查询抖音任务状态、爬取数量和处理配置。"""
    result = await api.request("GET", f"/douyin/tasks/{task_id}")
    return dict(result)


@mcp.tool()
async def list_douyin_task_shards(task_id: str) -> dict[str, Any]:
    """查询多账号任务的分片、账号别名、作品/评论进度和失败原因。"""
    result = await api.request("GET", f"/douyin/tasks/{task_id}/shards")
    return dict(result)


@mcp.tool()
async def cancel_douyin_task(task_id: str) -> dict[str, Any]:
    """取消正在爬取或处理媒体的抖音任务。"""
    result = await api.request("POST", f"/douyin/tasks/{task_id}/cancel")
    return dict(result)


@mcp.tool()
async def resume_douyin_task(
    task_id: str,
    resume_crawl: bool | None = None,
    resume_media: bool | None = None,
    cookies: str | None = None,
) -> dict[str, Any]:
    """从持久化断点继续爬取、视频下载和字幕任务；Cookie 仅用于本次恢复。"""
    payload: dict[str, Any] = {}
    if resume_crawl is not None:
        payload["resume_crawl"] = resume_crawl
    if resume_media is not None:
        payload["resume_media"] = resume_media
    if cookies:
        payload["cookies"] = cookies
    result = await api.request(
        "POST", f"/douyin/tasks/{task_id}/resume", json_body=payload
    )
    return dict(result)


__all__ = [
    "create_douyin_task",
    "list_douyin_tasks",
    "get_douyin_task",
    "list_douyin_task_shards",
    "cancel_douyin_task",
    "resume_douyin_task",
]
