from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any, Literal

import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.logging import configure_sensitive_transport_logging

configure_sensitive_transport_logging()

mcp = FastMCP("Douyin Crawler API")


class AuthenticatedApiClient:
    """Authenticate once and proxy MCP tools to the canonical FastAPI service."""

    def __init__(self) -> None:
        self._token = ""
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        return settings.MCP_API_BASE_URL.rstrip("/")

    async def _login(self) -> str:
        async with self._lock:
            if self._token:
                return self._token
            username = str(settings.MCP_API_USERNAME or settings.FIRST_SUPERUSER)
            configured_password = settings.MCP_API_PASSWORD
            password = (
                configured_password.get_secret_value()
                if configured_password
                else settings.FIRST_SUPERUSER_PASSWORD
            )
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                response = await client.post(
                    f"{self.base_url}/login/access-token",
                    data={"username": username, "password": password},
                )
            response.raise_for_status()
            payload = response.json()
            token = payload.get("access_token") if isinstance(payload, dict) else None
            if not isinstance(token, str) or not token:
                raise RuntimeError("FastAPI 登录响应缺少 access_token")
            self._token = token
            return token

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        token = await self._login()
        for attempt in range(2):
            async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    params=params,
                    json=json_body,
                    headers={"Authorization": f"Bearer {token}"},
                )
            if response.status_code not in {401, 403} or attempt:
                response.raise_for_status()
                return response.json()
            self._token = ""
            token = await self._login()
        raise RuntimeError("FastAPI 鉴权失败")


api = AuthenticatedApiClient()


@mcp.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]
async def health_check(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "Douyin Crawler MCP"})


@mcp.tool()
async def create_douyin_task(
    crawl_type: Literal["search", "detail", "creator", "liked", "collected"],
    targets: list[str] | None = None,
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
async def list_douyin_tasks(limit: int = 20, skip: int = 0) -> dict[str, Any]:
    """分页查询当前 MCP 服务账号可见的抖音任务。"""
    result = await api.request(
        "GET", "/douyin/tasks", params={"limit": limit, "skip": skip}
    )
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


@mcp.tool()
async def list_douyin_keywords(
    search: str | None = None,
    status: Literal["unprocessed", "active", "crawled", "failed"] | None = None,
    limit: int = 100,
    skip: int = 0,
) -> dict[str, Any]:
    """查询关键词资产、关联任务、爬取状态、作品数量和最近爬取时间。"""
    params: dict[str, Any] = {"limit": limit, "skip": skip}
    if search:
        params["search"] = search
    if status:
        params["status"] = status
    result = await api.request("GET", "/douyin/keywords/", params=params)
    return dict(result)


@mcp.tool()
async def list_douyin_tags(
    search: str | None = None,
    task_id: str | None = None,
    limit: int = 100,
    skip: int = 0,
) -> dict[str, Any]:
    """查询从作品描述抽取的抖音标签及其关联视频、任务数量。"""
    params: dict[str, Any] = {"limit": limit, "skip": skip}
    if search:
        params["search"] = search
    if task_id:
        params["task_id"] = task_id
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
    result = await api.request(
        "GET", f"/douyin/tasks/{task_id}/works", params=params
    )
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
async def prepare_douyin_interaction(
    task_id: str,
    aweme_id: str,
    account_id: str,
    interaction_type: Literal[
        "video_comment", "comment_reply", "creator_message"
    ],
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
    aweme_id: str | None = None,
    interaction_type: Literal[
        "video_comment", "comment_reply", "creator_message"
    ]
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


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Douyin Crawler MCP gateway")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.getenv("DOUYIN_MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.getenv("DOUYIN_MCP_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("DOUYIN_MCP_PORT", "8766"))
    )
    parser.add_argument("--path", default=os.getenv("DOUYIN_MCP_PATH", "/mcp"))
    parser.add_argument("--allowed-host", action="append", default=[])
    args = parser.parse_args(argv)
    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return
    if args.host in {"0.0.0.0", "::"} and not args.allowed_host:
        raise SystemExit("监听通配地址时必须至少提供一个 --allowed-host")
    mcp.settings.host = args.host
    mcp.settings.port = args.port
    mcp.settings.streamable_http_path = args.path
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=args.allowed_host
        or ["127.0.0.1:*", "localhost:*", "[::1]:*"],
        allowed_origins=[],
    )
    uvicorn.run(
        mcp.streamable_http_app(),
        host=args.host,
        port=args.port,
        log_level=mcp.settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
