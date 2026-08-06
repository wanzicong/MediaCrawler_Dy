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
    CrawlTaskPhase,
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
            checkpoint_json=json.dumps(
                {
                    "version": 1,
                    "phase": CrawlTaskPhase.crawl.value,
                    "crawl_type": request.crawl_type.value,
                    "position": {},
                },
                ensure_ascii=False,
            ),
        )
        with Session(engine) as session:
            session.add(task)
            session.commit()
            session.refresh(task)
            return task

    @staticmethod
    async def get_task(task_id: uuid.UUID) -> CrawlTask | None:
        return await asyncio.to_thread(DouyinStorage._get_task_sync, task_id)

    @staticmethod
    def _get_task_sync(task_id: uuid.UUID) -> CrawlTask | None:
        with Session(engine) as session:
            task = session.get(CrawlTask, task_id)
            if task is not None:
                session.expunge(task)
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

    async def load_checkpoint(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._load_checkpoint_sync)

    def _load_checkpoint_sync(self) -> dict[str, Any]:
        with Session(engine) as session:
            task = session.get(CrawlTask, self.task_id)
            if task is None:
                raise KeyError(f"Douyin task not found: {self.task_id}")
            try:
                checkpoint = json.loads(task.checkpoint_json or "{}")
            except json.JSONDecodeError:
                checkpoint = {}
            if not isinstance(checkpoint, dict):
                checkpoint = {}
            phase = checkpoint.get("phase")
            if phase not in {item.value for item in CrawlTaskPhase}:
                phase = (
                    CrawlTaskPhase.completed.value
                    if task.status == CrawlTaskStatus.succeeded.value
                    else CrawlTaskPhase.crawl.value
                )
            position = checkpoint.get("position")
            return {
                "version": 1,
                "phase": phase,
                "crawl_type": str(checkpoint.get("crawl_type") or task.crawl_type),
                "position": position if isinstance(position, dict) else {},
            }

    async def save_checkpoint(
        self,
        *,
        phase: CrawlTaskPhase,
        crawl_type: str,
        position: dict[str, Any] | None = None,
    ) -> None:
        checkpoint = {
            "version": 1,
            "phase": phase.value,
            "crawl_type": crawl_type,
            "position": position or {},
        }
        await asyncio.to_thread(self._save_checkpoint_sync, checkpoint)

    def _save_checkpoint_sync(self, checkpoint: dict[str, Any]) -> None:
        with Session(engine) as session:
            task = session.get(CrawlTask, self.task_id)
            if task is None:
                raise KeyError(f"Douyin task not found: {self.task_id}")
            task.checkpoint_json = json.dumps(checkpoint, ensure_ascii=False)
            session.add(task)
            session.commit()

    async def complete_task(self, crawl_type: str) -> CrawlTask:
        return await asyncio.to_thread(self._complete_task_sync, crawl_type)

    def _complete_task_sync(self, crawl_type: str) -> CrawlTask:
        checkpoint = {
            "version": 1,
            "phase": CrawlTaskPhase.completed.value,
            "crawl_type": crawl_type,
            "position": {},
        }
        with Session(engine) as session:
            task = session.get(CrawlTask, self.task_id)
            if task is None:
                raise KeyError(f"Douyin task not found: {self.task_id}")
            task.checkpoint_json = json.dumps(checkpoint, ensure_ascii=False)
            task.status = CrawlTaskStatus.succeeded.value
            task.error = None
            task.qrcode_path = None
            task.finished_at = get_datetime_utc()
            session.add(task)
            session.commit()
            session.refresh(task)
            session.expunge(task)
            return task

    async def mark_resumed(self, status: CrawlTaskStatus) -> CrawlTask:
        return await asyncio.to_thread(self._mark_resumed_sync, status)

    def _mark_resumed_sync(self, status: CrawlTaskStatus) -> CrawlTask:
        with Session(engine) as session:
            task = session.get(CrawlTask, self.task_id)
            if task is None:
                raise KeyError(f"Douyin task not found: {self.task_id}")
            task.status = status.value
            task.resume_count += 1
            task.last_resumed_at = get_datetime_utc()
            task.finished_at = None
            task.error = None
            task.qrcode_path = None
            session.add(task)
            session.commit()
            session.refresh(task)
            session.expunge(task)
            return task

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
                try:
                    checkpoint = json.loads(task.checkpoint_json or "{}")
                except json.JSONDecodeError:
                    checkpoint = {}
                completed = bool(
                    isinstance(checkpoint, dict)
                    and checkpoint.get("phase") == CrawlTaskPhase.completed.value
                )
                task.status = (
                    CrawlTaskStatus.succeeded.value
                    if completed
                    else CrawlTaskStatus.interrupted.value
                )
                task.error = None if completed else "API 服务重启，任务已中断"
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

    async def aweme_ids(self) -> set[str]:
        return await asyncio.to_thread(self._aweme_ids_sync)

    def _aweme_ids_sync(self) -> set[str]:
        with Session(engine) as session:
            return set(
                session.exec(
                    select(DouyinAweme.aweme_id).where(
                        DouyinAweme.task_id == self.task_id
                    )
                ).all()
            )

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
    try:
        request = json.loads(task.request_json)
    except json.JSONDecodeError:
        request = {}
    if not isinstance(request, dict):
        request = {}
    try:
        checkpoint = json.loads(task.checkpoint_json or "{}")
    except json.JSONDecodeError:
        checkpoint = {}
    if not isinstance(checkpoint, dict):
        checkpoint = {}
    raw_phase = checkpoint.get("phase")
    if raw_phase not in {phase.value for phase in CrawlTaskPhase}:
        raw_phase = (
            CrawlTaskPhase.completed.value
            if task.status == CrawlTaskStatus.succeeded.value
            else CrawlTaskPhase.crawl.value
        )
    phase = CrawlTaskPhase(raw_phase)
    terminal = task.status in {
        CrawlTaskStatus.succeeded.value,
        CrawlTaskStatus.failed.value,
        CrawlTaskStatus.cancelled.value,
        CrawlTaskStatus.interrupted.value,
    }
    return {
        "id": task.id,
        "owner_id": task.owner_id,
        "crawl_type": task.crawl_type,
        "status": task.status,
        "request": request,
        "aweme_count": task.aweme_count,
        "comment_count": task.comment_count,
        "action_count": task.action_count,
        "checkpoint_phase": phase,
        "resume_count": task.resume_count,
        "can_resume_crawl": bool(
            task.status
            in {
                CrawlTaskStatus.failed.value,
                CrawlTaskStatus.cancelled.value,
                CrawlTaskStatus.interrupted.value,
            }
            and phase == CrawlTaskPhase.crawl
        ),
        "can_resume_media": bool(terminal and request.get("download_media")),
        "error": task.error,
        "has_qrcode": bool(qrcode and qrcode.is_file()),
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "last_resumed_at": task.last_resumed_at,
    }
