"""Read-side identity tests for crawl-task list and detail responses."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import Session, select

from app.application.douyin.tasks.query_service import list_tasks
from app.bootstrap.settings import settings
from app.domain.douyin.content.models import DouyinAweme
from app.domain.douyin.tasks.models import CrawlTask
from app.domain.identity.models import User
from app.framework.database import engine
from tests.utils.douyin import default_track_id


def _superuser(db: Session) -> User:
    return db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()


def _task(db: Session, *, owner_id: uuid.UUID, video_id: str) -> CrawlTask:
    task = CrawlTask(
        owner_id=owner_id,
        track_id=default_track_id(db, owner_id=owner_id),
        crawl_type="detail",
        status="succeeded",
        request_json=json.dumps({"crawl_type": "detail", "video_ids": [video_id]}),
        aweme_count=1,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@contextmanager
def _record_selects() -> Iterator[list[str]]:
    statements: list[str] = []

    def before_cursor_execute(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)


def test_get_task_exposes_stable_chinese_work_identity(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    task = _task(db, owner_id=_superuser(db).id, video_id="7600000000000000001")
    db.add_all(
        [
            DouyinAweme(
                task_id=task.id,
                aweme_id="7600000000000000001",
                title="较早的作品",
                nickname="旧作者",
                create_time=100,
            ),
            DouyinAweme(
                task_id=task.id,
                aweme_id="7600000000000000002",
                title="夏日城市漫游",
                nickname="山海记录者",
                create_time=200,
            ),
        ]
    )
    db.commit()

    response = client.get(
        f"/api/v1/douyin/tasks/{task.id}", headers=superuser_token_headers
    )

    assert response.status_code == 200
    assert response.json()["display_title"] == "夏日城市漫游"
    assert response.json()["display_author"] == "山海记录者"
    assert response.json()["display_aweme_id"] == "7600000000000000002"


def test_get_task_without_work_has_null_display_identity(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    task = _task(db, owner_id=_superuser(db).id, video_id="7600000000000000099")

    response = client.get(
        f"/api/v1/douyin/tasks/{task.id}", headers=superuser_token_headers
    )

    assert response.status_code == 200
    assert response.json()["display_title"] is None
    assert response.json()["display_author"] is None
    assert response.json()["display_aweme_id"] is None


def test_list_tasks_batches_identity_query_and_maps_each_task(db: Session) -> None:
    owner = User(
        email=f"task-identity-{uuid.uuid4().hex}@example.com",
        hashed_password="unused-in-query-test",
    )
    db.add(owner)
    db.commit()
    db.refresh(owner)
    owner_id = owner.id

    first = _task(db, owner_id=owner_id, video_id="7610000000000000001")
    db.add(
        DouyinAweme(
            task_id=first.id,
            aweme_id="7610000000000000001",
            title="中文作品甲",
            nickname="作者甲",
            create_time=100,
        )
    )
    db.commit()

    with _record_selects() as select_statements:
        first_result = list_tasks(
            db,
            owner_id=owner_id,
            skip=0,
            limit=100,
        )
    # count + page + batched representative work + batched track metadata
    assert len(select_statements) == 4
    assert first_result.data[0].display_title == "中文作品甲"

    second = _task(db, owner_id=owner_id, video_id="7620000000000000002")
    db.add(
        DouyinAweme(
            task_id=second.id,
            aweme_id="7620000000000000002",
            title="中文作品乙",
            nickname="作者乙",
            create_time=200,
        )
    )
    db.commit()

    with _record_selects() as select_statements:
        second_result = list_tasks(
            db,
            owner_id=owner_id,
            skip=0,
            limit=100,
        )

    identities = {
        task.id: (task.display_title, task.display_author, task.display_aweme_id)
        for task in second_result.data
    }
    assert len(select_statements) == 4
    assert identities[first.id] == (
        "中文作品甲",
        "作者甲",
        "7610000000000000001",
    )
    assert identities[second.id] == (
        "中文作品乙",
        "作者乙",
        "7620000000000000002",
    )
