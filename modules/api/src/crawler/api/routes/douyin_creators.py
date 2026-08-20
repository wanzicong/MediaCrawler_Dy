"""抖音达人路由：达人名单查询、批量创建/删除、编辑、任务同步与批量创建采集任务。"""

import uuid
from typing import Any, Literal, NoReturn

from crawler.api.deps import CurrentUser, SessionDep
from crawler.business.common.models import Message
from crawler.business.douyin.creators import query_service, service
from crawler.business.douyin.creators.models import (
    DouyinAwemeSyncResult,
    DouyinBulkDeleteRequest,
    DouyinCreatorBatchTaskRequest,
    DouyinCreatorBulkCreateRequest,
    DouyinCreatorBulkCreateResult,
    DouyinCreatorPublic,
    DouyinCreatorsPublic,
    DouyinCreatorStatus,
    DouyinCreatorSyncResult,
    DouyinCreatorTaskBatchResult,
    DouyinCreatorUpdate,
)
from crawler.business.douyin.tasks.models import CrawlTaskPublic
from fastapi import APIRouter, HTTPException, Query, status

router = APIRouter(prefix="/douyin/creators", tags=["douyin-creators"])


def _raise_http_error(exc: service.CreatorServiceError) -> NoReturn:
    """把达人业务异常映射为对应的 HTTP 状态码（404/403/409/422，兜底 500）。"""
    if isinstance(exc, service.CreatorNotFoundError):
        status_code = 404
    elif isinstance(exc, service.CreatorPermissionDeniedError):
        status_code = 403
    elif isinstance(exc, service.CreatorConflictError):
        status_code = 409
    elif isinstance(exc, service.CreatorValidationError):
        status_code = 422
    else:
        status_code = 500
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("/", response_model=DouyinCreatorsPublic)
def list_creators(
    session: SessionDep,
    current_user: CurrentUser,
    search: str | None = Query(default=None, max_length=200),
    track_id: uuid.UUID | None = None,
    creator_status: DouyinCreatorStatus | None = Query(default=None, alias="status"),
    enabled: bool | None = None,
    sort_by: Literal[
        "nickname",
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
    """分页查询当前用户的达人名单，支持搜索、赛道、状态、启用过滤与排序。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        search: 搜索词（匹配昵称、sec_uid 与备注）。
        track_id: 按赛道过滤。
        creator_status: 按达人状态过滤（查询参数别名 status）。
        enabled: 按是否启用过滤。
        sort_by: 排序字段。
        sort_order: 排序方向。
        skip: 分页偏移量。
        limit: 每页数量。

    返回：
        达人分页结果。
    """
    try:
        return query_service.list_creators(
            session,
            owner_id=current_user.id,
            search=search,
            track_id=track_id,
            creator_status=creator_status,
            enabled=enabled,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=skip,
            limit=limit,
        )
    except service.CreatorServiceError as exc:
        _raise_http_error(exc)


@router.post(
    "/bulk",
    response_model=DouyinCreatorBulkCreateResult,
    status_code=status.HTTP_201_CREATED,
)
def bulk_create_creators(
    request: DouyinCreatorBulkCreateRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """批量创建达人（主页链接或 sec_user_id，已存在则复用）。

    参数：
        request: 批量创建请求（达人列表、备注、启用状态、所属赛道）。
        session: 数据库会话依赖。
        current_user: 当前登录用户。

    返回：
        批量创建结果（成功与失败明细）。
    """
    try:
        return service.create_creator_batch(
            session,
            owner_id=current_user.id,
            creators=request.creators,
            notes=request.notes,
            enabled=request.enabled,
            track_id=request.track_id,
        )
    except service.CreatorServiceError as exc:
        _raise_http_error(exc)


@router.patch("/by-id/{creator_id}", response_model=DouyinCreatorPublic)
def edit_creator(
    request: DouyinCreatorUpdate,
    session: SessionDep,
    current_user: CurrentUser,
    creator_id: uuid.UUID,
) -> Any:
    """更新指定达人的昵称、所属赛道、启用状态与备注；待补全达人可传 sec_uid 补全主页。

    参数：
        request: 达人更新参数。
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        creator_id: 目标达人 ID。

    返回：
        更新后的达人。
    """
    try:
        return service.edit_creator_record(
            session,
            creator_id=creator_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
            nickname=request.nickname,
            track_id=request.track_id,
            enabled=request.enabled,
            notes=request.notes,
            sec_uid=request.sec_uid,
        )
    except service.CreatorServiceError as exc:
        _raise_http_error(exc)


@router.delete("/by-id/{creator_id}")
def delete_creator(
    session: SessionDep,
    current_user: CurrentUser,
    creator_id: uuid.UUID,
) -> Message:
    """删除指定达人（关联任务与爬取结果保留）。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        creator_id: 目标达人 ID。

    返回：
        删除结果消息。
    """
    try:
        service.delete_creator_record(
            session,
            creator_id=creator_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
        )
    except service.CreatorServiceError as exc:
        _raise_http_error(exc)
    return Message(message="达人已删除；关联任务和爬取结果均已保留")


@router.post("/bulk-delete", response_model=Message)
def bulk_delete_creators(
    request: DouyinBulkDeleteRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    """批量删除达人（历史任务与作品保留）。

    参数：
        request: 批量删除请求（达人 ID 列表）。
        session: 数据库会话依赖。
        current_user: 当前登录用户。

    返回：
        删除数量消息。
    """
    count = service.delete_creator_batch(
        session,
        owner_id=current_user.id,
        creator_ids=request.ids,
    )
    return Message(message=f"已删除 {count} 个达人；历史任务和作品均已保留")


@router.get("/by-id/{creator_id}/tasks", response_model=list[CrawlTaskPublic])
def list_creator_tasks(
    session: SessionDep,
    current_user: CurrentUser,
    creator_id: uuid.UUID,
) -> Any:
    """查询指定达人关联的采集任务列表。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        creator_id: 目标达人 ID。

    返回：
        关联任务列表。
    """
    try:
        return query_service.list_creator_tasks(
            session,
            creator_id=creator_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
        )
    except service.CreatorServiceError as exc:
        _raise_http_error(exc)


@router.post("/sync/tasks/{task_id}", response_model=DouyinCreatorSyncResult)
def sync_creators_from_task(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
) -> Any:
    """把指定历史采集任务的达人同步进达人名单。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 来源任务 ID。

    返回：
        同步结果（新增/跳过统计）。
    """
    try:
        return service.sync_creator_task(
            session,
            task_id=task_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
        )
    except service.CreatorServiceError as exc:
        _raise_http_error(exc)


@router.post("/sync/history", response_model=DouyinCreatorSyncResult)
def sync_historical_creators(session: SessionDep, current_user: CurrentUser) -> Any:
    """把当前用户全部历史任务（达人爬取类型）的达人批量同步进达人名单。

    返回：
        同步结果（新增/跳过统计）。
    """
    try:
        return service.sync_creator_history(session, owner_id=current_user.id)
    except service.CreatorServiceError as exc:
        _raise_http_error(exc)


@router.post("/sync/awemes", response_model=DouyinAwemeSyncResult)
def sync_creators_from_awemes(
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """从当前用户的历史采集作品聚合导入占位达人（待补全）。

    按 (赛道, 作品脱敏 sec_uid) 聚合作品数据，把不在达人名单中的
    创作者以占位达人形式导入；之后可通过编辑接口补全主页链接转正。

    返回：
        导入结果统计（去重达人数、新建数、已存在数）。
    """
    try:
        return service.import_aweme_creators(session, owner_id=current_user.id)
    except service.CreatorServiceError as exc:
        _raise_http_error(exc)


@router.post(
    "/batch-tasks",
    response_model=DouyinCreatorTaskBatchResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_creator_tasks(
    request: DouyinCreatorBatchTaskRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """按达人批量创建采集任务（异步受理，每达人一个独立任务）。

    参数：
        request: 批量任务请求（达人范围与采集参数）。
        session: 数据库会话依赖。
        current_user: 当前登录用户。

    返回：
        批量任务创建结果。
    """
    try:
        return await service.create_creator_crawl_tasks(
            session,
            owner_id=current_user.id,
            request=request,
        )
    except service.CreatorServiceError as exc:
        _raise_http_error(exc)
