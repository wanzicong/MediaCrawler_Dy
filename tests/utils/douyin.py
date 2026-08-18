"""Shared Douyin persistence helpers for tests.

Production code creates tasks through the application layer, which resolves an
explicit track or the owner's default track before the first flush.  Tests that
insert ORM rows directly must model the same invariant explicitly.
"""

from __future__ import annotations

import uuid

from crawler.business.douyin.tracks.bindings import ensure_default_track
from sqlmodel import Session


def default_track_id(session: Session, *, owner_id: uuid.UUID) -> uuid.UUID:
    return ensure_default_track(session, owner_id=owner_id).id
