"""「我的」路由：账号维度的关注 / 点赞 / 收藏查询与概览。"""

import uuid
from typing import Any, Literal

from crawler.api.deps import CurrentUser, SessionDep
from crawler.business.douyin.mine.models import (
    DouyinAccountAwemesPublic,
    DouyinFollowingsPublic,
    DouyinMineSummaryPublic,
)
from crawler.business.douyin.mine.service import (
    list_account_awemes,
    list_followings,
    mine_summary,
)
from crawler.business.errors import (
    InvalidRequestError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/my", tags=["douyin-mine"])


def _raise_http_error(exc: Exception) -> None:
    """把业务层异常映射为 404/403/422。"""
    if isinstance(exc, ResourceNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PermissionDeniedError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, InvalidRequestError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.get("/summary", response_model=DouyinMineSummaryPublic)
def get_mine_summary(
    session: SessionDep,
    current_user: CurrentUser,
    account_id: uuid.UUID,
) -> Any:
    """某账号的关注 / 点赞 / 收藏计数与最近采集时间。"""
    try:
        return mine_summary(session, owner_id=current_user.id, account_id=account_id)
    except (ResourceNotFoundError, PermissionDeniedError, InvalidRequestError) as exc:
        _raise_http_error(exc)


@router.get("/followings", response_model=DouyinFollowingsPublic)
def get_mine_followings(
    session: SessionDep,
    current_user: CurrentUser,
    account_id: uuid.UUID,
    search: str | None = Query(default=None, max_length=100),
    sort_by: Literal["fetched_at", "follower_count", "nickname"] = "fetched_at",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    """查询某账号的关注博主列表（支持搜索、排序与分页）。"""
    try:
        return list_followings(
            session,
            owner_id=current_user.id,
            account_id=account_id,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=skip,
            limit=limit,
        )
    except (ResourceNotFoundError, PermissionDeniedError, InvalidRequestError) as exc:
        _raise_http_error(exc)


@router.get("/awemes", response_model=DouyinAccountAwemesPublic)
def get_mine_awemes(
    session: SessionDep,
    current_user: CurrentUser,
    account_id: uuid.UUID,
    kind: Literal["liked", "collected"] = "liked",
    search: str | None = Query(default=None, max_length=100),
    sort_by: Literal["fetched_at", "liked_count", "published_at"] = "fetched_at",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    """查询某账号的点赞（kind=liked）或收藏（kind=collected）作品列表。"""
    try:
        return list_account_awemes(
            session,
            owner_id=current_user.id,
            account_id=account_id,
            kind=kind,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=skip,
            limit=limit,
        )
    except (ResourceNotFoundError, PermissionDeniedError, InvalidRequestError) as exc:
        _raise_http_error(exc)


__all__ = ["router"]
