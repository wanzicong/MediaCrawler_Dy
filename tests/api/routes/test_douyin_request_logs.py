"""抖音请求日志路由的集成测试：分页、过滤参数与用户隔离。"""

import uuid
from datetime import timedelta

from crawler.bootstrap.security import get_password_hash
from crawler.bootstrap.settings import settings
from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.request_logs.models import DouyinRequestLog
from crawler.business.douyin.request_logs.service import record_sync
from crawler.business.douyin.tasks.models import CrawlTask, CrawlTaskStatus
from crawler.business.identity.models import User
from crawler.douyin_client.client import DouyinRequestLogEntry
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from tests.utils.douyin import default_track_id

_TEST_PASSWORD = "request-log-test-password"


def _seed_logs(owner_id: uuid.UUID) -> str:
    """为指定用户预置两条带唯一公共路径前缀的请求日志。"""
    marker = f"request-log-test-{uuid.uuid4().hex}"
    record_sync(
        owner_id,
        None,
        DouyinRequestLogEntry(
            method="GET",
            path=f"/aweme/v1/web/{marker}/general-search/",
            url=f"https://www.douyin.com/aweme/v1/web/{marker}/general-search/",
            query_params={"keyword": "露营"},
            request_headers={"Cookie": "sessionid=abc"},
            request_body=None,
            response_status=200,
            duration_ms=30,
            error=None,
            failure_detail=None,
        ),
    )
    record_sync(
        owner_id,
        None,
        DouyinRequestLogEntry(
            method="POST",
            path=f"/aweme/v1/web/{marker}/listcollection/",
            url=f"https://www.douyin.com/aweme/v1/web/{marker}/listcollection/",
            query_params={"aid": "6383"},
            request_headers={"Cookie": "sessionid=abc"},
            request_body={"count": 10},
            response_status=403,
            duration_ms=50,
            error="blocked",
            failure_detail={
                "http_status": 403,
                "body": {"status_code": 4, "status_msg": "请求过于频繁"},
            },
        ),
    )
    return marker


def test_request_logs_endpoint_filters_and_isolates(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证请求日志接口：默认分页返回、各过滤参数生效、仅返回当前用户数据。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    marker = _seed_logs(owner.id)

    # 默认查询：全部记录，按时间倒序
    response = client.get(
        "/api/v1/douyin/request-logs",
        params={"path": marker},
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 2
    first = payload["data"][0]
    assert set(first) == {
        "id",
        "task_id",
        "method",
        "path",
        "url",
        "query_params",
        "request_headers",
        "request_body",
        "response_status",
        "duration_ms",
        "error",
        "failure_detail",
        "created_at",
    }
    assert first["request_headers"]["Cookie"] == "[REDACTED]"
    failed = next(item for item in payload["data"] if item["error"] == "blocked")
    assert failed["failure_detail"]["body"]["status_msg"] == "请求过于频繁"

    # 方法过滤
    filtered = client.get(
        "/api/v1/douyin/request-logs",
        params={"method": "GET", "path": marker},
        headers=superuser_token_headers,
    )
    assert filtered.status_code == 200
    assert all(item["method"] == "GET" for item in filtered.json()["data"])

    # 路径包含过滤
    path_filtered = client.get(
        "/api/v1/douyin/request-logs",
        params={"path": f"{marker}/listcollection"},
        headers=superuser_token_headers,
    )
    assert path_filtered.status_code == 200
    assert path_filtered.json()["count"] == 1
    assert path_filtered.json()["data"][0]["method"] == "POST"

    # 状态码过滤
    status_filtered = client.get(
        "/api/v1/douyin/request-logs",
        params={"response_status": 403, "path": marker},
        headers=superuser_token_headers,
    )
    assert status_filtered.status_code == 200
    assert all(
        item["response_status"] == 403 for item in status_filtered.json()["data"]
    )

    # 分页参数
    paged = client.get(
        "/api/v1/douyin/request-logs",
        params={"skip": 1, "limit": 1, "path": marker},
        headers=superuser_token_headers,
    )
    assert paged.status_code == 200
    assert len(paged.json()["data"]) == 1

    # 用户隔离：新建用户查询不到他人日志
    other = User(
        email="request-log-api-other@example.com",
        full_name="接口隔离用户",
        hashed_password=get_password_hash(_TEST_PASSWORD),
        is_active=True,
    )
    db.add(other)
    db.commit()
    db.refresh(other)
    try:
        # 他人视角：隔离用户无任何记录
        other_token = _login_as(client, other.email)
        other_response = client.get(
            "/api/v1/douyin/request-logs",
            headers=other_token,
        )
        assert other_response.status_code == 200
        assert other_response.json()["count"] == 0
    finally:
        db.exec(delete(DouyinRequestLog).where(DouyinRequestLog.path.contains(marker)))
        db.exec(delete(DouyinRequestLog).where(DouyinRequestLog.owner_id == other.id))
        db.exec(delete(User).where(User.id == other.id))
        db.commit()


def test_request_logs_endpoint_filters_by_task_and_time(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证按任务 ID 与时间范围过滤。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="search",
        status=CrawlTaskStatus.succeeded.value,
        request_json='{"crawl_type": "search"}',
        checkpoint_json='{"version": 1, "phase": "completed"}',
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    record_sync(
        owner.id,
        task.id,
        DouyinRequestLogEntry(
            method="GET",
            path="/aweme/v1/web/aweme/detail/",
            url="https://www.douyin.com/aweme/v1/web/aweme/detail/",
            query_params={"aweme_id": "1"},
            request_headers={"Cookie": "c"},
            request_body=None,
            response_status=200,
            duration_ms=20,
            error=None,
        ),
    )

    by_task = client.get(
        "/api/v1/douyin/request-logs",
        params={"task_id": str(task.id)},
        headers=superuser_token_headers,
    )
    assert by_task.status_code == 200
    assert by_task.json()["count"] == 1
    assert by_task.json()["data"][0]["task_id"] == str(task.id)

    # 时间范围：未来起始时间应查不到任何记录
    future = get_datetime_utc() + timedelta(days=1)
    by_time = client.get(
        "/api/v1/douyin/request-logs",
        params={"created_from": future.isoformat()},
        headers=superuser_token_headers,
    )
    assert by_time.status_code == 200
    assert by_time.json()["count"] == 0

    # 非法参数：路径超长与非法状态码应返回 422
    invalid_status = client.get(
        "/api/v1/douyin/request-logs",
        params={"response_status": 99},
        headers=superuser_token_headers,
    )
    assert invalid_status.status_code == 422

    db.exec(delete(DouyinRequestLog).where(DouyinRequestLog.task_id == task.id))
    db.exec(delete(CrawlTask).where(CrawlTask.id == task.id))
    db.commit()


def _login_as(client: TestClient, email: str) -> dict[str, str]:
    """通过登录接口为指定用户签发 Bearer 请求头。"""
    response = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": email, "password": _TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
