import json
import os
import uuid
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Cookie, Header, HTTPException, Query, status
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlmodel import col, func, select
from starlette.background import BackgroundTask

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.douyin.storage import task_public_values
from app.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskPublic,
    CrawlTaskResumeRequest,
    CrawlTaskShard,
    CrawlTaskShardPublic,
    CrawlTaskShardsPublic,
    CrawlTasksPublic,
    CrawlTaskStatus,
    DouyinAccount,
    DouyinAweme,
    DouyinAwemeCommentCrawlRequest,
    DouyinAwemeCreatorCrawlRequest,
    DouyinAwemePublic,
    DouyinAwemesPublic,
    DouyinAwemeTag,
    DouyinComment,
    DouyinCommentExportRequest,
    DouyinCommentLibraryItemPublic,
    DouyinCommentLibraryPublic,
    DouyinCommentLibrarySummaryPublic,
    DouyinCommentSelectionExportRequest,
    DouyinCommentsPublic,
    DouyinCrawlType,
    DouyinCreatorOptionPublic,
    DouyinCreatorOptionsPublic,
    DouyinLibraryMediaMigrationRequest,
    DouyinLoginType,
    DouyinMediaAsset,
    DouyinMediaAssetsPublic,
    DouyinMediaMigrationAccepted,
    DouyinMediaMigrationRequest,
    DouyinMediaProcessRequest,
    DouyinMediaRetryRequest,
    DouyinMediaSummaryPublic,
    DouyinSubtitle,
    DouyinSubtitleExportRequest,
    DouyinTag,
    DouyinTagRefPublic,
    DouyinUserAction,
    DouyinUserActionsPublic,
    DouyinWorkPublic,
    DouyinWorksPublic,
    MediaDownloadStatus,
    MediaStorageBackend,
    Message,
)
from app.services.douyin_exports import (
    build_comment_selection_export,
    build_comments_export,
    build_subtitles_export,
)
from app.services.douyin_tasks import TaskResumeError, task_manager
from app.services.media_migration import media_migration_manager
from app.services.media_pipeline import (
    list_media_sync,
    media_manager,
    media_public,
    media_summary_sync,
)
from app.services.media_preview import (
    PREVIEW_COOKIE_NAME,
    RangeNotSatisfiable,
    create_preview_ticket,
    iter_local_file,
    parse_range_header,
    validate_preview_ticket,
)
from app.services.media_storage import (
    MediaObjectNotFoundError,
    MediaStorageUnavailableError,
    media_storage,
)

router = APIRouter(prefix="/douyin", tags=["douyin"])


