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
    download_media: bool = False,
    media_storage: Literal["local", "minio"] | None = None,
    translate_subtitles: bool = False,
    media_processing_mode: Literal["immediate", "batch"] = "immediate",
    transcription_language: str = "auto",
) -> dict[str, Any]:
    """创建抖音任务，可指定本机/远程 CDP 和媒体处理策略。"""
    values = targets or []
    payload: dict[str, Any] = {
        "crawl_type": crawl_type,
        "login_type": "qrcode",
        "max_awemes": max_awemes,
        "fetch_comments": fetch_comments,
        "download_media": download_media or translate_subtitles,
        "translate_subtitles": translate_subtitles,
        "media_processing_mode": (
            media_processing_mode if download_media or translate_subtitles else "none"
        ),
        "transcription_language": transcription_language,
    }
    if browser_mode is not None:
        payload["browser_mode"] = browser_mode
    if media_storage is not None:
        payload["media_storage"] = media_storage
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
async def list_douyin_comments(
    task_id: str,
    aweme_id: str | None = None,
    limit: int = 100,
    skip: int = 0,
) -> dict[str, Any]:
    """分页读取任务评论，可按作品 ID 过滤。"""
    params: dict[str, Any] = {"limit": limit, "skip": skip}
    if aweme_id:
        params["aweme_id"] = aweme_id
    result = await api.request(
        "GET", f"/douyin/tasks/{task_id}/comments", params=params
    )
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
