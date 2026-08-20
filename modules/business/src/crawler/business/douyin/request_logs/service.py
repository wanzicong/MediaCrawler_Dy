"""抖音接口请求日志的写侧应用服务：落盘调用记录、按任务解析归属用户。"""

from __future__ import annotations

import asyncio
import uuid

from crawler.bootstrap.database import engine
from crawler.business.douyin.request_logs.models import DouyinRequestLog
from crawler.business.douyin.tasks.models import CrawlTask
from crawler.douyin_client.client import (
    DouyinClient,
    DouyinRequestLogEntry,
    RequestLogCallback,
)
from sqlmodel import Session, select


def record_sync(
    owner_id: uuid.UUID,
    task_id: uuid.UUID | None,
    entry: DouyinRequestLogEntry,
) -> None:
    """同步落盘一条抖音请求日志（在 asyncio.to_thread 线程池中执行）。

    参数：
        owner_id: 归属用户 ID。
        task_id: 关联采集任务 ID；登录校验等非任务请求为 None。
        entry: 客户端记录的请求快照。
    """
    with Session(engine) as session:
        session.add(
            DouyinRequestLog(
                owner_id=owner_id,
                task_id=task_id,
                method=entry.method,
                path=entry.path,
                url=entry.url,
                query_params=entry.query_params,
                request_headers=entry.request_headers,
                request_body=entry.request_body,
                response_status=entry.response_status,
                duration_ms=entry.duration_ms,
                error=entry.error,
            )
        )
        session.commit()


async def record(
    owner_id: uuid.UUID,
    task_id: uuid.UUID | None,
    entry: DouyinRequestLogEntry,
) -> None:
    """异步落盘一条抖音请求日志（内部转线程池执行）。"""
    await asyncio.to_thread(record_sync, owner_id, task_id, entry)


def load_task_owner_sync(task_id: uuid.UUID) -> uuid.UUID | None:
    """同步查询任务归属用户（在 asyncio.to_thread 线程池中执行）。"""
    with Session(engine) as session:
        return session.exec(
            select(CrawlTask.owner_id).where(CrawlTask.id == task_id)
        ).first()


async def load_task_owner(task_id: uuid.UUID) -> uuid.UUID | None:
    """查询任务的归属用户；任务不存在时返回 None。"""
    return await asyncio.to_thread(load_task_owner_sync, task_id)


def build_request_logger(
    owner_id: uuid.UUID, task_id: uuid.UUID
) -> RequestLogCallback:
    """构造绑定任务上下文的抖音请求日志回调，供 DouyinClient.request_logger 使用。"""

    async def logger(
        _client: DouyinClient, entry: DouyinRequestLogEntry
    ) -> None:
        await record(owner_id, task_id, entry)

    return logger


__all__ = [
    "build_request_logger",
    "load_task_owner",
    "load_task_owner_sync",
    "record",
    "record_sync",
]
