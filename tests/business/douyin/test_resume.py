"""抖音任务断点续跑的测试：覆盖检查点持久化与续跑元信息、媒体阶段免浏览器恢复、启动时对中断任务的状态 reconcile、媒体补跑的请求改写与 cookies 一次性使用。"""

import asyncio
import json
from typing import Any

import pytest
from crawler.bootstrap.settings import settings
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.media.models import (
    DouyinMediaProcessRequest,
    MediaStorageBackend,
)
from crawler.business.douyin.tasks.models import (
    CrawlTaskCreate,
    CrawlTaskPhase,
    CrawlTaskResumeRequest,
    CrawlTaskStatus,
)
from crawler.business.douyin.tasks.persistence import DouyinStorage, task_public_values
from crawler.business.douyin.tasks.service import DouyinTaskManager
from crawler.business.identity.models import User
from sqlmodel import Session, select


def test_checkpoint_and_resume_metadata_are_persisted(db: Session) -> None:
    """验证采集中断后检查点位置被持久化、公开元信息标记可续跑，且续跑后状态/次数/错误字段被正确重置。"""
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
    """验证仅恢复媒体阶段时任务无需重新打开浏览器即可推进至完成，检查点随之标记 completed。"""
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
        """发起媒体恢复并轮询等待任务进入成功状态，超时则判定失败。"""
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
    """验证启动 reconcile 时：检查点已 completed 但状态停在 running 的任务被修正为成功并清除错误。"""
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
    """验证启动 reconcile 时：处于媒体处理中的任务不会被误判为成功，而是标记为中断并记录重启原因。"""
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
    """验证仅补跑媒体时检查点阶段从 completed 回切到 media，以便媒体流程按自身检查点推进。"""
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
    """验证已完成任务可单独发起媒体后处理而不重新采集：持久化请求被改写、cookies 仅存在于内存请求中不入库。"""
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
        """模拟采集服务：捕获构造时的请求对象与 run 调用参数，不执行真实采集。"""

        def __init__(self, **kwargs: Any) -> None:
            """记录传入的任务请求对象。"""
            captured["request"] = kwargs["request"]

        async def run(self, **kwargs: Any) -> None:
            """记录一次运行参数。"""
            captured["run"] = kwargs

    monkeypatch.setattr(
        "crawler.business.douyin.tasks.service.DouyinCrawlerService", FakeCrawler
    )
    manager = DouyinTaskManager()

    async def process_and_wait() -> None:
        """发起媒体后处理并轮询等待任务回到成功状态，超时则判定失败。"""
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
