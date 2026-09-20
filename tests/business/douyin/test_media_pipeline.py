"""抖音媒体处理管线的测试：覆盖任务公平限流、错误文案、入队与重试、存储后端切换、转写地址校验、FFmpeg 音频提取与超时治理、媒体列表排序、流式下载原子提交与端到端超时。"""

import asyncio
import hashlib
import os
import time
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from crawler.bootstrap.settings import settings
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.media.models import (
    DouyinMediaAsset,
    DouyinSubtitle,
    MediaDownloadStatus,
    MediaStorageBackend,
    SubtitleStatus,
)
from crawler.business.douyin.media.pipeline import (
    MediaPipelineManager,
    _safe_error,
    _TaskFairLimiter,
    list_media_sync,
    media_public,
    original_sound_url,
    retry_backoff_seconds,
)
from crawler.business.douyin.media.storage import StoredMedia, media_storage
from crawler.business.douyin.tasks.models import CrawlTask, CrawlTaskCreate
from crawler.business.douyin.tasks.persistence import DouyinStorage
from crawler.business.douyin.tracks.models import DouyinTrack
from crawler.business.identity.models import User
from sqlmodel import Session, select


def test_media_retry_backoff_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证媒体重试退避默认等价于旧实现，且可被 config.yaml 的 media.retry_backoff 覆盖。"""
    # 旧实现是 min(2 ** (attempt + 1), 5)，默认配置必须逐项一致
    assert [retry_backoff_seconds(attempt) for attempt in range(3)] == [2.0, 4.0, 5.0]

    monkeypatch.setattr(settings, "MEDIA_RETRY_BACKOFF_BASE_SECONDS", 1.0)
    monkeypatch.setattr(settings, "MEDIA_RETRY_BACKOFF_MULTIPLIER", 3.0)
    monkeypatch.setattr(settings, "MEDIA_RETRY_BACKOFF_MAX_SECONDS", 10.0)

    assert [retry_backoff_seconds(attempt) for attempt in range(4)] == [
        1.0,
        3.0,
        9.0,
        10.0,
    ]


def test_task_fair_limiter_does_not_starve_later_task() -> None:
    """验证按任务公平轮转的并发限制器：同任务连续排队不会饿死后到任务（交替获得槽位）。"""

    async def scenario() -> list[str]:
        """编排三同一异的四个协程竞争单槽位，返回实际执行顺序。"""
        limiter = _TaskFairLimiter(1)
        first_task = uuid.uuid4()
        later_task = uuid.uuid4()
        release_first = asyncio.Event()
        order: list[str] = []

        async def run(label: str, task_id: uuid.UUID, hold: bool = False) -> None:
            """占用一个槽位记录标签；hold 时先等待放行信号。"""
            async with limiter.slot(task_id):
                order.append(label)
                if hold:
                    await release_first.wait()

        first = asyncio.create_task(run("first-1", first_task, hold=True))
        await asyncio.sleep(0)
        queued = [
            asyncio.create_task(run("first-2", first_task)),
            asyncio.create_task(run("first-3", first_task)),
            asyncio.create_task(run("later-1", later_task)),
        ]
        await asyncio.sleep(0)
        release_first.set()
        await asyncio.gather(first, *queued)
        return order

    assert asyncio.run(scenario()) == [
        "first-1",
        "first-2",
        "later-1",
        "first-3",
    ]


def test_empty_remote_timeout_error_has_actionable_detail() -> None:
    """验证空消息的写超时异常被转换为带可操作指引的中文错误文案。"""
    error = _safe_error(httpx.WriteTimeout(""))

    assert error == "WriteTimeout: 远程服务未及时接收上传内容"


def test_empty_connect_error_has_actionable_detail() -> None:
    """验证空消息的连接异常被转换为带可操作指引的中文错误文案。"""
    error = _safe_error(httpx.ConnectError(""))

    assert error == "ConnectError: 无法连接媒体源或远程服务"


def test_enqueue_task_forwards_force_retranslation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证任务级媒体入队将强制重译、存储后端、语言与请求头等参数原样透传到作品级入队。"""
    manager = MediaPipelineManager()
    monkeypatch.setattr(manager, "_task_aweme_ids_sync", lambda _task_id: ["aweme-1"])
    enqueue = AsyncMock(return_value=None)
    monkeypatch.setattr(manager, "enqueue_aweme", enqueue)
    task_id = uuid.uuid4()

    queued = asyncio.run(
        manager.enqueue_task(
            task_id=task_id,
            storage_backend="minio",
            translate_subtitles=True,
            language="zh",
            headers={"Cookie": "sessionid=one-time"},
            force_retranslate=True,
        )
    )

    assert queued == 1
    enqueue.assert_awaited_once_with(
        task_id=task_id,
        aweme_id="aweme-1",
        storage_backend="minio",
        translate_subtitles=True,
        language="zh",
        headers={"Cookie": "sessionid=one-time"},
        force_retranslate=True,
        temporary_only=False,
    )


