"""HTTP adapter for the Douyin comment and unified content catalogs."""

from __future__ import annotations

import os
import uuid
from typing import Any, Literal

from crawler.api.deps import CurrentUser, SessionDep
from crawler.business.douyin.comments.exports import (
    build_comment_selection_export,
    build_comments_export,
    build_subtitles_export,
)
from crawler.business.douyin.comments.models import (
    DouyinAwemeCommentCrawlRequest,
    DouyinCommentExportRequest,
    DouyinCommentLibraryPublic,
    DouyinCommentSelectionExportRequest,
    DouyinCommentsPublic,
)
from crawler.business.douyin.comments.query_service import (
    list_comment_library as query_comment_library,
)
from crawler.business.douyin.comments.query_service import (
    list_task_actions as query_task_actions,
)
from crawler.business.douyin.comments.query_service import (
    list_task_comments as query_task_comments,
)
from crawler.business.douyin.content.models import (
    DouyinAwemeCreatorCrawlRequest,
    DouyinAwemesPublic,
    DouyinCreatorOptionsPublic,
    DouyinUserActionsPublic,
)
from crawler.business.douyin.library.models import DouyinWorkPublic, DouyinWorksPublic
from crawler.business.douyin.library.service import (
    create_aweme_comment_recrawl_task,
    create_aweme_creator_crawl_task,
    get_aweme_for_user,
    require_task_access,
)
from crawler.business.douyin.library.service import (
    get_task_work as query_task_work,
)
from crawler.business.douyin.library.service import (
    list_library_creators as query_library_creators,
)
from crawler.business.douyin.library.service import (
    list_library_works as query_library_works,
)
from crawler.business.douyin.library.service import (
    list_task_awemes as query_task_awemes,
)
from crawler.business.douyin.library.service import (
    list_task_works as query_task_works,
)
from crawler.business.douyin.media.models import (
    DouyinSubtitleExportRequest,
    MediaDownloadStatus,
)
from crawler.business.douyin.tasks.models import (
    CrawlTaskPublic,
)
from crawler.business.errors import (
    InvalidRequestError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

early_router = APIRouter()
late_router = APIRouter()


def _owner_id(current_user: CurrentUser) -> uuid.UUID | None:
    return None if current_user.is_superuser else current_user.id


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, ResourceNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PermissionDeniedError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, InvalidRequestError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


def _require_task(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
) -> None:
    try:
        require_task_access(
            session,
            task_id=task_id,
            owner_id=_owner_id(current_user),
        )
    except (ResourceNotFoundError, PermissionDeniedError, InvalidRequestError) as exc:
        _raise_http_error(exc)


def _get_aweme(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    aweme_id: str,
) -> Any:
    try:
        return get_aweme_for_user(
            session,
            task_id=task_id,
            aweme_id=aweme_id,
            owner_id=_owner_id(current_user),
        )
    except (
        ResourceNotFoundError,
        PermissionDeniedError,
        InvalidRequestError,
    ) as exc:
        _raise_http_error(exc)


@early_router.get("/comments", response_model=DouyinCommentLibraryPublic)
def list_comment_library(
    session: SessionDep,
    current_user: CurrentUser,
    comment_content: str | None = Query(default=None, max_length=200),
    search: str | None = Query(default=None, max_length=200),
    task_id: uuid.UUID | None = None,
    track_id: uuid.UUID | None = None,
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
    if min_likes is not None and max_likes is not None and min_likes > max_likes:
        raise HTTPException(status_code=422, detail="最小点赞数不能大于最大点赞数")
    if (
        published_from is not None
        and published_to is not None
        and published_from > published_to
    ):
        raise HTTPException(status_code=422, detail="评论开始时间不能晚于结束时间")
    try:
        return query_comment_library(
            session,
            owner_id=_owner_id(current_user),
            comment_content=comment_content,
            search=search,
            task_id=task_id,
            track_id=track_id,
            aweme_id=aweme_id,
            video_creator=video_creator,
            source_keyword=source_keyword,
            comment_type=comment_type,
            has_pictures=has_pictures,
            min_likes=min_likes,
            max_likes=max_likes,
            published_from=published_from,
            published_to=published_to,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=skip,
            limit=limit,
        )
    except (
        ResourceNotFoundError,
        PermissionDeniedError,
        InvalidRequestError,
    ) as exc:
        _raise_http_error(exc)


@early_router.post("/comments/export", response_class=FileResponse)
def export_comment_selection(
    request: DouyinCommentSelectionExportRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> FileResponse:
    path, filename, exported_count = build_comment_selection_export(
        session,
        owner_id=_owner_id(current_user),
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


@early_router.get("/library/creators", response_model=DouyinCreatorOptionsPublic)
def list_library_creators(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID | None = None,
    track_id: uuid.UUID | None = None,
) -> Any:
    try:
        return query_library_creators(
            session,
            owner_id=_owner_id(current_user),
            task_id=task_id,
            track_id=track_id,
            downloaded_status=MediaDownloadStatus.downloaded.value,
        )
    except (
        ResourceNotFoundError,
        PermissionDeniedError,
        InvalidRequestError,
    ) as exc:
        _raise_http_error(exc)


@early_router.get("/library/works", response_model=DouyinWorksPublic)
def list_library_works(
    session: SessionDep,
    current_user: CurrentUser,
    search: str | None = Query(default=None, max_length=200),
    task_id: uuid.UUID | None = None,
    track_id: uuid.UUID | None = None,
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
    try:
        return query_library_works(
            session,
            owner_id=_owner_id(current_user),
            search=search,
            task_id=task_id,
            track_id=track_id,
            creator_hash=creator_hash,
            tag_id=tag_id,
            download_status=download_status,
            subtitle_status=subtitle_status,
            storage_backend=storage_backend,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=skip,
            limit=limit,
        )
    except (
        ResourceNotFoundError,
        PermissionDeniedError,
        InvalidRequestError,
    ) as exc:
        _raise_http_error(exc)


@late_router.get("/tasks/{task_id}/works", response_model=DouyinWorksPublic)
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
    _require_task(session, current_user, task_id)
    return query_task_works(
        session,
        task_id=task_id,
        search=search,
        tag_id=tag_id,
        download_status=download_status,
        subtitle_status=subtitle_status,
        storage_backend=storage_backend,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )


@late_router.get("/tasks/{task_id}/works/{aweme_id}", response_model=DouyinWorkPublic)
def get_work(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    aweme_id: str,
) -> Any:
    aweme = _get_aweme(session, current_user, task_id, aweme_id)
    return query_task_work(session, task_id=task_id, aweme=aweme)


@late_router.get("/tasks/{task_id}/awemes", response_model=DouyinAwemesPublic)
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
    _require_task(session, current_user, task_id)
    return query_task_awemes(
        session,
        task_id=task_id,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )


@late_router.post(
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
    try:
        return await create_aweme_comment_recrawl_task(
            session,
            source_task_id=task_id,
            aweme_id=aweme_id,
            source_owner_id=_owner_id(current_user),
            new_task_owner_id=current_user.id,
            request=request,
        )
    except (ResourceNotFoundError, PermissionDeniedError, InvalidRequestError) as exc:
        _raise_http_error(exc)


@late_router.post(
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
    try:
        return await create_aweme_creator_crawl_task(
            session,
            source_task_id=task_id,
            aweme_id=aweme_id,
            source_owner_id=_owner_id(current_user),
            new_task_owner_id=current_user.id,
            request=request,
        )
    except (ResourceNotFoundError, PermissionDeniedError, InvalidRequestError) as exc:
        _raise_http_error(exc)


@late_router.get("/tasks/{task_id}/comments", response_model=DouyinCommentsPublic)
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
    _require_task(session, current_user, task_id)
    return query_task_comments(
        session,
        task_id=task_id,
        aweme_id=aweme_id,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )


@late_router.post("/tasks/{task_id}/exports/comments", response_class=FileResponse)
def export_comments(
    request: DouyinCommentExportRequest,
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
) -> FileResponse:
    _require_task(session, current_user, task_id)
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


@late_router.post("/tasks/{task_id}/exports/subtitles", response_class=FileResponse)
def export_subtitles(
    request: DouyinSubtitleExportRequest,
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
) -> FileResponse:
    _require_task(session, current_user, task_id)
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


@late_router.get("/tasks/{task_id}/actions", response_model=DouyinUserActionsPublic)
def list_actions(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> Any:
    _require_task(session, current_user, task_id)
    return query_task_actions(session, task_id=task_id, skip=skip, limit=limit)


# Compatibility aggregate for callers that previously imported this module directly.
router = APIRouter()
router.include_router(early_router)
router.include_router(late_router)

__all__ = ["early_router", "late_router", "router"]
