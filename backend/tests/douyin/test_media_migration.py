import asyncio
import hashlib
import uuid
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    CrawlTask,
    CrawlTaskStatus,
    DouyinMediaAsset,
    MediaDownloadStatus,
    MediaMigrationStatus,
    MediaStorageBackend,
    User,
)
from app.services.media_migration import MediaMigrationManager, MigrationEnqueueResult
from app.services.media_pipeline import media_summary_sync
from app.services.media_storage import MediaIntegrityError, StoredMedia


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