def test_retry_task_recovers_durable_queued_asset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证重试会捞起滞留 queued 状态的资产并以强制下载方式重新入队。"""
    manager = MediaPipelineManager()
    task_id = uuid.uuid4()
    asset = DouyinMediaAsset(
        task_id=task_id,
        aweme_id="stale-queued",
        status=MediaDownloadStatus.queued.value,
        storage_backend=MediaStorageBackend.minio.value,
    )
    monkeypatch.setattr(
        manager, "_retry_candidates_sync", lambda *_args: [(asset, None)]
    )
    enqueue = AsyncMock(return_value=asset)
    monkeypatch.setattr(manager, "enqueue_aweme", enqueue)

    recovered = asyncio.run(
        manager.retry_task(
            task_id=task_id,
            asset_ids=[],
            retry_downloads=True,
            retry_subtitles=False,
            force_retranslate=False,
        )
    )

    assert recovered == 1
    assert enqueue.await_args.kwargs["force_download"] is True


def test_disabled_track_rejects_media_retry(db: Session) -> None:
    """赛道冻结后，持久化媒体重试入口不得重新排队下载或字幕任务。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    track = DouyinTrack(
        owner_id=owner.id,
        name=f"媒体准入-{uuid.uuid4().hex[:8]}",
        normalized_name=f"media-admission-{uuid.uuid4().hex}",
    )
    db.add(track)
    db.flush()
    task = CrawlTask(
        owner_id=owner.id,
        track_id=track.id,
        crawl_type="search",
        status="failed",
        request_json='{"crawl_type":"search","keywords":["冻结媒体重试"]}',
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    track.enabled = False
    db.add(track)
    db.commit()
    manager = MediaPipelineManager()

    with pytest.raises(ValueError, match="赛道已停用"):
        asyncio.run(
            manager.retry_task(
                task_id=task.id,
                asset_ids=[],
                retry_downloads=True,
                retry_subtitles=True,
                force_retranslate=False,
            )
        )
    assert manager._handles == {}
    track.enabled = True
    db.add(track)
    db.commit()


def test_pending_asset_uses_new_storage_choice_but_downloaded_asset_stays_put(
    db: Session,
) -> None:
    """验证未完成资产重备时按新选择的存储后端重置；已下载资产保持原后端不被迁移。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(keywords=["切换媒体存储"]),
        )
    )
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id="storage-switch-aweme",
            video_download_url="https://example.invalid/video.mp4",
        )
    )
    db.add(
        DouyinMediaAsset(
            task_id=task.id,
            aweme_id="storage-switch-aweme",
            status=MediaDownloadStatus.failed.value,
            progress=63,
            error="API 服务重启，下载任务已中断",
            storage_backend=MediaStorageBackend.local.value,
            local_path="stale-local-path",
        )
    )
    db.commit()
    manager = MediaPipelineManager()

    pending = manager._prepare_asset_sync(
        task.id,
        "storage-switch-aweme",
        MediaStorageBackend.minio,
    )
    assert pending is not None
    assert pending.storage_backend == MediaStorageBackend.minio.value
    assert pending.storage_bucket == settings.MINIO_BUCKET
    assert pending.object_key
    assert pending.local_path == ""
    assert pending.status == MediaDownloadStatus.queued.value
    assert pending.progress == 0
    assert pending.error is None

    pending.status = MediaDownloadStatus.downloaded.value
    db.merge(pending)
    db.commit()
    downloaded = manager._prepare_asset_sync(
        task.id,
        "storage-switch-aweme",
        MediaStorageBackend.local,
    )
    assert downloaded is not None
    assert downloaded.storage_backend == MediaStorageBackend.minio.value


def test_new_task_reuses_existing_downloaded_aweme_media(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证不同任务再次命中同一作品时复用已有本地副本，不访问视频下载地址。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    first_task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(keywords=[f"媒体复用源-{uuid.uuid4().hex[:8]}"]),
        )
    )
    second_task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(keywords=[f"媒体复用目标-{uuid.uuid4().hex[:8]}"]),
        )
    )
    aweme_id = f"shared-media-{uuid.uuid4().hex}"
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    source_file = tmp_path / "source.mp4"
    source_file.write_bytes(b"already-downloaded")
    db.add(
        DouyinAweme(
            task_id=first_task.id,
            aweme_id=aweme_id,
            video_download_url="https://example.invalid/source.mp4",
        )
    )
    db.add(
        DouyinAweme(
            task_id=second_task.id,
            aweme_id=aweme_id,
            video_download_url="https://example.invalid/duplicate.mp4",
        )
    )
    db.add(
        DouyinMediaAsset(
            task_id=first_task.id,
            aweme_id=aweme_id,
            storage_backend=MediaStorageBackend.local.value,
            status=MediaDownloadStatus.downloaded.value,
            local_path=str(source_file),
            file_size=source_file.stat().st_size,
            sha256="source-sha256",
        )
    )
    db.commit()
    manager = MediaPipelineManager()
    prepared = manager._prepare_asset_sync(
        second_task.id,
        aweme_id,
        MediaStorageBackend.local,
    )
    assert prepared is not None
    assert prepared.status == MediaDownloadStatus.queued.value
    assert prepared.local_path == str(source_file)

    async def fail_download(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        """复用已有副本时不应调用网络下载。"""
        raise AssertionError("reused media must not access the video URL")

    monkeypatch.setattr(manager, "_download_once", fail_download)
    asyncio.run(manager._download(prepared, headers={}, force=False))
    db.expire_all()
    reused = db.exec(
        select(DouyinMediaAsset).where(
            DouyinMediaAsset.task_id == second_task.id,
            DouyinMediaAsset.aweme_id == aweme_id,
        )
    ).one()
    assert reused.status == MediaDownloadStatus.downloaded.value
    assert reused.local_path == str(source_file)


def test_startup_prepares_interrupted_media_for_automatic_resume(db: Session) -> None:
    """验证容器重启后下载和字幕回到可重入状态，并保留原任务依赖信息。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(keywords=[f"媒体自动续跑-{uuid.uuid4().hex[:8]}"]),
        )
    )
    aweme_id = f"resume-media-{uuid.uuid4().hex}"
    db.add(DouyinAweme(task_id=task.id, aweme_id=aweme_id))
    asset = DouyinMediaAsset(
        task_id=task.id,
        aweme_id=aweme_id,
        status=MediaDownloadStatus.downloading.value,
        progress=57,
        error="连接被中断",
        storage_backend=MediaStorageBackend.minio.value,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    subtitle = DouyinSubtitle(
        asset_id=asset.id,
        task_id=task.id,
        aweme_id=aweme_id,
        status=SubtitleStatus.running.value,
        progress=35,
        language="zh",
        error="转写被中断",
    )
    db.add(subtitle)
    db.commit()

    jobs = MediaPipelineManager()._prepare_interrupted_sync()

    assert (
        task.id,
        aweme_id,
        MediaStorageBackend.minio.value,
        True,
        "zh",
        False,
    ) in jobs
    db.expire_all()
    resumed_asset = db.get(DouyinMediaAsset, asset.id)
    resumed_subtitle = db.get(DouyinSubtitle, subtitle.id)
    assert resumed_asset is not None
    assert resumed_asset.status == MediaDownloadStatus.queued.value
    assert resumed_asset.progress == 0
    assert resumed_asset.error is None
    assert resumed_subtitle is not None
    assert resumed_subtitle.status == SubtitleStatus.pending.value
    assert resumed_subtitle.progress == 0
    assert resumed_subtitle.error is None


def test_subtitle_only_downloads_to_tmp_and_cleans_video(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证仅字幕任务只在临时目录准备视频，转写完成后不留下文件或可播放资产。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(
                keywords=[f"仅字幕临时下载-{uuid.uuid4().hex[:8]}"],
                subtitle_only=True,
            ),
        )
    )
    aweme_id = f"temporary-subtitle-{uuid.uuid4().hex}"
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id=aweme_id,
            video_download_url="https://example.invalid/temporary.mp4",
        )
    )
    db.commit()

    manager = MediaPipelineManager()
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    observed_paths: list[Path] = []

    async def fake_download(
        _asset_id: uuid.UUID,
        _source_url: str,
        _partial_path: Path,
        final_path: Path,
        _headers: dict[str, str],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        final_path.write_bytes(b"temporary-video")
        return {
            "file_size": 15,
            "sha256": "temporary-sha",
            "mime_type": "video/mp4",
        }

    async def fake_transcribe(
        _asset: DouyinMediaAsset,
        *,
        language: str,
        media_path: Path | None = None,
        mime_type: str | None = None,
    ) -> None:
        assert language == "zh"
        assert mime_type == "video/mp4"
        assert media_path is not None and media_path.is_file()
        observed_paths.append(media_path)

    monkeypatch.setattr(manager, "_download_once", fake_download)
    monkeypatch.setattr(manager, "_transcribe", fake_transcribe)

    async def run_media() -> None:
        await manager.enqueue_aweme(
            task_id=task.id,
            aweme_id=aweme_id,
            storage_backend=None,
            translate_subtitles=True,
            language="zh",
            temporary_only=True,
        )
        await manager.wait_for_task(task.id)

    asyncio.run(run_media())

    db.expire_all()
    asset = db.exec(
        select(DouyinMediaAsset).where(
            DouyinMediaAsset.task_id == task.id,
            DouyinMediaAsset.aweme_id == aweme_id,
        )
    ).one()
    assert observed_paths and not observed_paths[0].exists()
    assert asset.status == MediaDownloadStatus.temporary.value
    assert asset.local_path == ""
    assert asset.object_key == ""
    assert not media_public(asset, None).download_available
    tmp_root = tmp_path / ".tmp"
    assert not tmp_root.exists() or not list(tmp_root.iterdir())


def test_reused_copy_marks_asset_downloaded_in_subtitle_only_flow(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证仅字幕流程复用其它任务的已存副本时，资产要落成「已下载」而不是停在 queued。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(
                keywords=[f"复用副本-{uuid.uuid4().hex[:8]}"],
                subtitle_only=True,
            ),
        )
    )
    aweme_id = f"reuse-copy-{uuid.uuid4().hex}"
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id=aweme_id,
            video_download_url="https://example.invalid/reuse.mp4",
        )
    )
    db.commit()
    asset = DouyinMediaAsset(
        task_id=task.id,
        aweme_id=aweme_id,
        source_url="https://example.invalid/reuse.mp4",
        storage_backend=MediaStorageBackend.minio.value,
        storage_bucket="douyin-media",
        object_key="douyin/other-task/aweme/source.mp4",
        status=MediaDownloadStatus.queued.value,
        progress=0,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    stored = StoredMedia(
        backend=MediaStorageBackend.minio,
        local_path="",
        bucket="douyin-media",
        object_key="douyin/other-task/aweme/source.mp4",
        file_size=1024,
        sha256="reused-sha",
    )

    async def fake_existing(_asset: DouyinMediaAsset) -> StoredMedia:
        """模拟存储里已存在可复用副本。"""
        return stored

    monkeypatch.setattr(media_storage, "existing", fake_existing)
    manager = MediaPipelineManager()
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)

    async def run_media() -> None:
        """仅字幕流程，不需要转写，只验证状态落库。"""
        await manager.enqueue_aweme(
            task_id=task.id,
            aweme_id=aweme_id,
            storage_backend=None,
            translate_subtitles=False,
            language="zh",
            temporary_only=True,
        )
        await manager.wait_for_task(task.id)

    asyncio.run(run_media())

    db.expire_all()
    refreshed = db.get(DouyinMediaAsset, asset.id)
    assert refreshed is not None
    assert refreshed.status == MediaDownloadStatus.downloaded.value
    assert refreshed.file_size == 1024
    assert refreshed.sha256 == "reused-sha"


