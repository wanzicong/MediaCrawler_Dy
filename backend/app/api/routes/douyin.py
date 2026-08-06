import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.douyin.storage import task_public_values
from app.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskPublic,
    CrawlTasksPublic,
    CrawlTaskStatus,
    DouyinAweme,
    DouyinAwemesPublic,
    DouyinComment,
    DouyinCommentsPublic,
    DouyinMediaAsset,
    DouyinMediaAssetsPublic,
    DouyinMediaRetryRequest,
    DouyinMediaSummaryPublic,
    DouyinUserAction,
    DouyinUserActionsPublic,
    Message,
)
from app.services.douyin_tasks import task_manager
from app.services.media_pipeline import (
    list_media_sync,
    media_manager,
    media_summary_sync,
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
) -> FileResponse:
    asset = _get_media_asset(session, current_user, task_id, asset_id)
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
