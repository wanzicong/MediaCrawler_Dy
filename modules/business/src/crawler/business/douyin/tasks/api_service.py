"""面向 HTTP 与 MCP 入站适配器的任务命令服务（创建/取消/恢复爬取任务）。"""

from __future__ import annotations

import uuid

from crawler.business.common.models import Message
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskBulkDeleteRequest,
    CrawlTaskBulkResumePublic,
    CrawlTaskBulkResumeRequest,
    CrawlTaskCreate,
    CrawlTaskPublic,
    CrawlTaskResumeFailure,
    CrawlTaskResumeRequest,
    CrawlTaskStatus,
)
from crawler.business.douyin.tasks.query_service import (
    get_task_public,
    require_task_access,
)
from crawler.business.douyin.tasks.service import TaskResumeError, task_manager
from crawler.business.errors import (
    ConflictError,
    InvalidRequestError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from sqlmodel import Session, col, select

DELETABLE_TASK_STATUSES = frozenset(
    {
        CrawlTaskStatus.failed.value,
        CrawlTaskStatus.cancelled.value,
        CrawlTaskStatus.interrupted.value,
    }
)


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


async def bulk_resume_tasks(
    session: Session,
    *,
    request: CrawlTaskBulkResumeRequest,
    owner_id: uuid.UUID | None,
) -> CrawlTaskBulkResumePublic:
    """批量受理失效任务的断点恢复，并统一覆盖任务间隔配置。

    单个任务失败只记录到 failures，不阻断同批次其余任务；真正的执行顺序和
    任务完成后的冷却由任务管理器的全局闸门保证。
    """
    accepted: list[CrawlTaskPublic] = []
    failures: list[CrawlTaskResumeFailure] = []
    options = CrawlTaskResumeRequest(
        task_interval_seconds=request.task_interval_seconds
    )
    for task_id in dict.fromkeys(request.ids):
        try:
            accepted.append(
                await resume_task(
                    session,
                    task_id=task_id,
                    owner_id=owner_id,
                    options=options,
                )
            )
        except (
            ConflictError,
            InvalidRequestError,
            ResourceNotFoundError,
            PermissionDeniedError,
        ) as exc:
            failures.append(CrawlTaskResumeFailure(task_id=task_id, error=str(exc)))
    return CrawlTaskBulkResumePublic(
        data=accepted,
        count=len(accepted),
        failures=failures,
        failed_count=len(failures),
    )


async def restart_task(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> CrawlTaskPublic:
    """重新运行已失败/中断/已取消的任务（清空断点、从头开始采集）。

    参数：session 数据库会话；task_id 任务 ID；owner_id 归属用户 ID（None 表示不校验归属）。
    返回：重启后的任务展示模型。
    异常：ConflictError —— 任务仍在运行、不存在或状态不允许重启。
    """
    require_task_access(session, task_id=task_id, owner_id=owner_id)
    try:
        task = await task_manager.restart(task_id=task_id)
    except TaskResumeError as exc:
        raise ConflictError(str(exc)) from exc
    return get_task_public(session, task_id=task.id, owner_id=owner_id)


def _require_deletable_task(task: CrawlTask) -> None:
    """仅允许删除已结束且不可继续执行的任务，防止误删运行中的任务。"""
    if task.status not in DELETABLE_TASK_STATUSES:
        raise ConflictError("只能删除失败、已取消或已中断的任务")


def delete_task(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> Message:
    """删除一条失效任务及其级联的任务结果记录。"""
    task = require_task_access(session, task_id=task_id, owner_id=owner_id)
    _require_deletable_task(task)
    session.delete(task)
    session.commit()
    return Message(message="失效任务已删除")


def bulk_delete_tasks(
    session: Session,
    *,
    request: CrawlTaskBulkDeleteRequest,
    owner_id: uuid.UUID | None,
) -> Message:
    """批量删除当前用户选中的失效任务，运行中任务整体拒绝删除。"""
    statement = select(CrawlTask).where(col(CrawlTask.id).in_(set(request.ids)))
    if owner_id is not None:
        statement = statement.where(col(CrawlTask.owner_id) == owner_id)
    tasks = session.exec(statement).all()
    for task in tasks:
        _require_deletable_task(task)
    for task in tasks:
        session.delete(task)
    session.commit()
    return Message(message=f"已删除 {len(tasks)} 个失效任务")


__all__ = [
    "DELETABLE_TASK_STATUSES",
    "bulk_delete_tasks",
    "bulk_resume_tasks",
    "cancel_task",
    "create_task",
    "delete_task",
    "resume_task",
    "restart_task",
]
