"""抖音采集任务删除路由测试。"""

from __future__ import annotations

import json
import uuid

import pytest
from crawler.business.douyin.tasks.models import CrawlTask, CrawlTaskResumeRequest
from crawler.business.douyin.tasks.service import task_manager
from crawler.business.identity.models import User
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from tests.utils.douyin import default_track_id


def _superuser(db: Session) -> User:
    """获取测试用超级管理员。"""
    return db.exec(select(User).where(User.is_superuser.is_(True))).first()  # type: ignore[return-value]


def _task(db: Session, *, owner_id: uuid.UUID, status: str) -> CrawlTask:
    """创建一条最小化采集任务记录。"""
    task = CrawlTask(
        owner_id=owner_id,
        track_id=default_track_id(db, owner_id=owner_id),
        crawl_type="search",
        status=status,
        request_json=json.dumps({"crawl_type": "search", "keywords": ["删除测试"]}),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def test_bulk_delete_removes_selected_failed_task(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """批量删除只移除选中的失效任务，并保留未选中的成功任务。"""
    owner = _superuser(db)
    failed = _task(db, owner_id=owner.id, status="failed")
    succeeded = _task(db, owner_id=owner.id, status="succeeded")
    failed_id = failed.id
    succeeded_id = succeeded.id

    response = client.post(
        "/api/v1/douyin/tasks/bulk-delete",
        headers=superuser_token_headers,
        json={"ids": [str(failed_id)]},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "已删除 1 个失效任务"
    db.expire_all()
    assert db.get(CrawlTask, failed_id) is None
    assert db.get(CrawlTask, succeeded_id) is not None


def test_bulk_delete_rejects_active_task(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """批量删除包含活动任务时拒绝整批删除，避免误删正在执行的任务。"""
    owner = _superuser(db)
    running = _task(db, owner_id=owner.id, status="running")

    response = client.post(
        "/api/v1/douyin/tasks/bulk-delete",
        headers=superuser_token_headers,
        json={"ids": [str(running.id)]},
    )

    assert response.status_code == 409
    assert db.get(CrawlTask, running.id) is not None


def test_bulk_resume_accepts_interval_for_each_task(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """批量恢复接口统一受理失效任务并把指定间隔写回任务快照。"""
    owner = _superuser(db)
    first = _task(db, owner_id=owner.id, status="failed")
    second = _task(db, owner_id=owner.id, status="interrupted")

    async def fake_resume(
        *, task_id: uuid.UUID, options: CrawlTaskResumeRequest
    ) -> CrawlTask:
        """只在路由测试中模拟入队，避免启动真实采集后台任务。"""
        task = db.get(CrawlTask, task_id)
        assert task is not None
        payload = json.loads(task.request_json)
        payload["task_interval_seconds"] = options.task_interval_seconds
        task.request_json = json.dumps(payload)
        task.status = "queued"
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    monkeypatch.setattr(task_manager, "resume", fake_resume)

    response = client.post(
        "/api/v1/douyin/tasks/bulk-resume",
        headers=superuser_token_headers,
        json={
            "ids": [str(first.id), str(second.id)],
            "task_interval_seconds": 18,
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["count"] == 2
    assert body["failed_count"] == 0
    db.expire_all()
    assert (
        json.loads(db.get(CrawlTask, first.id).request_json)["task_interval_seconds"]
        == 18
    )
    assert (
        json.loads(db.get(CrawlTask, second.id).request_json)["task_interval_seconds"]
        == 18
    )
