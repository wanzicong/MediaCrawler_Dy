"""从后端 OpenAPI 生成 MCP 工具规格（一个 HTTP operation 对应一个 MCP 工具）。

用法::

    uv run python -c "import crawler.api.main, json, pathlib; \\
        pathlib.Path('frontend/openapi.json').write_text(json.dumps(crawler.api.main.app.openapi()), encoding='utf-8')"
    uv run python scripts/generate_mcp_tools.py

产物：``modules/mcp/src/crawler/mcp/tools_spec.json``，由
``crawler.mcp.spec`` 在导入时装配成 MCP 工具。工具的参数名、类型、
必填性与默认值全部取自 OpenAPI，因此与 HTTP 接口逐字段一致；
返回值就是接口响应体（二进制接口见 spec 中的 ``response`` 说明）。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "frontend" / "openapi.json"
TARGET = ROOT / "modules" / "mcp" / "src" / "crawler" / "mcp" / "tools_spec.json"
API_PREFIX = "/api/v1"

# OpenAPI 里声明成 JSON、实际返回文件/图片的接口（运行期按真实 content-type
# 判别并转换，这里只用于生成工具描述与《MCP 使用指南》里的说明）。
BINARY_OPERATIONS = {
    "douyin-download_media_file": "file",
    "douyin-preview_media_file": "file",
    "douyin-preview_online_media": "file",
    "douyin-get_qrcode": "image",
    "douyin-interactions-get_interaction_event_screenshot": "image",
    "douyin-export_comment_selection": "file",
    "douyin-export_comments": "file",
    "douyin-export_subtitles": "file",
}


def _deref(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """把 ``$ref`` 解析成真实 schema（只处理本地引用）。"""
    seen = 0
    while isinstance(schema, dict) and "$ref" in schema and seen < 5:
        ref = str(schema["$ref"])
        if not ref.startswith("#/"):
            return {}
        node: Any = spec
        for part in ref[2:].split("/"):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        schema = node if isinstance(node, dict) else {}
        seen += 1
    return schema


def _nullable(
    spec: dict[str, Any], schema: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    """拆出 ``anyOf`` 里的可空分支，返回 (非空 schema, 是否可空)。"""
    schema = _deref(spec, schema)
    options = schema.get("anyOf") or schema.get("oneOf")
    if isinstance(options, list):
        non_null = [
            _deref(spec, item)
            for item in options
            if not (isinstance(item, dict) and item.get("type") == "null")
        ]
        nullable = any(
            isinstance(item, dict) and item.get("type") == "null" for item in options
        )
        if non_null:
            merged = dict(non_null[0])
            if non_null[0].get("$ref"):
                merged = dict(_deref(spec, non_null[0]))
            return merged, nullable
    return schema, False


def _type_of(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """把 JSON Schema 收敛成生成器需要的类型描述。"""
    schema, nullable = _nullable(spec, schema)
    enum = schema.get("enum")
    if isinstance(enum, list) and enum and all(isinstance(item, str) for item in enum):
        return {"type": "string", "enum": enum, "nullable": nullable}
    kind = schema.get("type")
    if kind == "array":
        item = _type_of(spec, schema.get("items") or {})
        return {"type": "array", "items": item, "nullable": nullable}
    if kind == "object" or "properties" in schema:
        return {"type": "object", "nullable": nullable}
    if kind in {"integer", "number", "boolean", "string"}:
        return {"type": kind, "nullable": nullable}
    # 未标注类型的自由字段（例如 additionalProperties）
    return {"type": "object", "nullable": nullable}


def _description(schema: dict[str, Any]) -> str:
    text = schema.get("description") or schema.get("title") or ""
    return " ".join(str(text).split())


def _tool_name(operation_id: str, used: set[str]) -> str:
    name = re.sub(r"[^0-9a-zA-Z_]+", "_", operation_id).strip("_").lower()
    if not name:
        name = "api_operation"
    candidate = name
    index = 2
    while candidate in used:
        candidate = f"{name}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def _body_params(
    spec: dict[str, Any], operation: dict[str, Any]
) -> tuple[list[dict[str, Any]], bool]:
    body = operation.get("requestBody") or {}
    if not body:
        return [], False
    content = body.get("content", {})
    schema = _deref(spec, content.get("application/json", {}).get("schema", {}))
    required = set(schema.get("required") or [])
    properties = schema.get("properties") or {}
    params = []
    for name, raw in properties.items():
        resolved = _deref(spec, raw)
        entry: dict[str, Any] = {
            "name": str(name),
            "required": name in required,
            "description": _description(resolved),
            **_type_of(spec, raw),
        }
        if "default" in resolved:
            entry["default"] = resolved["default"]
        params.append(entry)
    return params, bool(body.get("required", False))


def _response_kind(operation_id: str) -> str:
    return BINARY_OPERATIONS.get(operation_id, "json")


def _operation_entry(
    spec: dict[str, Any],
    path: str,
    method: str,
    operation: dict[str, Any],
    used_names: set[str],
) -> dict[str, Any]:
    operation_id = str(operation.get("operationId") or f"{method}_{path}")
    path_params: list[dict[str, Any]] = []
    query_params: list[dict[str, Any]] = []
    for raw in operation.get("parameters", []):
        param = _deref(spec, raw)
        location = param.get("in")
        if location not in {"path", "query"}:
            # header / cookie 参数（媒体预览的 Range、票据）由浏览器场景使用，
            # MCP 侧不暴露，避免与鉴权头混淆
            continue
        entry = {
            "name": str(param.get("name")),
            "required": bool(param.get("required", location == "path")),
            "description": _description(param),
            **_type_of(spec, param.get("schema") or {}),
        }
        if "default" in (param.get("schema") or {}):
            entry["default"] = param["schema"]["default"]
        (path_params if location == "path" else query_params).append(entry)
    body_params, body_required = _body_params(spec, operation)
    summary = operation.get("summary") or ""
    description = _description(operation) or summary or operation_id
    entry = {
        "name": _tool_name(operation_id, used_names),
        "operation_id": operation_id,
        "title": summary,
        "description": description,
        "method": method.upper(),
        "path": path[len(API_PREFIX) :] if path.startswith(API_PREFIX) else path,
        "path_params": path_params,
        "query_params": query_params,
        "body_params": body_params,
        "body_required": body_required,
        "response": _response_kind(operation_id),
        "tags": operation.get("tags") or [],
    }
    return entry


def build_spec() -> dict[str, Any]:
    """读取 OpenAPI 并构建工具规格。"""
    raw = SOURCE.read_text(encoding="utf-8")
    spec = json.loads(raw)
    used_names: set[str] = set()
    operations: list[dict[str, Any]] = []
    for path, item in sorted(spec["paths"].items()):
        for method in sorted(item):
            operations.append(
                _operation_entry(spec, path, method, item[method], used_names)
            )
    return {
        "source": "frontend/openapi.json",
        "source_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "operation_count": len(operations),
        "operations": operations,
    }


def main() -> None:
    payload = build_spec()
    TARGET.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    names = [item["name"] for item in payload["operations"]]
    binary = [
        item["name"] for item in payload["operations"] if item["response"] != "json"
    ]
    sys.stdout.write(
        f"生成 {payload['operation_count']} 个工具 → {TARGET}\n"
        f"  示例：{', '.join(names[:6])} …\n"
        f"  非 JSON 响应工具 {len(binary)} 个：{', '.join(binary) or '无'}\n"
    )


if __name__ == "__main__":
    main()
