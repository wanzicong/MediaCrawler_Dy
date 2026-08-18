"""Media commands exposed to HTTP and MCP inbound adapters."""

from __future__ import annotations

import json
import uuid

from crawler.business.common.models import Message
from crawler.business.douyin.library.service import list_library_media_candidates
from crawler.business.douyin.media.migration import media_migration_manager
from crawler.business.douyin.media.models import (
    DouyinLibraryMediaMigrationRequest,
    DouyinMediaMigrationAccepted,
    DouyinMediaMigrationRequest,
    DouyinMediaProcessRequest,
    DouyinMediaRetryRequest,
    MediaDownloadStatus,
    MediaStorageBackend,
)
from crawler.business.douyin.media.pipeline import media_manager
from crawler.business.douyin.media.query_service import require_media_asset_access
from crawler.business.douyin.media.storage import (
    MediaStorageUnavailableError,
    media_storage,
)
from crawler.business.douyin.tasks.models import CrawlTaskPublic
from crawler.business.douyin.tasks.query_service import (
    build_tasks_public,
    require_task_access,
)
from crawler.business.douyin.tasks.service import TaskResumeError, task_manager
from crawler.business.errors import (
    ConflictError,
    ServiceUnavailableError,
)
from sqlmodel import Session


async def migrate_library_media(
    session: Session,
    *,
    owner_id: uuid.UUID | None,
    request: DouyinLibraryMediaMigrationRequest,
) -> DouyinMediaMigrationAccepted:
    rows = list_library_media_candidates(
        session,
        owner_id=owner_id,
        search=request.search,
        task_id=request.task_id,
        track_id=request.track_id,
        creator_hash=request.creator_hash,
        tag_id=request.tag_id,
        downloaded_status=MediaDownloadStatus.downloaded.value,
        subtitle_status=request.subtitle_status,
        local_backend=MediaStorageBackend.local.value,
    )
    if not rows:
        return DouyinMediaMigrationAccepted(
            queued=0,
            skipped=0,
            message="当前筛选条件下没有可迁移的本地视频",
        )
    try:
        await media_storage.ensure_minio_ready()
    except MediaStorageUnavailableError as exc:
        raise ServiceUnavailableError("Media storage is unavailable") from exc
    assets_by_task: dict[uuid.UUID, list[uuid.UUID]] = {}
    for task_id_value, asset_id in rows:
        assets_by_task.setdefault(task_id_value, []).append(asset_id)
    queued = 0
    skipped = 0
    for task_id_value, asset_ids in assets_by_task.items():
        result = await media_migration_manager.enqueue_task(task_id_value, asset_ids)
        queued += result.queued
        skipped += result.skipped
    return DouyinMediaMigrationAccepted(
        queued=queued,
        skipped=skipped,
        message=f"已将 {queued} 个本地视频加入 MinIO 迁移队列",
    )


async def migrate_task_media(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID | None,
    request: DouyinMediaMigrationRequest,
) -> DouyinMediaMigrationAccepted:
    require_task_access(session, task_id=task_id, owner_id=owner_id)
    for asset_id in request.asset_ids:
        require_media_asset_access(
            session,
            task_id=task_id,
            asset_id=asset_id,
            owner_id=owner_id,
        )
    try:
        await media_storage.ensure_minio_ready()
    except MediaStorageUnavailableError as exc:
        raise ServiceUnavailableError("Media storage is unavailable") from exc
    result = await media_migration_manager.enqueue_task(task_id, request.asset_ids)
    if request.asset_ids and result.queued == 0:
        raise ConflictError("Selected media cannot be migrated")
    return DouyinMediaMigrationAccepted(
        queued=result.queued,
        skipped=result.skipped,
        message=f"Queued {result.queued} media migrations",
    )


async def process_task_media(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID | None,
    options: DouyinMediaProcessRequest,
) -> CrawlTaskPublic:
    require_task_access(session, task_id=task_id, owner_id=owner_id)
    try:
        task = await task_manager.process_media(task_id=task_id, options=options)
    except TaskResumeError as exc:
        raise ConflictError(str(exc)) from exc
    return build_tasks_public(session, tasks=[task])[0]


async def retry_task_media(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID | None,
    request: DouyinMediaRetryRequest,
) -> Message:
    task = require_task_access(session, task_id=task_id, owner_id=owner_id)
    try:
        task_request = json.loads(task.request_json)
    except json.JSONDecodeError:
        task_request = {}
    queued = await media_manager.retry_task(
        task_id=task_id,
        asset_ids=request.asset_ids,
        retry_downloads=request.retry_downloads,
        retry_subtitles=request.retry_subtitles,
        force_retranslate=request.force_retranslate,
        translate_if_missing=bool(task_request.get("translate_subtitles")),
        language=str(task_request.get("transcription_language") or "auto"),
    )
    return Message(message=f"Queued {queued} media jobs")


async def retranslate_media_asset(
    session: Session,
    *,
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> Message:
    require_media_asset_access(
        session,
        task_id=task_id,
        asset_id=asset_id,
        owner_id=owner_id,
    )
    task = require_task_access(session, task_id=task_id, owner_id=owner_id)
    try:
        task_request = json.loads(task.request_json)
    except json.JSONDecodeError:
        task_request = {}
    queued = await media_manager.retry_task(
        task_id=task_id,
        asset_ids=[asset_id],
        retry_downloads=False,
        retry_subtitles=True,
        force_retranslate=True,
        translate_if_missing=True,
        language=str(task_request.get("transcription_language") or "auto"),
    )
    if not queued:
        raise ConflictError("Media must be downloaded before subtitle translation")
    return Message(message="Subtitle translation queued")


__all__ = [
    "migrate_library_media",
    "migrate_task_media",
    "process_task_media",
    "retranslate_media_asset",
    "retry_task_media",
]
