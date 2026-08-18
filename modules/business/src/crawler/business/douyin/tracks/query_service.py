"""Read-side application service for track management."""

from __future__ import annotations

import uuid

from crawler.business.douyin.keywords.models import DouyinKeywordsPublic
from crawler.business.douyin.tracks.bindings import ensure_default_track
from crawler.business.douyin.tracks.models import (
    DouyinTrackDetailPublic,
    DouyinTracksPublic,
)
from crawler.business.douyin.tracks.service import (
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
    track = get_track_for_actor(
        session,
        track_id=track_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    return build_track_keyword_rows(session, track=track)
