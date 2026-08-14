import uuid
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.models import (
    CrawlTask,
    CrawlTaskStatus,
    DouyinKeyword,
    DouyinTrack,
    DouyinTrackKeywordLink,
    DouyinTrackPublic,
    DouyinTrackTaskLink,
    get_datetime_utc,
)
from app.services.douyin_keywords import ACTIVE_TASK_STATUSES, create_keywords


def normalize_track_name(value: str) -> tuple[str, str]:
    name = " ".join(value.strip().split())
    if not name:
        raise HTTPException(status_code=422, detail="赛道名称不能为空")
    return name, name.casefold()


def create_track(
    session: Session,
    *,
    owner_id: uuid.UUID,
    name: str,
    description: str,
    keywords: list[str],
) -> DouyinTrack:
    cleaned_name, normalized_name = normalize_track_name(name)
    track = DouyinTrack(
        owner_id=owner_id,
        name=cleaned_name,
        normalized_name=normalized_name,
        description=description.strip(),
    )
    session.add(track)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="同名赛道已存在") from exc
    if keywords:
        add_track_keywords(
            session, track=track, owner_id=owner_id, values=keywords
        )
    return track


def add_track_keywords(
    session: Session,
    *,
    track: DouyinTrack,
    owner_id: uuid.UUID,
    values: list[str],
) -> tuple[int, int]:
    keywords, created, _ = create_keywords(
        session,
        owner_id=owner_id,
        values=values,
        notes=f"赛道：{track.name}",
    )
    existing_ids = set(
        session.exec(
            select(DouyinTrackKeywordLink.keyword_id).where(
                DouyinTrackKeywordLink.track_id == track.id,
                col(DouyinTrackKeywordLink.keyword_id).in_(
                    [item.id for item in keywords]
                ),
            )
        ).all()
    )
    bound = 0
    for keyword in keywords:
        if keyword.id in existing_ids:
            continue
        session.add(
            DouyinTrackKeywordLink(track_id=track.id, keyword_id=keyword.id)
        )
        bound += 1
    track.updated_at = get_datetime_utc()
    session.add(track)
    session.flush()
    return created, bound


def track_keywords(session: Session, *, track_id: uuid.UUID) -> list[DouyinKeyword]:
    return list(
        session.exec(
            select(DouyinKeyword)
            .join(
                DouyinTrackKeywordLink,
                col(DouyinTrackKeywordLink.keyword_id) == col(DouyinKeyword.id),
            )
            .where(DouyinTrackKeywordLink.track_id == track_id)
            .order_by(col(DouyinKeyword.keyword))
        ).all()
    )


def build_track_public_rows(
    session: Session,
    *,
    owner_id: uuid.UUID,
    search: str | None = None,
) -> list[DouyinTrackPublic]:
    statement = select(DouyinTrack).where(DouyinTrack.owner_id == owner_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            col(DouyinTrack.name).ilike(term)
            | col(DouyinTrack.description).ilike(term)
        )
    tracks = session.exec(statement.order_by(col(DouyinTrack.updated_at).desc())).all()
    if not tracks:
        return []
    track_ids = [item.id for item in tracks]
    keyword_rows = session.exec(
        select(DouyinTrackKeywordLink, DouyinKeyword)
        .join(
            DouyinKeyword,
            col(DouyinKeyword.id) == col(DouyinTrackKeywordLink.keyword_id),
        )
        .where(col(DouyinTrackKeywordLink.track_id).in_(track_ids))
    ).all()
    task_rows = session.exec(
        select(DouyinTrackTaskLink, CrawlTask)
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinTrackTaskLink.task_id))
        .where(col(DouyinTrackTaskLink.track_id).in_(track_ids))
    ).all()
    keywords_by_track: dict[uuid.UUID, list[DouyinKeyword]] = defaultdict(list)
    tasks_by_track: dict[uuid.UUID, list[CrawlTask]] = defaultdict(list)
    for keyword_link, keyword in keyword_rows:
        keywords_by_track[keyword_link.track_id].append(keyword)
    for task_link, task in task_rows:
        tasks_by_track[task_link.track_id].append(task)
    output: list[DouyinTrackPublic] = []
    for track in tracks:
        keywords = keywords_by_track[track.id]
        tasks = sorted(
            tasks_by_track[track.id], key=lambda item: item.created_at, reverse=True
        )
        last_task = tasks[0] if tasks else None
        output.append(
            DouyinTrackPublic(
                id=track.id,
                name=track.name,
                description=track.description,
                enabled=track.enabled,
                keyword_count=len(keywords),
                enabled_keyword_count=sum(item.enabled for item in keywords),
                task_count=len(tasks),
                active_task_count=sum(
                    item.status in ACTIVE_TASK_STATUSES for item in tasks
                ),
                aweme_count=sum(item.aweme_count for item in tasks),
                comment_count=sum(item.comment_count for item in tasks),
                last_task_id=last_task.id if last_task else None,
                last_task_status=(
                    CrawlTaskStatus(last_task.status) if last_task else None
                ),
                last_run_at=last_task.created_at if last_task else None,
                created_at=track.created_at,
                updated_at=track.updated_at,
            )
        )
    return output
