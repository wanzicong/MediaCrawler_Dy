"""抖音接口请求日志路由：按用户维度分页查询爬取过程中的抖音接口调用记录。"""

import uuid
from datetime import datetime
from typing import Any

from crawler.api.deps import CurrentUser, SessionDep
from crawler.business.douyin.request_logs import query_service
from crawler.business.douyin.request_logs.models import DouyinRequestLogsPublic
from fastapi import APIRouter, Query

router = APIRouter(tags=["douyin-request-logs"])


@router.get("/request-logs", response_model=DouyinRequestLogsPublic)
def list_request_logs(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID | None = None,
    method: str | None = Query(default=None, max_length=16),
    path: str | None = Query(default=None, max_length=500),
    response_status: int | None = Query(default=None, ge=100, le=599),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    """分页查询当前用户的抖音请求日志，支持按任务、方法、路径、状态码与时间范围过滤。"""
    return query_service.list_request_logs(
        session,
        owner_id=current_user.id,
        task_id=task_id,
        method=method,
        path=path,
        response_status=response_status,
        created_from=created_from,
        created_to=created_to,
        skip=skip,
        limit=limit,
    )


__all__ = ["router"]