def test_reused_copy_with_completed_subtitle_still_marks_downloaded(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证字幕已完成时复用副本同样会把资产落成「已下载」，而不是直接跳过不落库。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(
                keywords=[f"复用含字幕-{uuid.uuid4().hex[:8]}"],
                subtitle_only=True,
            ),
        )
    )
    aweme_id = f"reuse-done-{uuid.uuid4().hex}"
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id=aweme_id,
            video_download_url="https://example.invalid/reuse-done.mp4",
        )
    )
    db.commit()
    asset = DouyinMediaAsset(
        task_id=task.id,
        aweme_id=aweme_id,
        source_url="https://example.invalid/reuse-done.mp4",
        storage_backend=MediaStorageBackend.minio.value,
        storage_bucket="douyin-media",
        object_key="douyin/other-task/aweme/source.mp4",
        status=MediaDownloadStatus.queued.value,
        progress=0,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    db.add(
        DouyinSubtitle(
            asset_id=asset.id,
            task_id=task.id,
            aweme_id=aweme_id,
            status=SubtitleStatus.completed.value,
            progress=100,
            full_text="已经转写过的字幕",
        )
    )
    db.commit()

    stored = StoredMedia(
        backend=MediaStorageBackend.minio,
        local_path="",
        bucket="douyin-media",
        object_key="douyin/other-task/aweme/source.mp4",
        file_size=2048,
        sha256="reused-sha-2",
    )

    async def fake_existing(_asset: DouyinMediaAsset) -> StoredMedia:
        """模拟存储里已存在可复用副本。"""
        return stored

    monkeypatch.setattr(media_storage, "existing", fake_existing)
    manager = MediaPipelineManager()
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)

    async def run_media() -> None:
        """仅字幕流程：字幕已完成，不应重新转写。"""
        await manager.enqueue_aweme(
            task_id=task.id,
            aweme_id=aweme_id,
            storage_backend=None,
            translate_subtitles=True,
            language="zh",
            temporary_only=True,
        )
        await manager.wait_for_task(task.id)

    asyncio.run(run_media())

    db.expire_all()
    refreshed = db.get(DouyinMediaAsset, asset.id)
    assert refreshed is not None
    assert refreshed.status == MediaDownloadStatus.downloaded.value
    assert refreshed.file_size == 2048
    subtitle = db.exec(
        select(DouyinSubtitle).where(DouyinSubtitle.asset_id == asset.id)
    ).one()
    assert subtitle.full_text == "已经转写过的字幕"


