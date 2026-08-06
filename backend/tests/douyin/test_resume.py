import asyncio

from sqlmodel import Session, select

from app.core.config import settings
from app.douyin.storage import DouyinStorage, task_public_values
from app.models import (
    CrawlTaskCreate,
    CrawlTaskPhase,
    CrawlTaskResumeRequest,
    CrawlTaskStatus,
    User,
)
from app.services.douyin_tasks import DouyinTaskManager


def test_checkpoint_and_resume_metadata_are_persisted(db: Session) -> None:
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(
                keywords=["断点"],
                download_media=True,
                media_processing_mode="batch",
            ),
        )
    )
    storage = DouyinStorage(task.id)
    asyncio.run(
        storage.save_checkpoint(
            phase=CrawlTaskPhase.crawl,
            crawl_type="search",
            position={
                "target_index": 0,
                "page": 3,
                "stage": "comments",
                "pending_aweme_ids": ["123"],
            },
        )
    )
    asyncio.run(
        storage.update_task(
            status=CrawlTaskStatus.interrupted,
            error="simulated restart",
        )
    )

    checkpoint = asyncio.run(storage.load_checkpoint())
    interrupted = asyncio.run(DouyinStorage.get_task(task.id))

    assert checkpoint["position"]["page"] == 3
    assert checkpoint["position"]["stage"] == "comments"
    assert interrupted is not None
    public = task_public_values(interrupted)
    assert public["checkpoint_phase"] == CrawlTaskPhase.crawl
    assert public["can_resume_crawl"] is True
    assert public["can_resume_media"] is True

    resumed = asyncio.run(storage.mark_resumed(CrawlTaskStatus.queued))

    assert resumed.status == CrawlTaskStatus.queued.value
    assert resumed.resume_count == 1
    assert resumed.last_resumed_at is not None
    assert resumed.finished_at is None
    assert resumed.error is None


def test_media_phase_resume_completes_without_reopening_browser(db: Session) -> None:
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(
                keywords=["媒体恢复"],
                download_media=True,
                media_processing_mode="batch",
            ),
        )
    )
    storage = DouyinStorage(task.id)
    asyncio.run(
        storage.save_checkpoint(
            phase=CrawlTaskPhase.media,
            crawl_type="search",
        )
    )
    asyncio.run(
        storage.update_task(
            status=CrawlTaskStatus.interrupted,
            error="simulated media interruption",
        )
    )
    manager = DouyinTaskManager()

    async def resume_and_wait() -> None:
        await manager.resume(
            task_id=task.id,
            options=CrawlTaskResumeRequest(
                resume_crawl=False,
                resume_media=True,
            ),
        )
        for _ in range(100):
            current = await DouyinStorage.get_task(task.id)
            if current and current.status == CrawlTaskStatus.succeeded.value:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("媒体恢复任务没有完成")

    asyncio.run(resume_and_wait())

    completed = asyncio.run(DouyinStorage.get_task(task.id))
    checkpoint = asyncio.run(storage.load_checkpoint())
    assert completed is not None
    assert completed.status == CrawlTaskStatus.succeeded.value
    assert completed.resume_count == 1
    assert checkpoint["phase"] == CrawlTaskPhase.completed.value


def test_startup_reconciles_completed_checkpoint_to_success(db: Session) -> None:
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(keywords=["启动恢复"]),
        )
    )
    storage = DouyinStorage(task.id)
    asyncio.run(
        storage.save_checkpoint(
            phase=CrawlTaskPhase.completed,
            crawl_type="search",
        )
    )
    asyncio.run(
        storage.update_task(
            status=CrawlTaskStatus.running,
            error="simulated crash after checkpoint commit",
        )
    )

    asyncio.run(DouyinStorage.mark_active_tasks_interrupted())

    reconciled = asyncio.run(DouyinStorage.get_task(task.id))
    assert reconciled is not None
    assert reconciled.status == CrawlTaskStatus.succeeded.value
    assert reconciled.error is None
    assert reconciled.finished_at is not None
