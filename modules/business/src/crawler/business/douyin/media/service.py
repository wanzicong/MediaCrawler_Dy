"""面向 HTTP 与 MCP 入站适配层的媒体命令服务（迁移、处理、重试、重译）。"""

from __future__ import annotations

import json
import uuid

from crawler.business.common.models import Message
from crawler.business.douyin.library.service import (
    list_library_media_candidates,
    list_library_subtitle_targets,
)
from crawler.business.douyin.media.migration import media_migration_manager
from crawler.business.douyin.media.models import (
    DouyinLibraryMediaMigrationRequest,
    DouyinLibrarySubtitleProcessAccepted,
    DouyinLibrarySubtitleProcessRequest,
    DouyinMediaBatchProcessItem,
    DouyinMediaBatchProcessRequest,
    DouyinMediaBatchProcessResult,
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
    PermissionDeniedError,
    ResourceNotFoundError,
    ServiceUnavailableError,
)
from sqlmodel import Session

# 作品库批量生成字幕的单批上限：一次请求最多投递多少个作品。
# 字幕转写是重任务（每个作品都要临时下载音频再调用远端转写），
# 不设上限时一次「清除筛选后点一下」可能投递上万个作业。
_LIBRARY_SUBTITLE_BATCH_LIMIT = 1000


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


async def process_tasks_media(
    session: Session,
    *,
    owner_id: uuid.UUID | None,
    request: DouyinMediaBatchProcessRequest,
) -> DouyinMediaBatchProcessResult:
    """把同一套媒体处理配置应用到多个来源任务（下载 + 可选字幕转写）。

    逐个任务走与单任务完全相同的受理逻辑（``process_task_media``），因此存储位置、
    字幕开关、转写语言等配置对所有任务一视同仁；某个任务冲突或不存在时只跳过它，
    不中断整批，并在返回的逐任务明细里说明原因。

    参数：
        session: 数据库会话。
        owner_id: 当前用户 ID，用于归属校验。
        request: 批量处理请求（来源任务 ID 列表 + 与单任务一致的媒体处理选项）。

    返回：
        批量受理结果（受理数、跳过数与逐任务明细）。
    """
    items: list[DouyinMediaBatchProcessItem] = []
    for task_id in request.task_ids:
        # 每个任务单独构造一份选项：批量请求本身是请求体模型，不能直接复用到单任务受理
        options = DouyinMediaProcessRequest(
            media_storage=request.media_storage,
            translate_subtitles=request.translate_subtitles,
            subtitle_only=request.subtitle_only,
            force_retranslate=request.force_retranslate,
            transcription_language=request.transcription_language,
            cookies=request.cookies,
        )
        try:
            await process_task_media(
                session, task_id=task_id, owner_id=owner_id, options=options
            )
        except (
            ConflictError,
            ResourceNotFoundError,
            PermissionDeniedError,
        ) as exc:
            items.append(
                DouyinMediaBatchProcessItem(
                    task_id=task_id, accepted=False, message=str(exc)
                )
            )
            continue
        items.append(
            DouyinMediaBatchProcessItem(
                task_id=task_id, accepted=True, message="已加入下载与字幕处理"
            )
        )
    accepted = sum(1 for item in items if item.accepted)
    return DouyinMediaBatchProcessResult(
        accepted_count=accepted,
        skipped_count=len(items) - accepted,
        items=items,
    )


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


async def process_library_media_subtitles(
    session: Session,
    *,
    owner_id: uuid.UUID | None,
    category_owner_id: uuid.UUID,
    request: DouyinLibrarySubtitleProcessRequest,
) -> DouyinLibrarySubtitleProcessAccepted:
    """为作品库中「还没有字幕」的作品批量生成字幕（临时取音频→转写→删音频）。

    目标集合与列表页筛选口径一致（搜索/任务/赛道/创作者/标签/分类），并且固定
    只取「还没有字幕正文」的作品；下载状态与存储后端一律放开——生成字幕不要求
    作品已下载，管道会按需临时拉取原声音频（拿不到音频时回退整段视频），
    转写完成后立刻删除临时文件，不在任何存储后端留下视频。

    参数：
        session: 数据库会话。
        owner_id: 数据归属用户 ID，用于作品库隔离；None 表示超管不过滤。
        category_owner_id: 分类归属用户 ID（分类是用户资产，按归属人解析）。
        request: 定位条件与转写语言。

    返回：
        受理结果（入队数、跳过数、超上限截断数）。
    """
    limit = _LIBRARY_SUBTITLE_BATCH_LIMIT
    # 多取一条用来判断是否被上限截断，便于提示用户「先缩小筛选再继续」
    targets = list_library_subtitle_targets(
        session,
        owner_id=owner_id,
        search=request.search,
        task_id=request.task_id,
        track_id=request.track_id,
        creator_hash=request.creator_hash,
        tag_id=request.tag_id,
        category_id=request.category_id,
        category_owner_id=category_owner_id,
        limit=limit + 1,
    )
    truncated = max(len(targets) - limit, 0)
    targets = targets[:limit]
    if not targets:
        return DouyinLibrarySubtitleProcessAccepted(
            queued=0,
            skipped=0,
            truncated=0,
            message="当前筛选条件下没有需要生成字幕的作品",
        )
    queued = 0
    skipped = 0
    for target_task_id, aweme_id in targets:
        try:
            asset = await media_manager.enqueue_aweme(
                task_id=target_task_id,
                aweme_id=aweme_id,
                storage_backend=None,
                translate_subtitles=True,
                language=request.transcription_language or "auto",
                temporary_only=True,
                allow_download=True,
            )
        except ValueError:
            # 赛道停用或任务已删除：跳过该作品，不影响其余作品的投递
            skipped += 1
            continue
        if asset is None:
            skipped += 1
            continue
        queued += 1
    message = f"已将 {queued} 个作品加入字幕生成队列（临时取音频转写，完成后不留视频）"
    if truncated:
        message += f"；另有 {truncated} 个作品超出单批上限未处理，请缩小筛选后重试"
    return DouyinLibrarySubtitleProcessAccepted(
        queued=queued,
        skipped=skipped,
        truncated=truncated,
        message=message,
    )


__all__ = [
    "migrate_library_media",
    "migrate_task_media",
    "process_library_media_subtitles",
    "process_task_media",
    "process_tasks_media",
    "retranslate_media_asset",
    "retry_task_media",
]