def test_stale_temp_dirs_are_purged_on_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证启动清理只删掉过期的 minio-media / subtitle 临时目录，保留新目录与无关目录。"""
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    temp_root = tmp_path / ".tmp"
    temp_root.mkdir(parents=True)
    stale_media = temp_root / "minio-media-stale"
    stale_media.mkdir()
    (stale_media / "source.mp4").write_bytes(b"stale-video")
    stale_subtitle = temp_root / "subtitle-stale"
    stale_subtitle.mkdir()
    fresh_media = temp_root / "minio-media-fresh"
    fresh_media.mkdir()
    unrelated = temp_root / "keep-me"
    unrelated.mkdir()
    old = time.time() - 3 * 24 * 3600
    for path in (stale_media, stale_subtitle):
        os.utime(path, (old, old))

    removed = media_storage.purge_stale_temp_dirs()

    assert removed == 2
    assert not stale_media.exists()
    assert not stale_subtitle.exists()
    assert fresh_media.is_dir()
    assert unrelated.is_dir()


def test_rate_limited_download_is_retried_instead_of_marked_expired(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证源站 429（限流）按可重试处理，不会被当成「地址失效」直接放弃。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(
                keywords=[f"限流重试-{uuid.uuid4().hex[:8]}"],
                subtitle_only=True,
            ),
        )
    )
    aweme_id = f"rate-limited-{uuid.uuid4().hex}"
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id=aweme_id,
            video_download_url="https://example.invalid/limited.mp4",
        )
    )
    db.commit()

    attempts = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        """模拟源站限流。"""
        attempts["count"] += 1
        return httpx.Response(429, content=b"too many requests")

    transport = httpx.MockTransport(handler)
    manager = MediaPipelineManager()
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(settings, "MEDIA_DOWNLOAD_RETRIES", 3)
    monkeypatch.setattr(
        manager,
        "_download_client_factory",
        lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs),
    )

    async def run_media() -> None:
        """走仅字幕流程（临时下载）。"""
        await manager.enqueue_aweme(
            task_id=task.id,
            aweme_id=aweme_id,
            storage_backend=None,
            translate_subtitles=False,
            language="zh",
            temporary_only=True,
        )
        await manager.wait_for_task(task.id)

    asyncio.run(run_media())

    db.expire_all()
    asset = db.exec(
        select(DouyinMediaAsset).where(
            DouyinMediaAsset.task_id == task.id,
            DouyinMediaAsset.aweme_id == aweme_id,
        )
    ).one()
    assert attempts["count"] == 3
    assert asset.status == MediaDownloadStatus.failed.value
    assert "429" in (asset.error or "")
    assert "MediaSourceExpiredError" not in (asset.error or "")


def test_download_sends_default_referer_header(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证没有采集期请求头时媒体下载仍带 Referer/UA（抖音 CDN 缺 Referer 会 403）。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(
                keywords=[f"防盗链-{uuid.uuid4().hex[:8]}"],
                subtitle_only=True,
            ),
        )
    )
    aweme_id = f"referer-{uuid.uuid4().hex}"
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id=aweme_id,
            video_download_url="https://example.invalid/media.mp4",
        )
    )
    db.commit()

    captured: list[dict[str, str]] = []
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "video/mp4", "content-length": "5"},
            content=b"12345",
        )
    )

    def factory(**kwargs: object) -> httpx.AsyncClient:
        """记录下载客户端收到的请求头。"""
        captured.append(dict(kwargs.get("headers") or {}))
        return httpx.AsyncClient(transport=transport, **kwargs)

    manager = MediaPipelineManager()
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(manager, "_download_client_factory", factory)

    async def run_media() -> None:
        """走仅字幕流程（临时下载）：调用方没有传任何请求头。"""
        await manager.enqueue_aweme(
            task_id=task.id,
            aweme_id=aweme_id,
            storage_backend=None,
            translate_subtitles=False,
            language="zh",
            temporary_only=True,
        )
        await manager.wait_for_task(task.id)

    asyncio.run(run_media())

    assert captured, "下载客户端未被调用"
    assert captured[0].get("referer") == "https://www.douyin.com/"
    assert "chrome" in captured[0].get("user-agent", "").lower()


def test_force_download_bypasses_expired_source_skip(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证用户显式「重新下载」时不会被「地址已失效」的自动跳过规则拦住。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(
                keywords=[f"强制重下-{uuid.uuid4().hex[:8]}"],
                subtitle_only=True,
            ),
        )
    )
    aweme_id = f"force-retry-{uuid.uuid4().hex}"
    stale_url = "https://example.invalid/stale.mp4"
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id=aweme_id,
            video_download_url=stale_url,
        )
    )
    db.commit()
    asset = DouyinMediaAsset(
        task_id=task.id,
        aweme_id=aweme_id,
        source_url=stale_url,
        storage_backend=MediaStorageBackend.local.value,
        status=MediaDownloadStatus.failed.value,
        progress=0,
        attempt_count=2,
        error="MediaSourceExpiredError: 媒体地址返回 HTTP 403",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    manager = MediaPipelineManager()
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)

    async def enqueue() -> DouyinMediaAsset | None:
        """显式要求重新下载（force_download=True）并禁止真实网络请求。"""
        return await manager.enqueue_aweme(
            task_id=task.id,
            aweme_id=aweme_id,
            storage_backend=None,
            translate_subtitles=False,
            language="zh",
            temporary_only=True,
            force_download=True,
            allow_download=False,
        )

    refreshed = asyncio.run(enqueue())

    assert refreshed is not None
    assert refreshed.status == MediaDownloadStatus.queued.value
    asyncio.run(manager.wait_for_task(task.id))


def test_expired_source_is_skipped_until_recrawled(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证已判定「采集地址失效」的作品在重新采集前不再重复入队（不刷 attempt_count）。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(
                keywords=[f"过期跳过-{uuid.uuid4().hex[:8]}"],
                subtitle_only=True,
            ),
        )
    )
    aweme_id = f"expired-skip-{uuid.uuid4().hex}"
    stale_url = "https://example.invalid/expired.mp4"
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id=aweme_id,
            video_download_url=stale_url,
        )
    )
    db.commit()
    asset = DouyinMediaAsset(
        task_id=task.id,
        aweme_id=aweme_id,
        source_url=stale_url,
        storage_backend=MediaStorageBackend.local.value,
        status=MediaDownloadStatus.failed.value,
        progress=0,
        attempt_count=3,
        error=(
            "MediaSourceExpiredError: 采集地址已失效（HTTP 403），"
            "请重新采集该作品后再处理"
        ),
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    manager = MediaPipelineManager()
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)

    async def enqueue(*, allow_download: bool) -> DouyinMediaAsset | None:
        """走仅字幕流程入队一次。"""
        return await manager.enqueue_aweme(
            task_id=task.id,
            aweme_id=aweme_id,
            storage_backend=None,
            translate_subtitles=True,
            language="zh",
            temporary_only=True,
            allow_download=allow_download,
        )

    assert asyncio.run(enqueue(allow_download=True)) is None

    db.expire_all()
    skipped = db.get(DouyinMediaAsset, asset.id)
    assert skipped is not None
    assert skipped.status == MediaDownloadStatus.failed.value
    assert skipped.attempt_count == 3
    assert skipped.error == asset.error

    # 重新采集刷新作品地址后应恢复处理
    aweme = db.exec(
        select(DouyinAweme).where(
            DouyinAweme.task_id == task.id,
            DouyinAweme.aweme_id == aweme_id,
        )
    ).one()
    aweme.video_download_url = "https://example.invalid/refreshed.mp4"
    db.add(aweme)
    db.commit()

    refreshed = asyncio.run(enqueue(allow_download=False))

    assert refreshed is not None
    assert refreshed.status == MediaDownloadStatus.queued.value
    asyncio.run(manager.wait_for_task(task.id))


def test_expired_source_url_fails_fast_without_retrying(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证源站返回 403（直链过期）时只尝试一次，并落库「重新采集」的可执行提示。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(
                keywords=[f"过期直链-{uuid.uuid4().hex[:8]}"],
                subtitle_only=True,
            ),
        )
    )
    aweme_id = f"expired-{uuid.uuid4().hex}"
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id=aweme_id,
            video_download_url="https://example.invalid/expired.mp4",
        )
    )
    db.commit()

    attempts = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        """模拟抖音 CDN 对过期签名直链返回 403。"""
        attempts["count"] += 1
        return httpx.Response(403, content=b"forbidden")

    transport = httpx.MockTransport(handler)
    manager = MediaPipelineManager()
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        manager,
        "_download_client_factory",
        lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs),
    )

    async def run_media() -> None:
        """走仅字幕流程（临时下载）：下载失败后不应重试。"""
        await manager.enqueue_aweme(
            task_id=task.id,
            aweme_id=aweme_id,
            storage_backend=None,
            translate_subtitles=False,
            language="zh",
            temporary_only=True,
        )
        await manager.wait_for_task(task.id)

    asyncio.run(run_media())

    db.expire_all()
    asset = db.exec(
        select(DouyinMediaAsset).where(
            DouyinMediaAsset.task_id == task.id,
            DouyinMediaAsset.aweme_id == aweme_id,
        )
    ).one()
    assert attempts["count"] == 1
    assert asset.status == MediaDownloadStatus.failed.value
    assert "HTTP 403" in (asset.error or "")
    assert "重新采集" in (asset.error or "")


def test_transcription_url_accepts_loopback_and_openai_v1_shape() -> None:
    """验证转写地址校验放行回环地址与 OpenAI 兼容的 /v1 形式，并补全转写端点路径。"""
    assert (
        MediaPipelineManager._transcription_url("http://127.0.0.1:9000")
        == "http://127.0.0.1:9000/v1/audio/transcriptions"
    )
    assert (
        MediaPipelineManager._transcription_url("https://speech.example.com/v1")
        == "https://speech.example.com/v1/audio/transcriptions"
    )


def test_transcription_url_accepts_docker_host_gateway() -> None:
    """验证转写地址校验放行 Docker 宿主机网关地址（容器内访问宿主机服务的常见形式）。"""
    assert (
        MediaPipelineManager._transcription_url("http://host.docker.internal:9000")
        == "http://host.docker.internal:9000/v1/audio/transcriptions"
    )


def test_transcription_url_rejects_insecure_remote_host() -> None:
    """验证远程非回环地址必须使用 HTTPS，否则拒绝并提示。"""
    with pytest.raises(ValueError, match="HTTPS"):
        MediaPipelineManager._transcription_url("http://speech.example.com")


def test_parse_transcription_keeps_text_and_timestamps() -> None:
    """验证转写结果解析保留全文与分段时间戳，实际后端标记为 api。"""
    result = MediaPipelineManager._parse_transcription(
        {
            "language": "zh",
            "duration": 3.5,
            "text": "你好世界",
            "segments": [
                {"start": 0, "end": 1.2, "text": "你好"},
                {"start": 1.2, "end": 3.5, "text": "世界"},
            ],
        }
    )

    assert result["language"] == "zh"
    assert result["full_text"] == "你好世界"
    assert "你好" in str(result["segments_json"])
    assert result["actual_backend"] == "api"


def test_api_failure_marks_subtitle_job_failed_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证远程转写 API 失败时字幕任务被标记为失败且记录错误，不做本地回退、不误标完成。"""
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    media_path = tmp_path / "source.mp3"
    media_path.write_bytes(b"fake-audio")
    failed: dict[str, Any] = {}
    manager = MediaPipelineManager()
    subtitle_id = uuid.uuid4()
    monkeypatch.setattr(
        manager,
        "_begin_subtitle_sync",
        lambda _asset, _language: subtitle_id,
    )

    async def fail_api(_path: Path, *, mime_type: str, language: str) -> dict[str, Any]:
        """模拟远程转写 API 连接失败，断言传入的 MIME 与语言正确。"""
        assert mime_type == "audio/mpeg"
        assert language == "zh"
        raise httpx.ConnectError("remote unavailable")

    monkeypatch.setattr(manager, "_transcribe_api", fail_api)
    monkeypatch.setattr(
        manager,
        "_complete_subtitle_sync",
        lambda _actual_id, _values: pytest.fail("远程失败后不应完成字幕任务"),
    )
    monkeypatch.setattr(
        manager,
        "_fail_subtitle_sync",
        lambda actual_id, error: failed.update(id=actual_id, error=error),
    )
    asset = DouyinMediaAsset(
        task_id=uuid.uuid4(),
        aweme_id="123",
        local_path=str(media_path),
        mime_type="audio/mpeg",
    )

    asyncio.run(manager._transcribe(asset, language="zh"))

    assert failed["id"] == subtitle_id
    assert "ConnectError" in str(failed["error"])
    assert "remote unavailable" in str(failed["error"])


