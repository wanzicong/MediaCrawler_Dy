from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import engine
from app.models import (
    DouyinMediaAsset,
    MediaDownloadStatus,
    MediaMigrationStatus,
    MediaStorageBackend,
    get_datetime_utc,
)
from app.services.media_storage import StoredMedia, media_storage


class MigrationStorage(Protocol):
    async def ensure_verified_minio_copy(
        self,
        asset: DouyinMediaAsset,
        source_path: Path,
        *,
        file_size: int,
        sha256: str,
        mime_type: str,
    ) -> StoredMedia: ...

    async def remove_minio_copy(self, stored: StoredMedia) -> None: ...


@dataclass(frozen=True)
class MigrationEnqueueResult:
    queued: int
    skipped: int


@dataclass(frozen=True)
class LocalFingerprint:
    file_size: int
    sha256: str
    modified_ns: int


@dataclass
class MigrationHandle:
    task_id: uuid.UUID
    task: asyncio.Task[None]


def _safe_migration_error(exc: Exception) -> str:
    message = f"{type(exc).__name__}: {exc}"
    media_root = re.escape(str(settings.MEDIA_OUTPUT_DIR.resolve()))
    message = re.sub(
        rf"{media_root}[^\s'\"]*", "<media-path>", message, flags=re.IGNORECASE
    )
    message = re.sub(r"https?://\S+", "<url>", message)
    message = re.sub(
        r"(?i)(authorization|api[-_ ]?key|secret|password|token)=?\S+",
        r"\1=<redacted>",
        message,
    )
    return message[:1000]


