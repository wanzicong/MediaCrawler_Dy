"""抖音媒体资产的读侧查询与访问归属校验。"""

from __future__ import annotations

import uuid

from crawler.business.douyin.media.models import (
    DouyinMediaAsset,
    DouyinMediaAssetsPublic,
    DouyinMediaSummaryPublic,
)
from crawler.business.douyin.media.pipeline import list_media_sync, media_summary_sync
from crawler.business.douyin.tasks.query_service import require_task_access
from crawler.business.errors import ResourceNotFoundError
from sqlmodel import Session


def require_media_asset_access(
    session: Session,
    *,
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> DouyinMediaAsset:
    """校验任务归属并取出任务下的媒体资产。

    参数：
        session: 数据库会话。
        task_id: 采集任务 ID。
        asset_id: 媒体资产 ID。
        owner_id: 当前用户 ID，用于归属校验。

    返回：
        校验通过的媒体资产记录。

    异常：
        ResourceNotFoundError: 任务无权访问、资产不存在或不属于该任务。
    """
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
    """分页列出任务下的媒体资产（含字幕），按处理活跃度优先排序。

    参数：
        session: 数据库会话。
        task_id: 采集任务 ID。
        owner_id: 当前用户 ID，用于归属校验。
        skip: 分页偏移量。
        limit: 每页条数。

    返回：
        资产列表与总数。
    """
    require_task_access(session, task_id=task_id, owner_id=owner_id)
    return list_media_sync(task_id, skip, limit)


def get_task_media_summary(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> DouyinMediaSummaryPublic:
    """统计任务下媒体下载、字幕转写与迁移各状态的数量。

    参数：
        session: 数据库会话。
        task_id: 采集任务 ID。
        owner_id: 当前用户 ID，用于归属校验。

    返回：
        各状态计数汇总。
    """
    require_task_access(session, task_id=task_id, owner_id=owner_id)
    return media_summary_sync(task_id)


__all__ = [
    "get_task_media_summary",
    "list_task_media",
    "require_media_asset_access",
]