def test_video_is_compacted_to_audio_before_remote_transcription(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证视频文件先用 FFmpeg 压制为单声道 16kHz 小体积音频再上传转写，临时文件随上下文退出清理。"""
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    created: dict[str, object] = {}

    class FakeProcess:
        """模拟 FFmpeg 子进程：立即成功返回。"""

        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            """返回空的 stdout/stderr。"""
            return b"", b""

        def kill(self) -> None:
            """记录被强制结束（本用例不应触发）。"""
            created["killed"] = True

    async def create_process(*args: object, **kwargs: object) -> FakeProcess:
        """模拟创建子进程：记录命令行参数并写出压缩后的音频产物。"""
        output = Path(str(args[-1]))
        output.write_bytes(b"compact-audio")
        created["args"] = args
        created["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    manager = MediaPipelineManager()

    async def prepare() -> tuple[str, bytes, bool]:
        """在上下文内读取上传文件类型、内容与存在性。"""
        async with manager._transcription_upload_file(
            source, mime_type="video/mp4"
        ) as (upload_path, upload_type):
            return upload_type, upload_path.read_bytes(), upload_path.is_file()

    upload_type, content, existed_during_context = asyncio.run(prepare())

    assert upload_type == "audio/mpeg"
    assert content == b"compact-audio"
    assert existed_during_context is True
    process_args = created["args"]
    assert isinstance(process_args, tuple)
    assert process_args[:-1] == (
        settings.FFMPEG_BINARY,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        f"{settings.WHISPER_AUDIO_BITRATE_KBPS}k",
    )
    assert Path(str(process_args[-1])).name == "audio.mp3"
    assert created["kwargs"] == {
        "stdout": asyncio.subprocess.DEVNULL,
        "stderr": asyncio.subprocess.DEVNULL,
    }
    assert "killed" not in created


def test_missing_ffmpeg_falls_back_to_original_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证系统缺少 FFmpeg 时直接上传原始媒体（由远端解码），而不是让字幕任务失败。"""
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    async def missing_binary(*_args: object, **_kwargs: object) -> object:
        """模拟 FFmpeg 可执行文件不存在（Windows 开发机常见）。"""
        raise FileNotFoundError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", missing_binary)
    manager = MediaPipelineManager()

    async def prepare() -> tuple[Path, str]:
        """读取退回上传的原始媒体路径与声明类型。"""
        async with manager._transcription_upload_file(
            source, mime_type="video/mp4"
        ) as (upload_path, upload_type):
            return upload_path, upload_type

    upload_path, upload_type = asyncio.run(prepare())

    assert upload_path == source
    assert upload_type == "video/mp4"


def test_ffmpeg_timeout_kills_process_and_keeps_error_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证 FFmpeg 提取音频超时会 kill 子进程并抛出约定文案的超时错误。"""
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    state = {"calls": 0, "killed": False}

    class SlowProcess:
        """模拟迟迟不结束的 FFmpeg 子进程：被 kill 后才返回。"""

        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            """未被 kill 时长时间挂起，被 kill 后立即返回。"""
            state["calls"] += 1
            if not state["killed"]:
                await asyncio.sleep(60)
            return b"", b""

        def kill(self) -> None:
            """记录被强制结束。"""
            state["killed"] = True

    async def create_process(*_args: object, **_kwargs: object) -> SlowProcess:
        """返回慢速模拟子进程。"""
        return SlowProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr(settings, "WHISPER_AUDIO_PREPROCESS_TIMEOUT", 0.001)
    manager = MediaPipelineManager()

    async def prepare() -> None:
        """进入上传文件准备上下文（预期因超时而失败）。"""
        async with manager._transcription_upload_file(source, mime_type="video/mp4"):
            pytest.fail("FFmpeg 超时时不应产生上传文件")

    with pytest.raises(TimeoutError, match="^为远程字幕 API 提取音频超时$"):
        asyncio.run(prepare())
    assert state == {"calls": 2, "killed": True}


@pytest.mark.parametrize(
    ("returncode", "output", "message"),
    [
        (1, b"partial", "无法从视频提取可转写音频"),
        (0, None, "无法从视频提取可转写音频"),
        (0, b"", "从视频提取的音频为空"),
    ],
)
def test_ffmpeg_output_validation_keeps_application_error_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    output: bytes | None,
    message: str,
) -> None:
    """验证 FFmpeg 产物校验（非零退出码/无产物/空产物）抛出约定文案错误，且不误杀进程。

    参数：
        returncode: 模拟子进程退出码。
        output: 模拟写出的音频内容，None 表示未产出文件。
        message: 期望的中文错误文案。
    """
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    class FakeProcess:
        """模拟 FFmpeg 子进程：按参数化退出码立即结束。"""

        def __init__(self) -> None:
            """按参数化用例设置退出码。"""
            self.returncode = returncode

        async def communicate(self) -> tuple[bytes, bytes]:
            """返回空的 stdout/stderr。"""
            return b"", b""

        def kill(self) -> None:
            """非超时场景不应 kill 进程。"""
            pytest.fail("非超时失败不应 kill FFmpeg")

    async def create_process(*args: object, **_kwargs: object) -> FakeProcess:
        """模拟创建子进程：按用例写出（或不写）音频产物。"""
        if output is not None:
            Path(str(args[-1])).write_bytes(output)
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    manager = MediaPipelineManager()

    async def prepare() -> None:
        """进入上传文件准备上下文（预期因产物校验失败而不会成功进入）。"""
        async with manager._transcription_upload_file(source, mime_type="video/mp4"):
            pytest.fail("无效 FFmpeg 产物不应进入上传阶段")

    with pytest.raises(RuntimeError, match=f"^{message}$"):
        asyncio.run(prepare())


def test_media_list_prioritizes_active_work(
    db: Session,
) -> None:
    """验证媒体资产列表按活跃程度排序：下载中 > 转写中 > 失败 > 已完成。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(keywords=["活跃媒体优先"]),
        )
    )
    completed = DouyinMediaAsset(
        task_id=task.id,
        aweme_id="completed",
        status=MediaDownloadStatus.downloaded.value,
    )
    failed = DouyinMediaAsset(
        task_id=task.id,
        aweme_id="failed",
        status=MediaDownloadStatus.failed.value,
    )
    translating = DouyinMediaAsset(
        task_id=task.id,
        aweme_id="translating",
        status=MediaDownloadStatus.downloaded.value,
    )
    downloading = DouyinMediaAsset(
        task_id=task.id,
        aweme_id="downloading",
        status=MediaDownloadStatus.downloading.value,
    )
    db.add_all([completed, failed, translating, downloading])
    db.commit()
    db.refresh(translating)
    db.add(
        DouyinSubtitle(
            asset_id=translating.id,
            task_id=task.id,
            aweme_id=translating.aweme_id,
            status=SubtitleStatus.running.value,
        )
    )
    db.commit()

    result = list_media_sync(task.id, 0, 100)

    assert [asset.aweme_id for asset in result.data] == [
        "downloading",
        "translating",
        "failed",
        "completed",
    ]


