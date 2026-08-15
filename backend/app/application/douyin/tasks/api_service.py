"""Task commands exposed to HTTP and MCP inbound adapters."""

from __future__ import annotations

import uuid

from sqlmodel import Session

from app.application.douyin.tasks.query_service import (
    get_task_public,
    require_task_access,
)
from app.application.douyin.tasks.service import TaskResumeError, task_manager
from app.application.errors import ConflictError, InvalidRequestError
from app.domain.common.models import Message
from app.domain.douyin.tasks.models import (
    CrawlTaskCreate,
    CrawlTaskPublic,
    CrawlTaskResumeRequest,
    CrawlTaskStatus,
)


async def create_task(
    session: Session, *, owner_id: uuid.UUID, request: CrawlTaskCreate
) -> CrawlTaskPublic:
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
    require_task_access(session, task_id=task_id, owner_id=owner_id)
    try:
        task = await task_manager.resume(task_id=task_id, options=options)
    except TaskResumeError as exc:
        raise ConflictError(str(exc)) from exc
    return get_task_public(session, task_id=task.id, owner_id=owner_id)


__all__ = ["cancel_task", "create_task", "resume_task"]
