"""媒体资产相关的 MCP 工具：视频下载、字幕生成、MinIO 迁移与失败重试。

工具函数注册到共享 FastMCP 实例，代理到 FastAPI 的 /douyin/tasks/{id}/media
系列接口。
"""

from __future__ import annotations

from typing import Any

from crawler.mcp.runtime import api, mcp


@mcp.tool()
async def list_douyin_media(
    task_id: str, limit: int = 100, skip: int = 0
) -> dict[str, Any]:
    """查询视频下载、字幕进度、错误和已完成字幕正文。

    参数：
        task_id: 任务 ID。
        limit: 单页返回的最大数量。
        skip: 分页偏移量（跳过的记录数）。

    返回：
        FastAPI 接口返回的分页媒体资产列表 JSON。
    """
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
    """对已完成爬取任务批量下载视频，并可调用远程 API 生成或重做字幕。

    参数：
        task_id: 任务 ID。
        media_storage: 视频存储位置覆盖配置（如 local / minio），为空使用
            服务端默认。
        translate_subtitles: 是否生成字幕。
        force_retranslate: 已有字幕时是否强制重新生成。
        transcription_language: 转写语言，auto 表示自动识别。
        cookies: 本次下载临时使用的 Cookie，为空使用服务端配置；不会持久化。

    返回：
        FastAPI 接口返回的媒体处理结果 JSON。
    """
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
    """调用 FastAPI 的 MinIO 迁移接口；asset_ids 为空列表时迁移任务下全部资产。"""
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
    """上传本地视频到 MinIO；空列表迁移全部，完整校验成功后才删除本地文件。

    参数：
        task_id: 任务 ID。
        asset_ids: 要迁移的媒体资产 ID 列表，为 None 或空列表时迁移任务下
            全部本地视频。

    返回：
        FastAPI 接口返回的迁移结果 JSON。
    """
    return await _request_douyin_media_migration(task_id, asset_ids or [])


@mcp.tool()
async def get_douyin_media_summary(task_id: str) -> dict[str, Any]:
    """汇总视频下载和字幕任务的各状态数量。

    参数：
        task_id: 任务 ID。

    返回：
        FastAPI 接口返回的媒体状态统计 JSON。
    """
    result = await api.request("GET", f"/douyin/tasks/{task_id}/media-summary")
    return dict(result)


@mcp.tool()
async def retry_douyin_media(
    task_id: str,
    asset_ids: list[str] | None = None,
    retry_downloads: bool = True,
    retry_subtitles: bool = True,
) -> dict[str, Any]:
    """重试指定或全部失败的视频下载与字幕任务。

    参数：
        task_id: 任务 ID。
        asset_ids: 要重试的媒体资产 ID 列表，为 None 或空列表时重试任务下
            全部失败资产。
        retry_downloads: 是否重试失败的视频下载。
        retry_subtitles: 是否重试失败的字幕任务。

    返回：
        FastAPI 接口返回的重试结果 JSON。
    """
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
    """按服务端配置对已下载的视频强制重新生成字幕。

    参数：
        task_id: 任务 ID。
        asset_id: 要重新生成字幕的媒体资产 ID。

    返回：
        FastAPI 接口返回的字幕重生成结果 JSON。
    """
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
