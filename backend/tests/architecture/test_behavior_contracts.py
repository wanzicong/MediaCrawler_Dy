"""Freeze public and persistence contracts while packages are reorganized.

These tests intentionally compare canonical hashes instead of keeping large generated
snapshots in the repository.  When a deliberate API or database change is made, the
reviewer must inspect the semantic diff before updating the corresponding baseline.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from fastapi.routing import APIRoute
from sqlmodel import SQLModel

import app.models  # noqa: F401 - registers every table in SQLModel.metadata
from app.api.routes.douyin import router as douyin_router
from app.main import app
from app.mcp_server.server import mcp

EXPECTED_OPENAPI_PATHS = 76
EXPECTED_OPENAPI_SCHEMAS = 112
EXPECTED_OPENAPI_SHA256 = (
    "5e8479fc982ea71a47f72c418c39e6b1d1df11fb5034e2a0f62ef29b1ec1ba26"
)

EXPECTED_DATABASE_TABLES = 21
EXPECTED_DATABASE_METADATA_SHA256 = (
    "7ee410f1600a047043f69308fb35b9a60d7afb043ed0c83a4364bdd8ee0340e8"
)
EXPECTED_MCP_TOOLS = 32
EXPECTED_MCP_TOOLS_SHA256 = (
    "e5fe98658049e29c17765c7efaab8963bd29cd676503389fd20718fb596eaed2"
)
EXPECTED_DOUYIN_ROUTE_ORDER = [
    ("POST", "/douyin/tasks", "create_task_douyin_tasks_post"),
    ("GET", "/douyin/tasks", "list_tasks_douyin_tasks_get"),
    ("GET", "/douyin/comments", "list_comment_library_douyin_comments_get"),
    (
        "POST",
        "/douyin/comments/export",
        "export_comment_selection_douyin_comments_export_post",
    ),
    (
        "GET",
        "/douyin/library/creators",
        "list_library_creators_douyin_library_creators_get",
    ),
    (
        "GET",
        "/douyin/library/works",
        "list_library_works_douyin_library_works_get",
    ),
    (
        "POST",
        "/douyin/library/media/migrate-to-minio",
        "migrate_library_media_to_minio_douyin_library_media_migrate_to_minio_post",
    ),
    ("GET", "/douyin/tasks/{task_id}", "get_task_douyin_tasks__task_id__get"),
    (
        "GET",
        "/douyin/tasks/{task_id}/shards",
        "list_task_shards_douyin_tasks__task_id__shards_get",
    ),
    (
        "POST",
        "/douyin/tasks/{task_id}/cancel",
        "cancel_task_douyin_tasks__task_id__cancel_post",
    ),
    (
        "POST",
        "/douyin/tasks/{task_id}/resume",
        "resume_task_douyin_tasks__task_id__resume_post",
    ),
    (
        "GET",
        "/douyin/tasks/{task_id}/media",
        "list_media_douyin_tasks__task_id__media_get",
    ),
    (
        "GET",
        "/douyin/tasks/{task_id}/media-summary",
        "get_media_summary_douyin_tasks__task_id__media_summary_get",
    ),
    (
        "POST",
        "/douyin/tasks/{task_id}/media/migrate-to-minio",
        "migrate_media_to_minio_douyin_tasks__task_id__media_migrate_to_minio_post",
    ),
    (
        "POST",
        "/douyin/tasks/{task_id}/media/process",
        "process_media_douyin_tasks__task_id__media_process_post",
    ),
    (
        "POST",
        "/douyin/tasks/{task_id}/media/retry",
        "retry_media_douyin_tasks__task_id__media_retry_post",
    ),
    (
        "POST",
        "/douyin/tasks/{task_id}/media/{asset_id}/retranslate",
        "retranslate_media_douyin_tasks__task_id__media__asset_id__retranslate_post",
    ),
    (
        "GET",
        "/douyin/tasks/{task_id}/media/{asset_id}/file",
        "download_media_file_douyin_tasks__task_id__media__asset_id__file_get",
    ),
    (
        "POST",
        "/douyin/tasks/{task_id}/media/{asset_id}/preview-session",
        "create_media_preview_session_douyin_tasks__task_id__media__asset_id__preview_session_post",
    ),
    (
        "GET",
        "/douyin/tasks/{task_id}/media/{asset_id}/preview",
        "preview_media_file_douyin_tasks__task_id__media__asset_id__preview_get",
    ),
    (
        "GET",
        "/douyin/tasks/{task_id}/qrcode",
        "get_qrcode_douyin_tasks__task_id__qrcode_get",
    ),
    (
        "GET",
        "/douyin/tasks/{task_id}/works",
        "list_works_douyin_tasks__task_id__works_get",
    ),
    (
        "GET",
        "/douyin/tasks/{task_id}/works/{aweme_id}",
        "get_work_douyin_tasks__task_id__works__aweme_id__get",
    ),
    (
        "GET",
        "/douyin/tasks/{task_id}/awemes",
        "list_awemes_douyin_tasks__task_id__awemes_get",
    ),
    (
        "POST",
        "/douyin/tasks/{task_id}/awemes/{aweme_id}/comments/recrawl",
        "recrawl_aweme_comments_douyin_tasks__task_id__awemes__aweme_id__comments_recrawl_post",
    ),
    (
        "POST",
        "/douyin/tasks/{task_id}/awemes/{aweme_id}/creator/crawl",
        "crawl_aweme_creator_douyin_tasks__task_id__awemes__aweme_id__creator_crawl_post",
    ),
    (
        "GET",
        "/douyin/tasks/{task_id}/comments",
        "list_comments_douyin_tasks__task_id__comments_get",
    ),
    (
        "POST",
        "/douyin/tasks/{task_id}/exports/comments",
        "export_comments_douyin_tasks__task_id__exports_comments_post",
    ),
    (
        "POST",
        "/douyin/tasks/{task_id}/exports/subtitles",
        "export_subtitles_douyin_tasks__task_id__exports_subtitles_post",
    ),
    (
        "GET",
        "/douyin/tasks/{task_id}/actions",
        "list_actions_douyin_tasks__task_id__actions_get",
    ),
]


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _database_metadata_contract() -> list[dict[str, Any]]:
    """Return the stable, migration-relevant portion of SQLAlchemy metadata."""

    contract: list[dict[str, Any]] = []
    for table_name, table in sorted(SQLModel.metadata.tables.items()):
        contract.append(
            {
                "table": table_name,
                "columns": [
                    {
                        "name": column.name,
                        "type": str(column.type),
                        "nullable": column.nullable,
                        "primary_key": column.primary_key,
                        "foreign_keys": sorted(
                            str(foreign_key.target_fullname)
                            for foreign_key in column.foreign_keys
                        ),
                    }
                    for column in table.columns
                ],
                "indexes": sorted(
                    (
                        index.name or "",
                        tuple(column.name for column in index.columns),
                        index.unique,
                    )
                    for index in table.indexes
                ),
                "constraints": sorted(
                    (
                        type(constraint).__name__,
                        getattr(constraint, "name", None) or "",
                    )
                    for constraint in table.constraints
                ),
            }
        )
    return contract


def test_openapi_contract_is_unchanged() -> None:
    specification = app.openapi()

    assert len(specification["paths"]) == EXPECTED_OPENAPI_PATHS
    assert len(specification["components"]["schemas"]) == EXPECTED_OPENAPI_SCHEMAS
    assert _canonical_sha256(specification) == EXPECTED_OPENAPI_SHA256


def test_douyin_route_registration_order_is_unchanged() -> None:
    contract = []
    for route in douyin_router.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = sorted(route.methods - {"HEAD", "OPTIONS"})
        contract.extend((method, route.path, route.unique_id) for method in methods)

    assert contract == EXPECTED_DOUYIN_ROUTE_ORDER


def test_database_metadata_contract_is_unchanged() -> None:
    contract = _database_metadata_contract()

    assert len(contract) == EXPECTED_DATABASE_TABLES
    assert _canonical_sha256(contract) == EXPECTED_DATABASE_METADATA_SHA256


def test_mcp_tool_contract_is_unchanged() -> None:
    """Freeze MCP names, descriptions, input/output schemas independent of order."""

    tools = asyncio.run(mcp.list_tools())
    contract = sorted(
        (tool.model_dump(mode="json") for tool in tools),
        key=lambda tool: str(tool["name"]),
    )

    assert len(contract) == EXPECTED_MCP_TOOLS
    assert _canonical_sha256(contract) == EXPECTED_MCP_TOOLS_SHA256