def _get_task(
    session: SessionDep, current_user: CurrentUser, task_id: uuid.UUID
) -> CrawlTask:
    task = session.get(CrawlTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Douyin task not found")
    if not current_user.is_superuser and task.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return task


def _get_media_asset(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
) -> DouyinMediaAsset:
    _get_task(session, current_user, task_id)
    asset = session.get(DouyinMediaAsset, asset_id)
    if not asset or asset.task_id != task_id:
        raise HTTPException(status_code=404, detail="Douyin media asset not found")
    return asset


def _work_tag_map(
    session: SessionDep, aweme_record_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[DouyinTagRefPublic]]:
    if not aweme_record_ids:
        return {}
    rows = session.exec(
        select(DouyinAwemeTag.aweme_record_id, DouyinTag)
        .join(DouyinTag, col(DouyinTag.id) == col(DouyinAwemeTag.tag_id))
        .where(col(DouyinAwemeTag.aweme_record_id).in_(set(aweme_record_ids)))
        .order_by(DouyinTag.name)
    ).all()
    result: dict[uuid.UUID, list[DouyinTagRefPublic]] = {}
    for aweme_record_id, tag in rows:
        result.setdefault(aweme_record_id, []).append(
            DouyinTagRefPublic(id=tag.id, name=tag.name)
        )
    return result


def _library_work_filters(
    *,
    current_user: Any,
    search: str | None,
    task_id: uuid.UUID | None,
    creator_hash: str | None,
    tag_id: uuid.UUID | None,
    download_status: str,
    subtitle_status: str,
    storage_backend: str,
) -> list[Any]:
    filters: list[Any] = []
    if not current_user.is_superuser:
        filters.append(CrawlTask.owner_id == current_user.id)
    if task_id:
        filters.append(DouyinAweme.task_id == task_id)
    if creator_hash:
        filters.append(DouyinAweme.creator_hash == creator_hash)
    if tag_id:
        filters.append(
            col(DouyinAweme.id).in_(
                select(DouyinAwemeTag.aweme_record_id).where(
                    DouyinAwemeTag.tag_id == tag_id
                )
            )
        )
    if search and search.strip():
        term = f"%{search.strip()}%"
        filters.append(
            col(DouyinAweme.title).ilike(term)
            | col(DouyinAweme.description).ilike(term)
            | col(DouyinAweme.nickname).ilike(term)
            | col(DouyinAweme.aweme_id).ilike(term)
        )
    if download_status != "all":
        filters.append(DouyinMediaAsset.status == download_status)
    if subtitle_status != "all":
        filters.append(DouyinSubtitle.status == subtitle_status)
    if storage_backend != "all":
        filters.append(DouyinMediaAsset.storage_backend == storage_backend)
    return filters


def _get_aweme(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    aweme_id: str,
) -> DouyinAweme:
    _get_task(session, current_user, task_id)
    aweme = session.exec(
        select(DouyinAweme).where(
            DouyinAweme.task_id == task_id,
            DouyinAweme.aweme_id == aweme_id,
        )
    ).first()
    if aweme is None:
        raise HTTPException(status_code=404, detail="Douyin aweme not found")
    return aweme


@router.post(
    "/tasks",
    response_model=CrawlTaskPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_task(
    request: CrawlTaskCreate, current_user: CurrentUser
) -> Any:
    try:
        task = await task_manager.create(owner_id=current_user.id, request=request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CrawlTaskPublic(**task_public_values(task))


@router.get("/tasks", response_model=CrawlTasksPublic)
def list_tasks(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> Any:
    filters = [] if current_user.is_superuser else [CrawlTask.owner_id == current_user.id]
    count = session.exec(
        select(func.count()).select_from(CrawlTask).where(*filters)
    ).one()
    tasks = session.exec(
        select(CrawlTask)
        .where(*filters)
        .order_by(col(CrawlTask.created_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return CrawlTasksPublic(
        data=[CrawlTaskPublic(**task_public_values(task)) for task in tasks],
        count=count,
    )


def _comment_library_filters(
    *,
    current_user: Any,
    comment_content: str | None,
    search: str | None,
    task_id: uuid.UUID | None,
    aweme_id: str | None,
    video_creator: str | None,
    source_keyword: str | None,
    comment_type: str,
    has_pictures: str,
    min_likes: int | None,
    max_likes: int | None,
    published_from: int | None,
    published_to: int | None,
) -> list[Any]:
    filters: list[Any] = []
    if not current_user.is_superuser:
        filters.append(CrawlTask.owner_id == current_user.id)
    if task_id:
        filters.append(DouyinComment.task_id == task_id)
    if aweme_id and aweme_id.strip():
        filters.append(col(DouyinComment.aweme_id).ilike(f"%{aweme_id.strip()}%"))
    if comment_content and comment_content.strip():
        filters.append(
            col(DouyinComment.content).ilike(f"%{comment_content.strip()}%")
        )
    if search and search.strip():
        term = f"%{search.strip()}%"
        filters.append(
            col(DouyinComment.content).ilike(term)
            | col(DouyinComment.nickname).ilike(term)
            | col(DouyinComment.comment_id).ilike(term)
            | col(DouyinAweme.title).ilike(term)
            | col(DouyinAweme.aweme_id).ilike(term)
        )
    if video_creator and video_creator.strip():
        filters.append(
            col(DouyinAweme.nickname).ilike(f"%{video_creator.strip()}%")
        )
    if source_keyword and source_keyword.strip():
        filters.append(
            col(DouyinAweme.source_keyword).ilike(f"%{source_keyword.strip()}%")
        )
    top_level = col(DouyinComment.parent_comment_id).in_(["", "0"])
    if comment_type == "top_level":
        filters.append(top_level)
    elif comment_type == "reply":
        filters.append(~top_level)
    if has_pictures == "yes":
        filters.append(DouyinComment.pictures != "")
    elif has_pictures == "no":
        filters.append(DouyinComment.pictures == "")
    if min_likes is not None:
        filters.append(col(DouyinComment.like_count) >= min_likes)
    if max_likes is not None:
        filters.append(col(DouyinComment.like_count) <= max_likes)
    if published_from is not None:
        filters.append(col(DouyinComment.create_time) >= published_from)
    if published_to is not None:
        filters.append(col(DouyinComment.create_time) <= published_to)
    return filters


def _comment_library_count(session: SessionDep, filters: list[Any]) -> int:
    return session.exec(
        select(func.count())
        .select_from(DouyinComment)
        .join(
            DouyinAweme,
            (col(DouyinAweme.task_id) == col(DouyinComment.task_id))
            & (col(DouyinAweme.aweme_id) == col(DouyinComment.aweme_id)),
        )
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinComment.task_id))
        .where(*filters)
    ).one()


@router.get("/comments", response_model=DouyinCommentLibraryPublic)
def list_comment_library(
    session: SessionDep,
    current_user: CurrentUser,
    comment_content: str | None = Query(default=None, max_length=200),
    search: str | None = Query(default=None, max_length=200),
    task_id: uuid.UUID | None = None,
    aweme_id: str | None = Query(default=None, max_length=128),
    video_creator: str | None = Query(default=None, max_length=255),
    source_keyword: str | None = Query(default=None, max_length=200),
    comment_type: Literal["all", "top_level", "reply"] = "all",
    has_pictures: Literal["all", "yes", "no"] = "all",
    min_likes: int | None = Query(default=None, ge=0),
    max_likes: int | None = Query(default=None, ge=0),
    published_from: int | None = Query(default=None, ge=0),
    published_to: int | None = Query(default=None, ge=0),
    sort_by: Literal[
        "published_at", "like_count", "sub_comment_count", "fetched_at"
    ] = "published_at",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> Any:
    if task_id:
        _get_task(session, current_user, task_id)
    if min_likes is not None and max_likes is not None and min_likes > max_likes:
        raise HTTPException(status_code=422, detail="最小点赞数不能大于最大点赞数")
    if (
        published_from is not None
        and published_to is not None
        and published_from > published_to
    ):
        raise HTTPException(status_code=422, detail="评论开始时间不能晚于结束时间")
    filters = _comment_library_filters(
        current_user=current_user,
        comment_content=comment_content,
        search=search,
        task_id=task_id,
        aweme_id=aweme_id,
        video_creator=video_creator,
        source_keyword=source_keyword,
        comment_type=comment_type,
        has_pictures=has_pictures,
        min_likes=min_likes,
        max_likes=max_likes,
        published_from=published_from,
        published_to=published_to,
    )
    count = _comment_library_count(session, filters)
    top_level_filter = col(DouyinComment.parent_comment_id).in_(["", "0"])
    top_level_count = _comment_library_count(session, [*filters, top_level_filter])
    picture_count = _comment_library_count(
        session, [*filters, DouyinComment.pictures != ""]
    )
    total_like_count = session.exec(
        select(func.coalesce(func.sum(DouyinComment.like_count), 0))
        .select_from(DouyinComment)
        .join(
            DouyinAweme,
            (col(DouyinAweme.task_id) == col(DouyinComment.task_id))
            & (col(DouyinAweme.aweme_id) == col(DouyinComment.aweme_id)),
        )
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinComment.task_id))
        .where(*filters)
    ).one()
    sort_column = {
        "published_at": DouyinComment.create_time,
        "like_count": DouyinComment.like_count,
        "sub_comment_count": DouyinComment.sub_comment_count,
        "fetched_at": DouyinComment.fetched_at,
    }[sort_by]
    order_expression = (
        col(sort_column).asc() if sort_order == "asc" else col(sort_column).desc()
    ).nulls_last()
    rows = session.exec(
        select(DouyinComment, DouyinAweme, CrawlTask)
        .join(
            DouyinAweme,
            (col(DouyinAweme.task_id) == col(DouyinComment.task_id))
            & (col(DouyinAweme.aweme_id) == col(DouyinComment.aweme_id)),
        )
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinComment.task_id))
        .where(*filters)
        .order_by(order_expression, col(DouyinComment.fetched_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return DouyinCommentLibraryPublic(
        data=[
            DouyinCommentLibraryItemPublic(
                comment=comment,
                aweme=aweme,
                task_status=CrawlTaskStatus(task.status),
                task_created_at=task.created_at,
            )
            for comment, aweme, task in rows
        ],
        count=count,
        summary=DouyinCommentLibrarySummaryPublic(
            matched_count=count,
            top_level_count=top_level_count,
            reply_count=count - top_level_count,
            picture_count=picture_count,
            total_like_count=int(total_like_count),
        ),
    )


@router.post(
    "/comments/export",
    response_class=FileResponse,
)
def export_comment_selection(
    request: DouyinCommentSelectionExportRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> FileResponse:
    path, filename, exported_count = build_comment_selection_export(
        session,
        owner_id=None if current_user.is_superuser else current_user.id,
        comment_ids=request.comment_ids,
    )
    if exported_count == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail="没有找到可导出的评论")
    return FileResponse(
        path,
        filename=filename,
        media_type="text/plain; charset=utf-8",
        background=BackgroundTask(os.unlink, path),
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/library/creators", response_model=DouyinCreatorOptionsPublic)
def list_library_creators(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID | None = None,
) -> Any:
    filters: list[Any] = [
        DouyinMediaAsset.status == MediaDownloadStatus.downloaded.value,
        DouyinAweme.creator_hash != "",
    ]
    if not current_user.is_superuser:
        filters.append(CrawlTask.owner_id == current_user.id)
    if task_id:
        _get_task(session, current_user, task_id)
        filters.append(DouyinAweme.task_id == task_id)
    rows = session.exec(
        select(
            DouyinAweme.creator_hash,
            DouyinAweme.nickname,
            func.count(col(DouyinAweme.id)).label("work_count"),
        )
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
        .join(
            DouyinMediaAsset,
            (col(DouyinMediaAsset.task_id) == col(DouyinAweme.task_id))
            & (col(DouyinMediaAsset.aweme_id) == col(DouyinAweme.aweme_id)),
        )
        .where(*filters)
        .group_by(DouyinAweme.creator_hash, DouyinAweme.nickname)
        .order_by(func.count(col(DouyinAweme.id)).desc(), DouyinAweme.nickname)
        .limit(500)
    ).all()
    return DouyinCreatorOptionsPublic(
        data=[
            DouyinCreatorOptionPublic(
                creator_hash=creator_hash,
                nickname=nickname or "匿名创作者",
                work_count=int(work_count),
            )
            for creator_hash, nickname, work_count in rows
        ],
        count=len(rows),
    )


@router.get("/library/works", response_model=DouyinWorksPublic)
def list_library_works(
    session: SessionDep,
    current_user: CurrentUser,
    search: str | None = Query(default=None, max_length=200),
    task_id: uuid.UUID | None = None,
    creator_hash: str | None = Query(default=None, max_length=64),
    tag_id: uuid.UUID | None = None,
    download_status: Literal[
        "all", "queued", "downloading", "downloaded", "failed"
    ] = "downloaded",
    subtitle_status: Literal[
        "all", "pending", "running", "completed", "failed"
    ] = "all",
    storage_backend: Literal["all", "local", "minio"] = "all",
    sort_by: Literal[
        "published_at",
        "liked_count",
        "comment_count",
        "collected_count",
        "persisted_comment_count",
        "downloaded_at",
        "file_size",
        "fetched_at",
    ] = "downloaded_at",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=24, ge=1, le=100),
) -> Any:
    if task_id:
        _get_task(session, current_user, task_id)
    comment_counts = (
        select(
            DouyinComment.task_id,
            DouyinComment.aweme_id,
            func.count(col(DouyinComment.id)).label("persisted_comment_count"),
        )
        .group_by(col(DouyinComment.task_id), col(DouyinComment.aweme_id))
        .subquery()
    )
    persisted_count = func.coalesce(
        comment_counts.c.persisted_comment_count, 0
    ).label("persisted_comment_count")
    filters = _library_work_filters(
        current_user=current_user,
        search=search,
        task_id=task_id,
        creator_hash=creator_hash,
        tag_id=tag_id,
        download_status=download_status,
        subtitle_status=subtitle_status,
        storage_backend=storage_backend,
    )

    base = (
        select(DouyinAweme.id)
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
        .outerjoin(
            DouyinMediaAsset,
            (col(DouyinMediaAsset.task_id) == col(DouyinAweme.task_id))
            & (col(DouyinMediaAsset.aweme_id) == col(DouyinAweme.aweme_id)),
        )
        .outerjoin(
            DouyinSubtitle,
            col(DouyinSubtitle.asset_id) == col(DouyinMediaAsset.id),
        )
        .where(*filters)
    )
    count = session.exec(select(func.count()).select_from(base.subquery())).one()
    sort_column = {
        "published_at": DouyinAweme.create_time,
        "liked_count": DouyinAweme.liked_count,
        "comment_count": DouyinAweme.comment_count,
        "collected_count": DouyinAweme.collected_count,
        "persisted_comment_count": persisted_count,
        "downloaded_at": DouyinMediaAsset.completed_at,
        "file_size": DouyinMediaAsset.file_size,
        "fetched_at": DouyinAweme.fetched_at,
    }[sort_by]
    order_expression = (
        col(sort_column).asc() if sort_order == "asc" else col(sort_column).desc()
    ).nulls_last()
    rows = session.exec(
        select(DouyinAweme, DouyinMediaAsset, DouyinSubtitle, persisted_count)
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
        .outerjoin(
            DouyinMediaAsset,
            (col(DouyinMediaAsset.task_id) == col(DouyinAweme.task_id))
            & (col(DouyinMediaAsset.aweme_id) == col(DouyinAweme.aweme_id)),
        )
        .outerjoin(
            DouyinSubtitle,
            col(DouyinSubtitle.asset_id) == col(DouyinMediaAsset.id),
        )
        .outerjoin(
            comment_counts,
            (comment_counts.c.task_id == DouyinAweme.task_id)
            & (comment_counts.c.aweme_id == DouyinAweme.aweme_id),
        )
        .where(*filters)
        .order_by(order_expression, col(DouyinAweme.fetched_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    tag_map = _work_tag_map(session, [aweme.id for aweme, *_ in rows])
    return DouyinWorksPublic(
        data=[
            DouyinWorkPublic(
                aweme=DouyinAwemePublic.model_validate(aweme),
                persisted_comment_count=int(saved_count),
                media=media_public(asset, subtitle) if asset else None,
                tags=tag_map.get(aweme.id, []),
            )
            for aweme, asset, subtitle, saved_count in rows
        ],
        count=count,
    )


@router.post(
    "/library/media/migrate-to-minio",
    response_model=DouyinMediaMigrationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def migrate_library_media_to_minio(
    request: DouyinLibraryMediaMigrationRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> DouyinMediaMigrationAccepted:
    if request.task_id:
        _get_task(session, current_user, request.task_id)
    filters = _library_work_filters(
        current_user=current_user,
        search=request.search,
        task_id=request.task_id,
        creator_hash=request.creator_hash,
        tag_id=request.tag_id,
        download_status=MediaDownloadStatus.downloaded.value,
        subtitle_status=request.subtitle_status,
        storage_backend=MediaStorageBackend.local.value,
    )
    rows = session.exec(
        select(DouyinMediaAsset.task_id, DouyinMediaAsset.id)
        .join(
            DouyinAweme,
            (col(DouyinAweme.task_id) == col(DouyinMediaAsset.task_id))
            & (col(DouyinAweme.aweme_id) == col(DouyinMediaAsset.aweme_id)),
        )
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinMediaAsset.task_id))
        .outerjoin(
            DouyinSubtitle,
            col(DouyinSubtitle.asset_id) == col(DouyinMediaAsset.id),
        )
        .where(*filters)
        .distinct()
    ).all()
    if not rows:
        return DouyinMediaMigrationAccepted(
            queued=0,
            skipped=0,
            message="当前筛选条件下没有可迁移的本地视频",
        )
    try:
        await media_storage.ensure_minio_ready()
    except MediaStorageUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="Media storage is unavailable"
        ) from exc
    assets_by_task: dict[uuid.UUID, list[uuid.UUID]] = {}
    for task_id_value, asset_id in rows:
        assets_by_task.setdefault(task_id_value, []).append(asset_id)
    queued = 0
    skipped = 0
    for task_id_value, asset_ids in assets_by_task.items():
        result = await media_migration_manager.enqueue_task(
            task_id_value, asset_ids
        )
        queued += result.queued
        skipped += result.skipped
    return DouyinMediaMigrationAccepted(
        queued=queued,
        skipped=skipped,
        message=f"已将 {queued} 个本地视频加入 MinIO 迁移队列",
    )


@router.get("/tasks/{task_id}", response_model=CrawlTaskPublic)
def get_task(
    session: SessionDep, current_user: CurrentUser, task_id: uuid.UUID
) -> Any:
    return CrawlTaskPublic(**task_public_values(_get_task(session, current_user, task_id)))


@router.get("/tasks/{task_id}/shards", response_model=CrawlTaskShardsPublic)
def list_task_shards(
    session: SessionDep, current_user: CurrentUser, task_id: uuid.UUID
) -> Any:
    _get_task(session, current_user, task_id)
    rows = session.exec(
        select(CrawlTaskShard, DouyinAccount.name)
        .outerjoin(
            DouyinAccount,
            col(DouyinAccount.id) == col(CrawlTaskShard.account_id),
        )
        .where(CrawlTaskShard.task_id == task_id)
        .order_by(col(CrawlTaskShard.shard_index))
    ).all()
    data: list[CrawlTaskShardPublic] = []
    for shard, account_name in rows:
        try:
            request = json.loads(shard.request_json)
        except json.JSONDecodeError:
            request = {}
        data.append(
            CrawlTaskShardPublic(
                id=shard.id,
                task_id=shard.task_id,
                account_id=shard.account_id,
                account_name=account_name,
                shard_index=shard.shard_index,
                status=shard.status,
                request=request if isinstance(request, dict) else {},
                aweme_count=shard.aweme_count,
                comment_count=shard.comment_count,
                error=shard.error,
                started_at=shard.started_at,
                finished_at=shard.finished_at,
                created_at=shard.created_at,
            )
        )
    return CrawlTaskShardsPublic(data=data, count=len(data))


@router.post("/tasks/{task_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_task(
    session: SessionDep, current_user: CurrentUser, task_id: uuid.UUID
) -> Message:
    task = _get_task(session, current_user, task_id)
    if task.status in {
        CrawlTaskStatus.succeeded.value,
        CrawlTaskStatus.failed.value,
        CrawlTaskStatus.cancelled.value,
        CrawlTaskStatus.interrupted.value,
    }:
        raise HTTPException(status_code=409, detail="Task is already finished")
    if not await task_manager.cancel(task_id):
        raise HTTPException(status_code=409, detail="Task is not running in this process")
    return Message(message="Douyin task cancelled")


@router.post(
    "/tasks/{task_id}/resume",
    response_model=CrawlTaskPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_task(
    request: CrawlTaskResumeRequest,
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
) -> Any:
    _get_task(session, current_user, task_id)
    try:
        task = await task_manager.resume(task_id=task_id, options=request)
    except TaskResumeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return CrawlTaskPublic(**task_public_values(task))


@router.get("/tasks/{task_id}/media", response_model=DouyinMediaAssetsPublic)
def list_media(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> DouyinMediaAssetsPublic:
    _get_task(session, current_user, task_id)
    return list_media_sync(task_id, skip, limit)


@router.get(
    "/tasks/{task_id}/media-summary", response_model=DouyinMediaSummaryPublic
)
def get_media_summary(
    session: SessionDep, current_user: CurrentUser, task_id: uuid.UUID
) -> DouyinMediaSummaryPublic:
    _get_task(session, current_user, task_id)
    return media_summary_sync(task_id)


@router.post(
    "/tasks/{task_id}/media/migrate-to-minio",
    response_model=DouyinMediaMigrationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def migrate_media_to_minio(
    request: DouyinMediaMigrationRequest,
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
) -> DouyinMediaMigrationAccepted:
    _get_task(session, current_user, task_id)
    for asset_id in request.asset_ids:
        _get_media_asset(session, current_user, task_id, asset_id)
    try:
        await media_storage.ensure_minio_ready()
    except MediaStorageUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="Media storage is unavailable"
        ) from exc
    result = await media_migration_manager.enqueue_task(task_id, request.asset_ids)
    if request.asset_ids and result.queued == 0:
        raise HTTPException(
            status_code=409, detail="Selected media cannot be migrated"
        )
    return DouyinMediaMigrationAccepted(
        queued=result.queued,
        skipped=result.skipped,
        message=f"Queued {result.queued} media migrations",
    )


@router.post(
    "/tasks/{task_id}/media/process",
    response_model=CrawlTaskPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def process_media(
    request: DouyinMediaProcessRequest,
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
) -> Any:
    _get_task(session, current_user, task_id)
    try:
        task = await task_manager.process_media(task_id=task_id, options=request)
    except TaskResumeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return CrawlTaskPublic(**task_public_values(task))


@router.post(
    "/tasks/{task_id}/media/retry", status_code=status.HTTP_202_ACCEPTED
)
async def retry_media(
    request: DouyinMediaRetryRequest,
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
) -> Message:
    task = _get_task(session, current_user, task_id)
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


@router.post(
    "/tasks/{task_id}/media/{asset_id}/retranslate",
    status_code=status.HTTP_202_ACCEPTED,
)
async def retranslate_media(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
) -> Message:
    _get_media_asset(session, current_user, task_id, asset_id)
    task = _get_task(session, current_user, task_id)
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
        raise HTTPException(
            status_code=409,
            detail="Media must be downloaded before subtitle translation",
        )
    return Message(message="Subtitle translation queued")


@router.get("/tasks/{task_id}/media/{asset_id}/file", response_class=FileResponse)
def download_media_file(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
) -> Response:
    asset = _get_media_asset(session, current_user, task_id, asset_id)
    if asset.storage_backend == MediaStorageBackend.minio.value:
        try:
            remote = media_storage.open_object(asset)
        except MediaObjectNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Downloaded media object not found"
            ) from exc
        except MediaStorageUnavailableError as exc:
            raise HTTPException(
                status_code=503, detail="Media storage is unavailable"
            ) from exc
        filename = quote(f"douyin-{asset.aweme_id}.mp4")
        return StreamingResponse(
            media_storage.iter_object(remote),
            media_type=asset.mime_type or "application/octet-stream",
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
                **(
                    {"Content-Length": str(asset.file_size)}
                    if asset.file_size > 0
                    else {}
                ),
            },
        )
    path = media_storage.local_path(asset)
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="Downloaded media file not found")
    return FileResponse(
        path,
        media_type=asset.mime_type or "application/octet-stream",
        filename=f"douyin-{asset.aweme_id}{path.suffix or '.mp4'}",
        headers={"Cache-Control": "private, no-store"},
    )


@router.post(
    "/tasks/{task_id}/media/{asset_id}/preview-session",
    status_code=status.HTTP_201_CREATED,
)
def create_media_preview_session(
    response: Response,
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
) -> Message:
    asset = _get_media_asset(session, current_user, task_id, asset_id)
    if asset.status != MediaDownloadStatus.downloaded.value:
        raise HTTPException(status_code=409, detail="Media has not been downloaded")
    if asset.storage_backend == MediaStorageBackend.minio.value:
        _minio_preview_size(asset)
    else:
        _local_preview_path(asset)

    response.set_cookie(
        key=PREVIEW_COOKIE_NAME,
        value=create_preview_ticket(task_id, asset_id),
        max_age=settings.MEDIA_PREVIEW_TTL_SECONDS,
        httponly=True,
        secure=settings.ENVIRONMENT != "local",
        samesite="lax",
        path=(
            f"{settings.API_V1_STR}/douyin/tasks/{task_id}/media/"
            f"{asset_id}/preview"
        ),
    )
    return Message(message="Media preview session created")


@router.get("/tasks/{task_id}/media/{asset_id}/preview")
def preview_media_file(
    session: SessionDep,
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
    preview_ticket: str | None = Cookie(default=None, alias=PREVIEW_COOKIE_NAME),
    range_header: str | None = Header(default=None, alias="Range"),
) -> Response:
    if not validate_preview_ticket(preview_ticket, task_id, asset_id):
        raise HTTPException(status_code=401, detail="Invalid media preview session")
    asset = session.get(DouyinMediaAsset, asset_id)
    if not asset or asset.task_id != task_id:
        raise HTTPException(status_code=404, detail="Douyin media asset not found")
    if asset.status != MediaDownloadStatus.downloaded.value:
        raise HTTPException(status_code=409, detail="Media has not been downloaded")

    path: Path | None = None
    if asset.storage_backend == MediaStorageBackend.minio.value:
        file_size = asset.file_size if asset.file_size > 0 else _minio_preview_size(asset)
    else:
        path = _local_preview_path(asset)
        file_size = path.stat().st_size

    try:
        byte_range = parse_range_header(range_header, file_size)
    except RangeNotSatisfiable as exc:
        raise HTTPException(
            status_code=416,
            detail="Requested media range is not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        ) from exc

    start = byte_range.start if byte_range else 0
    length = byte_range.length if byte_range else file_size
    if path is not None:
        body = iter_local_file(path, start=start, length=length)
    else:
        try:
            remote = media_storage.open_object(asset, offset=start, length=length)
        except MediaObjectNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Downloaded media object not found"
            ) from exc
        except MediaStorageUnavailableError as exc:
            raise HTTPException(
                status_code=503, detail="Media storage is unavailable"
            ) from exc
        body = media_storage.iter_object(remote)

    filename = quote(f"douyin-{asset.aweme_id}.mp4")
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "Content-Disposition": f"inline; filename*=UTF-8''{filename}",
        "Content-Length": str(length),
    }
    if byte_range:
        headers["Content-Range"] = (
            f"bytes {byte_range.start}-{byte_range.end}/{file_size}"
        )
    return StreamingResponse(
        body,
        status_code=206 if byte_range else 200,
        media_type=asset.mime_type or "application/octet-stream",
        headers=headers,
    )


def _local_preview_path(asset: DouyinMediaAsset) -> Path:
    path = media_storage.local_path(asset)
    if not path or not path.is_file() or path.stat().st_size <= 0:
        raise HTTPException(status_code=404, detail="Downloaded media file not found")
    return path


def _minio_preview_size(asset: DouyinMediaAsset) -> int:
    try:
        file_size = media_storage.object_size(asset)
    except MediaObjectNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Downloaded media object not found"
        ) from exc
    except MediaStorageUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="Media storage is unavailable"
        ) from exc
    if file_size <= 0:
        raise HTTPException(status_code=404, detail="Downloaded media object is empty")
    return file_size


@router.get("/tasks/{task_id}/qrcode", response_class=FileResponse)
def get_qrcode(
    session: SessionDep, current_user: CurrentUser, task_id: uuid.UUID
) -> FileResponse:
    task = _get_task(session, current_user, task_id)
    if task.status != CrawlTaskStatus.waiting_login.value:
        raise HTTPException(status_code=409, detail="Task is not waiting for login")
    path = Path(task.qrcode_path or "")
    if not task.qrcode_path or not path.is_file():
        raise HTTPException(status_code=404, detail="QR code is not available")
    return FileResponse(
        path,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/tasks/{task_id}/works", response_model=DouyinWorksPublic)
def list_works(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    search: str | None = Query(default=None, max_length=200),
    tag_id: uuid.UUID | None = None,
    download_status: str | None = Query(default=None, max_length=32),
    subtitle_status: str | None = Query(default=None, max_length=32),
    storage_backend: str | None = Query(default=None, max_length=32),
    sort_by: Literal[
        "published_at",
        "liked_count",
        "comment_count",
        "collected_count",
        "persisted_comment_count",
        "fetched_at",
    ] = "published_at",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> Any:
    _get_task(session, current_user, task_id)
    comment_counts = (
        select(
            DouyinComment.aweme_id,
            func.count(col(DouyinComment.id)).label("persisted_comment_count"),
        )
        .where(DouyinComment.task_id == task_id)
        .group_by(DouyinComment.aweme_id)
        .subquery()
    )
    persisted_count = func.coalesce(
        comment_counts.c.persisted_comment_count, 0
    ).label("persisted_comment_count")
    filters: list[Any] = [DouyinAweme.task_id == task_id]
    if search and search.strip():
        term = f"%{search.strip()}%"
        filters.append(
            col(DouyinAweme.title).ilike(term)
            | col(DouyinAweme.nickname).ilike(term)
            | col(DouyinAweme.aweme_id).ilike(term)
        )
    if tag_id:
        filters.append(
            col(DouyinAweme.id).in_(
                select(DouyinAwemeTag.aweme_record_id).where(
                    DouyinAwemeTag.tag_id == tag_id
                )
            )
        )
    if download_status:
        filters.append(DouyinMediaAsset.status == download_status)
    if subtitle_status:
        filters.append(DouyinSubtitle.status == subtitle_status)
    if storage_backend:
        filters.append(DouyinMediaAsset.storage_backend == storage_backend)

    base = (
        select(DouyinAweme)
        .outerjoin(
            DouyinMediaAsset,
            (col(DouyinMediaAsset.task_id) == col(DouyinAweme.task_id))
            & (col(DouyinMediaAsset.aweme_id) == col(DouyinAweme.aweme_id)),
        )
        .outerjoin(
            DouyinSubtitle,
            col(DouyinSubtitle.asset_id) == col(DouyinMediaAsset.id),
        )
        .outerjoin(
            comment_counts,
            comment_counts.c.aweme_id == DouyinAweme.aweme_id,
        )
        .where(*filters)
    )
    count = session.exec(
        select(func.count()).select_from(base.subquery())
    ).one()
    sort_column = {
        "published_at": DouyinAweme.create_time,
        "liked_count": DouyinAweme.liked_count,
        "comment_count": DouyinAweme.comment_count,
        "collected_count": DouyinAweme.collected_count,
        "persisted_comment_count": persisted_count,
        "fetched_at": DouyinAweme.fetched_at,
    }[sort_by]
    order_expression = (
        col(sort_column).asc() if sort_order == "asc" else col(sort_column).desc()
    ).nulls_last()
    rows = session.exec(
        select(DouyinAweme, DouyinMediaAsset, DouyinSubtitle, persisted_count)
        .outerjoin(
            DouyinMediaAsset,
            (col(DouyinMediaAsset.task_id) == col(DouyinAweme.task_id))
            & (col(DouyinMediaAsset.aweme_id) == col(DouyinAweme.aweme_id)),
        )
        .outerjoin(
            DouyinSubtitle,
            col(DouyinSubtitle.asset_id) == col(DouyinMediaAsset.id),
        )
        .outerjoin(
            comment_counts,
            comment_counts.c.aweme_id == DouyinAweme.aweme_id,
        )
        .where(*filters)
        .order_by(order_expression, col(DouyinAweme.fetched_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    tag_map = _work_tag_map(session, [aweme.id for aweme, *_ in rows])
    return DouyinWorksPublic(
        data=[
            DouyinWorkPublic(
                aweme=DouyinAwemePublic.model_validate(aweme),
                persisted_comment_count=int(saved_count),
                media=media_public(asset, subtitle) if asset else None,
                tags=tag_map.get(aweme.id, []),
            )
            for aweme, asset, subtitle, saved_count in rows
        ],
        count=count,
    )


@router.get("/tasks/{task_id}/works/{aweme_id}", response_model=DouyinWorkPublic)
def get_work(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    aweme_id: str,
) -> Any:
    aweme = _get_aweme(session, current_user, task_id, aweme_id)
    row = session.exec(
        select(DouyinMediaAsset, DouyinSubtitle)
        .outerjoin(
            DouyinSubtitle,
            col(DouyinSubtitle.asset_id) == col(DouyinMediaAsset.id),
        )
        .where(
            DouyinMediaAsset.task_id == task_id,
            DouyinMediaAsset.aweme_id == aweme_id,
        )
    ).first()
    saved_count = session.exec(
        select(func.count()).select_from(DouyinComment).where(
            DouyinComment.task_id == task_id,
            DouyinComment.aweme_id == aweme_id,
        )
    ).one()
    asset, subtitle = row if row else (None, None)
    return DouyinWorkPublic(
        aweme=DouyinAwemePublic.model_validate(aweme),
        persisted_comment_count=saved_count,
        media=media_public(asset, subtitle) if asset else None,
        tags=_work_tag_map(session, [aweme.id]).get(aweme.id, []),
    )


@router.get("/tasks/{task_id}/awemes", response_model=DouyinAwemesPublic)
def list_awemes(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    sort_by: Literal[
        "published_at", "liked_count", "comment_count", "collected_count", "fetched_at"
    ] = "published_at",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> Any:
    _get_task(session, current_user, task_id)
    count = session.exec(
        select(func.count()).select_from(DouyinAweme).where(DouyinAweme.task_id == task_id)
    ).one()
    sort_column = {
        "published_at": DouyinAweme.create_time,
        "liked_count": DouyinAweme.liked_count,
        "comment_count": DouyinAweme.comment_count,
        "collected_count": DouyinAweme.collected_count,
        "fetched_at": DouyinAweme.fetched_at,
    }[sort_by]
    order_expression = (
        col(sort_column).asc() if sort_order == "asc" else col(sort_column).desc()
    ).nulls_last()
    data = session.exec(
        select(DouyinAweme)
        .where(DouyinAweme.task_id == task_id)
        .order_by(order_expression, col(DouyinAweme.fetched_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return DouyinAwemesPublic(data=data, count=count)


@router.post(
    "/tasks/{task_id}/awemes/{aweme_id}/comments/recrawl",
    response_model=CrawlTaskPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def recrawl_aweme_comments(
    request: DouyinAwemeCommentCrawlRequest,
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    aweme_id: str,
) -> Any:
    aweme = _get_aweme(session, current_user, task_id, aweme_id)
    cookies = request.cookies.get_secret_value().strip() if request.cookies else ""
    crawl_request = CrawlTaskCreate(
        crawl_type=DouyinCrawlType.detail,
        login_type=(DouyinLoginType.cookie if cookies else DouyinLoginType.qrcode),
        browser_mode=request.browser_mode,
        cookies=cookies or None,
        video_ids=[aweme.aweme_id],
        max_awemes=1,
        fetch_comments=True,
        fetch_sub_comments=request.fetch_sub_comments,
        max_comments_per_aweme=request.max_comments_per_aweme,
        concurrency=request.concurrency,
        request_delay_level=request.request_delay_level,
        request_interval_seconds=request.request_interval_seconds,
        account_id=request.account_id,
    )
    try:
        task = await task_manager.create(
            owner_id=current_user.id,
            request=crawl_request,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CrawlTaskPublic(**task_public_values(task))


@router.post(
    "/tasks/{task_id}/awemes/{aweme_id}/creator/crawl",
    response_model=CrawlTaskPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def crawl_aweme_creator(
    request: DouyinAwemeCreatorCrawlRequest,
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    aweme_id: str,
) -> Any:
    aweme = _get_aweme(session, current_user, task_id, aweme_id)
    cookies = request.cookies.get_secret_value().strip() if request.cookies else ""
    crawl_request = CrawlTaskCreate(
        crawl_type=DouyinCrawlType.creator_from_aweme,
        login_type=(DouyinLoginType.cookie if cookies else DouyinLoginType.qrcode),
        browser_mode=request.browser_mode,
        cookies=cookies or None,
        video_ids=[aweme.aweme_id],
        max_awemes=request.max_awemes,
        fetch_comments=request.fetch_comments,
        fetch_sub_comments=request.fetch_sub_comments,
        max_comments_per_aweme=request.max_comments_per_aweme,
        concurrency=request.concurrency,
        request_delay_level=request.request_delay_level,
        request_interval_seconds=request.request_interval_seconds,
        account_id=request.account_id,
    )
    try:
        task = await task_manager.create(
            owner_id=current_user.id,
            request=crawl_request,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CrawlTaskPublic(**task_public_values(task))


@router.get("/tasks/{task_id}/comments", response_model=DouyinCommentsPublic)
def list_comments(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    aweme_id: str | None = None,
    sort_by: Literal["published_at", "like_count", "fetched_at"] = "published_at",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> Any:
    _get_task(session, current_user, task_id)
    filters = [DouyinComment.task_id == task_id]
    if aweme_id:
        filters.append(DouyinComment.aweme_id == aweme_id)
    count = session.exec(
        select(func.count()).select_from(DouyinComment).where(*filters)
    ).one()
    sort_column = {
        "published_at": DouyinComment.create_time,
        "like_count": DouyinComment.like_count,
        "fetched_at": DouyinComment.fetched_at,
    }[sort_by]
    order_expression = (
        col(sort_column).asc() if sort_order == "asc" else col(sort_column).desc()
    ).nulls_last()
    data = session.exec(
        select(DouyinComment)
        .where(*filters)
        .order_by(order_expression, col(DouyinComment.fetched_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return DouyinCommentsPublic(data=data, count=count)


@router.post("/tasks/{task_id}/exports/comments", response_class=FileResponse)
def export_comments(
    request: DouyinCommentExportRequest,
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
) -> FileResponse:
    _get_task(session, current_user, task_id)
    path, filename = build_comments_export(
        session, task_id=task_id, aweme_ids=request.aweme_ids
    )
    return FileResponse(
        path,
        filename=filename,
        media_type="text/plain; charset=utf-8",
        background=BackgroundTask(os.unlink, path),
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/tasks/{task_id}/exports/subtitles", response_class=FileResponse)
def export_subtitles(
    request: DouyinSubtitleExportRequest,
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
) -> FileResponse:
    _get_task(session, current_user, task_id)
    path, filename, media_type = build_subtitles_export(
        session,
        task_id=task_id,
        aweme_ids=request.aweme_ids,
        export_format=request.format.value,
    )
    return FileResponse(
        path,
        filename=filename,
        media_type=media_type,
        background=BackgroundTask(os.unlink, path),
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/tasks/{task_id}/actions", response_model=DouyinUserActionsPublic)
def list_actions(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> Any:
    _get_task(session, current_user, task_id)
    count = session.exec(
        select(func.count())
        .select_from(DouyinUserAction)
        .where(DouyinUserAction.task_id == task_id)
    ).one()
    data = session.exec(
        select(DouyinUserAction)
        .where(DouyinUserAction.task_id == task_id)
        .order_by(col(DouyinUserAction.observed_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return DouyinUserActionsPublic(data=data, count=count)
