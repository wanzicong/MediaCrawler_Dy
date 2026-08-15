import uuid
from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, SessionDep
from app.application.douyin.tracks import query_service, service
from app.domain.common.models import Message
from app.domain.douyin.keywords.models import (
    DouyinBulkDeleteRequest,
    DouyinKeywordsPublic,
    DouyinKeywordTaskBatchResult,
)
from app.domain.douyin.tracks.models import (
    DouyinTrackCreate,
    DouyinTrackDetailPublic,
    DouyinTrackKeywordAdd,
    DouyinTracksPublic,
    DouyinTrackTaskRequest,
    DouyinTrackUpdate,
)

router = APIRouter(prefix="/douyin/tracks", tags=["douyin-tracks"])


def _raise_http_error(exc: service.TrackServiceError) -> NoReturn:
    if isinstance(exc, service.TrackNotFoundError):
        status_code = 404
    elif isinstance(exc, service.TrackPermissionDeniedError):
        status_code = 403
    elif isinstance(exc, service.TrackConflictError):
        status_code = 409
    elif isinstance(exc, service.TrackValidationError):
        status_code = 422
    else:
        status_code = 500
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("", response_model=DouyinTracksPublic)
def list_tracks(
    session: SessionDep,
    current_user: CurrentUser,
    search: str | None = Query(default=None, max_length=100),
    enabled: bool | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> Any:
    return query_service.list_tracks(
        session,
        owner_id=current_user.id,
        search=search,
        enabled=enabled,
        skip=skip,
        limit=limit,
    )


@router.get("/{track_id}", response_model=DouyinTrackDetailPublic)
def get_track(
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> DouyinTrackDetailPublic:
    try:
        return query_service.get_track_detail(
            session,
            track_id=track_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)


@router.post(
    "", response_model=DouyinTrackDetailPublic, status_code=status.HTTP_201_CREATED
)
def add_track(
    request: DouyinTrackCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    try:
        return service.create_track_record(
            session,
            owner_id=current_user.id,
            name=request.name,
            description=request.description,
            prompt=request.prompt,
            keywords=request.keywords,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)


@router.patch("/{track_id}", response_model=DouyinTrackDetailPublic)
def edit_track(
    request: DouyinTrackUpdate,
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> Any:
    try:
        return service.update_track_record(
            session,
            track_id=track_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
            name=request.name,
            description=request.description,
            prompt=request.prompt,
            enabled=request.enabled,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)


@router.delete("/{track_id}")
def delete_track(
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> Message:
    try:
        service.delete_track_record(
            session,
            track_id=track_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)
    return Message(message="赛道已删除；关键词、任务和采集结果均已保留")


@router.post("/bulk-delete", response_model=Message)
def bulk_delete_tracks(
    request: DouyinBulkDeleteRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    try:
        count = service.delete_track_batch(
            session,
            owner_id=current_user.id,
            track_ids=request.ids,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)
    return Message(message=f"已删除 {count} 个赛道；历史任务和作品均已保留")


@router.get("/{track_id}/keywords", response_model=DouyinKeywordsPublic)
def list_track_keywords(
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> Any:
    try:
        return query_service.list_track_keywords(
            session,
            track_id=track_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)


@router.post("/{track_id}/keywords", response_model=DouyinKeywordsPublic)
def append_track_keywords(
    request: DouyinTrackKeywordAdd,
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> Any:
    try:
        return service.append_track_keyword_records(
            session,
            track_id=track_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
            keywords=request.keywords,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)


@router.delete("/{track_id}/keywords/{keyword_id}")
def remove_track_keyword(
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
    keyword_id: uuid.UUID,
) -> Message:
    try:
        service.remove_track_keyword_record(
            session,
            track_id=track_id,
            keyword_id=keyword_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)
    return Message(message="关键词已从赛道移除，关键词本身及历史任务不受影响")


@router.post(
    "/{track_id}/tasks",
    response_model=DouyinKeywordTaskBatchResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_track_tasks(
    request: DouyinTrackTaskRequest,
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> Any:
    try:
        return await service.create_track_crawl_tasks(
            session,
            track_id=track_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
            request=request,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)
