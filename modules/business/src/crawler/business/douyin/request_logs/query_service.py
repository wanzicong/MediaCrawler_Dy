"""抖音接口请求日志的读侧应用服务：按用户维度分页查询。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from crawler.business.douyin.request_logs.models import (
    DouyinRequestLog,
    DouyinRequestLogPublic,
    DouyinRequestLogsPublic,
)
from crawler.business.douyin.request_logs.service import (
    sanitize_failure_detail,
    sanitize_mapping,
    sanitize_url,
)
from sqlmodel import Session, col, func, select


def list_request_logs(
    session: Session,
    *,
    owner_id: uuid.UUID,
    task_id: uuid.UUID | None,
    method: str | None,
    path: str | None,
    response_status: int | None,
    created_from: datetime | None,
    created_to: datetime | None,
    skip: int,
    limit: int,
) -> DouyinRequestLogsPublic:
    """分页查询当前用户的抖音请求日志，支持任务/方法/路径/状态/时间范围过滤。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 ID。
        task_id: 按任务过滤；None 表示不过滤。
        method: 按 HTTP 方法过滤；None 表示不过滤。
        path: 按路径包含过滤；None 表示不过滤。
        response_status: 按响应状态码过滤；None 表示不过滤。
        created_from: 记录时间下界（含）；None 表示不过滤。
        created_to: 记录时间上界（含）；None 表示不过滤。
        skip: 分页偏移量。
        limit: 分页大小。

    返回：
        请求日志分页列表（按记录时间倒序）。
    """
    filters: list[Any] = [DouyinRequestLog.owner_id == owner_id]
    if task_id is not None:
        filters.append(DouyinRequestLog.task_id == task_id)
    if method is not None:
        filters.append(DouyinRequestLog.method == method.upper())
    if path is not None:
        filters.append(col(DouyinRequestLog.path).contains(path))
    if response_status is not None:
        filters.append(DouyinRequestLog.response_status == response_status)
    if created_from is not None:
        filters.append(DouyinRequestLog.created_at >= created_from)
    if created_to is not None:
        filters.append(DouyinRequestLog.created_at <= created_to)
    count = session.exec(
        select(func.count()).select_from(DouyinRequestLog).where(*filters)
    ).one()
    rows = session.exec(
        select(DouyinRequestLog)
        .where(*filters)
        .order_by(col(DouyinRequestLog.created_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return DouyinRequestLogsPublic(
        data=[
            DouyinRequestLogPublic(
                id=row.id,
                task_id=row.task_id,
                method=row.method,
                path=row.path,
                url=sanitize_url(row.url),
                query_params=sanitize_mapping(row.query_params) or {},
                request_headers=sanitize_mapping(row.request_headers) or {},
                request_body=sanitize_mapping(row.request_body),
                response_status=row.response_status,
                duration_ms=row.duration_ms,
                error=row.error,
                failure_detail=sanitize_failure_detail(row.failure_detail),
                created_at=row.created_at,
            )
            for row in rows
        ],
        count=count,
    )


__all__ = ["list_request_logs"]
