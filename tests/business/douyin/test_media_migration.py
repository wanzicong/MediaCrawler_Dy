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
from crawler.business.identity.models import User
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from tests.utils.douyin import default_track_id


class RecordingMigrationStorage:
    def __init__(self, *, failure: Exception | None = None) -> None:
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
        self.remove_calls += 1


def create_local_asset(
    db: Session, tmp_path: Path, content: bytes
) -> tuple[CrawlTask, DouyinMediaAsset, Path]:
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


def test_library_migration_queues_all_matching_local_assets(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        return None

    async def fake_enqueue(
        task_id: uuid.UUID, asset_ids: list[uuid.UUID]
    ) -> MigrationEnqueueResult:
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
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    task, asset, source = create_local_asset(db, tmp_path, b"complete-video")
    storage = RecordingMigrationStorage()
    manager = MediaMigrationManager(storage=storage)  # type: ignore[arg-type]

    async def run() -> MigrationEnqueueResult:
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
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    task, asset, source = create_local_asset(db, tmp_path, b"keep-local-video")
    storage = RecordingMigrationStorage(
        failure=MediaIntegrityError(
            "remote failed https://storage.invalid?token=secret-value"
        )
    )
    manager = MediaMigrationManager(storage=storage)  # type: ignore[arg-type]

    async def run() -> None:
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
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    task, asset, source = create_local_asset(db, tmp_path, b"cleanup-video")
    storage = RecordingMigrationStorage()

    def blocked_removal(path: Path) -> None:
        raise PermissionError(f"file is busy: {path}")

    manager = MediaMigrationManager(  # type: ignore[arg-type]
        storage=storage,
        file_remover=blocked_removal,
    )

    async def first_run() -> None:
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
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    task, asset, source = create_local_asset(db, tmp_path, b"resume-migration")
    asset.migration_status = MediaMigrationStatus.verifying.value
    asset.migration_progress = 80
    db.add(asset)
    db.commit()
    storage = RecordingMigrationStorage()
    manager = MediaMigrationManager(storage=storage)  # type: ignore[arg-type]

    async def run() -> None:
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
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    task, asset, _source = create_local_asset(db, tmp_path, b"one-migration")
    manager = MediaMigrationManager(  # type: ignore[arg-type]
        storage=RecordingMigrationStorage()
    )

    async def run() -> tuple[MigrationEnqueueResult, MigrationEnqueueResult]:
        first = await manager.enqueue_task(task.id, [asset.id])
        second = await manager.enqueue_task(task.id, [asset.id])
        await manager.wait_for_task(task.id)
        return first, second

    first, second = asyncio.run(run())
    assert first == MigrationEnqueueResult(queued=1, skipped=0)
    assert second == MigrationEnqueueResult(queued=0, skipped=1)
