import json
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app.core.security import create_access_token
from app.models import CrawlTask, CrawlTaskStatus
from app.services.douyin_tasks import task_manager


def test_create_douyin_task_is_accepted_and_never_echoes_cookie(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    task = CrawlTask(
        owner_id=uuid.uuid4(),
        crawl_type="search",
        status=CrawlTaskStatus.queued.value,
        request_json=json.dumps(
            {
                "crawl_type": "search",
                "login_type": "cookie",
                "keywords": ["FastAPI"],
                "max_awemes": 1,
            }
        ),
    )
    create = AsyncMock(return_value=task)
    monkeypatch.setattr(task_manager, "create", create)

    response = client.post(
        "/api/v1/douyin/tasks",
        headers=superuser_token_headers,
        json={
            "crawl_type": "search",
            "keywords": ["FastAPI"],
            "cookies": "sessionid=top-secret",
            "max_awemes": 1,
            "fetch_comments": False,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert "cookies" not in payload["request"]
    assert "top-secret" not in response.text
    submitted = create.await_args.kwargs["request"]
    assert "cookies" not in submitted.public_request()


def test_douyin_tasks_require_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/douyin/tasks")

    assert response.status_code == 401


def test_douyin_tasks_reject_token_for_deleted_user(client: TestClient) -> None:
    access_token = create_access_token(
        subject=str(uuid.uuid4()), expires_delta=timedelta(minutes=5)
    )

    response = client.get(
        "/api/v1/douyin/tasks",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Could not validate credentials"}


def test_get_unknown_douyin_task_returns_404(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    response = client.get(
        f"/api/v1/douyin/tasks/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 404
