"""MCP gateway composition root.

Tool implementations live in ``crawler.mcp.tools`` and continue to call
the canonical FastAPI service rather than duplicating business logic.
"""

from __future__ import annotations

import argparse
import os
import sys

import uvicorn
from crawler.mcp.runtime import AuthenticatedApiClient, api, health_check, mcp
from crawler.mcp.tools.accounts import (
    list_douyin_account_pools,
    list_douyin_accounts,
)
from crawler.mcp.tools.catalog import (
    crawl_douyin_aweme_creator,
    create_douyin_keyword_tasks,
    create_douyin_track,
    list_douyin_actions,
    list_douyin_awemes,
    list_douyin_comments,
    list_douyin_keywords,
    list_douyin_tags,
    list_douyin_tracks,
    list_douyin_works,
    recrawl_douyin_aweme_comments,
    run_douyin_track,
    search_douyin_comments,
    sync_douyin_task_keywords,
    sync_historical_douyin_tags,
)
from crawler.mcp.tools.interactions import (
    get_douyin_interaction,
    list_douyin_interactions,
    prepare_douyin_interaction,
)
from crawler.mcp.tools.media import (
    _request_douyin_media_migration,
    get_douyin_media_summary,
    list_douyin_media,
    migrate_douyin_media_to_minio,
    process_douyin_task_media,
    retranslate_douyin_media,
    retry_douyin_media,
)
from crawler.mcp.tools.tasks import (
    cancel_douyin_task,
    create_douyin_task,
    get_douyin_task,
    list_douyin_task_shards,
    list_douyin_tasks,
    resume_douyin_task,
)

from mcp.server.transport_security import TransportSecuritySettings


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
        allowed_hosts=args.allowed_host or ["127.0.0.1:*", "localhost:*", "[::1]:*"],
        allowed_origins=[],
    )
    uvicorn.run(
        mcp.streamable_http_app(),
        host=args.host,
        port=args.port,
        log_level=mcp.settings.log_level.lower(),
    )


__all__ = [
    "AuthenticatedApiClient",
    "api",
    "health_check",
    "mcp",
    "create_douyin_task",
    "list_douyin_tasks",
    "get_douyin_task",
    "list_douyin_task_shards",
    "cancel_douyin_task",
    "resume_douyin_task",
    "list_douyin_accounts",
    "list_douyin_account_pools",
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
    "prepare_douyin_interaction",
    "list_douyin_interactions",
    "get_douyin_interaction",
    "list_douyin_media",
    "process_douyin_task_media",
    "_request_douyin_media_migration",
    "migrate_douyin_media_to_minio",
    "get_douyin_media_summary",
    "retry_douyin_media",
    "retranslate_douyin_media",
    "main",
]


if __name__ == "__main__":
    main()
