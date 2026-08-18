"""Read-side application service for the keyword library."""

from __future__ import annotations

import uuid
from typing import Literal

from crawler.business.douyin.keywords.models import (
    DouyinKeywordPublic,
    DouyinKeywordsPublic,
    DouyinKeywordStatus,
)
from crawler.business.douyin.keywords.service import (
    build_keyword_public_rows,
    get_keyword_for_actor,
    keyword_tasks,
)
from crawler.business.douyin.tasks.models import CrawlTaskPublic
from crawler.business.douyin.tasks.query_service import build_tasks_public
from crawler.business.douyin.tracks.bindings import require_owned_track
from sqlmodel import Session


def list_keywords(
    session: Session,
    *,
    owner_id: uuid.UUID,
    search: str | None,
    track_id: uuid.UUID | None,
    keyword_status: DouyinKeywordStatus | None,
    enabled: bool | None,
    sort_by: Literal[
        "keyword",
        "status",
        "task_count",
        "aweme_count",
        "last_crawled_at",
        "created_at",
    ],
    sort_order: Literal["asc", "desc"],
    skip: int,
    limit: int,
) -> DouyinKeywordsPublic:
    if track_id is not None:
        try:
            require_owned_track(session, owner_id=owner_id, track_id=track_id)
        except ValueError as exc:
            from crawler.business.douyin.keywords.service import KeywordNotFoundError

            raise KeywordNotFoundError("赛道不存在或无权访问") from exc
    rows = build_keyword_public_rows(
        session,
        owner_id=owner_id,
        search=search,
        track_id=track_id,
    )
    if keyword_status:
        rows = [item for item in rows if item.status == keyword_status]
    if enabled is not None:
        rows = [item for item in rows if item.enabled == enabled]
    status_order = {
        DouyinKeywordStatus.active: 0,
        DouyinKeywordStatus.failed: 1,
        DouyinKeywordStatus.unprocessed: 2,
        DouyinKeywordStatus.crawled: 3,
    }

    def sort_key(item: DouyinKeywordPublic) -> str | int | float:
        if sort_by == "keyword":
            return item.keyword.casefold()
        if sort_by == "status":
            return status_order[item.status]
        if sort_by == "task_count":
            return item.task_count
        if sort_by == "aweme_count":
            return item.aweme_count
        if sort_by == "created_at":
            return item.created_at.timestamp()
        return item.last_crawled_at.timestamp() if item.last_crawled_at else 0

    rows.sort(key=sort_key, reverse=sort_order == "desc")
    return DouyinKeywordsPublic(data=rows[skip : skip + limit], count=len(rows))


def list_keyword_tasks(
    session: Session,
    *,
    keyword_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> list[CrawlTaskPublic]:
    item = get_keyword_for_actor(
        session,
        keyword_id=keyword_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    return build_tasks_public(
        session,
        tasks=keyword_tasks(session, keyword_id=item.id),
    )
