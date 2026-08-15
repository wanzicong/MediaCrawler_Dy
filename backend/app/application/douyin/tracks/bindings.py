"""Canonical ownership and compatibility bindings for Douyin tracks."""

from __future__ import annotations

import uuid

from sqlmodel import Session, col, select

from app.domain.douyin.keywords.models import DouyinKeyword
from app.domain.douyin.tasks.models import CrawlTask
from app.domain.douyin.tracks.models import (
    DouyinTrack,
    DouyinTrackKeywordLink,
    DouyinTrackTaskLink,
)
from app.domain.identity.models import User

DEFAULT_TRACK_NAME = "默认赛道"
DEFAULT_TRACK_NORMALIZED_NAME = DEFAULT_TRACK_NAME.casefold()


def ensure_default_track(session: Session, *, owner_id: uuid.UUID) -> DouyinTrack:
    """Return the owner's singleton fallback track, creating it when needed."""
    # Serializing on the durable owner row closes the first-request race without
    # requiring callers to retry a failed outer transaction.
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

    # Preserve an existing user-created track with the canonical name instead of
    # manufacturing a colliding record during an upgrade.
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
    """Keep the legacy link table as an exact mirror of keyword.track_id."""
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
    if keyword.owner_id != track.owner_id:
        raise ValueError("关键词和赛道不属于同一用户")
    keyword.track_id = track.id
    session.add(keyword)
    sync_keyword_link(session, keyword=keyword, track=track)
    session.flush()


def sync_task_link(session: Session, *, task: CrawlTask, track: DouyinTrack) -> None:
    """Keep the legacy link table as an exact mirror of task.track_id."""
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


def assign_task_track(
    session: Session, *, task: CrawlTask, track: DouyinTrack
) -> None:
    if task.owner_id != track.owner_id:
        raise ValueError("任务和赛道不属于同一用户")
    task.track_id = track.id
    session.add(task)
    sync_task_link(session, task=task, track=track)
    session.flush()


def require_owned_track(
    session: Session, *, owner_id: uuid.UUID, track_id: uuid.UUID
) -> DouyinTrack:
    return resolve_track(
        session,
        owner_id=owner_id,
        track_id=track_id,
        require_enabled=False,
    )


def load_tracks_by_id(
    session: Session, track_ids: list[uuid.UUID]
) -> dict[uuid.UUID, DouyinTrack]:
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
