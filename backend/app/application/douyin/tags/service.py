from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, distinct
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col, func, select

from app.application.errors import PermissionDeniedError, ResourceNotFoundError
from app.domain.common.models import get_datetime_utc
from app.domain.douyin.content.models import DouyinAweme
from app.domain.douyin.tags.models import (
    DouyinAwemeTag,
    DouyinTag,
    DouyinTagPublic,
    DouyinTagsPublic,
    DouyinTagSyncResult,
)
from app.domain.douyin.tasks.models import CrawlTask

_TAG_PATTERN = re.compile(
    r"#([^#\s，。！？、；：,.!?;:|/\\()（）\[\]{}<>《》“”‘’\"'`~@￥$%^&*+=]{1,100})"
)


def normalize_tag_name(value: object) -> str:
    name = unicodedata.normalize("NFKC", str(value or "")).strip().lstrip("#").strip()
    return name[:100]


def extract_hashtags(item: dict[str, Any] | str) -> list[str]:
    if isinstance(item, str):
        description = item
        extras: list[Any] = []
    else:
        description = str(item.get("desc") or "")
        extras = item.get("text_extra") or []
        if not isinstance(extras, list):
            extras = []
    candidates = [match.group(1) for match in _TAG_PATTERN.finditer(description)]
    candidates.extend(
        extra.get("hashtag_name")
        for extra in extras
        if isinstance(extra, dict) and extra.get("hashtag_name")
    )
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        name = normalize_tag_name(candidate)
        normalized = name.casefold()
        if name and normalized not in seen:
            seen.add(normalized)
            result.append(name)
    return result


