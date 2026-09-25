"""按 OpenAPI 规格装配 MCP 工具：一个 HTTP operation 对应一个 MCP 工具。

设计要点：

* **参数与接口逐字段一致**：工具的参数名、类型、枚举、必填性与默认值全部由
  ``tools_spec.json``（从后端 OpenAPI 生成）推出，不做裁剪或重命名。
* **结果一致**：工具返回接口响应体本身；返回文件/图片/文本的接口按运行期
  ``content-type`` 转换（图片内联、文本原样、二进制给元信息信封）。
* **不复制业务逻辑**：所有调用都经由 ``crawler.mcp.runtime.api`` 走项目 HTTP API。

``tools_spec.json`` 由 ``scripts/generate_mcp_tools.py`` 生成并随代码提交。
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import quote

import httpx
from crawler.mcp.runtime import api, mcp

from mcp.server.fastmcp.utilities.types import Image

SPEC_PATH = Path(__file__).with_name("tools_spec.json")
# 图片内联上限：超过则只回元信息，避免把大文件塞进模型上下文
INLINE_IMAGE_MAX_BYTES = 512 * 1024


def load_spec() -> dict[str, Any]:
    """读取工具规格（由 ``scripts/generate_mcp_tools.py`` 生成）。"""
    return cast(dict[str, Any], json.loads(SPEC_PATH.read_text(encoding="utf-8")))


def _annotation(param: dict[str, Any]) -> Any:
    """把规格里的类型描述转成 Python 注解。"""
    kind = param.get("type")
    if kind == "string":
        enum = param.get("enum")
        if enum:
            values = tuple(str(item) for item in enum)
            return Literal[values]
        return str
    if kind == "integer":
        return int
    if kind == "number":
        return float
    if kind == "boolean":
        return bool
    if kind == "array":
        items = param.get("items") or {}
        item_type = _annotation(items)
        return list[item_type]  # type: ignore[valid-type]
    return dict[str, Any]


def _parameters(operation: dict[str, Any]) -> list[inspect.Parameter]:
    """按规格生成函数参数（路径 / 查询 / 请求体字段同名同义）。

    Python 要求「有默认值的参数」排在「没有默认值的参数」之后，而 OpenAPI 里
    同组参数的顺序不保证这一点，所以最后按必填性做一次稳定排序——参数名与
    类型不变，只是声明顺序不同。
    """
    required_params: list[inspect.Parameter] = []
    optional_params: list[inspect.Parameter] = []
    for group in ("path_params", "query_params", "body_params"):
        for param in operation.get(group, []):
            annotation: Any = _annotation(param)
            default: Any = inspect.Parameter.empty
            if not param.get("required"):
                nullable = bool(param.get("nullable"))
                has_default = "default" in param
                if nullable or not has_default:
                    # 接口声明可空的字段保持可空；接口没给默认值的可选字段，
                    # MCP 侧只能退化成「可空可选」，调用语义与不传该字段一致。
                    annotation = annotation | None
                default = param.get("default") if has_default else None
            item = inspect.Parameter(
                param["name"],
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=annotation,
                default=default,
            )
            (required_params if param.get("required") else optional_params).append(item)
    return [*required_params, *optional_params]


def _tool_description(operation: dict[str, Any]) -> str:
    """工具描述：接口语义 + 对应 HTTP 路由 + 非 JSON 响应的说明。"""
    lines = [
        operation.get("description") or operation.get("title") or operation["name"],
        "",
        f"对应 HTTP 接口：{operation['method']} {operation['path']}",
        "参数与返回结果与该接口一致。",
    ]
    if operation.get("response") == "image":
        lines.append("该接口返回图片：图片较小会内联返回，较大只回元信息。")
    elif operation.get("response") == "file":
        lines.append(
            "该接口返回文件/媒体流：MCP 返回元信息信封"
            "（content_type / size_bytes / filename），下载仍走前端或预览会话接口。"
        )
    return "\n".join(lines)


def _file_envelope(response: httpx.Response, data: bytes) -> dict[str, Any]:
    """二进制响应 → 可放进模型上下文的元信息信封。"""
    content_type = response.headers.get("content-type", "")
    disposition = response.headers.get("content-disposition", "")
    filename = ""
    if "filename=" in disposition:
        filename = disposition.split("filename=", 1)[1].strip().strip('"')
    return {
        "content_type": content_type,
        "size_bytes": len(data),
        "filename": filename or None,
        "note": "该接口返回文件/媒体流，MCP 只回元信息；下载请使用前端页面或预览会话接口。",
    }


def decode_response(response: httpx.Response) -> Any:
    """按运行期 content-type 把响应转成工具返回值。

    参数：
        response: 接口原始响应。

    返回：
        JSON 结构、图片内容块、文本信封或二进制元信息信封。
    """
    content_type = response.headers.get("content-type", "")
    mime = content_type.split(";")[0].strip().lower()
    if mime == "application/json" or mime.endswith("+json"):
        return response.json()
    data = response.content
    if mime.startswith("image/") and len(data) <= INLINE_IMAGE_MAX_BYTES:
        return Image(data=data, format=mime.split("/")[-1] or "png")
    if mime.startswith("text/"):
        return {"content_type": content_type, "text": data.decode("utf-8", "replace")}
    return _file_envelope(response, data)


async def call_operation(operation: dict[str, Any], values: dict[str, Any]) -> Any:
    """把一次工具调用翻译成对应的 HTTP 请求。

    参数：
        operation: 规格里的 operation 描述。
        values: 工具参数（路径 / 查询 / 请求体字段混在一个字典里）。

    返回：
        接口响应转换后的结果（见 :func:`decode_response`）。

    异常：
        ValueError: 缺少必填路径参数，或必填请求体没有任何字段。
    """
    path = operation["path"]
    for param in operation.get("path_params", []):
        value = values.get(param["name"])
        if value is None:
            raise ValueError(f"缺少路径参数 {param['name']}")
        path = path.replace("{" + param["name"] + "}", quote(str(value), safe=""))
    query = {
        param["name"]: values[param["name"]]
        for param in operation.get("query_params", [])
        if values.get(param["name"]) is not None
    }
    body = {
        param["name"]: values[param["name"]]
        for param in operation.get("body_params", [])
        if values.get(param["name"]) is not None
    }
    if operation.get("body_required") and not body:
        raise ValueError("该接口的请求体必填，请至少提供一个请求体字段")
    response = await api.request_raw(
        operation["method"],
        path,
        params=query or None,
        json_body=body if operation.get("body_params") else None,
    )
    return decode_response(response)


def _build_tool(operation: dict[str, Any]) -> Any:
    """按规格生成一个异步工具函数（签名即接口参数）。"""

    async def tool(**kwargs: Any) -> Any:
        return await call_operation(operation, kwargs)

    tool.__name__ = operation["name"]
    tool.__doc__ = _tool_description(operation)
    tool.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters=_parameters(operation),
        return_annotation=Any,
    )
    return tool


def register_api_tools() -> list[str]:
    """把规格里的每个 operation 注册成 MCP 工具，返回工具名列表。

    返回：
        本次注册的工具名（与 ``tools_spec.json`` 顺序一致）。
    """
    spec = load_spec()
    names: list[str] = []
    for operation in spec["operations"]:
        mcp.add_tool(
            _build_tool(operation),
            name=operation["name"],
            description=_tool_description(operation),
            meta={
                "api": {
                    "method": operation["method"],
                    "path": operation["path"],
                },
                "openapi_operation_id": operation["operation_id"],
            },
        )
        names.append(operation["name"])
    return names


__all__ = [
    "SPEC_PATH",
    "call_operation",
    "decode_response",
    "load_spec",
    "register_api_tools",
]
