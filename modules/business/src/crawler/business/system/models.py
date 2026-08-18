"""系统限界上下文的业务模型与 schema（集成文档等系统级视图模型）。"""

from typing import Any

from sqlmodel import SQLModel


class ApiOperationDocPublic(SQLModel):
    """单个 HTTP API 操作的文档视图模型。"""

    method: str  # HTTP 方法（GET/POST 等）
    path: str  # 接口路径
    summary: str  # 接口摘要
    description: str  # 接口详细描述
    operation_id: str  # OpenAPI operationId
    tags: list[str]  # 接口分组标签
    auth_required: bool  # 是否需要认证
    parameters: list[dict[str, Any]]  # 参数定义列表（OpenAPI parameters）
    request_body: (
        dict[str, Any] | None
    )  # 请求体定义（OpenAPI requestBody），无则为 None
    response_codes: list[str]  # 声明过的响应状态码列表


class McpToolDocPublic(SQLModel):
    """单个 MCP 工具的文档视图模型。"""

    name: str  # 工具名称
    title: str | None  # 工具显示标题，可空
    description: str  # 工具描述
    input_schema: dict[str, Any]  # 入参 JSON Schema
    output_schema: dict[str, Any] | None  # 出参 JSON Schema，可空


class IntegrationDocsPublic(SQLModel):
    """集成文档总览模型：汇总 HTTP API 与 MCP 服务的接入信息。"""

    api_title: str  # API 文档标题
    api_version: str  # API 版本号
    api_openapi_url: str  # OpenAPI 文档地址
    api_swagger_url: str  # Swagger UI 地址
    api_operations: list[ApiOperationDocPublic]  # API 操作文档列表
    api_operation_count: int  # API 操作总数
    mcp_server_name: str  # MCP 服务名称
    mcp_streamable_http_url: str  # MCP Streamable HTTP 接入地址
    mcp_health_url: str  # MCP 健康检查地址
    mcp_stdio_command: str  # MCP stdio 模式启动命令
    mcp_http_command: str  # MCP HTTP 模式启动命令
    mcp_tools: list[McpToolDocPublic]  # MCP 工具文档列表
    mcp_tool_count: int  # MCP 工具总数


__all__ = [
    "ApiOperationDocPublic",
    "McpToolDocPublic",
    "IntegrationDocsPublic",
]
