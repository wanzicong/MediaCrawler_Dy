"""面向 HTTP 与 MCP 入站适配器的任务命令服务（创建/取消/恢复爬取任务）。"""

from __future__ import annotations

import uuid

from crawler.business.common.models import Message
from crawler.business.douyin.tasks.models import (
    CrawlTaskCreate,
    CrawlTaskPublic,
    CrawlTaskResumeRequest,
    CrawlTaskStatus,
)
from crawler.business.douyin.tasks.query_service import (
    get_task_public,
    require_task_access,
)
from crawler.business.douyin.tasks.service import TaskResumeError, task_manager
from crawler.business.errors import ConflictError, InvalidRequestError
from sqlmodel import Session


async def create_task(
    session: Session, *, owner_id: uuid.UUID, request: CrawlTaskCreate
) -> CrawlTaskPublic:
    """创建并启动一个抖音爬取任务。

    参数：session 数据库会话；owner_id 任务归属用户 ID；request 任务创建请求。
    返回：创建后的任务展示模型。
    异常：InvalidRequestError —— 请求参数超出服务端限制或账号配置不合法。
    """
    try:
        task = await task_manager.create(owner_id=owner_id, request=request)
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc
    return get_task_public(session, task_id=task.id, owner_id=owner_id)


async def cancel_task(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> Message:
    """取消当前进程内正在运行的任务。

    参数：session 数据库会话；task_id 任务 ID；owner_id 归属用户 ID（None 表示不校验归属）。
    返回：取消结果消息。
    异常：ResourceNotFoundError/PermissionDeniedError —— 任务不存在或无权访问；
          ConflictError —— 任务已结束或不在当前进程运行。
    """
    task = require_task_access(session, task_id=task_id, owner_id=owner_id)
    if task.status in {
        CrawlTaskStatus.succeeded.value,
        CrawlTaskStatus.failed.value,
        CrawlTaskStatus.cancelled.value,
        CrawlTaskStatus.interrupted.value,
    }:
        raise ConflictError("Task is already finished")
    if not await task_manager.cancel(task_id):
        raise ConflictError("Task is not running in this process")
    return Message(message="Douyin task cancelled")


async def resume_task(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID | None,
    options: CrawlTaskResumeRequest,
) -> CrawlTaskPublic:
    """恢复已终止的任务（按请求恢复爬取阶段和/或媒体处理阶段）。

    参数：session 数据库会话；task_id 任务 ID；owner_id 归属用户 ID；options 恢复选项。
    返回：恢复后的任务展示模型。
    异常：ConflictError —— 任务仍在运行或没有可恢复的阶段。
    """
    require_task_access(session, task_id=task_id, owner_id=owner_id)
    try:
        task = await task_manager.resume(task_id=task_id, options=options)
    except TaskResumeError as exc:
        raise ConflictError(str(exc)) from exc
    return get_task_public(session, task_id=task.id, owner_id=owner_id)


__all__ = ["cancel_task", "create_task", "resume_task"]
