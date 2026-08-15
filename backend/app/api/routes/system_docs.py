import os
from typing import Any

from fastapi import APIRouter, Request

from app.api.deps import CurrentUser
from app.domain.system.models import (
    ApiOperationDocPublic,
    IntegrationDocsPublic,
    McpToolDocPublic,
)
from app.mcp_server.server import mcp

router = APIRouter(prefix="/system/integrations", tags=["system-integrations"])

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}
METHOD_ORDER = {
    "GET": 0,
    "POST": 1,
    "PUT": 2,
    "PATCH": 3,
    "DELETE": 4,
    "OPTIONS": 5,
    "HEAD": 6,
}


def _api_operations(schema: dict[str, Any]) -> list[ApiOperationDocPublic]:
    operations: list[ApiOperationDocPublic] = []
    global_security = schema.get("security", [])
    for path, path_item in schema.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        shared_parameters = path_item.get("parameters", [])
        for method, operation in path_item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            parameters = [*shared_parameters, *operation.get("parameters", [])]
            operations.append(
                ApiOperationDocPublic(
                    method=method.upper(),
                    path=path,
                    summary=str(operation.get("summary") or "未命名接口"),
                    description=str(operation.get("description") or ""),
                    operation_id=str(operation.get("operationId") or ""),
                    tags=[str(tag) for tag in operation.get("tags", [])],
                    auth_required=bool(operation.get("security", global_security)),
                    parameters=[
                        dict(parameter)
                        for parameter in parameters
                        if isinstance(parameter, dict)
                    ],
                    request_body=(
                        dict(operation["requestBody"])
                        if isinstance(operation.get("requestBody"), dict)
                        else None
                    ),
                    response_codes=[
                        str(code) for code in operation.get("responses", {}).keys()
                    ],
                )
            )
    return sorted(
        operations,
        key=lambda item: (item.path, METHOD_ORDER.get(item.method, 99)),
    )


def _service_url(request: Request, *, port: int, path: str) -> str:
    hostname = request.url.hostname or "127.0.0.1"
    display_host = "127.0.0.1" if hostname in {"localhost", "127.0.0.1"} else hostname
    normalized_path = "/" + path.strip("/")
    return f"{request.url.scheme}://{display_host}:{port}{normalized_path}"


@router.get("/", response_model=IntegrationDocsPublic)
async def get_integration_docs(
    request: Request,
    _current_user: CurrentUser,
) -> IntegrationDocsPublic:
    """返回系统内可检索的 OpenAPI 接口目录和真实 MCP 工具注册表。"""
    schema = request.app.openapi()
    operations = _api_operations(schema)
    registered_tools = await mcp.list_tools()
    tools = [
        McpToolDocPublic(
            name=tool.name,
            title=tool.title,
            description=tool.description or "",
            input_schema=dict(tool.inputSchema),
            output_schema=(dict(tool.outputSchema) if tool.outputSchema else None),
        )
        for tool in sorted(registered_tools, key=lambda item: item.name)
    ]
    mcp_port = int(os.getenv("DOUYIN_MCP_PORT", "8766"))
    mcp_path = os.getenv("DOUYIN_MCP_PATH", "/mcp")
    base_url = str(request.base_url).rstrip("/")
    return IntegrationDocsPublic(
        api_title=str(schema.get("info", {}).get("title") or "FastAPI"),
        api_version=str(schema.get("info", {}).get("version") or ""),
        api_openapi_url=f"{base_url}{request.app.openapi_url}",
        api_swagger_url=f"{base_url}{request.app.docs_url}",
        api_operations=operations,
        api_operation_count=len(operations),
        mcp_server_name="Douyin Crawler API",
        mcp_streamable_http_url=_service_url(request, port=mcp_port, path=mcp_path),
        mcp_health_url=_service_url(request, port=mcp_port, path="/health"),
        mcp_stdio_command="uv run python -m app.mcp_server",
        mcp_http_command=(
            "uv run python -m app.mcp_server --transport streamable-http "
            f"--host 127.0.0.1 --port {mcp_port}"
        ),
        mcp_tools=tools,
        mcp_tool_count=len(tools),
    )