def test_streaming_download_is_atomically_committed(tmp_path: Path) -> None:
    """验证流式下载先写入 .part 临时文件再原子改名为最终文件，成功后无临时文件残留。"""
    content = b"video-content"
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=content,
            headers={"content-type": "video/mp4", "content-length": str(len(content))},
        )
    )

    def client_factory(**kwargs: object) -> httpx.AsyncClient:
        """构造使用 MockTransport 的异步 HTTP 客户端。"""
        return httpx.AsyncClient(transport=transport, **kwargs)

    manager = MediaPipelineManager(download_client_factory=client_factory)
    partial_path = tmp_path / "source.mp4.part"
    final_path = tmp_path / "source.mp4"
    result = asyncio.run(
        manager._download_once(
            uuid.uuid4(),
            "https://video.example/source.mp4",
            partial_path,
            final_path,
            {},
        )
    )

    assert final_path.read_bytes() == content
    assert not partial_path.exists()
    assert result["file_size"] == len(content)


def test_streaming_download_has_an_end_to_end_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证流式下载有端到端总时限：慢速响应体整体超时报 TimeoutError。"""

    class SlowStream(httpx.AsyncByteStream):
        """模拟缓慢的字节响应流：首块数据前长时间挂起。"""

        async def __aiter__(self):  # type: ignore[no-untyped-def]
            await asyncio.sleep(1)
            yield b"never reached"

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            stream=SlowStream(),
            headers={"content-type": "video/mp4"},
        )
    )

    def client_factory(**kwargs: object) -> httpx.AsyncClient:
        """构造返回慢速流响应的异步 HTTP 客户端。"""
        return httpx.AsyncClient(transport=transport, **kwargs)

    monkeypatch.setattr(settings, "MEDIA_DOWNLOAD_TIMEOUT", 0.01)
    manager = MediaPipelineManager(download_client_factory=client_factory)

    with pytest.raises(TimeoutError, match="单次尝试超过 0.01 秒"):
        asyncio.run(
            manager._download_once(
                uuid.uuid4(),
                "https://video.example/slow.mp4",
                tmp_path / "slow.part",
                tmp_path / "slow.mp4",
                {},
            )
        )


def test_streaming_download_deadline_does_not_require_asyncio_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证下载总时限的实现不依赖 asyncio.timeout（兼容 Python 3.10），删除该属性后仍可正常下载。"""
    content = b"python-310-compatible-video"
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=content,
            headers={"content-type": "video/mp4"},
        )
    )

    def client_factory(**kwargs: object) -> httpx.AsyncClient:
        """构造使用 MockTransport 的异步 HTTP 客户端。"""
        return httpx.AsyncClient(transport=transport, **kwargs)

    monkeypatch.delattr(asyncio, "timeout", raising=False)
    manager = MediaPipelineManager(download_client_factory=client_factory)
    final_path = tmp_path / "compatible.mp4"

    result = asyncio.run(
        manager._download_once(
            uuid.uuid4(),
            "https://video.example/compatible.mp4",
            tmp_path / "compatible.part",
            final_path,
            {},
        )
    )

    assert result["file_size"] == len(content)
    assert final_path.read_bytes() == content


