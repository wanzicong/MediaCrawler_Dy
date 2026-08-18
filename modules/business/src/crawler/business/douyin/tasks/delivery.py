"""Task-owned file delivery preparation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from crawler.business.douyin.tasks.models import CrawlTaskStatus
from crawler.business.douyin.tasks.query_service import require_task_access
from crawler.business.errors import ConflictError, ResourceNotFoundError
from sqlmodel import Session


@dataclass(frozen=True)
class TaskFileDelivery:
    path: Path
    media_type: str
    headers: dict[str, str] = field(default_factory=dict)


def prepare_qrcode_delivery(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> TaskFileDelivery:
    task = require_task_access(session, task_id=task_id, owner_id=owner_id)
    if task.status != CrawlTaskStatus.waiting_login.value:
        raise ConflictError("Task is not waiting for login")
    path = Path(task.qrcode_path or "")
    if not task.qrcode_path or not path.is_file():
        raise ResourceNotFoundError("QR code is not available")
    return TaskFileDelivery(
        path=path,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


__all__ = ["TaskFileDelivery", "prepare_qrcode_delivery"]
