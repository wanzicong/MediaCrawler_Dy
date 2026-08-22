"""抖音媒体资产的读侧查询与访问归属校验。"""

from __future__ import annotations

import uuid
from collections import defaultdict

from crawler.business.douyin.media.models import (
    DouyinMediaAsset,
    DouyinMediaAssetsPublic,
    DouyinMediaSummaryPublic,
    DouyinMediaTaskPublic,
    DouyinMediaTasksPublic,
    DouyinMediaTaskStatus,
    DouyinSubtitle,
    MediaDownloadStatus,
    MediaMigrationStatus,
    MediaStorageBackend,
    SubtitleStatus,
)
from crawler.business.douyin.media.pipeline import list_media_sync, media_summary_sync
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskPhase,
    CrawlTaskStatus,
)
from crawler.business.douyin.tasks.query_service import (
    build_tasks_public,
    require_task_access,
)
from crawler.business.douyin.tracks.models import DouyinTrack
from crawler.business.errors import ResourceNotFoundError
from sqlalchemy import or_
from sqlmodel import Session, col, func, select


def _empty_media_summary() -> DouyinMediaSummaryPublic:
    """构造零值媒体摘要，供尚未创建下载任务的来源任务展示。"""
    return DouyinMediaSummaryPublic(
        total=0,
        queued=0,
        downloading=0,
        downloaded=0,
        temporary=0,
        download_failed=0,
        subtitle_pending=0,
        subtitle_running=0,
        subtitle_completed=0,
        subtitle_failed=0,
        local_downloaded=0,
        minio_downloaded=0,
        migration_queued=0,
        migration_running=0,
        migration_cleanup_pending=0,
        migration_completed=0,
        migration_failed=0,
    )


def _media_summaries_by_task(
    session: Session, task_ids: list[uuid.UUID]
) -> dict[uuid.UUID, DouyinMediaSummaryPublic]:
    """用两次批量查询汇总一页来源任务，避免管理页产生逐任务查询。"""
    if not task_ids:
        return {}
    asset_rows = session.exec(
        select(
            DouyinMediaAsset.task_id,
            DouyinMediaAsset.status,
            DouyinMediaAsset.storage_backend,
            DouyinMediaAsset.migration_status,
        ).where(col(DouyinMediaAsset.task_id).in_(task_ids))
    ).all()
    subtitle_rows = session.exec(
        select(DouyinSubtitle.task_id, DouyinSubtitle.status).where(
            col(DouyinSubtitle.task_id).in_(task_ids)
        )
    ).all()
    assets_by_task: dict[uuid.UUID, list[tuple[str, str, str]]] = defaultdict(list)
    subtitles_by_task: dict[uuid.UUID, list[str]] = defaultdict(list)
    for task_id, status, backend, migration in asset_rows:
        assets_by_task[task_id].append((status, backend, migration))
    for task_id, status in subtitle_rows:
        subtitles_by_task[task_id].append(status)

    output: dict[uuid.UUID, DouyinMediaSummaryPublic] = {}
    migration_running = {
        MediaMigrationStatus.uploading.value,
        MediaMigrationStatus.verifying.value,
        MediaMigrationStatus.switching.value,
    }
    for task_id in task_ids:
        assets = assets_by_task[task_id]
        subtitles = subtitles_by_task[task_id]
        output[task_id] = DouyinMediaSummaryPublic(
            total=len(assets),
            queued=sum(
                status == MediaDownloadStatus.queued.value for status, _, _ in assets
            ),
            downloading=sum(
                status == MediaDownloadStatus.downloading.value
                for status, _, _ in assets
            ),
            downloaded=sum(
                status == MediaDownloadStatus.downloaded.value
                for status, _, _ in assets
            ),
            temporary=sum(
                status == MediaDownloadStatus.temporary.value for status, _, _ in assets
            ),
            download_failed=sum(
                status == MediaDownloadStatus.failed.value for status, _, _ in assets
            ),
            subtitle_pending=subtitles.count(SubtitleStatus.pending.value),
            subtitle_running=subtitles.count(SubtitleStatus.running.value),
            subtitle_completed=subtitles.count(SubtitleStatus.completed.value),
            subtitle_failed=subtitles.count(SubtitleStatus.failed.value),
            local_downloaded=sum(
                status == MediaDownloadStatus.downloaded.value
                and backend == MediaStorageBackend.local.value
                for status, backend, _ in assets
            ),
            minio_downloaded=sum(
                status == MediaDownloadStatus.downloaded.value
                and backend == MediaStorageBackend.minio.value
                for status, backend, _ in assets
            ),
            migration_queued=sum(
                migration == MediaMigrationStatus.queued.value
                for _, _, migration in assets
            ),
            migration_running=sum(
                migration in migration_running for _, _, migration in assets
            ),
            migration_cleanup_pending=sum(
                migration == MediaMigrationStatus.cleanup_pending.value
                for _, _, migration in assets
            ),
            migration_completed=sum(
                migration == MediaMigrationStatus.completed.value
                for _, _, migration in assets
            ),
            migration_failed=sum(
                migration == MediaMigrationStatus.failed.value
                for _, _, migration in assets
            ),
        )
    return output


