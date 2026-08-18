"""抖音采集任务生命周期的纯 HTTP 适配层：任务创建、查询、分片、取消、恢复与登录二维码分发。"""

from __future__ import annotations

import uuid
from typing import Any, NoReturn

from crawler.api.deps import CurrentUser, SessionDep
from crawler.business.common.models import Message
from crawler.business.douyin.tasks.api_service import (
    cancel_task as cancel_task_command,
)
from crawler.business.douyin.tasks.api_service import (
    create_task as create_task_command,
)
from crawler.business.douyin.tasks.api_service import (
    resume_task as resume_task_command,
)
from crawler.business.douyin.tasks.delivery import prepare_qrcode_delivery
from crawler.business.douyin.tasks.models import (
    CrawlTaskCreate,
    CrawlTaskPublic,
    CrawlTaskResumeRequest,
    CrawlTaskShardsPublic,
    CrawlTasksPublic,
)
from crawler.business.douyin.tasks.query_service import (
    get_task_public as query_task,
)
from crawler.business.douyin.tasks.query_service import (
    list_task_shards as query_task_shards,
)
from crawler.business.douyin.tasks.query_service import list_tasks as query_tasks
from crawler.business.errors import (
    ConflictError,
    InvalidRequestError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse

creation_router = APIRouter()
management_router = APIRouter()
delivery_router = APIRouter()


def _owner_id(current_user: CurrentUser) -> uuid.UUID | None:
    """返回数据归属过滤用的 owner_id；超级管理员返回 None 表示不过滤（可见全部）。"""
    return None if current_user.is_superuser else current_user.id


def _raise_http_error(exc: Exception) -> NoReturn:
    """把业务层异常映射为对应的 HTTP 状态码（404/403/422/409），其余异常原样抛出。"""
    if isinstance(exc, ResourceNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PermissionDeniedError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, InvalidRequestError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, ConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise exc


@creation_router.post(
    "/tasks",
    response_model=CrawlTaskPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_task(
    request: CrawlTaskCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """创建一个抖音采集任务（异步受理，返回任务初始状态）。

    参数：
        request: 任务创建参数。
        session: 数据库会话依赖。
        current_user: 当前登录用户。

    返回：
        新创建的采集任务。

    异常：
        HTTPException: 参数不合法（422）。
    """
    try:
        return await create_task_command(
            session,
            owner_id=current_user.id,
            request=request,
        )
    except InvalidRequestError as exc:
        _raise_http_error(exc)


@creation_router.get("/tasks", response_model=CrawlTasksPublic)
def list_tasks(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    track_id: uuid.UUID | None = None,
) -> Any:
    """分页查询当前用户的采集任务列表，可按赛道过滤。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        skip: 分页偏移量。
        limit: 每页数量。
        track_id: 可选，限定赛道。

    返回：
        任务分页结果。

    异常：
        HTTPException: 赛道不存在（404）。
    """
    try:
        return query_tasks(
            session,
            owner_id=_owner_id(current_user),
            skip=skip,
            limit=limit,
            track_id=track_id,
        )
    except ResourceNotFoundError as exc:
        _raise_http_error(exc)


@management_router.get("/tasks/{task_id}", response_model=CrawlTaskPublic)
def get_task(session: SessionDep, current_user: CurrentUser, task_id: uuid.UUID) -> Any:
    """获取指定采集任务的详情。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。

    返回：
        任务详情。

    异常：
        HTTPException: 任务不存在（404）或无权访问（403）。
    """
    try:
        return query_task(
            session,
            task_id=task_id,
            owner_id=_owner_id(current_user),
        )
    except (ResourceNotFoundError, PermissionDeniedError) as exc:
        _raise_http_error(exc)


@management_router.get("/tasks/{task_id}/shards", response_model=CrawlTaskShardsPublic)
def list_task_shards(
    session: SessionDep, current_user: CurrentUser, task_id: uuid.UUID
) -> Any:
    """查询指定任务的分片执行进度列表。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。

    返回：
        任务分片列表。

    异常：
        HTTPException: 任务不存在（404）或无权访问（403）。
    """
    try:
        return query_task_shards(
            session,
            task_id=task_id,
            owner_id=_owner_id(current_user),
        )
    except (ResourceNotFoundError, PermissionDeniedError) as exc:
        _raise_http_error(exc)


@management_router.post("/tasks/{task_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_task(
    session: SessionDep, current_user: CurrentUser, task_id: uuid.UUID
) -> Message:
    """请求取消指定采集任务（异步受理）。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。

    返回：
        取消受理结果消息。

    异常：
        HTTPException: 任务不存在（404）、无权访问（403）或当前状态不允许取消（409）。
    """
    try:
        return await cancel_task_command(
            session,
            task_id=task_id,
            owner_id=_owner_id(current_user),
        )
    except (ResourceNotFoundError, PermissionDeniedError, ConflictError) as exc:
        _raise_http_error(exc)


@management_router.post(
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
    """恢复（断点续跑）指定采集任务，可附带恢复选项。

    参数：
        request: 恢复选项。
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。

    返回：
        恢复后的任务状态。

    异常：
        HTTPException: 任务不存在（404）、无权访问（403）或当前状态不允许恢复（409）。
    """
    try:
        return await resume_task_command(
            session,
            task_id=task_id,
            owner_id=_owner_id(current_user),
            options=request,
        )
    except (ResourceNotFoundError, PermissionDeniedError, ConflictError) as exc:
        _raise_http_error(exc)


@delivery_router.get("/tasks/{task_id}/qrcode", response_class=FileResponse)
def get_qrcode(
    session: SessionDep, current_user: CurrentUser, task_id: uuid.UUID
) -> FileResponse:
    """获取指定任务登录流程的二维码图片。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。

    返回：
        二维码图片文件响应。

    异常：
        HTTPException: 任务不存在（404）、无权访问（403）或当前无可用二维码（409）。
    """
    try:
        delivery = prepare_qrcode_delivery(
            session,
            task_id=task_id,
            owner_id=_owner_id(current_user),
        )
    except (ResourceNotFoundError, PermissionDeniedError, ConflictError) as exc:
        _raise_http_error(exc)
    return FileResponse(
        delivery.path,
        media_type=delivery.media_type,
        headers=delivery.headers,
    )


__all__ = ["creation_router", "delivery_router", "management_router"]
