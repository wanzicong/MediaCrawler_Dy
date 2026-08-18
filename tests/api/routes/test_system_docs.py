from crawler.bootstrap.settings import settings
from fastapi.testclient import TestClient


def test_integration_docs_require_authentication(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_STR}/system/integrations/")

    assert response.status_code == 401


def test_integration_docs_expose_live_api_and_mcp_catalogs(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/system/integrations/",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["api_operation_count"] == len(payload["api_operations"])
    assert payload["api_operation_count"] > 20
    assert any(
        item["path"] == f"{settings.API_V1_STR}/douyin/tasks"
        and item["method"] == "POST"
        and item["auth_required"]
        for item in payload["api_operations"]
    )
    assert payload["api_swagger_url"].endswith("/docs")
    assert payload["api_openapi_url"].endswith(f"{settings.API_V1_STR}/openapi.json")

    assert payload["mcp_tool_count"] == len(payload["mcp_tools"])
    assert payload["mcp_tool_count"] >= 23
    create_task = next(
        item for item in payload["mcp_tools"] if item["name"] == "create_douyin_task"
    )
    assert create_task["input_schema"]["required"] == ["crawl_type"]
    assert "账号池" in create_task["description"]
    serialized = response.text
    assert settings.FIRST_SUPERUSER_PASSWORD not in serialized
    assert "MCP_API_PASSWORD" not in serialized
