"""内容目录相关的 MCP 工具：关键词、标签、赛道、作品、评论与互动记录。

工具函数注册到共享 FastMCP 实例，代理到 FastAPI 的 /douyin 内容接口。
"""

from __future__ import annotations

from typing import Any, Literal

from crawler.mcp.runtime import api, mcp


@mcp.tool()
async def list_douyin_keywords(
    search: str | None = None,
    track_id: str | None = None,
    status: Literal["unprocessed", "active", "crawled", "failed"] | None = None,
    limit: int = 100,
    skip: int = 0,
) -> dict[str, Any]:
    """查询关键词资产、关联任务、爬取状态、作品数量和最近爬取时间。

    参数：
        search: 关键词模糊搜索词，为空不过滤。
        track_id: 按赛道 ID 过滤，为空不过滤。
        status: 按爬取状态过滤：unprocessed 未处理、active 采集中、
            crawled 已爬取、failed 失败。
        limit: 单页返回的最大数量。
        skip: 分页偏移量（跳过的记录数）。

    返回：
        FastAPI 接口返回的分页关键词列表 JSON。
    """
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
    """查询从作品描述抽取的抖音标签及其关联视频、任务数量。

    参数：
        search: 标签名模糊搜索词，为空不过滤。
        task_id: 按任务 ID 过滤，为空不过滤。
        track_id: 按赛道 ID 过滤，为空不过滤。
        limit: 单页返回的最大数量。
        skip: 分页偏移量（跳过的记录数）。

    返回：
        FastAPI 接口返回的分页标签列表 JSON。
    """
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
    """将指定搜索任务中的关键词幂等同步到关键词资产库并建立任务绑定。

    参数：
        task_id: 要同步关键词的搜索任务 ID。

    返回：
        FastAPI 接口返回的同步结果 JSON。
    """
    result = await api.request("POST", f"/douyin/keywords/sync/tasks/{task_id}")
    return dict(result)


