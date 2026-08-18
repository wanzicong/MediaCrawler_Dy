"""任务产出文件（如扫码登录二维码）的下载准备与交付描述。"""

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
    """待交付文件的路径与响应元信息。"""

    path: Path  # 文件在服务器上的路径
    media_type: str  # 响应 Content-Type
    headers: dict[str, str] = field(default_factory=dict)  # 附加响应头


def prepare_qrcode_delivery(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> TaskFileDelivery:
    """准备任务登录二维码图片的下载交付（含归属校验，禁缓存）。

    参数：session 数据库会话；task_id 任务 ID；owner_id 归属用户 ID。
    返回：二维码文件交付描述。
    异常：ConflictError —— 任务当前不在等待登录状态；
          ResourceNotFoundError —— 二维码文件不存在。
    """
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
