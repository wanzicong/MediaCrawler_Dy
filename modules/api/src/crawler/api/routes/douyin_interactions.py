import uuid
from typing import Any

from crawler.api.deps import CurrentUser, SessionDep
from crawler.business.douyin.interactions.models import (
    DouyinInteractionCreate,
    DouyinInteractionDetailPublic,
    DouyinInteractionPreflightPublic,
    DouyinInteractionPublic,
    DouyinInteractionQuotaPublic,
    DouyinInteractionRetryRequest,
    DouyinInteractionsPublic,
    DouyinInteractionStatus,
    DouyinInteractionType,
)
from crawler.business.douyin.interactions.screenshots import (
    InteractionScreenshotIntegrityError,
    InteractionScreenshotNotFoundError,
)
from crawler.business.douyin.interactions.service import (
    InteractionNotFoundError,
    InteractionStateError,
    InteractionValidationError,
    cancel_owned_interaction,
    confirm_owned_interaction,
    create_interaction_public,
    get_interaction_detail_public,
    get_interaction_screenshot_payload,
    list_interaction_quotas,
    list_interactions_public,
    preflight_interaction_public,
    retry_owned_interaction,
)
from fastapi import APIRouter, HTTPException, Query, Response, status

router = APIRouter(prefix="/douyin/interactions", tags=["douyin-interactions"])


def _validation_http_error(exc: InteractionValidationError) -> HTTPException:
    detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
    if exc.interaction_id:
        detail["interaction_id"] = str(exc.interaction_id)
    status_code = (
        status.HTTP_422_UNPROCESSABLE_ENTITY
        if exc.code == "task_track_mismatch"
        else status.HTTP_409_CONFLICT
    )
    return HTTPException(status_code=status_code, detail=detail)


@router.post("/preflight", response_model=DouyinInteractionPreflightPublic)
def preflight_interaction(
    request: DouyinInteractionCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    try:
        return preflight_interaction_public(
            session,
            owner_id=current_user.id,
            request=request,
        )
    except InteractionValidationError as exc:
        raise _validation_http_error(exc) from exc


@router.post(
    "",
    response_model=DouyinInteractionPublic,
    status_code=status.HTTP_201_CREATED,
)
def prepare_interaction(
    request: DouyinInteractionCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    try:
        return create_interaction_public(
            session,
            owner_id=current_user.id,
            request=request,
        )
    except InteractionValidationError as exc:
        raise _validation_http_error(exc) from exc


@router.get("", response_model=DouyinInteractionsPublic)
def list_interactions(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID | None = None,
    track_id: uuid.UUID | None = None,
    aweme_id: str | None = Query(default=None, max_length=128),
    interaction_type: DouyinInteractionType | None = None,
    interaction_status: DouyinInteractionStatus | None = Query(
        default=None, alias="status"
    ),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> Any:
    try:
        return list_interactions_public(
            session,
            owner_id=current_user.id,
            is_superuser=current_user.is_superuser,
            task_id=task_id,
            track_id=track_id,
            aweme_id=aweme_id,
            interaction_type=interaction_type,
            interaction_status=interaction_status,
            skip=skip,
            limit=limit,
        )
    except InteractionNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc) or "任务或赛道不存在或无权访问",
        ) from exc
    except InteractionValidationError as exc:
        raise _validation_http_error(exc) from exc


@router.get("/quota", response_model=list[DouyinInteractionQuotaPublic])
def list_interaction_quota(session: SessionDep, current_user: CurrentUser) -> Any:
    return list_interaction_quotas(session, owner_id=current_user.id)


@router.get("/{interaction_id}", response_model=DouyinInteractionDetailPublic)
def get_interaction(
    interaction_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    try:
        return get_interaction_detail_public(
            session,
            owner_id=current_user.id,
            interaction_id=interaction_id,
            is_superuser=current_user.is_superuser,
        )
    except InteractionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="互动任务不存在") from exc


@router.get(
    "/{interaction_id}/events/{event_id}/screenshot",
    response_class=Response,
)
def get_interaction_event_screenshot(
    interaction_id: uuid.UUID,
    event_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Response:
    try:
        payload = get_interaction_screenshot_payload(
            session,
            owner_id=current_user.id,
            interaction_id=interaction_id,
            event_id=event_id,
            is_superuser=current_user.is_superuser,
        )
    except InteractionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="互动任务不存在") from exc
    except InteractionScreenshotNotFoundError as exc:
        raise HTTPException(status_code=404, detail="操作截图不存在") from exc
    except InteractionScreenshotIntegrityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        content=payload.content,
        media_type=payload.media_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'inline; filename="{payload.event_id}.jpg"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/{interaction_id}/confirm",
    response_model=DouyinInteractionPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def confirm_interaction(
    interaction_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    try:
        return await confirm_owned_interaction(
            session,
            owner_id=current_user.id,
            interaction_id=interaction_id,
            is_superuser=current_user.is_superuser,
        )
    except InteractionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="互动任务不存在") from exc
    except InteractionValidationError as exc:
        raise _validation_http_error(exc) from exc
    except InteractionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/{interaction_id}/retry",
    response_model=DouyinInteractionPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_interaction(
    request: DouyinInteractionRetryRequest,
    interaction_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    try:
        return await retry_owned_interaction(
            session,
            owner_id=current_user.id,
            interaction_id=interaction_id,
            is_superuser=current_user.is_superuser,
            confirm_not_sent=request.confirm_not_sent,
        )
    except InteractionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="互动任务不存在") from exc
    except InteractionValidationError as exc:
        raise _validation_http_error(exc) from exc
    except InteractionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/{interaction_id}/cancel",
    response_model=DouyinInteractionPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_interaction(
    interaction_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    try:
        return await cancel_owned_interaction(
            session,
            owner_id=current_user.id,
            interaction_id=interaction_id,
            is_superuser=current_user.is_superuser,
        )
    except InteractionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="互动任务不存在") from exc
    except InteractionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