def test_original_sound_url_only_accepts_same_moment_music() -> None:
    """验证「原声」判定：music 与作品雪花 ID 同前缀才算作品自己的音轨。"""
    aweme_id = "7650141304860495154"
    # 原声：music 实体与作品同一时刻生成，高位一致
    assert (
        original_sound_url(
            aweme_id,
            "https://sf6-cdn-tos.douyinstatic.com/obj/ies-music/7650141441481640714.mp3",
        )
        == "https://sf6-cdn-tos.douyinstatic.com/obj/ies-music/7650141441481640714.mp3"
    )
    # 用别人的音乐：ID 相差很远，不能拿来转写（否则字幕会变成 BGM 歌词）
    assert (
        original_sound_url(
            "7597994908952575462",
            "https://lf26-music-east.douyinstatic.com/obj/ies-music-hj/7597460847127972666.mp3",
        )
        is None
    )
    # 非数字 ID / 空地址一律不认
    assert original_sound_url(aweme_id, "") is None
    assert original_sound_url(aweme_id, "https://example.invalid/music/abc.mp3") is None
    assert original_sound_url("not-a-number", "https://example.invalid/1.mp3") is None


def test_subtitle_only_download_limits_follow_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证仅字幕任务的大小上限与单次超时：未单独配置时沿用通用值，配置后用自己的。"""
    monkeypatch.setattr(settings, "MEDIA_MAX_SIZE_MB", 500)
    monkeypatch.setattr(settings, "MEDIA_DOWNLOAD_TIMEOUT", 180.0)
    monkeypatch.setattr(settings, "MEDIA_SUBTITLE_MAX_SIZE_MB", 0)
    monkeypatch.setattr(settings, "MEDIA_SUBTITLE_DOWNLOAD_TIMEOUT", 0.0)
    assert MediaPipelineManager._temporary_max_bytes() == 500 * 1024 * 1024
    assert MediaPipelineManager._temporary_download_timeout() == 180.0

    monkeypatch.setattr(settings, "MEDIA_SUBTITLE_MAX_SIZE_MB", 2048)
    monkeypatch.setattr(settings, "MEDIA_SUBTITLE_DOWNLOAD_TIMEOUT", 900.0)
    assert MediaPipelineManager._temporary_max_bytes() == 2048 * 1024 * 1024
    assert MediaPipelineManager._temporary_download_timeout() == 900.0


def test_subtitle_only_prefers_original_sound_audio(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证仅字幕任务优先下原声音频：不碰大视频，转写直接吃 mp3。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(
                keywords=[f"仅字幕原声-{uuid.uuid4().hex[:8]}"],
                subtitle_only=True,
            ),
        )
    )
    aweme_id = "7650141304860495154"
    audio_url = (
        "https://sf6-cdn-tos.douyinstatic.com/obj/ies-music/7650141441481640714.mp3"
    )
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id=aweme_id,
            video_download_url="https://www.douyin.com/aweme/v1/play/?video_id=huge",
            music_download_url=audio_url,
        )
    )
    db.commit()

    manager = MediaPipelineManager()
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    requested: list[tuple[str, Path, str]] = []

    async def fake_download(
        _asset_id: uuid.UUID,
        source_url: str,
        _partial_path: Path,
        final_path: Path,
        _headers: dict[str, str],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        requested.append((source_url, final_path, final_path.suffix))
        final_path.write_bytes(b"audio-bytes")
        return {"file_size": 11, "sha256": "audio-sha", "mime_type": "audio/mpeg"}

    observed: list[tuple[Path, str]] = []

    async def fake_transcribe(
        _asset: DouyinMediaAsset,
        *,
        language: str = "auto",
        media_path: Path | None = None,
        mime_type: str | None = None,
    ) -> None:
        assert language == "zh"
        assert media_path is not None
        observed.append((media_path, mime_type or ""))

    monkeypatch.setattr(manager, "_download_once", fake_download)
    monkeypatch.setattr(manager, "_transcribe", fake_transcribe)

    async def run_media() -> None:
        await manager.enqueue_aweme(
            task_id=task.id,
            aweme_id=aweme_id,
            storage_backend=None,
            translate_subtitles=True,
            language="zh",
            temporary_only=True,
        )
        await manager.wait_for_task(task.id)

    asyncio.run(run_media())

    # 只下了音频，没有碰视频地址；转写拿到的就是那个 mp3
    assert [(url, suffix) for url, _path, suffix in requested] == [(audio_url, ".mp3")]
    assert observed and observed[0][1] == "audio/mpeg"
    assert not observed[0][0].exists()  # 临时文件用完即删


def test_subtitle_only_falls_back_to_video_when_audio_unusable(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证没有原声音频、或音频下载失败时，仍然回退下载整段视频。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(
                keywords=[f"仅字幕回退-{uuid.uuid4().hex[:8]}"],
                subtitle_only=True,
            ),
        )
    )
    # 用别人的音乐：判不出原声，只能下视频
    foreign_aweme_id = "7597994908952575462"
    no_audio_aweme_id = "7616034349699304723"
    for aweme_id, music_url in (
        (
            foreign_aweme_id,
            "https://lf26-music-east.douyinstatic.com/obj/ies-music-hj/7597460847127972666.mp3",
        ),
        (no_audio_aweme_id, ""),
    ):
        db.add(
            DouyinAweme(
                task_id=task.id,
                aweme_id=aweme_id,
                video_download_url=f"https://www.douyin.com/aweme/v1/play/?video_id={aweme_id}",
                music_download_url=music_url,
            )
        )
    db.commit()

    manager = MediaPipelineManager()
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    requested: list[str] = []

    async def fake_download(
        _asset_id: uuid.UUID,
        source_url: str,
        _partial_path: Path,
        final_path: Path,
        _headers: dict[str, str],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        requested.append(source_url)
        final_path.write_bytes(b"video-bytes")
        return {"file_size": 11, "sha256": "video-sha", "mime_type": "video/mp4"}

    monkeypatch.setattr(manager, "_download_once", fake_download)

    async def fake_transcribe(_asset: DouyinMediaAsset, **_kwargs: Any) -> None:
        """回退下载视频后照常转写，这里只需要它不抛异常。"""
        return None

    monkeypatch.setattr(manager, "_transcribe", fake_transcribe)

    async def run_media() -> None:
        for aweme_id in (foreign_aweme_id, no_audio_aweme_id):
            await manager.enqueue_aweme(
                task_id=task.id,
                aweme_id=aweme_id,
                storage_backend=None,
                translate_subtitles=True,
                language="zh",
                temporary_only=True,
            )
        await manager.wait_for_task(task.id)

    asyncio.run(run_media())

    # 两个作品是并发处理的，只断言「各自都走了视频地址」
    assert sorted(requested) == sorted(
        [
            f"https://www.douyin.com/aweme/v1/play/?video_id={foreign_aweme_id}",
            f"https://www.douyin.com/aweme/v1/play/?video_id={no_audio_aweme_id}",
        ]
    )


def test_download_resumes_from_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证断点续传：上一轮留下的 .part 用 Range 续拉，摘要按完整文件重算。"""
    content = b"0123456789abcdefghij" * 1024
    first_half = content[: len(content) // 2]
    seen_ranges: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_ranges.append(request.headers.get("range"))
        offset = int(request.headers.get("range", "bytes=0-").split("=")[1].rstrip("-"))
        return httpx.Response(
            206,
            content=content[offset:],
            headers={
                "content-type": "video/mp4",
                "content-length": str(len(content) - offset),
            },
        )

    def client_factory(**kwargs: object) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    manager = MediaPipelineManager(download_client_factory=client_factory)
    partial_path = tmp_path / "resume.mp4.part"
    partial_path.write_bytes(first_half)
    final_path = tmp_path / "resume.mp4"

    result = asyncio.run(
        manager._download_once(
            uuid.uuid4(),
            "https://video.example/resume.mp4",
            partial_path,
            final_path,
            {},
            resume=True,
        )
    )

    assert seen_ranges == [f"bytes={len(first_half)}-"]
    assert final_path.read_bytes() == content
    assert result["file_size"] == len(content)
    assert result["sha256"] == hashlib.sha256(content).hexdigest()


def test_download_rejects_truncated_body(tmp_path: Path) -> None:
    """验证「没报错但少了一截」的响应会被当成失败，避免把半截文件当成品入库。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"only-a-few-bytes",
            headers={"content-type": "video/mp4", "content-length": "1048576"},
        )

    def client_factory(**kwargs: object) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    manager = MediaPipelineManager(download_client_factory=client_factory)
    with pytest.raises(ValueError, match="媒体下载不完整"):
        asyncio.run(
            manager._download_once(
                uuid.uuid4(),
                "https://video.example/truncated.mp4",
                tmp_path / "truncated.part",
                tmp_path / "truncated.mp4",
                {},
            )
        )
