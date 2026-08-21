"""抖音媒体处理与分发的纯 HTTP 适配层：媒体列表/摘要、MinIO 迁移、处理/重试/重翻译、文件下载与预览。"""

from __future__ import annotations

import uuid
from typing import Any, NoReturn

from crawler.api.deps import CurrentUser, SessionDep
from crawler.business.common.models import Message
from crawler.business.douyin.media.delivery import (
    MediaDelivery,
    MediaRangeNotSatisfiableError,
    prepare_download_delivery,
    prepare_preview_delivery,
    prepare_preview_session,
)
from crawler.business.douyin.media.models import (
    DouyinLibraryMediaMigrationRequest,
    DouyinMediaAssetsPublic,
    DouyinMediaMigrationAccepted,
    DouyinMediaMigrationRequest,
    DouyinMediaProcessRequest,
    DouyinMediaRetryRequest,
    DouyinMediaSummaryPublic,
    DouyinMediaTasksPublic,
)
from crawler.business.douyin.media.preview import PREVIEW_COOKIE_NAME
from crawler.business.douyin.media.query_service import (
    get_task_media_summary as query_media_summary,
)
from crawler.business.douyin.media.query_service import (
    list_media_tasks as query_media_tasks,
)
from crawler.business.douyin.media.query_service import (
    list_task_media as query_task_media,
)
from crawler.business.douyin.media.service import (
    migrate_library_media as migrate_library_media_command,
)
from crawler.business.douyin.media.service import (
    migrate_task_media as migrate_task_media_command,
)
from crawler.business.douyin.media.service import (
    process_task_media as process_task_media_command,
)
from crawler.business.douyin.media.service import (
    retranslate_media_asset as retranslate_media_command,
)
from crawler.business.douyin.media.service import (
    retry_task_media as retry_task_media_command,
)
from crawler.business.douyin.tasks.models import CrawlTaskPublic
from crawler.business.errors import (
    ConflictError,
    InvalidRequestError,
    PermissionDeniedError,
    ResourceNotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
)
from fastapi import APIRouter, Cookie, Header, HTTPException, Query, status
from fastapi.responses import FileResponse, Response, StreamingResponse

library_router = APIRouter()
router = APIRouter()


def _owner_id(current_user: CurrentUser) -> uuid.UUID | None:
    """返回数据归属过滤用的 owner_id；超级管理员返回 None 表示不过滤（可见全部）。"""
    return None if current_user.is_superuser else current_user.id


def _raise_http_error(exc: Exception) -> NoReturn:
    """把业务层异常映射为对应的 HTTP 状态码；Range 不可满足时返回 416 并携带 Content-Range。"""
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
    """把业务层的媒体分发描述转换为 FastAPI 响应：本地文件走 FileResponse，其余走流式响应。

    参数：
        delivery: 媒体分发描述（文件路径或字节流、媒体类型、响应头等）。

    返回：
        文件响应或流式响应。
    """
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


@router.get("/media-tasks", response_model=DouyinMediaTasksPublic)
def list_media_tasks(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    track_id: uuid.UUID | None = Query(default=None),
) -> DouyinMediaTasksPublic:
    """分页查询下载与字幕任务，并返回来源采集依赖和聚合进度。"""
    try:
        return query_media_tasks(
            session,
            owner_id=_owner_id(current_user),
            skip=skip,
            limit=limit,
            track_id=track_id,
        )
    except (ResourceNotFoundError, PermissionDeniedError) as exc:
        _raise_http_error(exc)


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
    """将作品库媒体批量迁移到 MinIO 对象存储（异步执行，立即返回受理结果）。

    参数：
        request: 库级迁移请求参数。
        session: 数据库会话依赖。
        current_user: 当前登录用户。

    返回：
        迁移任务受理信息。

    异常：
        HTTPException: 资源不存在（404）、无权访问（403）、参数不合法（422）或服务不可用（503）。
    """
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
    """分页查询指定任务下的媒体资产列表。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。
        skip: 分页偏移量。
        limit: 每页数量。

    返回：
        媒体资产分页结果。

    异常：
        HTTPException: 任务不存在（404）或无权访问（403）。
    """
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
    """获取指定任务的媒体处理汇总统计（下载、字幕等状态计数）。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。

    返回：
        媒体汇总统计。

    异常：
        HTTPException: 任务不存在（404）或无权访问（403）。
    """
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
    """将指定任务的媒体迁移到 MinIO 对象存储（异步执行，立即返回受理结果）。

    参数：
        request: 任务级迁移请求参数。
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。

    返回：
        迁移任务受理信息。

    异常：
        HTTPException: 资源不存在（404）、无权访问（403）、状态冲突（409）或服务不可用（503）。
    """
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
    """对指定任务发起媒体处理流程（下载、字幕抽取等），返回派生的处理任务。

    参数：
        request: 媒体处理选项。
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。

    返回：
        新创建的媒体处理任务。

    异常：
        HTTPException: 资源不存在（404）、无权访问（403）或状态冲突（409）。
    """
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
    """重试指定任务中失败的媒体处理项。

    参数：
        request: 重试请求参数。
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。

    返回：
        重试受理结果消息。

    异常：
        HTTPException: 资源不存在（404）或无权访问（403）。
    """
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
    """对指定媒体资产重新执行字幕/文案翻译。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。
        asset_id: 目标媒体资产 ID。

    返回：
        受理结果消息。

    异常：
        HTTPException: 资源不存在（404）、无权访问（403）或状态冲突（409）。
    """
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
    """下载指定媒体资产的原始文件。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。
        asset_id: 目标媒体资产 ID。

    返回：
        媒体文件响应。

    异常：
        HTTPException: 资源不存在（404）、无权访问（403）或服务不可用（503）。
    """
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
    """为指定媒体资产创建预览会话：通过 HttpOnly Cookie 下发预览票据。

    参数：
        response: FastAPI 响应对象（用于写入 Cookie）。
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。
        asset_id: 目标媒体资产 ID。

    返回：
        会话创建结果消息。

    异常：
        HTTPException: 资源不存在（404）、无权访问（403）、状态冲突（409）或服务不可用（503）。
    """
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
    """凭预览票据在线预览媒体文件，支持 HTTP Range 分段请求（供播放器拖动进度）。

    参数：
        session: 数据库会话依赖。
        task_id: 目标任务 ID。
        asset_id: 目标媒体资产 ID。
        preview_ticket: 预览会话 Cookie 中的票据。
        range_header: HTTP Range 请求头。

    返回：
        媒体文件或字节范围响应。

    异常：
        HTTPException: 资源不存在（404）、票据无效（401）、状态冲突（409）、
            服务不可用（503）或 Range 不可满足（416）。
    """
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
