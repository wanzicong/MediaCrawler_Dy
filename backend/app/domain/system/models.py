"""Business models and schemas for this bounded context."""

from typing import Any

from sqlmodel import SQLModel


class ApiOperationDocPublic(SQLModel):
    method: str
    path: str
    summary: str
    description: str
    operation_id: str
    tags: list[str]
    auth_required: bool
    parameters: list[dict[str, Any]]
    request_body: dict[str, Any] | None
    response_codes: list[str]


class McpToolDocPublic(SQLModel):
    name: str
    title: str | None
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None


class IntegrationDocsPublic(SQLModel):
    api_title: str
    api_version: str
    api_openapi_url: str
    api_swagger_url: str
    api_operations: list[ApiOperationDocPublic]
    api_operation_count: int
    mcp_server_name: str
    mcp_streamable_http_url: str
    mcp_health_url: str
    mcp_stdio_command: str
    mcp_http_command: str
    mcp_tools: list[McpToolDocPublic]
    mcp_tool_count: int


__all__ = [
    "ApiOperationDocPublic",
    "McpToolDocPublic",
    "IntegrationDocsPublic",
]
