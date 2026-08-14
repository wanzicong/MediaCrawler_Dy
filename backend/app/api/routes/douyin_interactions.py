import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    DouyinAccount,
    DouyinInteraction,
    DouyinInteractionCreate,
    DouyinInteractionDetailPublic,
    DouyinInteractionEvent,
    DouyinInteractionPreflightPublic,
    DouyinInteractionPublic,
    DouyinInteractionQuotaPublic,
    DouyinInteractionRetryRequest,
    DouyinInteractionsPublic,
    DouyinInteractionStatus,
    DouyinInteractionType,
)
from app.services.douyin_interactions import (
    InteractionStateError,
    InteractionValidationError,
    account_quota,
    create_interaction,
    get_owned_interaction,
    interaction_detail,
    interaction_manager,
    interaction_public,
    interaction_public_with_target,
    interaction_target_comment_contents,
    preflight,
)
from app.services.interaction_screenshots import (
    InteractionScreenshotIntegrityError,
    InteractionScreenshotNotFoundError,
    read_interaction_screenshot,
)

router = APIRouter(prefix="/douyin/interactions", tags=["douyin-interactions"])


def _interaction_or_404(
    session: SessionDep,
    current_user: CurrentUser,
    interaction_id: uuid.UUID,
) -> DouyinInteraction:
    interaction = get_owned_interaction(
        session,
        owner_id=current_user.id,
        interaction_id=interaction_id,
        is_superuser=current_user.is_superuser,
    )
    if interaction is None:
        raise HTTPException(status_code=404, detail="互动任务不存在")
    return interaction


def _validation_http_error(exc: InteractionValidationError) -> HTTPException:
    detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
    if exc.interaction_id:
        detail["interaction_id"] = str(exc.interaction_id)
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


@router.post("/preflight", response_model=DouyinInteractionPreflightPublic)
def preflight_interaction(
    request: DouyinInteractionCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    try:
        return preflight(
            session, owner_id=current_user.id, request=request
        ).public
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
        interaction = create_interaction(
            session, owner_id=current_user.id, request=request
        )
    except InteractionValidationError as exc:
        raise _validation_http_error(exc) from exc
    return interaction_public_with_target(session, interaction)


@router.get("", response_model=DouyinInteractionsPublic)
def list_interactions(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID | None = None,
    aweme_id: str | None = Query(default=None, max_length=128),
    interaction_type: DouyinInteractionType | None = None,
    interaction_status: DouyinInteractionStatus | None = Query(
        default=None, alias="status"
    ),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> Any:
    filters: list[Any] = []
    if not current_user.is_superuser:
        filters.append(DouyinInteraction.owner_id == current_user.id)
    if task_id:
        filters.append(DouyinInteraction.task_id == task_id)
    if aweme_id:
        filters.append(DouyinInteraction.aweme_id == aweme_id)
    if interaction_type:
        filters.append(DouyinInteraction.interaction_type == interaction_type.value)
    if interaction_status:
        filters.append(DouyinInteraction.status == interaction_status.value)
    count = session.exec(
        select(func.count()).select_from(DouyinInteraction).where(*filters)
    ).one()
    data = session.exec(
        select(DouyinInteraction)
        .where(*filters)
        .order_by(col(DouyinInteraction.created_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    target_contents = interaction_target_comment_contents(session, data)
    return DouyinInteractionsPublic(
        data=[
            interaction_public(
                item,
                target_comment_content=(
                    target_contents.get(
                        (item.task_id, item.aweme_id, item.target_comment_id)
                    )
                    if item.target_comment_id
                    else None
                ),
            )
            for item in data
        ],
        count=count,
    )


@router.get("/quota", response_model=list[DouyinInteractionQuotaPublic])
def list_interaction_quota(
    session: SessionDep, current_user: CurrentUser
) -> Any:
    accounts = session.exec(
        select(DouyinAccount)
        .where(DouyinAccount.owner_id == current_user.id)
        .order_by(col(DouyinAccount.name).asc())
    ).all()
    return [
        account_quota(session, owner_id=current_user.id, account=account)
        for account in accounts
    ]


@router.get("/{interaction_id}", response_model=DouyinInteractionDetailPublic)
def get_interaction(
    interaction_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    interaction = _interaction_or_404(session, current_user, interaction_id)
    return interaction_detail(session, interaction)


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
    interaction = _interaction_or_404(session, current_user, interaction_id)
    event = session.get(DouyinInteractionEvent, event_id)
    if event is None or event.interaction_id != interaction.id:
        raise HTTPException(status_code=404, detail="操作截图不存在")
    try:
        payload = read_interaction_screenshot(event)
    except InteractionScreenshotNotFoundError as exc:
        raise HTTPException(status_code=404, detail="操作截图不存在") from exc
    except InteractionScreenshotIntegrityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        content=payload,
        media_type=event.screenshot_mime_type or "image/jpeg",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'inline; filename="{event.id}.jpg"',
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
    interaction = _interaction_or_404(session, current_user, interaction_id)
    try:
        result = await interaction_manager.confirm(
            interaction_id=interaction.id, owner_id=interaction.owner_id
        )
    except InteractionValidationError as exc:
        raise _validation_http_error(exc) from exc
    except InteractionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return interaction_public_with_target(session, result)


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
    interaction = _interaction_or_404(session, current_user, interaction_id)
    try:
        result = await interaction_manager.retry(
            interaction_id=interaction.id,
            owner_id=interaction.owner_id,
            confirm_not_sent=request.confirm_not_sent,
        )
    except InteractionValidationError as exc:
        raise _validation_http_error(exc) from exc
    except InteractionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return interaction_public_with_target(session, result)


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
    interaction = _interaction_or_404(session, current_user, interaction_id)
    try:
        result = await interaction_manager.cancel(
            interaction_id=interaction.id, owner_id=interaction.owner_id
        )
    except InteractionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return interaction_public_with_target(session, result)
