"""在包结构重构期间冻结对外 API 与持久化契约。

这些测试刻意比较规范化哈希，而不是在仓库中保存大量生成的快照。当确需变更
API 或数据库结构时，审查者必须先检查语义差异，再更新对应基线。
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from typing import Any

import crawler.business.model_registry  # noqa: F401 - registers every table in SQLModel.metadata
from crawler.api.main import app
from crawler.api.routes.douyin import router as douyin_router
from crawler.mcp.server import mcp
from fastapi.routing import APIRoute
from sqlmodel import SQLModel

# 对外契约基线：任何 API/DB/MCP 变更都需先审查语义差异，再更新以下常量
EXPECTED_OPENAPI_PATHS = 95
EXPECTED_OPENAPI_SCHEMAS = 140
# 2026-09-13 本机浏览器槽位：账号绑定字段由 remote_slot 推广为按 browser_mode
# 解析的 slot（schema 数量不变，仅字段名与槽位响应新增 browser_mode）。
EXPECTED_OPENAPI_SHA256 = (
    "c41c69b8cc600702b3d3505575ce05eba788adffb24deefea7c816f4b89a6918"
)

EXPECTED_DATABASE_TABLES = 24
# 同一变更：douyin_account.remote_slot → slot（同类型、同可空性，
# 索引 ix_douyin_account_remote_slot → ix_douyin_account_slot，表数量不变）。
EXPECTED_DATABASE_METADATA_SHA256 = (
    "f41d9eb214ae95b057bc292f9e991aa76e762158952ceff5f920c0e0409d376f"
)
EXPECTED_MCP_TOOLS = 32
# 工具描述在入哈希前先经 inspect.cleandoc 归一化（见 _mcp_tool_contract），
# 以消除解释器之间的缩进差异：FastMCP 逐字取 fn.__doc__ 作工具描述
# （mcp/server/fastmcp/tools/base.py: func_doc = description or fn.__doc__ or ""），
# 而 CPython 3.13 起在编译期对 __doc__ 去缩进，3.10/3.11/3.12 则保留源码缩进。
# 不归一化时同一份源码会因解释器而得到不同哈希（实测同一 revision：
#   py3.10.21 as-is = 31149ed5…，py3.13.15 as-is = dc3d502a…），
# 而本机 venv 是 3.13、CI 是 3.10，门禁必然在一边永久变红。
# 归一化后两侧描述逐字节相同，故本常量必须是归一化后的值：
#   py3.10.21 与 py3.13.15 实测均为 25de4e2a…（工具数、名称与 input/output schema 原样保留）。
# 值从 31149ed5… 变为 25de4e2a… 仅因提取方式改为归一化，描述文案本身未变。
EXPECTED_MCP_TOOLS_SHA256 = (
    "25de4e2a2b5d258cb3140f0a403a185863235bb4e5ee75386a4e59e9f779c209"
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
        "/douyin/source-options",
        "list_source_options_douyin_source_options_get",
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
        "POST",
        "/douyin/tasks/bulk-resume",
        "bulk_resume_tasks_douyin_tasks_bulk_resume_post",
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


def _mcp_tool_contract() -> list[dict[str, Any]]:
    """提取 MCP 工具契约（按名称排序，与注册顺序无关）。

    名称与 inputSchema/outputSchema 原样保留；仅 description 做 cleandoc 归一化，
    因为它在 3.10/3.11/3.12 上保留源码缩进，而 3.13 起已在编译期被去缩进。
    描述缺失（None）时不做转换，以免抹掉「无描述」与「空描述」的区别。
    """

    contract = [tool.model_dump(mode="json") for tool in asyncio.run(mcp.list_tools())]
    for payload in contract:
        description = payload.get("description")
        if isinstance(description, str):
            payload["description"] = inspect.cleandoc(description)
    contract.sort(key=lambda payload: str(payload["name"]))
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

    contract = _mcp_tool_contract()

    assert len(contract) == EXPECTED_MCP_TOOLS
    assert _canonical_sha256(contract) == EXPECTED_MCP_TOOLS_SHA256
