"""Read-side queries and ownership checks for Douyin media assets."""

from __future__ import annotations

import uuid

from sqlmodel import Session

from app.application.douyin.media.pipeline import list_media_sync, media_summary_sync
from app.application.douyin.tasks.query_service import require_task_access
from app.application.errors import ResourceNotFoundError
from app.domain.douyin.media.models import (
    DouyinMediaAsset,
    DouyinMediaAssetsPublic,
    DouyinMediaSummaryPublic,
)


def require_media_asset_access(
    session: Session,
    *,
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> DouyinMediaAsset:
    require_task_access(session, task_id=task_id, owner_id=owner_id)
    asset = session.get(DouyinMediaAsset, asset_id)
    if asset is None or asset.task_id != task_id:
        raise ResourceNotFoundError("Douyin media asset not found")
    return asset


def list_task_media(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID | None,
    skip: int,
    limit: int,
) -> DouyinMediaAssetsPublic:
    require_task_access(session, task_id=task_id, owner_id=owner_id)
    return list_media_sync(task_id, skip, limit)


def get_task_media_summary(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> DouyinMediaSummaryPublic:
    require_task_access(session, task_id=task_id, owner_id=owner_id)
    return media_summary_sync(task_id)


__all__ = [
    "get_task_media_summary",
    "list_task_media",
    "require_media_asset_access",
]
