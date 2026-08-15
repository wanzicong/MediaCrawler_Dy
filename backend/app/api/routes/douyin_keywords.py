import uuid
from typing import Any, Literal, NoReturn

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, SessionDep
from app.application.douyin.keywords import query_service, service
from app.domain.common.models import Message
from app.domain.douyin.keywords.models import (
    DouyinBulkDeleteRequest,
    DouyinKeywordBatchTaskRequest,
    DouyinKeywordBulkCreateRequest,
    DouyinKeywordBulkCreateResult,
    DouyinKeywordPublic,
    DouyinKeywordsPublic,
    DouyinKeywordStatus,
    DouyinKeywordSyncResult,
    DouyinKeywordTaskBatchResult,
    DouyinKeywordUpdate,
)
from app.domain.douyin.tasks.models import CrawlTaskPublic

router = APIRouter(prefix="/douyin/keywords", tags=["douyin-keywords"])


def _raise_http_error(exc: service.KeywordServiceError) -> NoReturn:
    if isinstance(exc, service.KeywordNotFoundError):
        status_code = 404
    elif isinstance(exc, service.KeywordPermissionDeniedError):
        status_code = 403
    elif isinstance(exc, service.KeywordConflictError):
        status_code = 409
    elif isinstance(exc, service.KeywordValidationError):
        status_code = 422
    else:
        status_code = 500
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("/", response_model=DouyinKeywordsPublic)
def list_keywords(
    session: SessionDep,
    current_user: CurrentUser,
    search: str | None = Query(default=None, max_length=200),
    track_id: uuid.UUID | None = None,
    keyword_status: DouyinKeywordStatus | None = Query(default=None, alias="status"),
    enabled: bool | None = None,
    sort_by: Literal[
        "keyword",
        "status",
        "task_count",
        "aweme_count",
        "last_crawled_at",
        "created_at",
    ] = "last_crawled_at",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    try:
        return query_service.list_keywords(
            session,
            owner_id=current_user.id,
            search=search,
            track_id=track_id,
            keyword_status=keyword_status,
            enabled=enabled,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=skip,
            limit=limit,
        )
    except service.KeywordServiceError as exc:
        _raise_http_error(exc)


@router.post(
    "/bulk",
    response_model=DouyinKeywordBulkCreateResult,
    status_code=status.HTTP_201_CREATED,
)
def bulk_create_keywords(
    request: DouyinKeywordBulkCreateRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    try:
        return service.create_keyword_batch(
            session,
            owner_id=current_user.id,
            values=request.keywords,
            notes=request.notes,
            enabled=request.enabled,
            track_id=request.track_id,
        )
    except service.KeywordServiceError as exc:
        _raise_http_error(exc)


@router.patch("/by-id/{keyword_id}", response_model=DouyinKeywordPublic)
def edit_keyword(
    request: DouyinKeywordUpdate,
    session: SessionDep,
    current_user: CurrentUser,
    keyword_id: uuid.UUID,
) -> Any:
    try:
        return service.edit_keyword_record(
            session,
            keyword_id=keyword_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
            keyword=request.keyword,
            track_id=request.track_id,
            enabled=request.enabled,
            notes=request.notes,
        )
    except service.KeywordServiceError as exc:
        _raise_http_error(exc)


@router.delete("/by-id/{keyword_id}")
def delete_keyword(
    session: SessionDep,
    current_user: CurrentUser,
    keyword_id: uuid.UUID,
) -> Message:
    try:
        service.delete_keyword_record(
            session,
            keyword_id=keyword_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
        )
    except service.KeywordServiceError as exc:
        _raise_http_error(exc)
    return Message(message="关键词已删除；关联任务和爬取结果均已保留")


@router.post("/bulk-delete", response_model=Message)
def bulk_delete_keywords(
    request: DouyinBulkDeleteRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    count = service.delete_keyword_batch(
        session,
        owner_id=current_user.id,
        keyword_ids=request.ids,
    )
    return Message(message=f"已删除 {count} 个关键词；历史任务和作品均已保留")


@router.get("/by-id/{keyword_id}/tasks", response_model=list[CrawlTaskPublic])
def list_keyword_tasks(
    session: SessionDep,
    current_user: CurrentUser,
    keyword_id: uuid.UUID,
) -> Any:
    try:
        return query_service.list_keyword_tasks(
            session,
            keyword_id=keyword_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
        )
    except service.KeywordServiceError as exc:
        _raise_http_error(exc)


@router.post("/sync/tasks/{task_id}", response_model=DouyinKeywordSyncResult)
def sync_keywords_from_task(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
) -> Any:
    try:
        return service.sync_keyword_task(
            session,
            task_id=task_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
        )
    except service.KeywordServiceError as exc:
        _raise_http_error(exc)


@router.post("/sync/history", response_model=DouyinKeywordSyncResult)
def sync_historical_keywords(session: SessionDep, current_user: CurrentUser) -> Any:
    try:
        return service.sync_keyword_history(session, owner_id=current_user.id)
    except service.KeywordServiceError as exc:
        _raise_http_error(exc)


@router.post(
    "/batch-tasks",
    response_model=DouyinKeywordTaskBatchResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_keyword_tasks(
    request: DouyinKeywordBatchTaskRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    try:
        return await service.create_keyword_crawl_tasks(
            session,
            owner_id=current_user.id,
            request=request,
        )
    except service.KeywordServiceError as exc:
        _raise_http_error(exc)
