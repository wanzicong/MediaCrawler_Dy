import asyncio
import json
from typing import Any

import pytest
from sqlmodel import Session, select

from app.application.douyin.tasks.persistence import DouyinStorage, task_public_values
from app.application.douyin.tasks.service import DouyinTaskManager
from app.bootstrap.settings import settings
from app.domain.douyin.content.models import DouyinAweme
from app.domain.douyin.media.models import (
    DouyinMediaProcessRequest,
    MediaStorageBackend,
)
from app.domain.douyin.tasks.models import (
    CrawlTaskCreate,
    CrawlTaskPhase,
    CrawlTaskResumeRequest,
    CrawlTaskStatus,
)
from app.domain.identity.models import User


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


def test_startup_does_not_mark_interrupted_media_as_success(db: Session) -> None:
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(
                keywords=["媒体处理中重启"],
                download_media=True,
                media_processing_mode="batch",
            ),
        )
    )
    storage = DouyinStorage(task.id)
    asyncio.run(
        storage.save_checkpoint(
            phase=CrawlTaskPhase.completed,
            crawl_type="search",
        )
    )
    asyncio.run(storage.update_task(status=CrawlTaskStatus.processing_media))

    asyncio.run(DouyinStorage.mark_active_tasks_interrupted())

    reconciled = asyncio.run(DouyinStorage.get_task(task.id))
    assert reconciled is not None
    assert reconciled.status == CrawlTaskStatus.interrupted.value
    assert reconciled.error == "API 服务重启，任务已中断"
    assert reconciled.finished_at is not None


def test_media_only_resume_switches_checkpoint_back_to_media(db: Session) -> None:
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(
                keywords=["媒体断点阶段"],
                download_media=True,
                media_processing_mode="batch",
            ),
        )
    )
    storage = DouyinStorage(task.id)
    asyncio.run(
        storage.save_checkpoint(
            phase=CrawlTaskPhase.completed,
            crawl_type="search",
        )
    )
    asyncio.run(storage.update_task(status=CrawlTaskStatus.interrupted))

    resumed = asyncio.run(
        storage.mark_resumed(
            CrawlTaskStatus.queued,
            phase=CrawlTaskPhase.media,
            crawl_type="search",
        )
    )

    checkpoint = asyncio.run(storage.load_checkpoint())
    assert resumed.status == CrawlTaskStatus.queued.value
    assert checkpoint["phase"] == CrawlTaskPhase.media.value


def test_completed_task_can_start_media_processing_without_recrawling(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(keywords=["完成后媒体处理"]),
        )
    )
    storage = DouyinStorage(task.id)
    asyncio.run(
        storage.save_checkpoint(
            phase=CrawlTaskPhase.completed,
            crawl_type="search",
        )
    )
    asyncio.run(storage.update_task(status=CrawlTaskStatus.succeeded))
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id="post-process-aweme",
            video_download_url="https://example.invalid/video.mp4",
        )
    )
    db.commit()
    asyncio.run(storage.update_task(aweme_count=1))
    captured: dict[str, Any] = {}

    class FakeCrawler:
        def __init__(self, **kwargs: Any) -> None:
            captured["request"] = kwargs["request"]

        async def run(self, **kwargs: Any) -> None:
            captured["run"] = kwargs

    monkeypatch.setattr(
        "app.application.douyin.tasks.service.DouyinCrawlerService", FakeCrawler
    )
    manager = DouyinTaskManager()

    async def process_and_wait() -> None:
        await manager.process_media(
            task_id=task.id,
            options=DouyinMediaProcessRequest(
                media_storage=MediaStorageBackend.minio,
                force_retranslate=True,
                transcription_language="zh",
                cookies="sessionid=one-time-media-secret",
            ),
        )
        for _ in range(100):
            current = await DouyinStorage.get_task(task.id)
            if current and current.status == CrawlTaskStatus.succeeded.value:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("完成后媒体处理任务没有结束")

    asyncio.run(process_and_wait())

    completed = asyncio.run(DouyinStorage.get_task(task.id))
    assert completed is not None
    persisted_request = json.loads(completed.request_json)
    assert persisted_request["download_media"] is True
    assert persisted_request["translate_subtitles"] is True
    assert persisted_request["media_storage"] == "minio"
    assert persisted_request["transcription_language"] == "zh"
    assert "cookies" not in persisted_request
    assert "one-time-media-secret" not in completed.request_json
    assert completed.resume_count == 1
    assert captured["run"] == {
        "crawl_enabled": False,
        "media_enabled": True,
        "force_retranslate": True,
    }
    in_memory_request = captured["request"]
    assert in_memory_request.cookies is not None
    assert (
        in_memory_request.cookies.get_secret_value()
        == "sessionid=one-time-media-secret"
    )
