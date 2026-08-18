"""Pure HTTP adapter for Douyin crawl-task lifecycle operations."""

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
    return None if current_user.is_superuser else current_user.id


def _raise_http_error(exc: Exception) -> NoReturn:
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
