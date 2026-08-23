"""面向 HTTP 与 MCP 入站适配层的媒体命令服务（迁移、处理、重试、重译）。"""

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
from crawler.business.douyin.tasks.models import CrawlTask, CrawlTaskPublic
from crawler.business.douyin.tasks.query_service import (
    build_tasks_public,
    require_task_access,
)
from crawler.business.douyin.tasks.service import TaskResumeError, task_manager
from crawler.business.douyin.tracks.bindings import require_task_track_enabled
from crawler.business.errors import (
    ConflictError,
    ServiceUnavailableError,
)
from sqlmodel import Session


def _require_enabled_task_access(
    session: Session, *, task_id: uuid.UUID, owner_id: uuid.UUID | None
) -> CrawlTask:
    """校验任务访问权限及赛道准入，并把停用状态映射为业务冲突。"""
    task = require_task_access(session, task_id=task_id, owner_id=owner_id)
    try:
        require_task_track_enabled(session, task=task)
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    return task


async def migrate_library_media(
    session: Session,
    *,
    owner_id: uuid.UUID | None,
    request: DouyinLibraryMediaMigrationRequest,
) -> DouyinMediaMigrationAccepted:
    """按媒体库筛选条件把已下载的本地视频批量加入 MinIO 迁移队列。

    参数：
        session: 数据库会话。
        owner_id: 当前用户 ID，用于媒体库数据隔离。
        request: 筛选条件（关键词、任务、追踪对象、创作者、标签、字幕状态）。

    返回：
        迁移受理结果（入队数、跳过数与提示信息）。

    异常：
        ServiceUnavailableError: MinIO 存储不可用。
    """
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
        try:
            result = await media_migration_manager.enqueue_task(
                task_id_value, asset_ids
            )
        except ValueError:
            skipped += len(asset_ids)
            continue
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
    """将指定任务下的本地媒体资产加入 MinIO 迁移队列。

    参数：
        session: 数据库会话。
        task_id: 采集任务 ID。
        owner_id: 当前用户 ID，用于归属校验。
        request: 待迁移的资产 ID 列表，为空表示任务内全部候选资产。

    返回：
        迁移受理结果。

    异常：
        ServiceUnavailableError: MinIO 存储不可用。
        ConflictError: 指定了资产但无一满足迁移条件。
    """
    _require_enabled_task_access(session, task_id=task_id, owner_id=owner_id)
    # 逐个校验资产归属，防止越权迁移他人任务的媒体
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
    """触发任务的媒体处理流程（下载与可选的字幕转写）。

    参数：
        session: 数据库会话。
        task_id: 采集任务 ID。
        owner_id: 当前用户 ID，用于归属校验。
        options: 处理选项（存储后端、字幕转写、转写语言、cookie 等）。

    返回：
        更新后的任务对外视图。

    异常：
        ConflictError: 任务当前状态不允许恢复媒体处理。
    """
    _require_enabled_task_access(session, task_id=task_id, owner_id=owner_id)
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
    """重试任务内失败的媒体下载与字幕转写。

    参数：
        session: 数据库会话。
        task_id: 采集任务 ID。
        owner_id: 当前用户 ID，用于归属校验。
        request: 重试范围与选项（资产列表、是否重试下载/字幕、是否强制重译）。

    返回：
        提示入队数量的消息。
    """
    task = _require_enabled_task_access(session, task_id=task_id, owner_id=owner_id)
    # 从任务原始请求中恢复转写语言等上下文，解析失败按空配置处理
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
        temporary_only=bool(task_request.get("subtitle_only")),
    )
    return Message(message=f"Queued {queued} media jobs")


async def retranslate_media_asset(
    session: Session,
    *,
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> Message:
    """对单个已下载媒体资产强制重新转写字幕。

    参数：
        session: 数据库会话。
        task_id: 采集任务 ID。
        asset_id: 媒体资产 ID。
        owner_id: 当前用户 ID，用于归属校验。

    返回：
        提示字幕转写已入队的消息。

    异常：
        ConflictError: 媒体尚未下载完成，无法转写。
    """
    require_media_asset_access(
        session,
        task_id=task_id,
        asset_id=asset_id,
        owner_id=owner_id,
    )
    task = _require_enabled_task_access(session, task_id=task_id, owner_id=owner_id)
    # 从任务原始请求中恢复转写语言等上下文，解析失败按空配置处理
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
        temporary_only=bool(task_request.get("subtitle_only")),
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
