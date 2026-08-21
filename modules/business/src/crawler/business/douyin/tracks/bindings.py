"""抖音赛道的归属解析与遗留关联表的兼容绑定。

负责默认赛道的惰性创建、赛道归属校验，以及把 keyword.track_id /
task.track_id 的归属关系同步到遗留的关联表，保证两侧数据一致。
"""

from __future__ import annotations

import uuid

from crawler.business.douyin.keywords.models import DouyinKeyword
from crawler.business.douyin.tasks.models import CrawlTask
from crawler.business.douyin.tracks.models import (
    DouyinTrack,
    DouyinTrackKeywordLink,
    DouyinTrackTaskLink,
)
from crawler.business.identity.models import User
from sqlmodel import Session, col, select

DEFAULT_TRACK_NAME = "默认赛道"
DEFAULT_TRACK_NORMALIZED_NAME = DEFAULT_TRACK_NAME.casefold()


def ensure_default_track(session: Session, *, owner_id: uuid.UUID) -> DouyinTrack:
    """返回用户的兜底默认赛道，不存在时创建。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 ID。

    返回：
        该用户的默认赛道（保证存在且处于启用状态）。

    异常：
        ValueError: 用户不存在时抛出。
    """
    # 通过对用户主表行加排他锁串行化首次并发请求，
    # 避免调用方需要重试失败的外层事务。
    owner = session.exec(
        select(User).where(User.id == owner_id).with_for_update()
    ).first()
    if owner is None:
        raise ValueError("用户不存在，无法创建默认赛道")
    track = session.exec(
        select(DouyinTrack).where(
            DouyinTrack.owner_id == owner_id,
            col(DouyinTrack.is_default).is_(True),
        )
    ).first()
    if track is not None:
        if not track.enabled:
            track.enabled = True
            session.add(track)
            session.flush()
        return track

    # 若用户已手工创建同名赛道，则直接复用为默认赛道，
    # 避免升级时制造名称冲突的记录。
    track = session.exec(
        select(DouyinTrack).where(
            DouyinTrack.owner_id == owner_id,
            DouyinTrack.normalized_name == DEFAULT_TRACK_NORMALIZED_NAME,
        )
    ).first()
    if track is None:
        track = DouyinTrack(
            owner_id=owner_id,
            name=DEFAULT_TRACK_NAME,
            normalized_name=DEFAULT_TRACK_NORMALIZED_NAME,
            description="未选择赛道时，关键词、任务和内容会自动归入这里。",
            enabled=True,
            is_default=True,
        )
        session.add(track)
    else:
        track.is_default = True
        track.enabled = True
        session.add(track)
    session.flush()
    return track


def resolve_track(
    session: Session,
    *,
    owner_id: uuid.UUID,
    track_id: uuid.UUID | None,
    require_enabled: bool = True,
) -> DouyinTrack:
    """解析并校验赛道归属；track_id 为空时回落到默认赛道。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 ID。
        track_id: 目标赛道 ID；None 表示使用默认赛道。
        require_enabled: 是否要求赛道处于启用状态。

    返回：
        归属校验通过的赛道实体。

    异常：
        ValueError: 赛道不存在、无权访问或已停用时抛出。
    """
    track = (
        ensure_default_track(session, owner_id=owner_id)
        if track_id is None
        else session.get(DouyinTrack, track_id)
    )
    if track is None or track.owner_id != owner_id:
        raise ValueError("赛道不存在或无权访问")
    if require_enabled and not track.enabled:
        raise ValueError("赛道已停用，不能创建关键词或任务")
    return track


def sync_keyword_link(
    session: Session, *, keyword: DouyinKeyword, track: DouyinTrack
) -> None:
    """让遗留关联表与 keyword.track_id 保持精确镜像。"""
    links = session.exec(
        select(DouyinTrackKeywordLink).where(
            DouyinTrackKeywordLink.keyword_id == keyword.id
        )
    ).all()
    matched = False
    deleted = False
    for link in links:
        if link.track_id == track.id and not matched:
            matched = True
        else:
            session.delete(link)
            deleted = True
    if deleted:
        session.flush()
    if not matched:
        session.add(DouyinTrackKeywordLink(track_id=track.id, keyword_id=keyword.id))


def assign_keyword_track(
    session: Session, *, keyword: DouyinKeyword, track: DouyinTrack
) -> None:
    """把关键词归属到指定赛道，并同步遗留关联表。

    异常：
        ValueError: 关键词与赛道不属于同一用户时抛出。
    """
    if keyword.owner_id != track.owner_id:
        raise ValueError("关键词和赛道不属于同一用户")
    if keyword.category:
        matched_category = next(
            (
                category
                for category in track.keyword_categories
                if category.casefold() == keyword.category.casefold()
            ),
            None,
        )
        keyword.category = matched_category or ""
    keyword.track_id = track.id
    session.add(keyword)
    sync_keyword_link(session, keyword=keyword, track=track)
    session.flush()


def sync_task_link(session: Session, *, task: CrawlTask, track: DouyinTrack) -> None:
    """让遗留关联表与 task.track_id 保持精确镜像。"""
    links = session.exec(
        select(DouyinTrackTaskLink).where(DouyinTrackTaskLink.task_id == task.id)
    ).all()
    matched = False
    deleted = False
    for link in links:
        if link.track_id == track.id and not matched:
            matched = True
        else:
            session.delete(link)
            deleted = True
    if deleted:
        session.flush()
    if not matched:
        session.add(DouyinTrackTaskLink(track_id=track.id, task_id=task.id))


def assign_task_track(session: Session, *, task: CrawlTask, track: DouyinTrack) -> None:
    """把采集任务归属到指定赛道，并同步遗留关联表。

    异常：
        ValueError: 任务与赛道不属于同一用户时抛出。
    """
    if task.owner_id != track.owner_id:
        raise ValueError("任务和赛道不属于同一用户")
    task.track_id = track.id
    session.add(task)
    sync_task_link(session, task=task, track=track)
    session.flush()


def require_owned_track(
    session: Session, *, owner_id: uuid.UUID, track_id: uuid.UUID
) -> DouyinTrack:
    """加载并校验归属的赛道（不要求启用状态），失败抛出 ValueError。"""
    return resolve_track(
        session,
        owner_id=owner_id,
        track_id=track_id,
        require_enabled=False,
    )


def load_tracks_by_id(
    session: Session, track_ids: list[uuid.UUID]
) -> dict[uuid.UUID, DouyinTrack]:
    """按 ID 批量加载赛道，返回 {赛道 ID: 赛道实体} 映射。"""
    if not track_ids:
        return {}
    rows = session.exec(
        select(DouyinTrack).where(col(DouyinTrack.id).in_(set(track_ids)))
    ).all()
    return {row.id: row for row in rows}


__all__ = [
    "DEFAULT_TRACK_NAME",
    "assign_keyword_track",
    "assign_task_track",
    "ensure_default_track",
    "load_tracks_by_id",
    "require_owned_track",
    "resolve_track",
    "sync_keyword_link",
    "sync_task_link",
]
