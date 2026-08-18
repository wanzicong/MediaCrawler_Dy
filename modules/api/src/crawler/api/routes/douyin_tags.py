"""抖音标签路由：作品标签查询与历史数据同步。"""

import uuid
from typing import Any, Literal

from crawler.api.deps import CurrentUser, SessionDep
from crawler.business.douyin.tags.models import (
    DouyinTagsPublic,
    DouyinTagSyncResult,
)
from crawler.business.douyin.tags.service import list_tags_for_actor, sync_tag_history
from crawler.business.errors import (
    InvalidRequestError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from fastapi import APIRouter, HTTPException, Query

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
    """分页查询当前用户可见的作品标签，支持搜索、任务、赛道过滤与排序。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        search: 按标签名搜索。
        task_id: 按来源任务过滤。
        track_id: 按赛道过滤。
        sort_by: 排序字段（名称/作品数/任务数/最近出现时间）。
        sort_order: 排序方向。
        skip: 分页偏移量。
        limit: 每页数量。

    返回：
        标签分页结果。

    异常：
        HTTPException: 资源不存在（404）、无权访问（403）或参数不合法（422）。
    """
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
    """从当前用户的历史作品数据中同步提取标签入库。

    返回：
        标签同步结果。
    """
    return sync_tag_history(session, owner_id=current_user.id)
