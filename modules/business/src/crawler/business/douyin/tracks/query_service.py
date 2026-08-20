"""赛道管理的读侧应用服务：赛道列表、详情与赛道关键词查询。"""

from __future__ import annotations

import uuid

from crawler.business.douyin.creators.models import DouyinCreatorsPublic
from crawler.business.douyin.keywords.models import DouyinKeywordsPublic
from crawler.business.douyin.tracks.bindings import ensure_default_track
from crawler.business.douyin.tracks.models import (
    DouyinTrackDetailPublic,
    DouyinTracksPublic,
)
from crawler.business.douyin.tracks.service import (
    build_track_creator_rows,
    build_track_detail,
    build_track_keyword_rows,
    build_track_public_rows,
    get_track_for_actor,
)
from sqlmodel import Session


def list_tracks(
    session: Session,
    *,
    owner_id: uuid.UUID,
    search: str | None,
    enabled: bool | None,
    skip: int,
    limit: int,
) -> DouyinTracksPublic:
    """分页查询用户的赛道列表（含聚合统计），必要时先确保默认赛道存在。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 ID。
        search: 名称/描述模糊搜索词。
        enabled: 按启用状态过滤；None 表示不过滤。
        skip: 分页偏移量。
        limit: 分页大小。

    返回：
        赛道分页列表。
    """
    ensure_default_track(session, owner_id=owner_id)
    session.commit()
    rows = build_track_public_rows(session, owner_id=owner_id, search=search)
    if enabled is not None:
        rows = [item for item in rows if item.enabled == enabled]
    return DouyinTracksPublic(data=rows[skip : skip + limit], count=len(rows))


def get_track_detail(
    session: Session,
    *,
    track_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> DouyinTrackDetailPublic:
    """查询单个赛道详情（归属或超管可见）。"""
    track = get_track_for_actor(
        session,
        track_id=track_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    return build_track_detail(session, track=track)


def list_track_keywords(
    session: Session,
    *,
    track_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> DouyinKeywordsPublic:
    """查询赛道下的关键词列表（归属或超管可见）。"""
    track = get_track_for_actor(
        session,
        track_id=track_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    return build_track_keyword_rows(session, track=track)


def list_track_creators(
    session: Session,
    *,
    track_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> DouyinCreatorsPublic:
    """查询赛道下的达人列表（归属或超管可见）。"""
    track = get_track_for_actor(
        session,
        track_id=track_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    return build_track_creator_rows(session, track=track)
