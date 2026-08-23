"""抖音媒体文件向 MinIO 迁移的测试：覆盖迁移入队筛选、校验通过后切换存储后端并清理本地文件、失败保留本地、断点续迁与重复入队去重等行为。"""

import asyncio
import hashlib
import uuid
from pathlib import Path

import pytest
from crawler.api.routes import douyin as douyin_route
from crawler.bootstrap.settings import settings
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.media.migration import (
    MediaMigrationManager,
    MigrationEnqueueResult,
)
from crawler.business.douyin.media.models import (
    DouyinMediaAsset,
    MediaDownloadStatus,
    MediaMigrationStatus,
    MediaStorageBackend,
)
from crawler.business.douyin.media.pipeline import media_summary_sync
from crawler.business.douyin.media.storage import MediaIntegrityError, StoredMedia
from crawler.business.douyin.tasks.models import CrawlTask, CrawlTaskStatus
from crawler.business.douyin.tracks.models import DouyinTrack
from crawler.business.identity.models import User
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from tests.utils.douyin import default_track_id


class RecordingMigrationStorage:
    """记录型媒体存储替身：校验入参完整性、统计复制/删除调用次数，可按需注入失败以模拟迁移异常。"""

    def __init__(self, *, failure: Exception | None = None) -> None:
        """初始化记录器。

        参数：
            failure: 非空时在执行复制时抛出，用于模拟 MinIO 校验/上传失败。
        """
        self.failure = failure
        self.copy_calls = 0
        self.remove_calls = 0

    async def ensure_verified_minio_copy(
        self,
        asset: DouyinMediaAsset,
        source_path: Path,
        *,
        file_size: int,
        sha256: str,
        mime_type: str,
    ) -> StoredMedia:
        """模拟带校验的 MinIO 复制：断言源文件与元数据一致后返回已存储对象信息。"""
        self.copy_calls += 1
        assert source_path.is_file()
        assert file_size == source_path.stat().st_size
        assert sha256 == hashlib.sha256(source_path.read_bytes()).hexdigest()
        assert mime_type == "video/mp4"
        if self.failure:
            raise self.failure
        return StoredMedia(
            backend=MediaStorageBackend.minio,
            local_path="",
            bucket="douyin-media",
            object_key=f"douyin/{asset.task_id}/{asset.aweme_id}/source.mp4",
            file_size=file_size,
            sha256=sha256,
        )

    async def remove_minio_copy(self, _stored: StoredMedia) -> None:
        """模拟删除 MinIO 副本，仅记录调用次数。"""
        self.remove_calls += 1


