"""本地到 MinIO 的单向媒体迁移管理器。

把已下载到本地磁盘的媒体安全迁移到 MinIO：上传、完整性校验、切换资产记录、
清理本地副本；全流程状态落库，支持服务重启后断点续迁。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from crawler.bootstrap.database import engine
from crawler.bootstrap.settings import settings
from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.media.models import (
    DouyinMediaAsset,
    MediaDownloadStatus,
    MediaMigrationStatus,
    MediaStorageBackend,
)
from sqlmodel import Session, col, select

from .storage import StoredMedia, media_storage


class MigrationStorage(Protocol):
    """迁移流程依赖的存储接口（抽象出来便于测试替换）。"""

    # 确保 MinIO 上存在与本地文件一致的已校验副本
    async def ensure_verified_minio_copy(
        self,
        asset: DouyinMediaAsset,
        source_path: Path,
        *,
        file_size: int,
        sha256: str,
        mime_type: str,
    ) -> StoredMedia: ...

    # 删除 MinIO 上的副本
    async def remove_minio_copy(self, stored: StoredMedia) -> None: ...


@dataclass(frozen=True)
class MigrationEnqueueResult:
    """迁移入队结果统计。"""

    queued: int  # 本次新加入迁移队列的资产数
    skipped: int  # 因已在运行或状态不符合而跳过的资产数


@dataclass(frozen=True)
class LocalFingerprint:
    """本地源文件指纹：用于检测迁移期间源文件是否被并发改动。"""

    file_size: int  # 文件大小（字节）
    sha256: str  # 文件内容 SHA-256 摘要
    modified_ns: int  # 文件修改时间（纳秒）


@dataclass
class MigrationHandle:
    """单个资产迁移协程的句柄。"""

    task_id: uuid.UUID  # 所属采集任务 ID
    task: asyncio.Task[None]  # 运行迁移流程的 asyncio 任务


def _safe_migration_error(exc: Exception) -> str:
    """把迁移异常转为脱敏并截断的错误文本（移除本地路径、URL 与凭据），用于安全落库。"""
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
    """安全地执行本地到 MinIO 的单向媒体迁移，状态持久化并支持重启后恢复。"""

    # 重启后可从本地文件侧重新执行的迁移状态
    _local_recoverable = {
        MediaMigrationStatus.queued.value,
        MediaMigrationStatus.uploading.value,
        MediaMigrationStatus.verifying.value,
        MediaMigrationStatus.switching.value,
    }
    # 表示迁移正在执行中的状态集合
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
        """初始化迁移管理器；storage 与 file_remover 可注入以便测试。"""
        self._storage = storage
        self._file_remover = file_remover or self._remove_file
        self._semaphore = asyncio.Semaphore(
            max(settings.MEDIA_MIGRATION_CONCURRENCY, 1)
        )
        self._handles: dict[uuid.UUID, MigrationHandle] = {}
        self._lock = asyncio.Lock()

    async def startup(self) -> None:
        """服务启动时恢复所有处于可恢复状态的迁移任务。"""
        asset_ids = await asyncio.to_thread(self._recoverable_ids_sync)
        await self._start_assets(asset_ids)

    async def enqueue_task(
        self, task_id: uuid.UUID, asset_ids: list[uuid.UUID]
    ) -> MigrationEnqueueResult:
        """把任务下的候选资产加入迁移队列并启动迁移协程。

        参数：
            task_id: 采集任务 ID。
            asset_ids: 指定迁移的资产 ID 列表，为空表示任务内全部候选。

        返回：
            入队与跳过数量统计。
        """
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
        """等待指定任务的所有迁移协程结束（主要供测试与关停流程使用）。"""
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
        """取消并等待全部迁移协程退出（服务关闭时调用）。"""
        async with self._lock:
            tasks = [handle.task for handle in self._handles.values()]
            for task in tasks:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _start_assets(self, asset_ids: list[uuid.UUID]) -> None:
        """为给定资产逐个创建迁移协程，已在运行的跳过。"""
        async with self._lock:
            for asset_id in asset_ids:
                if (
                    asset_id in self._handles
                    and not self._handles[asset_id].task.done()
                ):
                    continue
                task_id = await asyncio.to_thread(self._task_id_sync, asset_id)
                if task_id is not None:
                    self._create_handle(task_id, asset_id)

    def _create_handle(self, task_id: uuid.UUID, asset_id: uuid.UUID) -> None:
        """创建资产的迁移协程并登记句柄。"""
        runner = asyncio.create_task(
            self._run_asset(asset_id), name=f"media-migration-{asset_id}"
        )
        self._handles[asset_id] = MigrationHandle(task_id=task_id, task=runner)

    async def _run_asset(self, asset_id: uuid.UUID) -> None:
        """执行单个资产的完整迁移流程：上传、校验、切换记录、清理本地副本。

        任何阶段失败都会按当前后端落库为可恢复状态：local 侧标记 failed 并尽力
        回滚远端副本，minio 侧标记 cleanup_pending。状态全程落库，保证重启后可续迁。
        """
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
        """切换完成后删除本地副本并把迁移标记为完成；失败则保持 cleanup_pending 并记录错误。"""
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
        """删除本地文件，文件不存在时忽略。"""
        path.unlink(missing_ok=True)

    @staticmethod
    def _validated_local_path(raw_path: str, *, must_exist: bool = True) -> Path:
        """校验本地路径必须位于媒体根目录内；must_exist 为真时还要求文件存在且非空。"""
        path = Path(raw_path).resolve() if raw_path else None
        root = settings.MEDIA_OUTPUT_DIR.resolve()
        if path is None or not path.is_relative_to(root):
            raise FileNotFoundError("Local media file is outside the media root")
        if must_exist and (not path.is_file() or path.stat().st_size <= 0):
            raise FileNotFoundError("Local media file not found")
        return path

    @staticmethod
    def _fingerprint(path: Path) -> LocalFingerprint:
        """计算本地文件指纹（大小、SHA-256、修改时间），读取期间文件被改动则抛错。"""
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
        """断言源文件相对指纹未发生变化，否则中止迁移以防切换到错误内容。"""
        stat = path.stat()
        if (
            stat.st_size != fingerprint.file_size
            or stat.st_mtime_ns != fingerprint.modified_ns
        ):
            raise RuntimeError("Local media changed during migration")

    @staticmethod
    def _get_asset_sync(asset_id: uuid.UUID) -> DouyinMediaAsset | None:
        """按 ID 读取资产并脱离会话返回。"""
        with Session(engine) as session:
            asset = session.get(DouyinMediaAsset, asset_id)
            if asset:
                session.expunge(asset)
            return asset

    @staticmethod
    def _task_id_sync(asset_id: uuid.UUID) -> uuid.UUID | None:
        """按资产 ID 查询所属任务 ID。"""
        with Session(engine) as session:
            asset = session.get(DouyinMediaAsset, asset_id)
            return asset.task_id if asset else None

    @classmethod
    def _recoverable_ids_sync(cls) -> list[uuid.UUID]:
        """查询所有重启后需要恢复迁移的资产 ID。"""
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
        """在事务内筛选可迁移资产并标记为排队。

        候选包括两类：已下载且未迁移/迁移失败的本地资产，以及已切换但本地副本
        待清理的 MinIO 资产（续跑清理）。

        返回：
            （可入队的资产 ID 列表, 跳过数）。
        """
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
        """迁移开始：状态置为 uploading、清零进度并累加尝试次数。"""
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
        """更新迁移阶段与进度（仅本地侧资产生效）。"""
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
        """在事务内把资产记录从本地切换到 MinIO 副本。

        切换前复核资产状态、本地路径与源文件指纹，任何不一致都会中止，
        防止迁移期间资产被并发修改。切换成功后状态置为 cleanup_pending。
        """
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
        """本地副本清理完成：清空 local_path 并把迁移标记为 completed。"""
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
        """记录清理失败：保持 cleanup_pending 状态并写入错误信息（稍后重试清理）。"""
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
        """迁移失败：本地资产标记为 failed 并写入脱敏后的错误信息。"""
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


# 全局共享的迁移管理器实例
media_migration_manager = MediaMigrationManager(storage=media_storage)
