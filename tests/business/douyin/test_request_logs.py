"""抖音请求日志的写读侧服务测试：落盘字段、按任务解析归属、查询过滤与用户隔离。"""

import asyncio
import uuid
from datetime import timedelta

from crawler.bootstrap.settings import settings
from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.request_logs.models import DouyinRequestLog
from crawler.business.douyin.request_logs.query_service import list_request_logs
from crawler.business.douyin.request_logs.service import (
    MAX_FAILURE_DETAIL_CHARS,
    load_task_owner,
    record_sync,
)
from crawler.business.douyin.tasks.models import CrawlTask, CrawlTaskStatus
from crawler.business.identity.models import User
from crawler.douyin_client.client import DouyinRequestLogEntry
from sqlmodel import Session, delete, select

from tests.utils.douyin import default_track_id


def _make_entry(
    *,
    method: str = "GET",
    path: str = "/aweme/v1/web/general/search/single/",
    response_status: int | None = 200,
    error: str | None = None,
    failure_detail: dict[str, object] | None = None,
) -> DouyinRequestLogEntry:
    """构造一次抖音接口调用的记录快照。"""
    return DouyinRequestLogEntry(
        method=method,
        path=path,
        url=f"https://www.douyin.com{path}?a_bogus=sig&keyword=test",
        query_params={"a_bogus": "sig", "keyword": "test"},
        request_headers={
            "User-Agent": "Mozilla/5.0",
            "Cookie": "sessionid=abc; LOGIN_STATUS=1",
            "Referer": "https://www.douyin.com/",
        },
        request_body={"count": 20, "account_id": "raw-account-id"}
        if method == "POST"
        else None,
        response_status=response_status,
        duration_ms=42,
        error=error,
        failure_detail=failure_detail,
    )


def test_record_redacts_sensitive_request_values(db: Session) -> None:
    """验证落库前清除签名、Cookie 等敏感请求值，同时保留诊断字段。"""
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

    entry = _make_entry(method="POST", path="/aweme/v1/web/comment/list/")
    record_sync(owner.id, task.id, entry)

    row = db.exec(
        select(DouyinRequestLog).where(DouyinRequestLog.task_id == task.id)
    ).one()
    assert row.task_id == task.id
    assert row.method == "POST"
    assert row.path == "/aweme/v1/web/comment/list/"
    assert row.url == "https://www.douyin.com/aweme/v1/web/comment/list/"
    assert row.query_params == {"a_bogus": "[REDACTED]", "keyword": "test"}
    assert row.request_headers["Cookie"] == "[REDACTED]"
    assert row.request_headers["User-Agent"] == "Mozilla/5.0"
    assert row.request_body == {"count": 20, "account_id": "[REDACTED]"}
    assert row.response_status == 200
    assert row.duration_ms == 42
    assert row.error is None
    assert row.failure_detail is None
    assert row.created_at is not None

    # 清理：日志与任务
    db.exec(delete(DouyinRequestLog).where(DouyinRequestLog.task_id == task.id))
    db.exec(delete(CrawlTask).where(CrawlTask.id == task.id))
    db.commit()


def test_record_keeps_error_without_status(db: Session) -> None:
    """验证网络异常时记录异常类型且响应状态为空。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    record_sync(owner.id, None, _make_entry(response_status=None, error="ConnectError"))
    row = db.exec(
        select(DouyinRequestLog)
        .where(
            DouyinRequestLog.owner_id == owner.id,
            DouyinRequestLog.error == "ConnectError",
        )
        .order_by(DouyinRequestLog.created_at.desc())
    ).first()
    assert row is not None
    assert row.response_status is None
    assert row.error == "ConnectError"
    assert row.task_id is None
    db.exec(delete(DouyinRequestLog).where(DouyinRequestLog.id == row.id))
    db.commit()


def test_record_redacts_and_limits_failure_response(db: Session) -> None:
    """验证失败返回正文可诊断，但令牌、账号标识和超长正文不会原样落库。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    record_sync(
        owner.id,
        None,
        _make_entry(
            response_status=200,
            error="DouyinBusinessError:4",
            failure_detail={
                "http_status": 200,
                "body": {
                    "status_code": 4,
                    "status_msg": "请求过于频繁",
                    "msToken": "secret-token",
                    "nested": {"sec_uid": "raw-user-id"},
                    "html": "token=inline-secret " + ("x" * 12_000),
                },
            },
        ),
    )
    row = db.exec(
        select(DouyinRequestLog)
        .where(
            DouyinRequestLog.owner_id == owner.id,
            DouyinRequestLog.error == "DouyinBusinessError:4",
        )
        .order_by(DouyinRequestLog.created_at.desc())
    ).first()
    assert row is not None
    assert row.failure_detail is not None
    serialized = str(row.failure_detail)
    assert "请求过于频繁" in serialized
    assert "secret-token" not in serialized
    assert "raw-user-id" not in serialized
    assert "inline-secret" not in serialized
    assert len(serialized) <= MAX_FAILURE_DETAIL_CHARS + 200
    db.exec(delete(DouyinRequestLog).where(DouyinRequestLog.id == row.id))
    db.commit()


