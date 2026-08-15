"""Authenticated MCP tools for this capability."""

from __future__ import annotations

from typing import Any

from app.mcp_server.runtime import api, mcp


@mcp.tool()
async def list_douyin_media(
    task_id: str, limit: int = 100, skip: int = 0
) -> dict[str, Any]:
    """查询视频下载、字幕进度、错误和已完成字幕正文。"""
    result = await api.request(
        "GET",
        f"/douyin/tasks/{task_id}/media",
        params={"limit": limit, "skip": skip},
    )
    return dict(result)


@mcp.tool()
async def process_douyin_task_media(
    task_id: str,
    media_storage: str | None = None,
    translate_subtitles: bool = False,
    force_retranslate: bool = False,
    transcription_language: str = "auto",
    cookies: str | None = None,
) -> dict[str, Any]:
    """对已完成爬取任务批量下载视频，并可调用远程 API 生成或重做字幕。"""
    payload: dict[str, Any] = {
        "translate_subtitles": translate_subtitles,
        "force_retranslate": force_retranslate,
        "transcription_language": transcription_language,
    }
    if media_storage:
        payload["media_storage"] = media_storage
    if cookies:
        payload["cookies"] = cookies
    result = await api.request(
        "POST", f"/douyin/tasks/{task_id}/media/process", json_body=payload
    )
    return dict(result)


async def _request_douyin_media_migration(
    task_id: str, asset_ids: list[str]
) -> dict[str, Any]:
    result = await api.request(
        "POST",
        f"/douyin/tasks/{task_id}/media/migrate-to-minio",
        json_body={"asset_ids": asset_ids},
    )
    return dict(result)


@mcp.tool()
async def migrate_douyin_media_to_minio(
    task_id: str, asset_ids: list[str] | None = None
) -> dict[str, Any]:
    """上传本地视频到 MinIO；空列表迁移全部，完整校验成功后才删除本地文件。"""
    return await _request_douyin_media_migration(task_id, asset_ids or [])


@mcp.tool()
async def get_douyin_media_summary(task_id: str) -> dict[str, Any]:
    """汇总视频下载和字幕任务的各状态数量。"""
    result = await api.request("GET", f"/douyin/tasks/{task_id}/media-summary")
    return dict(result)


@mcp.tool()
async def retry_douyin_media(
    task_id: str,
    asset_ids: list[str] | None = None,
    retry_downloads: bool = True,
    retry_subtitles: bool = True,
) -> dict[str, Any]:
    """重试指定或全部失败的视频下载与字幕任务。"""
    result = await api.request(
        "POST",
        f"/douyin/tasks/{task_id}/media/retry",
        json_body={
            "asset_ids": asset_ids or [],
            "retry_downloads": retry_downloads,
            "retry_subtitles": retry_subtitles,
            "force_retranslate": False,
        },
    )
    return dict(result)


@mcp.tool()
async def retranslate_douyin_media(task_id: str, asset_id: str) -> dict[str, Any]:
    """按服务端配置对已下载的视频强制重新生成字幕。"""
    result = await api.request(
        "POST", f"/douyin/tasks/{task_id}/media/{asset_id}/retranslate"
    )
    return dict(result)


__all__ = [
    "list_douyin_media",
    "process_douyin_task_media",
    "_request_douyin_media_migration",
    "migrate_douyin_media_to_minio",
    "get_douyin_media_summary",
    "retry_douyin_media",
    "retranslate_douyin_media",
]
