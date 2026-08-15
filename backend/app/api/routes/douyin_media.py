"""Pure HTTP adapter for Douyin media processing and delivery."""

from __future__ import annotations

import uuid
from typing import Any, NoReturn

from fastapi import APIRouter, Cookie, Header, HTTPException, Query, status
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.api.deps import CurrentUser, SessionDep
from app.application.douyin.media.delivery import (
    MediaDelivery,
    MediaRangeNotSatisfiableError,
    prepare_download_delivery,
    prepare_preview_delivery,
    prepare_preview_session,
)
from app.application.douyin.media.preview import PREVIEW_COOKIE_NAME
from app.application.douyin.media.query_service import (
    get_task_media_summary as query_media_summary,
)
from app.application.douyin.media.query_service import (
    list_task_media as query_task_media,
)
from app.application.douyin.media.service import (
    migrate_library_media as migrate_library_media_command,
)
from app.application.douyin.media.service import (
    migrate_task_media as migrate_task_media_command,
)
from app.application.douyin.media.service import (
    process_task_media as process_task_media_command,
)
from app.application.douyin.media.service import (
    retranslate_media_asset as retranslate_media_command,
)
from app.application.douyin.media.service import (
    retry_task_media as retry_task_media_command,
)
from app.application.errors import (
    ConflictError,
    InvalidRequestError,
    PermissionDeniedError,
    ResourceNotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
)
from app.domain.common.models import Message
from app.domain.douyin.media.models import (
    DouyinLibraryMediaMigrationRequest,
    DouyinMediaAssetsPublic,
    DouyinMediaMigrationAccepted,
    DouyinMediaMigrationRequest,
    DouyinMediaProcessRequest,
    DouyinMediaRetryRequest,
    DouyinMediaSummaryPublic,
)
from app.domain.douyin.tasks.models import CrawlTaskPublic

library_router = APIRouter()
router = APIRouter()


def _owner_id(current_user: CurrentUser) -> uuid.UUID | None:
    return None if current_user.is_superuser else current_user.id


def _raise_http_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ResourceNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PermissionDeniedError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, UnauthorizedError):
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if isinstance(exc, ConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, InvalidRequestError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, ServiceUnavailableError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, MediaRangeNotSatisfiableError):
        raise HTTPException(
            status_code=416,
            detail=str(exc),
            headers={"Content-Range": f"bytes */{exc.file_size}"},
        ) from exc
    raise exc


def _delivery_response(delivery: MediaDelivery) -> Response:
    if delivery.kind == "file":
        assert delivery.path is not None
        return FileResponse(
            delivery.path,
            media_type=delivery.media_type,
            filename=delivery.filename,
            headers=delivery.headers,
        )
    assert delivery.body is not None
    return StreamingResponse(
        delivery.body,
        status_code=delivery.status_code,
        media_type=delivery.media_type,
        headers=delivery.headers,
    )


@library_router.post(
    "/library/media/migrate-to-minio",
    response_model=DouyinMediaMigrationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def migrate_library_media_to_minio(
    request: DouyinLibraryMediaMigrationRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> DouyinMediaMigrationAccepted:
    try:
        return await migrate_library_media_command(
            session,
            owner_id=_owner_id(current_user),
            request=request,
        )
    except (
        ResourceNotFoundError,
        PermissionDeniedError,
        InvalidRequestError,
        ServiceUnavailableError,
    ) as exc:
        _raise_http_error(exc)


@router.get("/tasks/{task_id}/media", response_model=DouyinMediaAssetsPublic)
def list_media(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> DouyinMediaAssetsPublic:
    try:
        return query_task_media(
            session,
            task_id=task_id,
            owner_id=_owner_id(current_user),
            skip=skip,
            limit=limit,
        )
    except (ResourceNotFoundError, PermissionDeniedError) as exc:
        _raise_http_error(exc)


@router.get("/tasks/{task_id}/media-summary", response_model=DouyinMediaSummaryPublic)
def get_media_summary(
    session: SessionDep, current_user: CurrentUser, task_id: uuid.UUID
) -> DouyinMediaSummaryPublic:
    try:
        return query_media_summary(
            session,
            task_id=task_id,
            owner_id=_owner_id(current_user),
        )
    except (ResourceNotFoundError, PermissionDeniedError) as exc:
        _raise_http_error(exc)


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
    try:
        return await migrate_task_media_command(
            session,
            task_id=task_id,
            owner_id=_owner_id(current_user),
            request=request,
        )
    except (
        ResourceNotFoundError,
        PermissionDeniedError,
        ConflictError,
        ServiceUnavailableError,
    ) as exc:
        _raise_http_error(exc)


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
    try:
        return await process_task_media_command(
            session,
            task_id=task_id,
            owner_id=_owner_id(current_user),
            options=request,
        )
    except (ResourceNotFoundError, PermissionDeniedError, ConflictError) as exc:
        _raise_http_error(exc)


@router.post("/tasks/{task_id}/media/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_media(
    request: DouyinMediaRetryRequest,
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
) -> Message:
    try:
        return await retry_task_media_command(
            session,
            task_id=task_id,
            owner_id=_owner_id(current_user),
            request=request,
        )
    except (ResourceNotFoundError, PermissionDeniedError) as exc:
        _raise_http_error(exc)


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
    try:
        return await retranslate_media_command(
            session,
            task_id=task_id,
            asset_id=asset_id,
            owner_id=_owner_id(current_user),
        )
    except (ResourceNotFoundError, PermissionDeniedError, ConflictError) as exc:
        _raise_http_error(exc)


@router.get("/tasks/{task_id}/media/{asset_id}/file", response_class=FileResponse)
def download_media_file(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
) -> Response:
    try:
        delivery = prepare_download_delivery(
            session,
            task_id=task_id,
            asset_id=asset_id,
            owner_id=_owner_id(current_user),
        )
    except (
        ResourceNotFoundError,
        PermissionDeniedError,
        ServiceUnavailableError,
    ) as exc:
        _raise_http_error(exc)
    return _delivery_response(delivery)


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
    try:
        preview_session = prepare_preview_session(
            session,
            task_id=task_id,
            asset_id=asset_id,
            owner_id=_owner_id(current_user),
        )
    except (
        ResourceNotFoundError,
        PermissionDeniedError,
        ConflictError,
        ServiceUnavailableError,
    ) as exc:
        _raise_http_error(exc)
    response.set_cookie(
        key=preview_session.cookie_name,
        value=preview_session.cookie_value,
        max_age=preview_session.max_age,
        httponly=True,
        secure=preview_session.secure,
        samesite="lax",
        path=preview_session.path,
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
    try:
        delivery = prepare_preview_delivery(
            session,
            task_id=task_id,
            asset_id=asset_id,
            preview_ticket=preview_ticket,
            range_header=range_header,
        )
    except (
        ResourceNotFoundError,
        UnauthorizedError,
        ConflictError,
        ServiceUnavailableError,
        MediaRangeNotSatisfiableError,
    ) as exc:
        _raise_http_error(exc)
    return _delivery_response(delivery)


__all__ = ["library_router", "router"]