def test_load_task_owner_resolves_and_misses(db: Session) -> None:
    """验证按任务解析归属用户，任务不存在时返回 None。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="search",
        status=CrawlTaskStatus.queued.value,
        request_json='{"crawl_type": "search"}',
        checkpoint_json='{"version": 1, "phase": "crawl"}',
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    resolved = asyncio.run(load_task_owner(task.id))
    assert resolved == owner.id
    missing = asyncio.run(load_task_owner(uuid.uuid4()))
    assert missing is None

    db.exec(delete(CrawlTask).where(CrawlTask.id == task.id))
    db.commit()


def test_list_request_logs_filters_and_isolates(db: Session) -> None:
    """验证分页查询：任务/方法/路径/状态/时间范围过滤、倒序分页与用户隔离。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    now = get_datetime_utc()
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
    entries = [
        DouyinRequestLog(
            owner_id=owner.id,
            task_id=task.id,
            method="GET",
            path="/aweme/v1/web/general/search/single/",
            url="https://www.douyin.com/aweme/v1/web/general/search/single/",
            query_params={"keyword": "露营"},
            request_headers={"Cookie": "c"},
            request_body=None,
            response_status=200,
            duration_ms=30,
            error=None,
            created_at=now - timedelta(hours=3),
        ),
        DouyinRequestLog(
            owner_id=owner.id,
            task_id=task.id,
            method="GET",
            path="/aweme/v1/web/aweme/detail/",
            url="https://www.douyin.com/aweme/v1/web/aweme/detail/",
            query_params={"aweme_id": "1"},
            request_headers={"Cookie": "c"},
            request_body=None,
            response_status=403,
            duration_ms=50,
            error="blocked",
            created_at=now - timedelta(hours=2),
        ),
        DouyinRequestLog(
            owner_id=owner.id,
            task_id=task.id,
            method="POST",
            path="/aweme/v1/web/aweme/listcollection/",
            url="https://www.douyin.com/aweme/v1/web/aweme/listcollection/",
            query_params={"aid": "6383"},
            request_headers={"Cookie": "c"},
            request_body={"count": 10},
            response_status=200,
            duration_ms=60,
            error=None,
            created_at=now - timedelta(hours=1),
        ),
    ]
    db.add_all(entries)
    other = User(
        email="request-log-other@example.com",
        full_name="日志隔离用户",
        hashed_password="x",
        is_active=True,
    )
    db.add(other)
    db.commit()
    db.refresh(other)
    db.add(
        DouyinRequestLog(
            owner_id=other.id,
            task_id=task.id,
            method="GET",
            path="/aweme/v1/web/aweme/detail/",
            url="https://www.douyin.com/aweme/v1/web/aweme/detail/",
            query_params={},
            request_headers={},
            request_body=None,
            response_status=200,
            duration_ms=10,
            error=None,
            created_at=now,
        )
    )
    db.commit()

    try:
        page = list_request_logs(
            db,
            owner_id=owner.id,
            task_id=task.id,
            method=None,
            path=None,
            response_status=None,
            created_from=None,
            created_to=None,
            skip=0,
            limit=10,
        )
        assert page.count == 3
        assert [item.path for item in page.data] == [
            "/aweme/v1/web/aweme/listcollection/",
            "/aweme/v1/web/aweme/detail/",
            "/aweme/v1/web/general/search/single/",
        ]
        assert page.data[0].request_body == {"count": 10}
        assert page.data[1].response_status == 403
        assert page.data[1].error == "blocked"
        assert page.data[1].request_headers == {"Cookie": "[REDACTED]"}

        # 方法过滤
        get_page = list_request_logs(
            db,
            owner_id=owner.id,
            task_id=task.id,
            method="get",
            path=None,
            response_status=None,
            created_from=None,
            created_to=None,
            skip=0,
            limit=10,
        )
        assert get_page.count == 2

        # 路径包含过滤
        detail_page = list_request_logs(
            db,
            owner_id=owner.id,
            task_id=task.id,
            method=None,
            path="aweme/detail",
            response_status=None,
            created_from=None,
            created_to=None,
            skip=0,
            limit=10,
        )
        assert detail_page.count == 1
        assert detail_page.data[0].path.endswith("/aweme/detail/")

        # 状态码过滤
        blocked_page = list_request_logs(
            db,
            owner_id=owner.id,
            task_id=task.id,
            method=None,
            path=None,
            response_status=403,
            created_from=None,
            created_to=None,
            skip=0,
            limit=10,
        )
        assert blocked_page.count == 1

        # 时间范围过滤（近 90 分钟内的仅 POST 记录）
        recent_page = list_request_logs(
            db,
            owner_id=owner.id,
            task_id=task.id,
            method=None,
            path=None,
            response_status=None,
            created_from=now - timedelta(minutes=90),
            created_to=None,
            skip=0,
            limit=10,
        )
        assert recent_page.count == 1
        assert recent_page.data[0].method == "POST"

        # 分页
        paged = list_request_logs(
            db,
            owner_id=owner.id,
            task_id=task.id,
            method=None,
            path=None,
            response_status=None,
            created_from=None,
            created_to=None,
            skip=1,
            limit=1,
        )
        assert paged.count == 3
        assert len(paged.data) == 1
        assert paged.data[0].path.endswith("/aweme/detail/")

        # 用户隔离：其他用户的记录不可见
        isolated = list_request_logs(
            db,
            owner_id=owner.id,
            task_id=task.id,
            method="GET",
            path="aweme/detail",
            response_status=None,
            created_from=None,
            created_to=None,
            skip=0,
            limit=10,
        )
        assert isolated.count == 1
    finally:
        db.exec(delete(DouyinRequestLog).where(DouyinRequestLog.task_id == task.id))
        db.exec(delete(DouyinRequestLog).where(DouyinRequestLog.owner_id == other.id))
        db.exec(delete(CrawlTask).where(CrawlTask.id == task.id))
        db.exec(delete(User).where(User.id == other.id))
        db.commit()