def _media_task_status(
    *,
    source_status: CrawlTaskStatus,
    checkpoint_phase: CrawlTaskPhase,
    eligible_count: int,
    summary: DouyinMediaSummaryPublic,
) -> tuple[bool, str, DouyinMediaTaskStatus]:
    """根据来源断点与媒体队列推导依赖说明和聚合状态。"""
    if checkpoint_phase == CrawlTaskPhase.crawl:
        if source_status in {
            CrawlTaskStatus.failed,
            CrawlTaskStatus.interrupted,
            CrawlTaskStatus.cancelled,
        }:
            message = f"来源采集尚未完成，已产出 {eligible_count} 条；请先恢复采集任务"
        else:
            message = f"来源采集正在执行，当前已产出 {eligible_count} 条"
        return False, message, DouyinMediaTaskStatus.waiting_source

    dependency_message = f"来源采集已完成，可处理 {eligible_count} 条作品"
    if source_status == CrawlTaskStatus.processing_media:
        return True, dependency_message, DouyinMediaTaskStatus.running
    if summary.downloading or summary.subtitle_running:
        return True, dependency_message, DouyinMediaTaskStatus.running
    if summary.queued or summary.subtitle_pending:
        return True, dependency_message, DouyinMediaTaskStatus.queued
    if summary.download_failed or summary.subtitle_failed:
        return True, dependency_message, DouyinMediaTaskStatus.attention
    if summary.total == 0 or summary.total < eligible_count:
        return True, dependency_message, DouyinMediaTaskStatus.ready
    return True, dependency_message, DouyinMediaTaskStatus.completed


def require_media_asset_access(
    session: Session,
    *,
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> DouyinMediaAsset:
    """校验任务归属并取出任务下的媒体资产。

    参数：
        session: 数据库会话。
        task_id: 采集任务 ID。
        asset_id: 媒体资产 ID。
        owner_id: 当前用户 ID，用于归属校验。

    返回：
        校验通过的媒体资产记录。

    异常：
        ResourceNotFoundError: 任务无权访问、资产不存在或不属于该任务。
    """
    require_task_access(session, task_id=task_id, owner_id=owner_id)
    asset = session.get(DouyinMediaAsset, asset_id)
    if asset is None or asset.task_id != task_id:
        raise ResourceNotFoundError("Douyin media asset not found")
    return asset


def list_task_media(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID | None,
    skip: int,
    limit: int,
) -> DouyinMediaAssetsPublic:
    """分页列出任务下的媒体资产（含字幕），按处理活跃度优先排序。

    参数：
        session: 数据库会话。
        task_id: 采集任务 ID。
        owner_id: 当前用户 ID，用于归属校验。
        skip: 分页偏移量。
        limit: 每页条数。

    返回：
        资产列表与总数。
    """
    require_task_access(session, task_id=task_id, owner_id=owner_id)
    return list_media_sync(task_id, skip, limit)


def get_task_media_summary(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> DouyinMediaSummaryPublic:
    """统计任务下媒体下载、字幕转写与迁移各状态的数量。

    参数：
        session: 数据库会话。
        task_id: 采集任务 ID。
        owner_id: 当前用户 ID，用于归属校验。

    返回：
        各状态计数汇总。
    """
    require_task_access(session, task_id=task_id, owner_id=owner_id)
    return media_summary_sync(task_id)


def list_media_tasks(
    session: Session,
    *,
    owner_id: uuid.UUID | None,
    skip: int,
    limit: int,
    track_id: uuid.UUID | None = None,
) -> DouyinMediaTasksPublic:
    """分页列出媒体处理任务，并一次性聚合其来源依赖与处理进度。"""
    filters = [] if owner_id is None else [CrawlTask.owner_id == owner_id]
    if track_id is not None:
        track = session.get(DouyinTrack, track_id)
        if track is None or (owner_id is not None and track.owner_id != owner_id):
            raise ResourceNotFoundError("赛道不存在或无权访问")
        filters.append(CrawlTask.track_id == track_id)
    # 已产出作品的任务可以成为媒体来源；仍在运行的采集任务也展示出来，
    # 让用户能明确看到依赖尚未满足，而不是误以为任务消失。
    source_filter = or_(
        col(CrawlTask.aweme_count) > 0,
        col(CrawlTask.status).in_(
            {
                CrawlTaskStatus.queued.value,
                CrawlTaskStatus.waiting_login.value,
                CrawlTaskStatus.running.value,
            }
        ),
    )
    count = session.exec(
        select(func.count()).select_from(CrawlTask).where(*filters, source_filter)
    ).one()
    tasks = list(
        session.exec(
            select(CrawlTask)
            .where(*filters, source_filter)
            .order_by(col(CrawlTask.created_at).desc())
            .offset(skip)
            .limit(limit)
        ).all()
    )
    public_tasks = build_tasks_public(session, tasks=tasks)
    summaries = _media_summaries_by_task(session, [task.id for task in tasks])
    data: list[DouyinMediaTaskPublic] = []
    for task in public_tasks:
        summary = summaries.get(task.id, _empty_media_summary())
        dependency_ready, dependency_message, status = _media_task_status(
            source_status=task.status,
            checkpoint_phase=task.checkpoint_phase,
            eligible_count=task.aweme_count,
            summary=summary,
        )
        data.append(
            DouyinMediaTaskPublic(
                source_task_id=task.id,
                track_id=task.track_id,
                track_name=task.track_name,
                track_is_default=task.track_is_default,
                source_title=task.display_title,
                source_author=task.display_author,
                source_creator_names=task.creator_names,
                crawl_type=task.crawl_type.value,
                crawl_status=task.status.value,
                checkpoint_phase=task.checkpoint_phase.value,
                source_request=task.request,
                eligible_count=task.aweme_count,
                dependency_ready=dependency_ready,
                dependency_message=dependency_message,
                status=status,
                summary=summary,
                created_at=task.created_at,
                finished_at=task.finished_at,
            )
        )
    return DouyinMediaTasksPublic(data=data, count=count)


__all__ = [
    "get_task_media_summary",
    "list_media_tasks",
    "list_task_media",
    "require_media_asset_access",
]
