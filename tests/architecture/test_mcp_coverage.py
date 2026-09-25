"""MCP 覆盖率契约：每个后端接口都要有对应工具，且参数与接口逐字段一致。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from crawler.api.main import app
from crawler.mcp.server import API_TOOL_NAMES, mcp

SPEC = json.loads(
    (
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "modules"
        / "mcp"
        / "src"
        / "crawler"
        / "mcp"
        / "tools_spec.json"
    ).read_text(encoding="utf-8")
)
API_PREFIX = "/api/v1"


def _tools() -> dict[str, Any]:
    listed = asyncio.run(mcp.list_tools())
    return {tool.name: tool for tool in listed}


def _api_operations() -> dict[tuple[str, str], dict[str, Any]]:
    """{(method, path): operation}，路径去掉 /api/v1 前缀。"""
    specification = app.openapi()
    operations: dict[tuple[str, str], dict[str, Any]] = {}
    for path, item in specification["paths"].items():
        for method, operation in item.items():
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            trimmed = path[len(API_PREFIX) :] if path.startswith(API_PREFIX) else path
            operations[(method.upper(), trimmed)] = operation
    return operations


def test_every_api_operation_has_an_mcp_tool() -> None:
    """后端每个 HTTP operation 都必须有一个携带 api meta 的 MCP 工具。"""
    covered = {
        (tool.meta["api"]["method"], tool.meta["api"]["path"])
        for tool in _tools().values()
        if tool.meta and tool.meta.get("api")
    }
    missing = sorted(set(_api_operations()) - covered)

    assert not missing, f"以下接口没有 MCP 工具：{missing}"
    assert len(API_TOOL_NAMES) == len(SPEC["operations"])


def test_generated_tool_names_are_unique_and_curated_tools_kept() -> None:
    """工具名唯一，且原有 32 个便捷工具保持可用（向后兼容）。"""
    names = list(_tools())
    assert len(names) == len(set(names))
    curated = {
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
        "migrate_douyin_media_to_minio",
        "get_douyin_media_summary",
        "retry_douyin_media",
        "retranslate_douyin_media",
    }
    assert curated <= set(names)


def _deref(schema: Any) -> Any:
    """把 ``$ref``（含 anyOf/oneOf/items 里的引用）解析成真实 schema。"""
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        node: Any = app.openapi()
        for part in str(schema["$ref"])[2:].split("/"):
            node = node[part]
        return _deref(node)
    for key in ("anyOf", "oneOf"):
        if isinstance(schema.get(key), list):
            schema = dict(schema)
            schema[key] = [_deref(item) for item in schema[key]]
    if isinstance(schema.get("items"), dict):
        schema = dict(schema)
        schema["items"] = _deref(schema["items"])
    return schema


def _normalize_type(raw: Any) -> tuple[str, Any, bool]:
    """把 JSON Schema 片段归一成 (类型, 枚举, 是否可空)。"""
    schema = _deref(raw)
    if not isinstance(schema, dict):
        return ("unknown", None, False)
    options = schema.get("anyOf") or schema.get("oneOf")
    nullable = False
    if isinstance(options, list):
        non_null = [item for item in options if item.get("type") != "null"]
        nullable = any(item.get("type") == "null" for item in options)
        schema = _deref(non_null[0]) if non_null else {}
    enum = schema.get("enum")
    if isinstance(enum, list) and enum and all(isinstance(item, str) for item in enum):
        return ("enum", tuple(enum), nullable)
    kind = schema.get("type")
    if kind == "array":
        item_type = _normalize_type(schema.get("items") or {})
        return ("array", item_type[0], nullable)
    if kind in {"integer", "number", "boolean", "string"}:
        return (kind, None, nullable)
    if kind == "object" or "properties" in schema:
        return ("object", None, nullable)
    return (str(kind or "object"), None, nullable)


def _expected_parameters(operation: dict[str, Any]) -> dict[str, Any]:
    """接口的参数集合：路径 + 查询 + 请求体字段（同名同义）。"""
    specification = app.openapi()
    expected: dict[str, Any] = {}
    for param in operation.get("parameters", []):
        if "$ref" in param:
            node: Any = specification
            for part in param["$ref"][2:].split("/"):
                node = node[part]
            param = node
        if param.get("in") not in {"path", "query"}:
            continue
        param_schema = dict(param.get("schema") or {})
        expected[str(param["name"])] = {
            "type": _normalize_type(param_schema),
            "required": bool(param.get("required") or param.get("in") == "path"),
        }
    body = operation.get("requestBody") or {}
    schema = (
        body.get("content", {}).get("application/json", {}).get("schema")
        if body
        else None
    )
    if isinstance(schema, dict) and "$ref" in schema:
        node = specification
        for part in schema["$ref"][2:].split("/"):
            node = node[part]
        schema = node
    if isinstance(schema, dict):
        required = set(schema.get("required") or [])
        for name, raw in (schema.get("properties") or {}).items():
            if isinstance(raw, dict) and "$ref" in raw:
                node = specification
                for part in raw["$ref"][2:].split("/"):
                    node = node[part]
                raw = node
            expected[str(name)] = {
                "type": _normalize_type(raw),
                "required": name in required,
            }
    return expected


def test_generated_tool_parameters_match_api_schema() -> None:
    """生成工具的入参名称、类型、必填性与接口 schema 完全一致。"""
    tools = _tools()
    mismatches: list[str] = []
    for operation in SPEC["operations"]:
        tool = tools[operation["name"]]
        properties = tool.inputSchema.get("properties", {})
        required = set(tool.inputSchema.get("required") or [])
        # 规格本身就是从 OpenAPI 生成的，这里再对着运行期 OpenAPI 复核一次
        api_operation = _api_operations()[(operation["method"], operation["path"])]
        expected = _expected_parameters(api_operation)
        if set(properties) != set(expected):
            mismatches.append(
                f"{operation['name']} 字段不一致："
                f"缺 {sorted(set(expected) - set(properties))} "
                f"多 {sorted(set(properties) - set(expected))}"
            )
            continue
        for name, want in expected.items():
            got = properties[name]
            got_type = _normalize_type(got)
            if got_type != want["type"]:
                # 可选参数在 MCP 侧必须带默认值，因此允许「工具可空、接口非空」；
                # 反过来（接口可空、工具非空）会导致字段无法回传，按不一致处理。
                relaxed = (
                    got_type[0] == want["type"][0]
                    and got_type[1] == want["type"][1]
                    and got_type[2]
                    and not want["type"][2]
                    and not want["required"]
                )
                if not relaxed:
                    mismatches.append(
                        f"{operation['name']}.{name} 类型不一致："
                        f"{got_type} != {want['type']}"
                    )
            got_required = name in required
            if got_required != want["required"]:
                mismatches.append(
                    f"{operation['name']}.{name} 必填性不一致："
                    f"{got_required} != {want['required']}"
                )
    assert not mismatches, "\n".join(mismatches[:20])


def _response(
    payload: Any = None, *, content_type: str = "application/json", content: bytes = b""
) -> Any:
    """构造 httpx 响应，用于替身接口客户端。"""
    import httpx

    body = content if content else json.dumps(payload or {}).encode("utf-8")
    return httpx.Response(
        200,
        content=body,
        headers={"content-type": content_type},
        request=httpx.Request("GET", "http://127.0.0.1:8000/api/v1"),
    )


def test_generated_tool_forwards_path_query_and_body(monkeypatch: Any) -> None:
    """生成工具：路径参数做替换、查询与请求体按字段透传、返回原始 JSON。"""
    from crawler.mcp import spec as mcp_spec

    calls: list[dict[str, Any]] = []

    async def fake_request_raw(method, path, *, params=None, json_body=None):  # noqa: ANN001, ANN202
        calls.append(
            {"method": method, "path": path, "params": params, "json_body": json_body}
        )
        return _response({"ok": True})

    monkeypatch.setattr(mcp_spec.api, "request_raw", fake_request_raw)
    tools = _tools()
    operations = {item["name"]: item for item in SPEC["operations"]}

    create = operations["douyin_create_task"]
    result = asyncio.run(
        mcp_spec.call_operation(
            create,
            {"crawl_type": "search", "keywords": ["露营"], "max_awemes": 5},
        )
    )
    assert result == {"ok": True}
    assert calls[0]["method"] == create["method"]
    assert calls[0]["path"] == create["path"]
    assert calls[0]["json_body"] == {
        "crawl_type": "search",
        "keywords": ["露营"],
        "max_awemes": 5,
    }
    assert calls[0]["params"] is None

    listing = operations["douyin_get_task"]
    asyncio.run(
        mcp_spec.call_operation(listing, {"task_id": "task-1", "unknown": None})
    )
    assert calls[1]["path"] == "/douyin/tasks/task-1"
    assert calls[1]["params"] is None
    assert tools["douyin_get_task"].inputSchema["required"] == ["task_id"]


def test_generated_tool_decodes_image_and_binary(monkeypatch: Any) -> None:
    """生成工具：图片内联返回，二进制返回元信息信封，文本原样返回。"""
    from crawler.mcp import spec as mcp_spec

    payloads = [
        _response(content_type="image/png", content=b"\x89PNG\r\n"),
        _response(content_type="video/mp4", content=b"\x00" * 8),
        _response(content_type="text/csv; charset=utf-8", content=b"a,b\n1,2\n"),
    ]

    async def fake_request_raw(  # noqa: ANN001, ANN202
        method,  # noqa: ARG001 - 与生产签名一致
        path,  # noqa: ARG001
        *,
        params=None,  # noqa: ANN001, ARG001
        json_body=None,  # noqa: ANN001, ARG001
    ):
        return payloads.pop(0)

    monkeypatch.setattr(mcp_spec.api, "request_raw", fake_request_raw)
    operations = {item["name"]: item for item in SPEC["operations"]}

    image = asyncio.run(
        mcp_spec.call_operation(operations["douyin_get_qrcode"], {"task_id": "task-1"})
    )
    assert type(image).__name__ == "Image"

    binary = asyncio.run(
        mcp_spec.call_operation(
            operations["douyin_download_media_file"],
            {"task_id": "task-1", "asset_id": "asset-1"},
        )
    )
    assert binary["content_type"] == "video/mp4"
    assert binary["size_bytes"] == 8

    text = asyncio.run(
        mcp_spec.call_operation(
            operations["login_recover_password_html_content"],
            {"email": "user@example.com"},
        )
    )
    assert text["text"].startswith("a,b")