@mcp.tool()
async def create_douyin_keyword_tasks(
    keyword_ids: list[str],
    track_id: str | None = None,
    mode: Literal["combined", "separate"] = "separate",
    max_awemes: int = 10,
    fetch_comments: bool = True,
    task_interval_seconds: float | None = None,
    account_id: str | None = None,
    account_pool_id: str | None = None,
) -> dict[str, Any]:
    """从关键词资产批量创建搜索任务；每个关键词固定创建一个独立任务。

    参数：
        keyword_ids: 关键词资产 ID 列表。
        track_id: 关联的赛道 ID，为空则不关联。
        mode: 兼容旧客户端的任务模式字段；无论取值为何都按一词一任务创建。
        max_awemes: 每个任务最多抓取的作品数量。
        fetch_comments: 是否同时抓取作品评论。
        task_interval_seconds: 任务完成后到下一采集任务开始前的间隔（秒），
            为空时沿用服务端请求风控区间。
        account_id: 指定单个托管账号 ID，为空由系统分配。
        account_pool_id: 指定账号池 ID，与 account_id 二选一。

    返回：
        FastAPI 接口返回的任务创建结果 JSON。
    """
    payload: dict[str, Any] = {
        "keyword_ids": keyword_ids,
        "mode": mode,
        "max_awemes": max_awemes,
        "fetch_comments": fetch_comments,
    }
    if task_interval_seconds is not None:
        payload["task_interval_seconds"] = task_interval_seconds
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
    """查询私域运营赛道、关键词数量、任务与内容产出统计。

    参数：
        search: 赛道名模糊搜索词，为空不过滤。
        enabled: 按启用状态过滤，为 None 不过滤。
        limit: 单页返回的最大数量。
        skip: 分页偏移量（跳过的记录数）。

    返回：
        FastAPI 接口返回的分页赛道列表 JSON。
    """
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
    """创建运营赛道，并将种子搜索词同步到可复用关键词资产库。

    参数：
        name: 赛道名称。
        keywords: 种子搜索词列表，会同步进关键词资产库。
        description: 赛道描述，可为空。

    返回：
        FastAPI 接口返回的赛道创建结果 JSON。
    """
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
    mode: Literal["combined", "separate"] = "separate",
    max_awemes: int = 30,
    max_comments_per_aweme: int = 10,
    account_id: str | None = None,
    account_pool_id: str | None = None,
    keyword_ids: list[str] | None = None,
    task_interval_seconds: float | None = None,
) -> dict[str, Any]:
    """使用选中的赛道关键词创建采集任务；不传或传空列表时默认全选。

    参数：
        track_id: 赛道 ID。
        mode: 兼容旧客户端的任务模式字段；无论取值为何都按一词一任务创建。
        max_awemes: 每个任务最多抓取的作品数量。
        max_comments_per_aweme: 每个作品最多抓取的评论数量。
        account_id: 指定单个托管账号 ID，为空由系统分配。
        account_pool_id: 指定账号池 ID，与 account_id 二选一。
        keyword_ids: 要使用的关键词资产 ID 列表，为 None 或空列表时使用
            赛道下全部关键词。
        task_interval_seconds: 任务完成后到下一采集任务开始前的间隔（秒），
            为空时沿用服务端请求风控区间。

    返回：
        FastAPI 接口返回的任务创建结果 JSON。
    """
    payload: dict[str, Any] = {
        "keyword_ids": keyword_ids or [],
        "mode": mode,
        "max_awemes": max_awemes,
        "fetch_comments": True,
        "max_comments_per_aweme": max_comments_per_aweme,
        "request_delay_level": "steady",
    }
    if task_interval_seconds is not None:
        payload["task_interval_seconds"] = task_interval_seconds
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
    """分页读取任务抓取到的抖音作品。

    参数：
        task_id: 任务 ID。
        limit: 单页返回的最大数量。
        skip: 分页偏移量（跳过的记录数）。

    返回：
        FastAPI 接口返回的分页作品列表 JSON。
    """
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
    """统一读取作品、发布时间、互动、已保存评论、视频存储与字幕进度。

    参数：
        task_id: 任务 ID。
        search: 作品标题/描述模糊搜索词，为空不过滤。
        sort_by: 排序字段：published_at 发布时间、liked_count 点赞数、
            comment_count 评论数、collected_count 收藏数、
            persisted_comment_count 已保存评论数、fetched_at 抓取时间。
        sort_order: 排序方向：asc 升序、desc 降序。
        download_status: 按视频下载状态过滤，为空不过滤。
        subtitle_status: 按字幕处理状态过滤，为空不过滤。
        tag_id: 按标签 ID 过滤，为空不过滤。
        limit: 单页返回的最大数量。
        skip: 分页偏移量（跳过的记录数）。

    返回：
        FastAPI 接口返回的分页作品列表 JSON。
    """
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
    """分页读取任务评论，可按作品 ID 过滤。

    参数：
        task_id: 任务 ID。
        aweme_id: 按作品 ID 过滤，为空返回任务下全部评论。
        limit: 单页返回的最大数量。
        skip: 分页偏移量（跳过的记录数）。
        sort_by: 排序字段：published_at 评论发布时间、like_count 点赞数、
            fetched_at 抓取时间。
        sort_order: 排序方向：asc 升序、desc 降序。

    返回：
        FastAPI 接口返回的分页评论列表 JSON。
    """
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
    """跨任务检索评论；comment_content 仅对评论正文进行模糊匹配。

    参数：
        comment_content: 评论正文模糊匹配词，仅匹配评论内容本身。
        search: 广义搜索词（匹配范围由服务端定义），与 comment_content 可同时使用。
        task_id: 按任务 ID 过滤。
        track_id: 按赛道 ID 过滤。
        aweme_id: 按作品 ID 过滤。
        video_creator: 按视频作者昵称过滤。
        source_keyword: 按来源关键词过滤。
        comment_type: 评论类型：all 全部、top_level 仅顶层评论、reply 仅回复。
        has_pictures: 是否带图：all 全部、yes 仅带图、no 仅无图。
        min_likes: 最小点赞数，为 None 不限制。
        max_likes: 最大点赞数，为 None 不限制。
        published_from: 评论发布时间下界（时间戳），为 None 不限制。
        published_to: 评论发布时间上界（时间戳），为 None 不限制。
        sort_by: 排序字段：published_at 发布时间、like_count 点赞数、
            sub_comment_count 子评论数、fetched_at 抓取时间。
        sort_order: 排序方向：asc 升序、desc 降序。
        limit: 单页返回的最大数量。
        skip: 分页偏移量（跳过的记录数）。

    返回：
        FastAPI 接口返回的分页评论检索结果 JSON。
    """
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
    """为任务中的单个作品创建独立评论重爬任务。

    参数：
        task_id: 任务 ID。
        aweme_id: 要重爬评论的作品 ID。
        max_comments_per_aweme: 最多抓取的评论数量。
        fetch_sub_comments: 是否同时抓取子评论（回复）。
        browser_mode: 浏览器模式覆盖配置，为空使用服务端默认。
        cookies: 本次抓取临时使用的 Cookie，为空使用服务端配置；不会持久化。

    返回：
        FastAPI 接口返回的重爬任务创建结果 JSON。
    """
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
    """从指定作品发现作者，并创建作者作品抓取任务；作者原始 ID 不会持久化。

    参数：
        task_id: 任务 ID。
        aweme_id: 用于发现作者的作品 ID。
        max_awemes: 最多抓取的作者作品数量。
        fetch_comments: 是否同时抓取作品评论。
        fetch_sub_comments: 是否同时抓取子评论（回复）。
        max_comments_per_aweme: 每个作品最多抓取的评论数量。
        browser_mode: 浏览器模式覆盖配置，为空使用服务端默认。
        cookies: 本次抓取临时使用的 Cookie，为空使用服务端配置；不会持久化。

    返回：
        FastAPI 接口返回的作者抓取任务创建结果 JSON。
    """
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
    """分页读取点赞或收藏任务生成的匿名化账号互动记录。

    参数：
        task_id: 任务 ID。
        limit: 单页返回的最大数量。
        skip: 分页偏移量（跳过的记录数）。

    返回：
        FastAPI 接口返回的分页互动记录 JSON。
    """
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
