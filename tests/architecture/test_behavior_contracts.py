"""在包结构重构期间冻结对外 API 与持久化契约。

这些测试刻意比较规范化哈希，而不是在仓库中保存大量生成的快照。当确需变更
API 或数据库结构时，审查者必须先检查语义差异，再更新对应基线。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import crawler.business.model_registry  # noqa: F401 - registers every table in SQLModel.metadata
from crawler.api.main import app
from crawler.api.routes.douyin import router as douyin_router
from crawler.mcp.server import mcp
from fastapi.routing import APIRoute
from sqlmodel import SQLModel

# 对外契约基线：任何 API/DB/MCP 变更都需先审查语义差异，再更新以下常量
EXPECTED_OPENAPI_PATHS = 92
EXPECTED_OPENAPI_SCHEMAS = 134
EXPECTED_OPENAPI_SHA256 = (
    "802d651d662e98ef9897fee3b2fefb0cd8cfc72482162ab5324c01d5b9aa6c74"
)

EXPECTED_DATABASE_TABLES = 24
EXPECTED_DATABASE_METADATA_SHA256 = (
    "8112b4666f2df4bb251e55e6e45a3d1d3b9effd796fb1a18a186c89d7b586d2a"
)
EXPECTED_MCP_TOOLS = 32
EXPECTED_MCP_TOOLS_SHA256 = (
    "b7a579664ead197b1f1cbe4fd2cdf0afcd5979e58e4c65cd181688ce36076139"
)
# 抖音路由注册顺序基线：(HTTP 方法, 路径, 路由唯一 id)
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
        "DELETE",
        "/douyin/tasks/{task_id}",
        "delete_task_douyin_tasks__task_id__delete",
    ),
    (
        "POST",
        "/douyin/tasks/bulk-delete",
        "bulk_delete_tasks_douyin_tasks_bulk_delete_post",
    ),
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
        "POST",
        "/douyin/tasks/{task_id}/restart",
        "restart_task_douyin_tasks__task_id__restart_post",
    ),
    (
        "GET",
        "/douyin/media-tasks",
        "list_media_tasks_douyin_media_tasks_get",
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
    (
        "GET",
        "/douyin/request-logs",
        "list_request_logs_douyin_request_logs_get",
    ),
]


def _canonical_sha256(value: Any) -> str:
    """对任意可 JSON 序列化的值计算键排序后的规范化 SHA-256 哈希。"""
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _database_metadata_contract() -> list[dict[str, Any]]:
    """提取 SQLAlchemy 元数据中稳定且与迁移相关的部分（表、列、索引、约束）。"""

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
    """验证 OpenAPI 文档的路径数、schema 数与规范化哈希均未变化。"""
    specification = app.openapi()

    assert len(specification["paths"]) == EXPECTED_OPENAPI_PATHS
    assert len(specification["components"]["schemas"]) == EXPECTED_OPENAPI_SCHEMAS
    assert _canonical_sha256(specification) == EXPECTED_OPENAPI_SHA256


def test_douyin_route_registration_order_is_unchanged() -> None:
    """验证抖音路由的注册顺序、路径与唯一 id 与基线完全一致。"""
    contract = []
    for route in douyin_router.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = sorted(route.methods - {"HEAD", "OPTIONS"})
        contract.extend((method, route.path, route.unique_id) for method in methods)

    assert contract == EXPECTED_DOUYIN_ROUTE_ORDER


def test_database_metadata_contract_is_unchanged() -> None:
    """验证数据库表数量与元数据规范化哈希均未变化。"""
    contract = _database_metadata_contract()

    assert len(contract) == EXPECTED_DATABASE_TABLES
    assert _canonical_sha256(contract) == EXPECTED_DATABASE_METADATA_SHA256


def test_mcp_tool_contract_is_unchanged() -> None:
    """冻结 MCP 工具的名称、描述与输入/输出 schema（与注册顺序无关）。"""

    tools = asyncio.run(mcp.list_tools())
    contract = sorted(
        (tool.model_dump(mode="json") for tool in tools),
        key=lambda tool: str(tool["name"]),
    )

    assert len(contract) == EXPECTED_MCP_TOOLS
    assert _canonical_sha256(contract) == EXPECTED_MCP_TOOLS_SHA256
