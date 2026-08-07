import json
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Cookie, Header, HTTPException, Query, status
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.douyin.storage import task_public_values
from app.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskPublic,
    CrawlTaskResumeRequest,
    CrawlTasksPublic,
    CrawlTaskStatus,
    DouyinAweme,
    DouyinAwemeCommentCrawlRequest,
    DouyinAwemeCreatorCrawlRequest,
    DouyinAwemesPublic,
    DouyinComment,
    DouyinCommentsPublic,
    DouyinCrawlType,
    DouyinLoginType,
    DouyinMediaAsset,
    DouyinMediaAssetsPublic,
    DouyinMediaMigrationAccepted,
    DouyinMediaMigrationRequest,
    DouyinMediaProcessRequest,
    DouyinMediaRetryRequest,
    DouyinMediaSummaryPublic,
    DouyinUserAction,
    DouyinUserActionsPublic,
    MediaDownloadStatus,
    MediaStorageBackend,
    Message,
)
from app.services.douyin_tasks import TaskResumeError, task_manager
from app.services.media_migration import media_migration_manager
from app.services.media_pipeline import (
    list_media_sync,
    media_manager,
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


@router.get("/tasks/{task_id}", response_model=CrawlTaskPublic)
def get_task(
    session: SessionDep, current_user: CurrentUser, task_id: uuid.UUID
) -> Any:
    return CrawlTaskPublic(**task_public_values(_get_task(session, current_user, task_id)))


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
    path = Path(asset.local_path).resolve() if asset.local_path else None
    media_root = settings.MEDIA_OUTPUT_DIR.resolve()
    if not path or not path.is_file() or not path.is_relative_to(media_root):
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
    path = Path(asset.local_path).resolve() if asset.local_path else None
    media_root = settings.MEDIA_OUTPUT_DIR.resolve()
    if (
        not path
        or not path.is_file()
        or not path.is_relative_to(media_root)
        or path.stat().st_size <= 0
    ):
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


@router.get("/tasks/{task_id}/awemes", response_model=DouyinAwemesPublic)
def list_awemes(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> Any:
    _get_task(session, current_user, task_id)
    count = session.exec(
        select(func.count()).select_from(DouyinAweme).where(DouyinAweme.task_id == task_id)
    ).one()
    data = session.exec(
        select(DouyinAweme)
        .where(DouyinAweme.task_id == task_id)
        .order_by(col(DouyinAweme.fetched_at).desc())
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
        request_interval_seconds=request.request_interval_seconds,
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
        request_interval_seconds=request.request_interval_seconds,
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
    data = session.exec(
        select(DouyinComment)
        .where(*filters)
        .order_by(col(DouyinComment.fetched_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return DouyinCommentsPublic(data=data, count=count)


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
