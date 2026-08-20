"""采集任务列表与详情响应中展示身份（代表作品标题/作者/aweme_id）的读侧测试。"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from crawler.bootstrap.database import engine
from crawler.bootstrap.settings import settings
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.tasks.models import CrawlTask
from crawler.business.douyin.tasks.query_service import list_tasks
from crawler.business.identity.models import User
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import Session, select

from tests.utils.douyin import default_track_id


def _superuser(db: Session) -> User:
    """获取首位超级管理员用户。"""
    return db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()


def _task(db: Session, *, owner_id: uuid.UUID, video_id: str) -> CrawlTask:
    """创建并入库一条指定视频 id 的已完成详情采集任务。"""
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
    """记录上下文期间对引擎执行的全部 SELECT 语句（用于验证批量查询不产生 N+1）。"""
    statements: list[str] = []

    def before_cursor_execute(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        """捕获 SELECT 语句文本。"""
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
    """验证任务详情返回稳定的代表作品身份（取最新作品的标题/作者/aweme_id）。"""
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
    """验证无作品的任务详情中展示身份字段为空值而非报错。"""
    task = _task(db, owner_id=_superuser(db).id, video_id="7600000000000000099")

    response = client.get(
        f"/api/v1/douyin/tasks/{task.id}", headers=superuser_token_headers
    )

    assert response.status_code == 200
    assert response.json()["display_title"] is None
    assert response.json()["display_author"] is None
    assert response.json()["display_aweme_id"] is None


def test_list_tasks_batches_identity_query_and_maps_each_task(db: Session) -> None:
    """验证任务列表的代表作品身份与达人名通过批量查询装配（固定 5 条 SELECT，无 N+1），且每个任务映射到各自作品。"""
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
    # 计数 + 分页 + 代表作品批量查询 + 达人名批量查询 + 赛道元信息批量查询
    assert len(select_statements) == 5
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
    assert len(select_statements) == 5
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
