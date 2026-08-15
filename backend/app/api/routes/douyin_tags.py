import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, SessionDep
from app.application.douyin.tags.service import list_tags_for_actor, sync_tag_history
from app.application.errors import (
    InvalidRequestError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from app.domain.douyin.tags.models import (
    DouyinTagsPublic,
    DouyinTagSyncResult,
)

router = APIRouter(prefix="/douyin/tags", tags=["douyin-tags"])


@router.get("/", response_model=DouyinTagsPublic)
def list_tags(
    session: SessionDep,
    current_user: CurrentUser,
    search: str | None = Query(default=None, max_length=100),
    task_id: uuid.UUID | None = None,
    track_id: uuid.UUID | None = None,
    sort_by: Literal[
        "name", "aweme_count", "task_count", "last_seen_at"
    ] = "aweme_count",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    try:
        return list_tags_for_actor(
            session,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
            search=search,
            task_id=task_id,
            track_id=track_id,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=skip,
            limit=limit,
        )
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except InvalidRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sync", response_model=DouyinTagSyncResult)
def sync_tags(session: SessionDep, current_user: CurrentUser) -> Any:
    return sync_tag_history(session, owner_id=current_user.id)
