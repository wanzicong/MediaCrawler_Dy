"""抖音采集任务相关的 MCP 工具：任务创建、查询、分片、取消与断点恢复。

工具函数注册到共享 FastMCP 实例，代理到 FastAPI 的 /douyin/tasks 接口。
"""

from __future__ import annotations

from typing import Any, Literal

from crawler.mcp.runtime import api, mcp


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
    """创建抖音任务，可使用临时 CDP、托管账号或账号池并行分片。

    登录方式固定为扫码（qrcode）；targets 的含义随 crawl_type 变化。
    开启 translate_subtitles 会自动打开视频下载。

    参数：
        crawl_type: 采集类型：search 关键词搜索、detail 按作品 ID 抓详情、
            creator 按作者抓作品、liked 账号点赞列表、collected 账号收藏列表。
        targets: 采集目标列表，按 crawl_type 分别表示关键词、作品 ID 或
            作者 ID；liked / collected 类型无需传入。
        track_id: 关联的赛道 ID，为空则不关联。
        browser_mode: 浏览器模式：local 本地浏览器、remote 远程 CDP，为
            None 使用服务端默认。
        max_awemes: 最多抓取的作品数量。
        fetch_comments: 是否同时抓取作品评论。
        request_delay_level: 请求间隔档位：fast 较快、steady 均衡、
            ultra_steady 最保守。
        download_media: 是否下载视频。
        media_storage: 视频存储位置：local 本地、minio 对象存储，为 None
            使用服务端默认。
        translate_subtitles: 是否生成字幕（会自动开启视频下载）。
        media_processing_mode: 媒体处理时机：immediate 任务完成后立即处理、
            batch 批量处理；未开启下载/字幕时服务端按 none 处理。
        transcription_language: 转写语言，auto 表示自动识别。
        account_id: 指定单个托管账号 ID。
        account_ids: 指定多个托管账号 ID 并行分片，与 account_id 二选一。
        account_pool_id: 指定账号池 ID，优先级低于 account_id / account_ids。
        account_strategy: 账号调度策略：least_loaded 最少负载优先、
            round_robin 轮询、weighted_round_robin 加权轮询。

    返回：
        FastAPI 接口返回的任务创建结果 JSON。
    """
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
    """分页查询当前 MCP 服务账号可见的抖音任务。

    参数：
        limit: 单页返回的最大数量。
        skip: 分页偏移量（跳过的记录数）。
        track_id: 按赛道 ID 过滤，为空不过滤。

    返回：
        FastAPI 接口返回的分页任务列表 JSON。
    """
    params: dict[str, Any] = {"limit": limit, "skip": skip}
    if track_id:
        params["track_id"] = track_id
    result = await api.request("GET", "/douyin/tasks", params=params)
    return dict(result)


@mcp.tool()
async def get_douyin_task(task_id: str) -> dict[str, Any]:
    """查询抖音任务状态、爬取数量和处理配置。

    参数：
        task_id: 任务 ID。

    返回：
        FastAPI 接口返回的任务详情 JSON。
    """
    result = await api.request("GET", f"/douyin/tasks/{task_id}")
    return dict(result)


@mcp.tool()
async def list_douyin_task_shards(task_id: str) -> dict[str, Any]:
    """查询多账号任务的分片、账号别名、作品/评论进度和失败原因。

    参数：
        task_id: 任务 ID。

    返回：
        FastAPI 接口返回的任务分片列表 JSON。
    """
    result = await api.request("GET", f"/douyin/tasks/{task_id}/shards")
    return dict(result)


@mcp.tool()
async def cancel_douyin_task(task_id: str) -> dict[str, Any]:
    """取消正在爬取或处理媒体的抖音任务。

    参数：
        task_id: 任务 ID。

    返回：
        FastAPI 接口返回的取消结果 JSON。
    """
    result = await api.request("POST", f"/douyin/tasks/{task_id}/cancel")
    return dict(result)


@mcp.tool()
async def resume_douyin_task(
    task_id: str,
    resume_crawl: bool | None = None,
    resume_media: bool | None = None,
    cookies: str | None = None,
) -> dict[str, Any]:
    """从持久化断点继续爬取、视频下载和字幕任务；Cookie 仅用于本次恢复。

    参数：
        task_id: 任务 ID。
        resume_crawl: 是否恢复爬取，为 None 由服务端按断点状态决定。
        resume_media: 是否恢复视频下载与字幕任务，为 None 由服务端按断点
            状态决定。
        cookies: 本次恢复临时使用的 Cookie，为空使用服务端配置；不会持久化。

    返回：
        FastAPI 接口返回的恢复结果 JSON。
    """
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