def sync_aweme_tags(
    session: Session,
    *,
    task_id: uuid.UUID,
    aweme_record_id: uuid.UUID,
    tag_names: list[str],
    seen_at: datetime | None = None,
) -> tuple[int, int]:
    owner_id = session.exec(
        select(CrawlTask.owner_id).where(CrawlTask.id == task_id)
    ).one()
    names = {
        normalized: name
        for name in tag_names
        if (normalized := normalize_tag_name(name).casefold())
    }
    existing_names = (
        set(
            session.exec(
                select(DouyinTag.normalized_name).where(
                    DouyinTag.owner_id == owner_id,
                    col(DouyinTag.normalized_name).in_(set(names)),
                )
            ).all()
        )
        if names
        else set()
    )
    now = seen_at or get_datetime_utc()
    tag_ids: list[uuid.UUID] = []
    for normalized, name in names.items():
        row = session.execute(
            insert(DouyinTag)
            .values(
                id=uuid.uuid4(),
                owner_id=owner_id,
                name=name,
                normalized_name=normalized,
                last_seen_at=now,
                created_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_douyin_tag_owner_name",
                set_={"name": name, "last_seen_at": now},
            )
            .returning(col(DouyinTag.id))
        ).one()
        tag_ids.append(row[0])

    existing_links = (
        set(
            session.exec(
                select(DouyinAwemeTag.tag_id).where(
                    DouyinAwemeTag.aweme_record_id == aweme_record_id,
                    col(DouyinAwemeTag.tag_id).in_(set(tag_ids)),
                )
            ).all()
        )
        if tag_ids
        else set()
    )
    for tag_id in tag_ids:
        session.execute(
            insert(DouyinAwemeTag)
            .values(
                id=uuid.uuid4(),
                aweme_record_id=aweme_record_id,
                tag_id=tag_id,
                created_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_douyin_aweme_tag_record_tag")
        )
    stale = delete(DouyinAwemeTag).where(
        col(DouyinAwemeTag.aweme_record_id) == aweme_record_id
    )
    if tag_ids:
        stale = stale.where(col(DouyinAwemeTag.tag_id).not_in(set(tag_ids)))
    session.execute(stale)
    return len(set(names) - existing_names), len(set(tag_ids) - existing_links)


def sync_tag_history(session: Session, *, owner_id: uuid.UUID) -> DouyinTagSyncResult:
    rows = session.exec(
        select(DouyinAweme)
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
        .where(CrawlTask.owner_id == owner_id)
    ).all()
    created_count = 0
    binding_count = 0
    discovered: set[str] = set()
    for aweme in rows:
        names = extract_hashtags(aweme.description or aweme.title)
        discovered.update(name.casefold() for name in names)
        created, bound = sync_aweme_tags(
            session,
            task_id=aweme.task_id,
            aweme_record_id=aweme.id,
            tag_names=names,
            seen_at=aweme.fetched_at,
        )
        created_count += created
        binding_count += bound
    session.commit()
    return DouyinTagSyncResult(
        aweme_count=len(rows),
        tag_count=len(discovered),
        created_count=created_count,
        binding_count=binding_count,
    )


def build_tag_public_rows(
    session: Session,
    *,
    owner_id: uuid.UUID,
    task_id: uuid.UUID | None = None,
    track_id: uuid.UUID | None = None,
    search: str | None = None,
) -> list[DouyinTagPublic]:
    statement = (
        select(
            DouyinTag,
            func.count(distinct(col(DouyinAwemeTag.aweme_record_id))).label(
                "aweme_count"
            ),
            func.count(distinct(col(DouyinAweme.task_id))).label("task_count"),
        )
        .outerjoin(DouyinAwemeTag, col(DouyinAwemeTag.tag_id) == col(DouyinTag.id))
        .outerjoin(
            DouyinAweme,
            col(DouyinAweme.id) == col(DouyinAwemeTag.aweme_record_id),
        )
        .outerjoin(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
        .where(DouyinTag.owner_id == owner_id)
    )
    if task_id:
        statement = statement.where(DouyinAweme.task_id == task_id)
    if track_id:
        statement = statement.where(CrawlTask.track_id == track_id)
    if search and search.strip():
        statement = statement.where(col(DouyinTag.name).ilike(f"%{search.strip()}%"))
    rows = session.exec(statement.group_by(col(DouyinTag.id))).all()
    return [
        DouyinTagPublic(
            id=tag.id,
            name=tag.name,
            aweme_count=int(aweme_count),
            task_count=int(task_count),
            last_seen_at=tag.last_seen_at,
            created_at=tag.created_at,
        )
        for tag, aweme_count, task_count in rows
    ]


def list_tags_for_actor(
    session: Session,
    *,
    actor_id: uuid.UUID,
    is_superuser: bool,
    search: str | None,
    task_id: uuid.UUID | None,
    track_id: uuid.UUID | None,
    sort_by: str,
    sort_order: str,
    skip: int,
    limit: int,
) -> DouyinTagsPublic:
    """List tags while keeping ownership and ordering outside the HTTP adapter."""

    task: CrawlTask | None = None
    if task_id:
        task = session.get(CrawlTask, task_id)
        if not task:
            raise ResourceNotFoundError("抖音任务不存在")
        if task.owner_id != actor_id and not is_superuser:
            raise PermissionDeniedError("Not enough permissions")

    from app.domain.douyin.tracks.models import DouyinTrack

    track = session.get(DouyinTrack, track_id) if track_id else None
    if track_id and (
        track is None or (track.owner_id != actor_id and not is_superuser)
    ):
        raise ResourceNotFoundError("赛道不存在或无权访问")
    if task is not None and track is not None and task.track_id != track.id:
        from app.application.errors import InvalidRequestError

        raise InvalidRequestError("任务不属于所选赛道，请调整筛选条件")

    owner_id = (
        track.owner_id
        if track is not None
        else task.owner_id if task is not None else actor_id
    )

    rows = build_tag_public_rows(
        session,
        owner_id=owner_id,
        task_id=task_id,
        track_id=track_id,
        search=search,
    )

    def sort_key(item: DouyinTagPublic) -> str | int | float:
        if sort_by == "name":
            return item.name.casefold()
        if sort_by == "task_count":
            return item.task_count
        if sort_by == "last_seen_at":
            return item.last_seen_at.timestamp()
        return item.aweme_count

    rows.sort(key=sort_key, reverse=sort_order == "desc")
    return DouyinTagsPublic(data=rows[skip : skip + limit], count=len(rows))