class MediaMigrationManager:
    """Persist and resume safe one-way local-to-MinIO media migrations."""

    _local_recoverable = {
        MediaMigrationStatus.queued.value,
        MediaMigrationStatus.uploading.value,
        MediaMigrationStatus.verifying.value,
        MediaMigrationStatus.switching.value,
    }
    _running = {
        MediaMigrationStatus.uploading.value,
        MediaMigrationStatus.verifying.value,
        MediaMigrationStatus.switching.value,
    }

    def __init__(
        self,
        *,
        storage: MigrationStorage = media_storage,
        file_remover: Callable[[Path], None] | None = None,
    ) -> None:
        self._storage = storage
        self._file_remover = file_remover or self._remove_file
        self._semaphore = asyncio.Semaphore(
            max(settings.MEDIA_MIGRATION_CONCURRENCY, 1)
        )
        self._handles: dict[uuid.UUID, MigrationHandle] = {}
        self._lock = asyncio.Lock()

    async def startup(self) -> None:
        asset_ids = await asyncio.to_thread(self._recoverable_ids_sync)
        await self._start_assets(asset_ids)

    async def enqueue_task(
        self, task_id: uuid.UUID, asset_ids: list[uuid.UUID]
    ) -> MigrationEnqueueResult:
        async with self._lock:
            queued_ids, skipped = await asyncio.to_thread(
                self._queue_candidates_sync, task_id, asset_ids
            )
            queued = 0
            for asset_id in queued_ids:
                handle = self._handles.get(asset_id)
                if handle and not handle.task.done():
                    skipped += 1
                    continue
                self._create_handle(task_id, asset_id)
                queued += 1
        return MigrationEnqueueResult(queued=queued, skipped=skipped)

    async def wait_for_task(self, task_id: uuid.UUID) -> None:
        while True:
            async with self._lock:
                tasks = [
                    handle.task
                    for handle in self._handles.values()
                    if handle.task_id == task_id and not handle.task.done()
                ]
            if not tasks:
                return
            await asyncio.gather(*tasks, return_exceptions=True)

    async def shutdown(self) -> None:
        async with self._lock:
            tasks = [handle.task for handle in self._handles.values()]
            for task in tasks:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _start_assets(self, asset_ids: list[uuid.UUID]) -> None:
        async with self._lock:
            for asset_id in asset_ids:
                if asset_id in self._handles and not self._handles[asset_id].task.done():
                    continue
                task_id = await asyncio.to_thread(self._task_id_sync, asset_id)
                if task_id is not None:
                    self._create_handle(task_id, asset_id)

    def _create_handle(self, task_id: uuid.UUID, asset_id: uuid.UUID) -> None:
        runner = asyncio.create_task(
            self._run_asset(asset_id), name=f"media-migration-{asset_id}"
        )
        self._handles[asset_id] = MigrationHandle(task_id=task_id, task=runner)

    async def _run_asset(self, asset_id: uuid.UUID) -> None:
        stored: StoredMedia | None = None
        try:
            async with self._semaphore:
                asset = await asyncio.to_thread(self._get_asset_sync, asset_id)
                if asset is None:
                    return
                if asset.storage_backend == MediaStorageBackend.minio.value:
                    await self._cleanup_local(asset_id)
                    return
                source = self._validated_local_path(asset.local_path)
                await asyncio.to_thread(self._begin_sync, asset_id)
                fingerprint = await asyncio.to_thread(self._fingerprint, source)
                await asyncio.to_thread(
                    self._set_phase_sync,
                    asset_id,
                    MediaMigrationStatus.uploading,
                    20,
                )
                stored = await self._storage.ensure_verified_minio_copy(
                    asset,
                    source,
                    file_size=fingerprint.file_size,
                    sha256=fingerprint.sha256,
                    mime_type=asset.mime_type or "video/mp4",
                )
                self._assert_source_unchanged(source, fingerprint)
                await asyncio.to_thread(
                    self._set_phase_sync,
                    asset_id,
                    MediaMigrationStatus.verifying,
                    90,
                )
                await asyncio.to_thread(
                    self._set_phase_sync,
                    asset_id,
                    MediaMigrationStatus.switching,
                    95,
                )
                await asyncio.to_thread(
                    self._switch_to_minio_sync,
                    asset_id,
                    str(source),
                    fingerprint,
                    stored,
                )
                await self._cleanup_local(asset_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            asset = await asyncio.to_thread(self._get_asset_sync, asset_id)
            if asset and asset.storage_backend == MediaStorageBackend.local.value:
                if stored is not None:
                    try:
                        await self._storage.remove_minio_copy(stored)
                    except Exception:
                        pass
                await asyncio.to_thread(
                    self._fail_local_sync, asset_id, _safe_migration_error(exc)
                )
            elif asset:
                await asyncio.to_thread(
                    self._mark_cleanup_error_sync,
                    asset_id,
                    _safe_migration_error(exc),
                )
        finally:
            async with self._lock:
                handle = self._handles.get(asset_id)
                if handle is not None and handle.task is asyncio.current_task():
                    self._handles.pop(asset_id, None)

    async def _cleanup_local(self, asset_id: uuid.UUID) -> None:
        asset = await asyncio.to_thread(self._get_asset_sync, asset_id)
        if asset is None or asset.storage_backend != MediaStorageBackend.minio.value:
            return
        try:
            if asset.local_path:
                path = self._validated_local_path(asset.local_path, must_exist=False)
                await asyncio.to_thread(self._file_remover, path)
            await asyncio.to_thread(self._complete_cleanup_sync, asset_id)
        except Exception as exc:
            await asyncio.to_thread(
                self._mark_cleanup_error_sync,
                asset_id,
                _safe_migration_error(exc),
            )

    @staticmethod
    def _remove_file(path: Path) -> None:
        path.unlink(missing_ok=True)

    @staticmethod
    def _validated_local_path(raw_path: str, *, must_exist: bool = True) -> Path:
        path = Path(raw_path).resolve() if raw_path else None
        root = settings.MEDIA_OUTPUT_DIR.resolve()
        if path is None or not path.is_relative_to(root):
            raise FileNotFoundError("Local media file is outside the media root")
        if must_exist and (not path.is_file() or path.stat().st_size <= 0):
            raise FileNotFoundError("Local media file not found")
        return path

    @staticmethod
    def _fingerprint(path: Path) -> LocalFingerprint:
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as file:
            while chunk := file.read(1024 * 1024):
                digest.update(chunk)
        after = path.stat()
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            raise RuntimeError("Local media changed while hashing")
        return LocalFingerprint(
            file_size=after.st_size,
            sha256=digest.hexdigest(),
            modified_ns=after.st_mtime_ns,
        )

    @staticmethod
    def _assert_source_unchanged(path: Path, fingerprint: LocalFingerprint) -> None:
        stat = path.stat()
        if (
            stat.st_size != fingerprint.file_size
            or stat.st_mtime_ns != fingerprint.modified_ns
        ):
            raise RuntimeError("Local media changed during migration")

    @staticmethod
    def _get_asset_sync(asset_id: uuid.UUID) -> DouyinMediaAsset | None:
        with Session(engine) as session:
            asset = session.get(DouyinMediaAsset, asset_id)
            if asset:
                session.expunge(asset)
            return asset

    @staticmethod
    def _task_id_sync(asset_id: uuid.UUID) -> uuid.UUID | None:
        with Session(engine) as session:
            asset = session.get(DouyinMediaAsset, asset_id)
            return asset.task_id if asset else None

    @classmethod
    def _recoverable_ids_sync(cls) -> list[uuid.UUID]:
        statuses = [*cls._local_recoverable, MediaMigrationStatus.cleanup_pending.value]
        with Session(engine) as session:
            return list(
                session.exec(
                    select(DouyinMediaAsset.id).where(
                        col(DouyinMediaAsset.migration_status).in_(statuses)
                    )
                ).all()
            )

    @staticmethod
    def _queue_candidates_sync(
        task_id: uuid.UUID, asset_ids: list[uuid.UUID]
    ) -> tuple[list[uuid.UUID], int]:
        with Session(engine) as session:
            statement = select(DouyinMediaAsset).where(
                DouyinMediaAsset.task_id == task_id
            )
            if asset_ids:
                statement = statement.where(col(DouyinMediaAsset.id).in_(asset_ids))
            assets = session.exec(statement.with_for_update()).all()
            queued: list[uuid.UUID] = []
            for asset in assets:
                local_candidate = bool(
                    asset.storage_backend == MediaStorageBackend.local.value
                    and asset.status == MediaDownloadStatus.downloaded.value
                    and asset.migration_status
                    in {
                        MediaMigrationStatus.idle.value,
                        MediaMigrationStatus.failed.value,
                    }
                )
                cleanup_candidate = bool(
                    asset.storage_backend == MediaStorageBackend.minio.value
                    and asset.migration_status
                    in {
                        MediaMigrationStatus.cleanup_pending.value,
                        MediaMigrationStatus.switching.value,
                    }
                )
                if not local_candidate and not cleanup_candidate:
                    continue
                if local_candidate:
                    asset.migration_status = MediaMigrationStatus.queued.value
                    asset.migration_progress = 0
                    asset.migration_error = None
                    asset.migration_finished_at = None
                    session.add(asset)
                queued.append(asset.id)
            session.commit()
            requested = len(asset_ids) if asset_ids else len(assets)
            return queued, max(requested - len(queued), 0)

    @staticmethod
    def _begin_sync(asset_id: uuid.UUID) -> None:
        with Session(engine) as session:
            asset = session.get(DouyinMediaAsset, asset_id)
            if not asset or asset.storage_backend != MediaStorageBackend.local.value:
                return
            asset.migration_status = MediaMigrationStatus.uploading.value
            asset.migration_progress = 5
            asset.migration_attempt_count += 1
            asset.migration_error = None
            asset.migration_started_at = get_datetime_utc()
            asset.migration_finished_at = None
            session.add(asset)
            session.commit()

    @staticmethod
    def _set_phase_sync(
        asset_id: uuid.UUID, status: MediaMigrationStatus, progress: int
    ) -> None:
        with Session(engine) as session:
            asset = session.get(DouyinMediaAsset, asset_id)
            if not asset or asset.storage_backend != MediaStorageBackend.local.value:
                return
            asset.migration_status = status.value
            asset.migration_progress = progress
            asset.migration_error = None
            session.add(asset)
            session.commit()

    @staticmethod
    def _switch_to_minio_sync(
        asset_id: uuid.UUID,
        expected_local_path: str,
        fingerprint: LocalFingerprint,
        stored: StoredMedia,
    ) -> None:
        with Session(engine) as session:
            asset = session.exec(
                select(DouyinMediaAsset)
                .where(DouyinMediaAsset.id == asset_id)
                .with_for_update()
            ).one()
            if (
                asset.storage_backend != MediaStorageBackend.local.value
                or asset.status != MediaDownloadStatus.downloaded.value
                or str(Path(asset.local_path).resolve()) != expected_local_path
                or asset.migration_status
                not in {
                    MediaMigrationStatus.uploading.value,
                    MediaMigrationStatus.verifying.value,
                    MediaMigrationStatus.switching.value,
                }
            ):
                raise RuntimeError("Media migration state changed before switch")
            source = Path(expected_local_path)
            MediaMigrationManager._assert_source_unchanged(source, fingerprint)
            asset.storage_backend = stored.backend.value
            asset.storage_bucket = stored.bucket
            asset.object_key = stored.object_key
            asset.file_size = stored.file_size
            asset.sha256 = stored.sha256
            asset.migration_status = MediaMigrationStatus.cleanup_pending.value
            asset.migration_progress = 98
            asset.migration_error = None
            session.add(asset)
            session.commit()

    @staticmethod
    def _complete_cleanup_sync(asset_id: uuid.UUID) -> None:
        with Session(engine) as session:
            asset = session.get(DouyinMediaAsset, asset_id)
            if not asset or asset.storage_backend != MediaStorageBackend.minio.value:
                return
            asset.local_path = ""
            asset.migration_status = MediaMigrationStatus.completed.value
            asset.migration_progress = 100
            asset.migration_error = None
            asset.migration_finished_at = get_datetime_utc()
            session.add(asset)
            session.commit()

    @staticmethod
    def _mark_cleanup_error_sync(asset_id: uuid.UUID, error: str) -> None:
        with Session(engine) as session:
            asset = session.get(DouyinMediaAsset, asset_id)
            if not asset or asset.storage_backend != MediaStorageBackend.minio.value:
                return
            asset.migration_status = MediaMigrationStatus.cleanup_pending.value
            asset.migration_progress = 98
            asset.migration_error = error
            session.add(asset)
            session.commit()

    @staticmethod
    def _fail_local_sync(asset_id: uuid.UUID, error: str) -> None:
        with Session(engine) as session:
            asset = session.get(DouyinMediaAsset, asset_id)
            if not asset or asset.storage_backend != MediaStorageBackend.local.value:
                return
            asset.migration_status = MediaMigrationStatus.failed.value
            asset.migration_progress = 0
            asset.migration_error = error
            asset.migration_finished_at = get_datetime_utc()
            session.add(asset)
            session.commit()


media_migration_manager = MediaMigrationManager(storage=media_storage)
