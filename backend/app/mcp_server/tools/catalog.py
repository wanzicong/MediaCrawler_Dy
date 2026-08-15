"""Authenticated MCP tools for this capability."""

from __future__ import annotations

from typing import Any, Literal

from app.mcp_server.runtime import api, mcp


@mcp.tool()
async def list_douyin_keywords(
    search: str | None = None,
    track_id: str | None = None,
    status: Literal["unprocessed", "active", "crawled", "failed"] | None = None,
    limit: int = 100,
    skip: int = 0,
) -> dict[str, Any]:
    """查询关键词资产、关联任务、爬取状态、作品数量和最近爬取时间。"""
    params: dict[str, Any] = {"limit": limit, "skip": skip}
    if search:
        params["search"] = search
    if track_id:
        params["track_id"] = track_id
    if status:
        params["status"] = status
    result = await api.request("GET", "/douyin/keywords/", params=params)
    return dict(result)


@mcp.tool()
async def list_douyin_tags(
    search: str | None = None,
    task_id: str | None = None,
    track_id: str | None = None,
    limit: int = 100,
    skip: int = 0,
) -> dict[str, Any]:
    """查询从作品描述抽取的抖音标签及其关联视频、任务数量。"""
    params: dict[str, Any] = {"limit": limit, "skip": skip}
    if search:
        params["search"] = search
    if task_id:
        params["task_id"] = task_id
    if track_id:
        params["track_id"] = track_id
    result = await api.request("GET", "/douyin/tags/", params=params)
    return dict(result)


@mcp.tool()
async def sync_historical_douyin_tags() -> dict[str, Any]:
    """从当前账号已有作品中重新抽取并同步抖音标签。"""
    result = await api.request("POST", "/douyin/tags/sync")
    return dict(result)


@mcp.tool()
async def sync_douyin_task_keywords(task_id: str) -> dict[str, Any]:
    """将指定搜索任务中的关键词幂等同步到关键词资产库并建立任务绑定。"""
    result = await api.request("POST", f"/douyin/keywords/sync/tasks/{task_id}")
    return dict(result)


@mcp.tool()
async def create_douyin_keyword_tasks(
    keyword_ids: list[str],
    track_id: str | None = None,
    mode: Literal["combined", "separate"] = "combined",
    max_awemes: int = 10,
    fetch_comments: bool = True,
    account_id: str | None = None,
    account_pool_id: str | None = None,
) -> dict[str, Any]:
    """从关键词资产批量创建搜索任务；合并模式每 20 个关键词自动分组。"""
    payload: dict[str, Any] = {
        "keyword_ids": keyword_ids,
        "mode": mode,
        "max_awemes": max_awemes,
        "fetch_comments": fetch_comments,
    }
    if track_id:
        payload["track_id"] = track_id
    if account_id:
        payload["account_id"] = account_id
    if account_pool_id:
        payload["account_pool_id"] = account_pool_id
    result = await api.request(
        "POST", "/douyin/keywords/batch-tasks", json_body=payload
    )
    return dict(result)


@mcp.tool()
async def list_douyin_tracks(
    search: str | None = None,
    enabled: bool | None = None,
    limit: int = 100,
    skip: int = 0,
) -> dict[str, Any]:
    """查询私域运营赛道、关键词数量、任务与内容产出统计。"""
    params: dict[str, Any] = {"limit": limit, "skip": skip}
    if search:
        params["search"] = search
    if enabled is not None:
        params["enabled"] = enabled
    result = await api.request("GET", "/douyin/tracks", params=params)
    return dict(result)


@mcp.tool()
async def create_douyin_track(
    name: str,
    keywords: list[str],
    description: str = "",
) -> dict[str, Any]:
    """创建运营赛道，并将种子搜索词同步到可复用关键词资产库。"""
    result = await api.request(
        "POST",
        "/douyin/tracks",
        json_body={
            "name": name,
            "description": description,
            "keywords": keywords,
        },
    )
    return dict(result)


@mcp.tool()
async def run_douyin_track(
    track_id: str,
    mode: Literal["combined", "separate"] = "combined",
    max_awemes: int = 30,
    max_comments_per_aweme: int = 10,
    account_id: str | None = None,
    account_pool_id: str | None = None,
) -> dict[str, Any]:
    """使用赛道中全部已启用关键词创建可归因的采集任务。"""
    payload: dict[str, Any] = {
        "keyword_ids": [],
        "mode": mode,
        "max_awemes": max_awemes,
        "fetch_comments": True,
        "max_comments_per_aweme": max_comments_per_aweme,
        "request_delay_level": "steady",
    }
    if account_id:
        payload["account_id"] = account_id
    if account_pool_id:
        payload["account_pool_id"] = account_pool_id
    result = await api.request(
        "POST", f"/douyin/tracks/{track_id}/tasks", json_body=payload
    )
    return dict(result)


@mcp.tool()
async def list_douyin_awemes(
    task_id: str, limit: int = 100, skip: int = 0
) -> dict[str, Any]:
    """分页读取任务抓取到的抖音作品。"""
    result = await api.request(
        "GET",
        f"/douyin/tasks/{task_id}/awemes",
        params={"limit": limit, "skip": skip},
    )
    return dict(result)


