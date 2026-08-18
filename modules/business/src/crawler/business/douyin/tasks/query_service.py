"""抖音爬取任务的读侧查询与归属校验（任务详情、分页列表、分片列表）。"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from crawler.business.douyin.accounts.models import DouyinAccount
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskPublic,
    CrawlTaskShard,
    CrawlTaskShardPublic,
    CrawlTaskShardsPublic,
    CrawlTasksPublic,
)
from crawler.business.douyin.tasks.persistence import task_public_values
from crawler.business.douyin.tracks.models import DouyinTrack
from crawler.business.errors import PermissionDeniedError, ResourceNotFoundError
from sqlalchemy import select as sa_select
from sqlmodel import Session, col, func, select


@dataclass(frozen=True, slots=True)
class _TaskDisplayIdentity:
    """任务在列表页展示用的代表性作品信息。"""

    title: str | None  # 代表作品标题（取作品标题，缺省回退到描述）
    author: str | None  # 代表作品作者昵称
    aweme_id: str | None  # 代表作品 aweme_id


def _normalized_optional_text(value: str) -> str | None:
    """去除首尾空白，空串归一化为 None。"""
    normalized = value.strip()
    return normalized or None


def _representative_awemes_by_task(
    session: Session,
    task_ids: list[uuid.UUID],
) -> dict[uuid.UUID, _TaskDisplayIdentity]:
    """用一次查询为每个任务取一条稳定的代表性作品（按发布时间、入库时间倒序取第一条）。

    参数：session 数据库会话；task_ids 任务 ID 列表。
    返回：task_id -> 代表作品展示信息 的映射。
    """
    if not task_ids:
        return {}

    task_id_column = col(DouyinAweme.task_id)
    title_column = col(DouyinAweme.title)
    description_column = col(DouyinAweme.description)
    nickname_column = col(DouyinAweme.nickname)
    aweme_id_column = col(DouyinAweme.aweme_id)
    row_number = (
        func.row_number()
        .over(
            partition_by=task_id_column,
            order_by=(
                func.coalesce(col(DouyinAweme.create_time), -1).desc(),
                col(DouyinAweme.fetched_at).desc(),
                aweme_id_column,
                col(DouyinAweme.id),
            ),
        )
        .label("representative_rank")
    )
    ranked_awemes = (
        sa_select(
            task_id_column.label("task_id"),
            title_column.label("title"),
            description_column.label("description"),
            nickname_column.label("nickname"),
            aweme_id_column.label("aweme_id"),
            row_number,
        )
        .where(task_id_column.in_(set(task_ids)))
        .subquery()
    )
    rows = session.execute(
        sa_select(
            ranked_awemes.c.task_id,
            ranked_awemes.c.title,
            ranked_awemes.c.description,
            ranked_awemes.c.nickname,
            ranked_awemes.c.aweme_id,
        ).where(ranked_awemes.c.representative_rank == 1)
    ).all()

    identities: dict[uuid.UUID, _TaskDisplayIdentity] = {}
    for task_id, title, description, nickname, aweme_id in rows:
        identities[task_id] = _TaskDisplayIdentity(
            title=_normalized_optional_text(title)
            or _normalized_optional_text(description),
            author=_normalized_optional_text(nickname),
            aweme_id=_normalized_optional_text(aweme_id),
        )
    return identities


def _task_public(
    task: CrawlTask,
    identity: _TaskDisplayIdentity | None,
    track: DouyinTrack,
) -> CrawlTaskPublic:
    """由任务实体、代表作品与赛道组装单个任务展示模型。"""
    return CrawlTaskPublic(
        **task_public_values(task),
        track_id=track.id,
        track_name=track.name,
        track_is_default=track.is_default,
        display_title=identity.title if identity else None,
        display_author=identity.author if identity else None,
        display_aweme_id=identity.aweme_id if identity else None,
    )


def require_task_access(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> CrawlTask:
    """读取任务并校验存在性与归属（owner_id 为 None 时跳过归属校验）。

    返回：任务实体。
    异常：ResourceNotFoundError —— 任务不存在；PermissionDeniedError —— 无权访问。
    """
    task = session.get(CrawlTask, task_id)
    if task is None:
        raise ResourceNotFoundError("Douyin task not found")
    if owner_id is not None and task.owner_id != owner_id:
        raise PermissionDeniedError("Not enough permissions")
    return task


def get_task_public(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> CrawlTaskPublic:
    """获取单个任务的对外展示模型（含归属校验）。"""
    task = require_task_access(session, task_id=task_id, owner_id=owner_id)
    return build_tasks_public(session, tasks=[task])[0]


def build_tasks_public(
    session: Session, *, tasks: list[CrawlTask]
) -> list[CrawlTaskPublic]:
    """批量组装任务展示模型（补全赛道信息与代表性作品）。

    参数：session 数据库会话；tasks 任务实体列表。
    返回：与输入顺序一致的任务展示模型列表。
    异常：ResourceNotFoundError —— 任务缺少赛道归属或关联的赛道不存在。
    """
    if not tasks:
        return []
    if any(task.track_id is None for task in tasks):
        raise ResourceNotFoundError("任务缺少赛道归属，请先执行数据迁移")
    identities = _representative_awemes_by_task(session, [task.id for task in tasks])
    tracks = {
        item.id: item
        for item in session.exec(
            select(DouyinTrack).where(
                col(DouyinTrack.id).in_(
                    {task.track_id for task in tasks if task.track_id is not None}
                )
            )
        ).all()
    }
    missing = {task.track_id for task in tasks} - tracks.keys()
    if missing:
        raise ResourceNotFoundError("任务关联的赛道不存在")
    output: list[CrawlTaskPublic] = []
    for task in tasks:
        assert task.track_id is not None
        output.append(
            _task_public(task, identities.get(task.id), tracks[task.track_id])
        )
    return output


def list_tasks(
    session: Session,
    *,
    owner_id: uuid.UUID | None,
    skip: int,
    limit: int,
    track_id: uuid.UUID | None = None,
) -> CrawlTasksPublic:
    """按归属（可选按赛道过滤）分页查询任务列表，按创建时间倒序。

    参数：session 数据库会话；owner_id 归属用户 ID（None 表示不过滤）；skip/limit 分页参数；
          track_id 可选的赛道过滤。
    返回：任务分页列表。
    异常：ResourceNotFoundError —— 指定赛道不存在或无权访问。
    """
    filters = [] if owner_id is None else [CrawlTask.owner_id == owner_id]
    if track_id is not None:
        track = session.get(DouyinTrack, track_id)
        if track is None or (owner_id is not None and track.owner_id != owner_id):
            raise ResourceNotFoundError("赛道不存在或无权访问")
        filters.append(CrawlTask.track_id == track_id)
    count = session.exec(
        select(func.count()).select_from(CrawlTask).where(*filters)
    ).one()
    tasks = session.exec(
        select(CrawlTask)
        .where(*filters)
        .order_by(col(CrawlTask.created_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return CrawlTasksPublic(
        data=build_tasks_public(session, tasks=list(tasks)),
        count=count,
    )


def list_task_shards(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> CrawlTaskShardsPublic:
    """查询任务的全部分片（按分片序号排序，附带账号名称；含归属校验）。"""
    require_task_access(session, task_id=task_id, owner_id=owner_id)
    rows = session.exec(
        select(CrawlTaskShard, DouyinAccount.name)
        .outerjoin(
            DouyinAccount,
            col(DouyinAccount.id) == col(CrawlTaskShard.account_id),
        )
        .where(CrawlTaskShard.task_id == task_id)
        .order_by(col(CrawlTaskShard.shard_index))
    ).all()
    data: list[CrawlTaskShardPublic] = []
    for shard, account_name in rows:
        try:
            request = json.loads(shard.request_json)
        except json.JSONDecodeError:
            request = {}
        data.append(
            CrawlTaskShardPublic(
                id=shard.id,
                task_id=shard.task_id,
                account_id=shard.account_id,
                account_name=account_name,
                shard_index=shard.shard_index,
                status=shard.status,
                request=request if isinstance(request, dict) else {},
                aweme_count=shard.aweme_count,
                comment_count=shard.comment_count,
                error=shard.error,
                started_at=shard.started_at,
                finished_at=shard.finished_at,
                created_at=shard.created_at,
            )
        )
    return CrawlTaskShardsPublic(data=data, count=len(data))


__all__ = [
    "build_tasks_public",
    "get_task_public",
    "list_task_shards",
    "list_tasks",
    "require_task_access",
]