def create_local_asset(
    db: Session, tmp_path: Path, content: bytes
) -> tuple[CrawlTask, DouyinMediaAsset, Path]:
    """构造一条已完成采集任务及其本地媒体资产，并在临时目录写入真实源文件。

    参数：
        db: 数据库会话。
        tmp_path: pytest 临时目录，用于承载模拟的本地媒体文件。
        content: 源文件内容（用于校验大小与 sha256）。

    返回：
        (采集任务, 媒体资产, 源文件路径) 三元组。
    """
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="detail",
        status=CrawlTaskStatus.succeeded.value,
        request_json="{}",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    source = tmp_path / "douyin" / str(task.id) / "asset" / "source.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(content)
    asset = DouyinMediaAsset(
        task_id=task.id,
        aweme_id=f"migration-{uuid.uuid4().hex}",
        local_path=str(source),
        storage_backend=MediaStorageBackend.local.value,
        status=MediaDownloadStatus.downloaded.value,
        progress=100,
        mime_type="video/mp4",
        file_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return task, asset, source


def test_disabled_track_rejects_media_migration_enqueue(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """赛道冻结后，手动迁移/重试入口不得再创建媒体迁移 worker。"""
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    task, asset, _source = create_local_asset(db, tmp_path, b"blocked-migration")
    track = DouyinTrack(
        owner_id=task.owner_id,
        name=f"迁移准入-{uuid.uuid4().hex[:8]}",
        normalized_name=f"migration-admission-{uuid.uuid4().hex}",
    )
    db.add(track)
    db.flush()
    task.track_id = track.id
    db.add(task)
    track.enabled = False
    db.add(track)
    db.commit()
    manager = MediaMigrationManager(storage=RecordingMigrationStorage())  # type: ignore[arg-type]

    async def run() -> None:
        with pytest.raises(ValueError, match="赛道已停用"):
            await manager.enqueue_task(task.id, [asset.id])
        assert manager._handles == {}

    asyncio.run(run())
    db.expire_all()
    persisted = db.get(DouyinMediaAsset, asset.id)
    assert persisted is not None
    assert persisted.migration_status == MediaMigrationStatus.idle.value
    track.enabled = True
    db.add(track)
    db.commit()


def test_cancel_task_only_stops_matching_migrations_and_waits_for_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证按采集任务取消迁移时会等待目标协程退出，且不影响其他任务。"""

    async def run() -> None:
        manager = MediaMigrationManager()
        target_task_id = uuid.uuid4()
        other_task_id = uuid.uuid4()
        target_assets = [uuid.uuid4(), uuid.uuid4()]
        other_asset = uuid.uuid4()
        asset_ids = [*target_assets, other_asset]
        started = {asset_id: asyncio.Event() for asset_id in asset_ids}
        release = {asset_id: asyncio.Event() for asset_id in asset_ids}
        exited = {asset_id: asyncio.Event() for asset_id in asset_ids}

        async def suspended_migration(asset_id: uuid.UUID) -> None:
            started[asset_id].set()
            try:
                await release[asset_id].wait()
            finally:
                # 保留一次异步清理点，确保 cancel_task 确实等待 finally 收尾。
                await asyncio.sleep(0)
                exited[asset_id].set()

        monkeypatch.setattr(manager, "_run_asset", suspended_migration)
        for asset_id in target_assets:
            manager._create_handle(target_task_id, asset_id)
        manager._create_handle(other_task_id, other_asset)
        await asyncio.gather(*(event.wait() for event in started.values()))

        await manager.cancel_task(uuid.uuid4())
        other_handle = manager._handles[other_asset].task
        assert not other_handle.done()

        await manager.cancel_task(target_task_id)

        assert all(exited[asset_id].is_set() for asset_id in target_assets)
        assert all(manager._handles[asset_id].task.done() for asset_id in target_assets)
        assert not exited[other_asset].is_set()
        assert not other_handle.done()

        release[other_asset].set()
        await other_handle
        assert exited[other_asset].is_set()

    asyncio.run(run())


def test_library_migration_queues_all_matching_local_assets(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证素材库批量迁移接口仅将搜索命中的本地资产入队，未命中任务的资产不受影响。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    selected_task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="detail",
        status=CrawlTaskStatus.succeeded.value,
        request_json="{}",
    )
    excluded_task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="detail",
        status=CrawlTaskStatus.succeeded.value,
        request_json="{}",
    )
    db.add(selected_task)
    db.add(excluded_task)
    db.flush()
    selected_aweme = DouyinAweme(
        task_id=selected_task.id,
        aweme_id=f"selected-{uuid.uuid4().hex}",
        title="需要迁移的视频",
    )
    excluded_aweme = DouyinAweme(
        task_id=excluded_task.id,
        aweme_id=f"excluded-{uuid.uuid4().hex}",
        title="保留在本地的视频",
    )
    db.add(selected_aweme)
    db.add(excluded_aweme)
    db.flush()
    selected_asset = DouyinMediaAsset(
        task_id=selected_task.id,
        aweme_id=selected_aweme.aweme_id,
        local_path="test-selected.mp4",
        storage_backend=MediaStorageBackend.local.value,
        status=MediaDownloadStatus.downloaded.value,
        progress=100,
    )
    excluded_asset = DouyinMediaAsset(
        task_id=excluded_task.id,
        aweme_id=excluded_aweme.aweme_id,
        local_path="test-excluded.mp4",
        storage_backend=MediaStorageBackend.local.value,
        status=MediaDownloadStatus.downloaded.value,
        progress=100,
    )
    db.add(selected_asset)
    db.add(excluded_asset)
    db.commit()

    queued: dict[uuid.UUID, list[uuid.UUID]] = {}

    async def fake_ready() -> None:
        """模拟 MinIO 就绪检查，直接通过。"""
        return None

    async def fake_enqueue(
        task_id: uuid.UUID, asset_ids: list[uuid.UUID]
    ) -> MigrationEnqueueResult:
        """模拟迁移入队，记录每个任务被入队的资产 id 列表。"""
        queued[task_id] = asset_ids
        return MigrationEnqueueResult(queued=len(asset_ids), skipped=0)

    monkeypatch.setattr(douyin_route.media_storage, "ensure_minio_ready", fake_ready)
    monkeypatch.setattr(
        douyin_route.media_migration_manager, "enqueue_task", fake_enqueue
    )
    response = client.post(
        f"{settings.API_V1_STR}/douyin/library/media/migrate-to-minio",
        headers=superuser_token_headers,
        json={"search": "需要迁移"},
    )
    assert response.status_code == 202
    assert response.json()["queued"] == 1
    assert queued == {selected_task.id: [selected_asset.id]}


def test_migration_switches_only_after_verified_copy_and_deletes_local(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证资产仅在 MinIO 副本校验通过后才切换存储后端并删除本地文件，统计口径同步更新。"""
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    task, asset, source = create_local_asset(db, tmp_path, b"complete-video")
    storage = RecordingMigrationStorage()
    manager = MediaMigrationManager(storage=storage)  # type: ignore[arg-type]

    async def run() -> MigrationEnqueueResult:
        """提交迁移任务并等待完成，返回入队结果。"""
        result = await manager.enqueue_task(task.id, [asset.id])
        await manager.wait_for_task(task.id)
        return result

    result = asyncio.run(run())
    db.expire_all()
    migrated = db.get(DouyinMediaAsset, asset.id)

    assert result == MigrationEnqueueResult(queued=1, skipped=0)
    assert storage.copy_calls == 1
    assert migrated is not None
    assert migrated.storage_backend == MediaStorageBackend.minio.value
    assert migrated.local_path == ""
    assert migrated.migration_status == MediaMigrationStatus.completed.value
    assert migrated.migration_progress == 100
    assert not source.exists()
    summary = media_summary_sync(task.id)
    assert summary.local_downloaded == 0
    assert summary.minio_downloaded == 1
    assert summary.migration_completed == 1


def test_verification_failure_preserves_local_asset(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证 MinIO 校验失败时资产保持本地存储、标记迁移失败，且错误信息中不包含 URL 与密钥等敏感内容。"""
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    task, asset, source = create_local_asset(db, tmp_path, b"keep-local-video")
    storage = RecordingMigrationStorage(
        failure=MediaIntegrityError(
            "remote failed https://storage.invalid?token=secret-value"
        )
    )
    manager = MediaMigrationManager(storage=storage)  # type: ignore[arg-type]

    async def run() -> None:
        """提交迁移任务并等待其走完失败路径。"""
        await manager.enqueue_task(task.id, [asset.id])
        await manager.wait_for_task(task.id)

    asyncio.run(run())
    db.expire_all()
    failed = db.get(DouyinMediaAsset, asset.id)

    assert failed is not None
    assert failed.storage_backend == MediaStorageBackend.local.value
    assert failed.local_path == str(source)
    assert failed.migration_status == MediaMigrationStatus.failed.value
    assert "storage.invalid" not in str(failed.migration_error)
    assert "secret-value" not in str(failed.migration_error)
    assert source.read_bytes() == b"keep-local-video"


def test_cleanup_pending_retries_without_uploading_again(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证本地文件删除失败进入待清理状态后，重试仅补删本地文件而不重复上传，错误信息不泄露本地路径。"""
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    task, asset, source = create_local_asset(db, tmp_path, b"cleanup-video")
    storage = RecordingMigrationStorage()

    def blocked_removal(path: Path) -> None:
        """模拟文件被占用导致删除失败的移除函数。"""
        raise PermissionError(f"file is busy: {path}")

    manager = MediaMigrationManager(  # type: ignore[arg-type]
        storage=storage,
        file_remover=blocked_removal,
    )

    async def first_run() -> None:
        """首次执行迁移：上传成功但本地删除失败，进入 cleanup_pending。"""
        await manager.enqueue_task(task.id, [asset.id])
        await manager.wait_for_task(task.id)

    asyncio.run(first_run())
    db.expire_all()
    pending = db.get(DouyinMediaAsset, asset.id)
    assert pending is not None
    assert pending.storage_backend == MediaStorageBackend.minio.value
    assert pending.migration_status == MediaMigrationStatus.cleanup_pending.value
    assert str(tmp_path) not in str(pending.migration_error)
    assert source.exists()

    manager._file_remover = lambda path: path.unlink(missing_ok=True)

    async def retry() -> MigrationEnqueueResult:
        """恢复文件删除后重试迁移，返回入队结果。"""
        result = await manager.enqueue_task(task.id, [asset.id])
        await manager.wait_for_task(task.id)
        return result

    result = asyncio.run(retry())
    db.expire_all()
    completed = db.get(DouyinMediaAsset, asset.id)
    assert result.queued == 1
    assert storage.copy_calls == 1
    assert completed is not None
    assert completed.migration_status == MediaMigrationStatus.completed.value
    assert completed.local_path == ""
    assert not source.exists()


def test_startup_resumes_interrupted_local_migration(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证管理器启动时能接管此前中断（verifying 状态）的本地迁移并推进至完成。"""
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    task, asset, source = create_local_asset(db, tmp_path, b"resume-migration")
    asset.migration_status = MediaMigrationStatus.verifying.value
    asset.migration_progress = 80
    db.add(asset)
    db.commit()
    storage = RecordingMigrationStorage()
    manager = MediaMigrationManager(storage=storage)  # type: ignore[arg-type]

    async def run() -> None:
        """模拟服务启动：恢复中断的迁移并等待完成。"""
        await manager.startup()
        await manager.wait_for_task(task.id)

    asyncio.run(run())
    db.expire_all()
    resumed = db.get(DouyinMediaAsset, asset.id)
    assert resumed is not None
    assert resumed.migration_status == MediaMigrationStatus.completed.value
    assert resumed.storage_backend == MediaStorageBackend.minio.value
    assert not source.exists()


def test_duplicate_enqueue_is_skipped(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证同一资产重复入队时第二次被跳过，避免并发重复迁移。"""
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    task, asset, _source = create_local_asset(db, tmp_path, b"one-migration")
    manager = MediaMigrationManager(  # type: ignore[arg-type]
        storage=RecordingMigrationStorage()
    )

    async def run() -> tuple[MigrationEnqueueResult, MigrationEnqueueResult]:
        """连续两次入队同一资产并等待完成，返回两次入队结果。"""
        first = await manager.enqueue_task(task.id, [asset.id])
        second = await manager.enqueue_task(task.id, [asset.id])
        await manager.wait_for_task(task.id)
        return first, second

    first, second = asyncio.run(run())
    assert first == MigrationEnqueueResult(queued=1, skipped=0)
    assert second == MigrationEnqueueResult(queued=0, skipped=1)