@mcp.tool()
async def list_douyin_works(
    task_id: str,
    search: str | None = None,
    sort_by: Literal[
        "published_at",
        "liked_count",
        "comment_count",
        "collected_count",
        "persisted_comment_count",
        "fetched_at",
    ] = "published_at",
    sort_order: Literal["asc", "desc"] = "desc",
    download_status: str | None = None,
    subtitle_status: str | None = None,
    tag_id: str | None = None,
    limit: int = 100,
    skip: int = 0,
) -> dict[str, Any]:
    """统一读取作品、发布时间、互动、已保存评论、视频存储与字幕进度。"""
    params: dict[str, Any] = {
        "sort_by": sort_by,
        "sort_order": sort_order,
        "limit": limit,
        "skip": skip,
    }
    if search:
        params["search"] = search
    if download_status:
        params["download_status"] = download_status
    if subtitle_status:
        params["subtitle_status"] = subtitle_status
    if tag_id:
        params["tag_id"] = tag_id
    result = await api.request("GET", f"/douyin/tasks/{task_id}/works", params=params)
    return dict(result)


@mcp.tool()
async def list_douyin_comments(
    task_id: str,
    aweme_id: str | None = None,
    limit: int = 100,
    skip: int = 0,
    sort_by: Literal["published_at", "like_count", "fetched_at"] = "published_at",
    sort_order: Literal["asc", "desc"] = "desc",
) -> dict[str, Any]:
    """分页读取任务评论，可按作品 ID 过滤。"""
    params: dict[str, Any] = {
        "limit": limit,
        "skip": skip,
        "sort_by": sort_by,
        "sort_order": sort_order,
    }
    if aweme_id:
        params["aweme_id"] = aweme_id
    result = await api.request(
        "GET", f"/douyin/tasks/{task_id}/comments", params=params
    )
    return dict(result)


@mcp.tool()
async def search_douyin_comments(
    comment_content: str | None = None,
    search: str | None = None,
    task_id: str | None = None,
    track_id: str | None = None,
    aweme_id: str | None = None,
    video_creator: str | None = None,
    source_keyword: str | None = None,
    comment_type: Literal["all", "top_level", "reply"] = "all",
    has_pictures: Literal["all", "yes", "no"] = "all",
    min_likes: int | None = None,
    max_likes: int | None = None,
    published_from: int | None = None,
    published_to: int | None = None,
    sort_by: Literal[
        "published_at", "like_count", "sub_comment_count", "fetched_at"
    ] = "published_at",
    sort_order: Literal["asc", "desc"] = "desc",
    limit: int = 50,
    skip: int = 0,
) -> dict[str, Any]:
    """跨任务检索评论；comment_content 仅对评论正文进行模糊匹配。"""
    params: dict[str, Any] = {
        "comment_type": comment_type,
        "has_pictures": has_pictures,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "limit": limit,
        "skip": skip,
    }
    optional = {
        "comment_content": comment_content,
        "search": search,
        "task_id": task_id,
        "track_id": track_id,
        "aweme_id": aweme_id,
        "video_creator": video_creator,
        "source_keyword": source_keyword,
        "min_likes": min_likes,
        "max_likes": max_likes,
        "published_from": published_from,
        "published_to": published_to,
    }
    params.update({key: value for key, value in optional.items() if value is not None})
    result = await api.request("GET", "/douyin/comments", params=params)
    return dict(result)


@mcp.tool()
async def recrawl_douyin_aweme_comments(
    task_id: str,
    aweme_id: str,
    max_comments_per_aweme: int = 10,
    fetch_sub_comments: bool = False,
    browser_mode: str | None = None,
    cookies: str | None = None,
) -> dict[str, Any]:
    """为任务中的单个作品创建独立评论重爬任务。"""
    payload: dict[str, Any] = {
        "max_comments_per_aweme": max_comments_per_aweme,
        "fetch_sub_comments": fetch_sub_comments,
    }
    if browser_mode:
        payload["browser_mode"] = browser_mode
    if cookies:
        payload["cookies"] = cookies
    result = await api.request(
        "POST",
        f"/douyin/tasks/{task_id}/awemes/{aweme_id}/comments/recrawl",
        json_body=payload,
    )
    return dict(result)


@mcp.tool()
async def crawl_douyin_aweme_creator(
    task_id: str,
    aweme_id: str,
    max_awemes: int = 20,
    fetch_comments: bool = False,
    fetch_sub_comments: bool = False,
    max_comments_per_aweme: int = 10,
    browser_mode: str | None = None,
    cookies: str | None = None,
) -> dict[str, Any]:
    """从指定作品发现作者，并创建作者作品抓取任务；作者原始 ID 不会持久化。"""
    payload: dict[str, Any] = {
        "max_awemes": max_awemes,
        "fetch_comments": fetch_comments,
        "fetch_sub_comments": fetch_sub_comments,
        "max_comments_per_aweme": max_comments_per_aweme,
    }
    if browser_mode:
        payload["browser_mode"] = browser_mode
    if cookies:
        payload["cookies"] = cookies
    result = await api.request(
        "POST",
        f"/douyin/tasks/{task_id}/awemes/{aweme_id}/creator/crawl",
        json_body=payload,
    )
    return dict(result)


@mcp.tool()
async def list_douyin_actions(
    task_id: str, limit: int = 100, skip: int = 0
) -> dict[str, Any]:
    """分页读取点赞或收藏任务生成的匿名化账号互动记录。"""
    result = await api.request(
        "GET",
        f"/douyin/tasks/{task_id}/actions",
        params={"limit": limit, "skip": skip},
    )
    return dict(result)


__all__ = [
    "list_douyin_keywords",
    "list_douyin_tags",
    "sync_historical_douyin_tags",
    "sync_douyin_task_keywords",
    "create_douyin_keyword_tasks",
    "list_douyin_tracks",
    "create_douyin_track",
    "run_douyin_track",
    "list_douyin_awemes",
    "list_douyin_works",
    "list_douyin_comments",
    "search_douyin_comments",
    "recrawl_douyin_aweme_comments",
    "crawl_douyin_aweme_creator",
    "list_douyin_actions",
]
