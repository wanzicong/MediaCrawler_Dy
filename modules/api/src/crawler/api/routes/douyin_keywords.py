"""抖音关键词路由：关键词库查询、批量创建/删除、编辑、任务同步与批量创建采集任务。"""

import uuid
from typing import Any, Literal, NoReturn

from crawler.api.deps import CurrentUser, SessionDep
from crawler.business.common.models import Message
from crawler.business.douyin.keywords import query_service, service
from crawler.business.douyin.keywords.models import (
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
from crawler.business.douyin.tasks.models import CrawlTaskPublic
from fastapi import APIRouter, HTTPException, Query, status

router = APIRouter(prefix="/douyin/keywords", tags=["douyin-keywords"])


def _raise_http_error(exc: service.KeywordServiceError) -> NoReturn:
    """把关键词业务异常映射为对应的 HTTP 状态码（404/403/409/422，兜底 500）。"""
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
    category: str | None = Query(default=None, max_length=100),
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
    """分页查询当前用户的关键词库，支持搜索、赛道、状态、启用过滤与排序。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        search: 搜索关键词。
        track_id: 按赛道过滤。
        keyword_status: 按关键词状态过滤（查询参数别名 status）。
        enabled: 按是否启用过滤。
        sort_by: 排序字段。
        sort_order: 排序方向。
        skip: 分页偏移量。
        limit: 每页数量。

    返回：
        关键词分页结果。
    """
    try:
        return query_service.list_keywords(
            session,
            owner_id=current_user.id,
            search=search,
            track_id=track_id,
            category=category,
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
    """批量创建关键词。

    参数：
        request: 批量创建请求（关键词列表、备注、启用状态、所属赛道）。
        session: 数据库会话依赖。
        current_user: 当前登录用户。

    返回：
        批量创建结果（成功与失败明细）。
    """
    try:
        return service.create_keyword_batch(
            session,
            owner_id=current_user.id,
            values=request.keywords,
            notes=request.notes,
            category=request.category,
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
    """更新指定关键词的内容、所属赛道、启用状态与备注。

    参数：
        request: 关键词更新参数。
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        keyword_id: 目标关键词 ID。

    返回：
        更新后的关键词。
    """
    try:
        return service.edit_keyword_record(
            session,
            keyword_id=keyword_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
            keyword=request.keyword,
            track_id=request.track_id,
            enabled=request.enabled,
            category=request.category,
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
    """删除指定关键词（关联任务与爬取结果保留）。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        keyword_id: 目标关键词 ID。

    返回：
        删除结果消息。
    """
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
    """批量删除关键词（历史任务与作品保留）。

    参数：
        request: 批量删除请求（关键词 ID 列表）。
        session: 数据库会话依赖。
        current_user: 当前登录用户。

    返回：
        删除数量消息。
    """
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
    """查询指定关键词关联的采集任务列表。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        keyword_id: 目标关键词 ID。

    返回：
        关联任务列表。
    """
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
    """把指定历史采集任务的关键词同步进关键词库。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 来源任务 ID。

    返回：
        同步结果（新增/跳过统计）。
    """
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
    """把当前用户全部历史任务的关键词批量同步进关键词库。

    返回：
        同步结果（新增/跳过统计）。
    """
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
    """按关键词批量创建采集任务（异步受理）。

    参数：
        request: 批量任务请求（关键词范围与采集参数）。
        session: 数据库会话依赖。
        current_user: 当前登录用户。

    返回：
        批量任务创建结果。
    """
    try:
        return await service.create_keyword_crawl_tasks(
            session,
            owner_id=current_user.id,
            request=request,
        )
    except service.KeywordServiceError as exc:
        _raise_http_error(exc)
