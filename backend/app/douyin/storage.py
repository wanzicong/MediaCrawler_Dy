# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col, func, select

from app.core.db import engine
from app.douyin.privacy import map_aweme, map_comment
from app.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskStatus,
    DouyinAweme,
    DouyinComment,
    DouyinUserAction,
    get_datetime_utc,
)


class DouyinStorage:
    """SQLModel/PostgreSQL adapter used by the extracted crawler."""

    def __init__(self, task_id: uuid.UUID):
        self.task_id = task_id

    @staticmethod
    async def create_task(
        owner_id: uuid.UUID, request: CrawlTaskCreate
    ) -> CrawlTask:
        return await asyncio.to_thread(
            DouyinStorage._create_task_sync, owner_id, request
        )

    @staticmethod
    def _create_task_sync(owner_id: uuid.UUID, request: CrawlTaskCreate) -> CrawlTask:
        task = CrawlTask(
            owner_id=owner_id,
            crawl_type=request.crawl_type.value,
            status=CrawlTaskStatus.queued.value,
            request_json=json.dumps(request.public_request(), ensure_ascii=False),
        )
        with Session(engine) as session:
            session.add(task)
            session.commit()
            session.refresh(task)
            return task

    async def update_task(self, **values: Any) -> None:
        await asyncio.to_thread(self._update_task_sync, values)

    def _update_task_sync(self, values: dict[str, Any]) -> None:
        normalized = {
            key: (value.value if isinstance(value, CrawlTaskStatus) else value)
            for key, value in values.items()
        }
        with Session(engine) as session:
            task = session.get(CrawlTask, self.task_id)
            if task is None:
                raise KeyError(f"Douyin task not found: {self.task_id}")
            task.sqlmodel_update(normalized)
            session.add(task)
            session.commit()

    @staticmethod
    async def mark_active_tasks_interrupted() -> None:
        await asyncio.to_thread(DouyinStorage._mark_active_tasks_interrupted_sync)

    @staticmethod
    def _mark_active_tasks_interrupted_sync() -> None:
        active = {
            CrawlTaskStatus.queued.value,
            CrawlTaskStatus.waiting_login.value,
            CrawlTaskStatus.running.value,
            CrawlTaskStatus.processing_media.value,
            CrawlTaskStatus.cancelling.value,
        }
        now = get_datetime_utc()
        with Session(engine) as session:
            tasks = session.exec(
                select(CrawlTask).where(col(CrawlTask.status).in_(active))
            ).all()
            for task in tasks:
                task.status = CrawlTaskStatus.interrupted.value
                task.error = "API 服务重启，任务已中断"
                task.finished_at = now
                task.qrcode_path = None
                session.add(task)
            session.commit()

    async def save_aweme(
        self, item: dict[str, Any], *, source_keyword: str
    ) -> bool:
        mapped = map_aweme(item, source_keyword)
        if not mapped["aweme_id"]:
            return False
        return await asyncio.to_thread(self._save_aweme_sync, mapped)

    def _save_aweme_sync(self, mapped: dict[str, Any]) -> bool:
        values = {"id": uuid.uuid4(), "task_id": self.task_id, **mapped}
        statement = insert(DouyinAweme).values(**values)
        statement = statement.on_conflict_do_update(
            constraint="uq_douyin_aweme_task_aweme",
            set_={
                key: value
                for key, value in mapped.items()
                if key not in {"aweme_id"}
            }
            | {"fetched_at": get_datetime_utc()},
        )
        with Session(engine) as session:
            existed = session.exec(
                select(DouyinAweme.id).where(
                    DouyinAweme.task_id == self.task_id,
                    DouyinAweme.aweme_id == mapped["aweme_id"],
                )
            ).first()
            session.execute(statement)
            session.commit()
            self._refresh_counts(session)
            return existed is None

    async def save_comments(
        self, aweme_id: str, items: list[dict[str, Any]]
    ) -> None:
        mapped = [value for item in items if (value := map_comment(item, aweme_id))]
        if mapped:
            await asyncio.to_thread(self._save_comments_sync, mapped)

    def _save_comments_sync(self, mapped_items: list[dict[str, Any]]) -> None:
        with Session(engine) as session:
            for mapped in mapped_items:
                values = {"id": uuid.uuid4(), "task_id": self.task_id, **mapped}
                statement = insert(DouyinComment).values(**values)
                statement = statement.on_conflict_do_update(
                    constraint="uq_douyin_comment_task_comment",
                    set_={
                        key: value
                        for key, value in mapped.items()
                        if key not in {"comment_id"}
                    }
                    | {"fetched_at": get_datetime_utc()},
                )
                session.execute(statement)
            session.commit()
            self._refresh_counts(session)

    async def save_action(
        self, account_hash: str, aweme_id: str, action_type: str
    ) -> None:
        await asyncio.to_thread(
            self._save_action_sync, account_hash, aweme_id, action_type
        )

    def _save_action_sync(
        self, account_hash: str, aweme_id: str, action_type: str
    ) -> None:
        values = {
            "id": uuid.uuid4(),
            "task_id": self.task_id,
            "account_hash": account_hash,
            "aweme_id": aweme_id,
            "action_type": action_type,
            "observed_at": get_datetime_utc(),
        }
        statement = insert(DouyinUserAction).values(**values)
        statement = statement.on_conflict_do_update(
            constraint="uq_douyin_action_task_account_aweme_type",
            set_={"observed_at": values["observed_at"]},
        )
        with Session(engine) as session:
            session.execute(statement)
            session.commit()
            self._refresh_counts(session)

    def _refresh_counts(self, session: Session) -> None:
        aweme_count = session.exec(
            select(func.count()).select_from(DouyinAweme).where(
                DouyinAweme.task_id == self.task_id
            )
        ).one()
        comment_count = session.exec(
            select(func.count()).select_from(DouyinComment).where(
                DouyinComment.task_id == self.task_id
            )
        ).one()
        action_count = session.exec(
            select(func.count()).select_from(DouyinUserAction).where(
                DouyinUserAction.task_id == self.task_id
            )
        ).one()
        task = session.get(CrawlTask, self.task_id)
        if task is None:
            raise KeyError(f"Douyin task not found: {self.task_id}")
        task.aweme_count = aweme_count
        task.comment_count = comment_count
        task.action_count = action_count
        session.add(task)
        session.commit()

    async def counts(self) -> tuple[int, int, int]:
        return await asyncio.to_thread(self._counts_sync)

    def _counts_sync(self) -> tuple[int, int, int]:
        with Session(engine) as session:
            task = session.get(CrawlTask, self.task_id)
            if not task:
                return 0, 0, 0
            return task.aweme_count, task.comment_count, task.action_count


def task_public_values(task: CrawlTask) -> dict[str, Any]:
    qrcode = Path(task.qrcode_path) if task.qrcode_path else None
    return {
        "id": task.id,
        "owner_id": task.owner_id,
        "crawl_type": task.crawl_type,
        "status": task.status,
        "request": json.loads(task.request_json),
        "aweme_count": task.aweme_count,
        "comment_count": task.comment_count,
        "action_count": task.action_count,
        "error": task.error,
        "has_qrcode": bool(qrcode and qrcode.is_file()),
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
    }
