import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, SessionDep
from app.models import CrawlTask, DouyinTagPublic, DouyinTagsPublic, DouyinTagSyncResult
from app.services.douyin_tags import build_tag_public_rows, sync_tag_history

router = APIRouter(prefix="/douyin/tags", tags=["douyin-tags"])


@router.get("/", response_model=DouyinTagsPublic)
def list_tags(
    session: SessionDep,
    current_user: CurrentUser,
    search: str | None = Query(default=None, max_length=100),
    task_id: uuid.UUID | None = None,
    sort_by: Literal["name", "aweme_count", "task_count", "last_seen_at"] = "aweme_count",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    if task_id:
        task = session.get(CrawlTask, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="抖音任务不存在")
        if task.owner_id != current_user.id and not current_user.is_superuser:
            raise HTTPException(status_code=403, detail="Not enough permissions")
    owner_id = current_user.id
    rows = build_tag_public_rows(
        session,
        owner_id=owner_id,
        task_id=task_id,
        search=search,
    )

    def sort_key(item: DouyinTagPublic) -> str | int | float:
        if sort_by == "name":
            return item.name.casefold()
        if sort_by == "task_count":
            return item.task_count
        if sort_by == "last_seen_at":
            return item.last_seen_at.timestamp()
        return item.aweme_count

    rows.sort(key=sort_key, reverse=sort_order == "desc")
    return DouyinTagsPublic(data=rows[skip : skip + limit], count=len(rows))


@router.post("/sync", response_model=DouyinTagSyncResult)
def sync_tags(session: SessionDep, current_user: CurrentUser) -> Any:
    return sync_tag_history(session, owner_id=current_user.id)
