import uuid
from collections import defaultdict

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.application.douyin.keywords.service import (
    ACTIVE_TASK_STATUSES,
    KeywordValidationError,
    build_keyword_public_rows,
    create_keywords,
)
from app.application.douyin.tracks.bindings import (
    assign_keyword_track,
    assign_task_track,
    ensure_default_track,
)
from app.domain.common.models import get_datetime_utc
from app.domain.douyin.keywords.models import (
    DouyinKeyword,
    DouyinKeywordBatchMode,
    DouyinKeywordsPublic,
    DouyinKeywordTaskBatchResult,
)
from app.domain.douyin.media.models import MediaProcessingMode
from app.domain.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskStatus,
    DouyinCrawlType,
)
from app.domain.douyin.tracks.models import (
    DouyinTrack,
    DouyinTrackDetailPublic,
    DouyinTrackPublic,
    DouyinTrackTaskRequest,
)


class TrackServiceError(Exception):
    """Base error translated by the HTTP adapter."""


class TrackNotFoundError(TrackServiceError):
    pass


class TrackPermissionDeniedError(TrackServiceError):
    pass


class TrackValidationError(TrackServiceError):
    pass


class TrackConflictError(TrackServiceError):
    pass


def get_track_for_actor(
    session: Session,
    *,
    track_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> DouyinTrack:
    item = session.get(DouyinTrack, track_id)
    if item is None or (item.owner_id != actor_id and not is_superuser):
        raise TrackNotFoundError("赛道不存在")
    return item


def normalize_track_name(value: str) -> tuple[str, str]:
    name = " ".join(value.strip().split())
    if not name:
        raise TrackValidationError("赛道名称不能为空")
    return name, name.casefold()


def create_track(
    session: Session,
    *,
    owner_id: uuid.UUID,
    name: str,
    description: str,
    prompt: str,
    keywords: list[str],
) -> DouyinTrack:
    ensure_default_track(session, owner_id=owner_id)
    cleaned_name, normalized_name = normalize_track_name(name)
    track = DouyinTrack(
        owner_id=owner_id,
        name=cleaned_name,
        normalized_name=normalized_name,
        description=description.strip(),
        prompt=prompt.strip(),
    )
    session.add(track)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise TrackConflictError("同名赛道已存在") from exc
    if keywords:
        add_track_keywords(session, track=track, owner_id=owner_id, values=keywords)
    return track


def add_track_keywords(
    session: Session,
    *,
    track: DouyinTrack,
    owner_id: uuid.UUID,
    values: list[str],
) -> tuple[int, int]:
    if not track.enabled:
        raise TrackConflictError("赛道已停用，不能添加关键词")
    try:
        keywords, created, _ = create_keywords(
            session,
            owner_id=owner_id,
            values=values,
            notes=f"赛道：{track.name}",
            track_id=track.id,
        )
    except KeywordValidationError as exc:
        raise TrackValidationError(str(exc)) from exc
    track.updated_at = get_datetime_utc()
    session.add(track)
    session.flush()
    return created, len(keywords)


def track_keywords(session: Session, *, track_id: uuid.UUID) -> list[DouyinKeyword]:
    return list(
        session.exec(
            select(DouyinKeyword)
            .where(DouyinKeyword.track_id == track_id)
            .order_by(col(DouyinKeyword.keyword))
        ).all()
    )


def build_track_public_rows(
    session: Session,
    *,
    owner_id: uuid.UUID,
    search: str | None = None,
    track_id: uuid.UUID | None = None,
) -> list[DouyinTrackPublic]:
    statement = select(DouyinTrack).where(DouyinTrack.owner_id == owner_id)
    if track_id is not None:
        statement = statement.where(DouyinTrack.id == track_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            col(DouyinTrack.name).ilike(term) | col(DouyinTrack.description).ilike(term)
        )
    tracks = session.exec(
        statement.order_by(
            col(DouyinTrack.is_default).desc(),
            col(DouyinTrack.updated_at).desc(),
        )
    ).all()
    if not tracks:
        return []
    track_ids = [item.id for item in tracks]
    keyword_rows = session.exec(
        select(DouyinKeyword).where(col(DouyinKeyword.track_id).in_(track_ids))
    ).all()
    task_rows = session.exec(
        select(CrawlTask).where(col(CrawlTask.track_id).in_(track_ids))
    ).all()
    keywords_by_track: dict[uuid.UUID, list[DouyinKeyword]] = defaultdict(list)
    tasks_by_track: dict[uuid.UUID, list[CrawlTask]] = defaultdict(list)
    for keyword in keyword_rows:
        assert keyword.track_id is not None
        keywords_by_track[keyword.track_id].append(keyword)
    for task in task_rows:
        assert task.track_id is not None
        tasks_by_track[task.track_id].append(task)
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
                is_default=track.is_default,
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


def build_track_detail(
    session: Session,
    *,
    track: DouyinTrack,
) -> DouyinTrackDetailPublic:
    summary = next(
        item
        for item in build_track_public_rows(
            session,
            owner_id=track.owner_id,
            track_id=track.id,
        )
        if item.id == track.id
    )
    return DouyinTrackDetailPublic(**summary.model_dump(), prompt=track.prompt)


def build_track_keyword_rows(
    session: Session,
    *,
    track: DouyinTrack,
) -> DouyinKeywordsPublic:
    ids = {item.id for item in track_keywords(session, track_id=track.id)}
    rows = [
        item
        for item in build_keyword_public_rows(session, owner_id=track.owner_id)
        if item.id in ids
    ]
    return DouyinKeywordsPublic(data=rows, count=len(rows))


def create_track_record(
    session: Session,
    *,
    owner_id: uuid.UUID,
    name: str,
    description: str,
    prompt: str,
    keywords: list[str],
) -> DouyinTrackDetailPublic:
    track = create_track(
        session,
        owner_id=owner_id,
        name=name,
        description=description,
        prompt=prompt,
        keywords=keywords,
    )
    session.commit()
    session.refresh(track)
    return build_track_detail(session, track=track)


def update_track_record(
    session: Session,
    *,
    track_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
    name: str | None,
    description: str | None,
    prompt: str | None,
    enabled: bool | None,
) -> DouyinTrackDetailPublic:
    track = get_track_for_actor(
        session,
        track_id=track_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    if track.is_default:
        if name is not None and normalize_track_name(name)[1] != track.normalized_name:
            raise TrackConflictError("默认赛道不能重命名")
        if enabled is False:
            raise TrackConflictError("默认赛道不能停用")
    if name is not None:
        clean_name, normalized = normalize_track_name(name)
        conflict = session.exec(
            select(DouyinTrack).where(
                DouyinTrack.owner_id == track.owner_id,
                DouyinTrack.normalized_name == normalized,
                DouyinTrack.id != track.id,
            )
        ).first()
        if conflict:
            raise TrackConflictError("同名赛道已存在")
        track.name, track.normalized_name = clean_name, normalized
    if description is not None:
        track.description = description.strip()
    if prompt is not None:
        track.prompt = prompt.strip()
    if enabled is not None:
        track.enabled = enabled
    track.updated_at = get_datetime_utc()
    session.add(track)
    session.commit()
    return build_track_detail(session, track=track)


def delete_track_record(
    session: Session,
    *,
    track_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> None:
    track = get_track_for_actor(
        session,
        track_id=track_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    if track.is_default:
        raise TrackConflictError("默认赛道不能删除")
    _rehome_track_records(session, track=track)
    session.delete(track)
    session.commit()


def _rehome_track_records(session: Session, *, track: DouyinTrack) -> None:
    fallback = ensure_default_track(session, owner_id=track.owner_id)
    for keyword in session.exec(
        select(DouyinKeyword).where(DouyinKeyword.track_id == track.id)
    ).all():
        assign_keyword_track(session, keyword=keyword, track=fallback)
    for task in session.exec(
        select(CrawlTask).where(CrawlTask.track_id == track.id)
    ).all():
        assign_task_track(session, task=task, track=fallback)


def delete_track_batch(
    session: Session,
    *,
    owner_id: uuid.UUID,
    track_ids: list[uuid.UUID],
) -> int:
    rows = session.exec(
        select(DouyinTrack).where(
            DouyinTrack.owner_id == owner_id,
            col(DouyinTrack.id).in_(track_ids),
        )
    ).all()
    if any(row.is_default for row in rows):
        raise TrackConflictError("默认赛道不能批量删除")
    for row in rows:
        _rehome_track_records(session, track=row)
        session.delete(row)
    session.commit()
    return len(rows)


def append_track_keyword_records(
    session: Session,
    *,
    track_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
    keywords: list[str],
) -> DouyinKeywordsPublic:
    track = get_track_for_actor(
        session,
        track_id=track_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    add_track_keywords(
        session,
        track=track,
        owner_id=track.owner_id,
        values=keywords,
    )
    session.commit()
    return build_track_keyword_rows(session, track=track)


def remove_track_keyword_record(
    session: Session,
    *,
    track_id: uuid.UUID,
    keyword_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> None:
    track = get_track_for_actor(
        session,
        track_id=track_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    keyword = session.get(DouyinKeyword, keyword_id)
    if keyword is None or keyword.track_id != track_id:
        raise TrackNotFoundError("赛道关键词关联不存在")
    if track.is_default:
        raise TrackConflictError("关键词必须归属一个赛道，不能从默认赛道直接移除")
    fallback = ensure_default_track(session, owner_id=track.owner_id)
    assign_keyword_track(session, keyword=keyword, track=fallback)
    track.updated_at = get_datetime_utc()
    session.add(track)
    session.commit()


async def create_track_crawl_tasks(
    session: Session,
    *,
    track_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
    request: DouyinTrackTaskRequest,
) -> DouyinKeywordTaskBatchResult:
    from app.application.douyin.tasks.query_service import build_tasks_public
    from app.application.douyin.tasks.service import task_manager

    track = get_track_for_actor(
        session,
        track_id=track_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    if track.owner_id != actor_id:
        raise TrackPermissionDeniedError("不能为其他用户的赛道创建采集任务")
    if not track.enabled:
        raise TrackConflictError("赛道已停用")
    available = track_keywords(session, track_id=track.id)
    by_id = {item.id: item for item in available}
    selected_ids = list(dict.fromkeys(request.keyword_ids)) or [
        item.id for item in available if item.enabled
    ]
    if not selected_ids:
        raise TrackValidationError("赛道没有可运行的关键词")
    if any(item_id not in by_id for item_id in selected_ids):
        raise TrackNotFoundError("部分关键词不属于该赛道")
    selected = [by_id[item_id] for item_id in selected_ids]
    if any(not item.enabled for item in selected):
        raise TrackConflictError("选中的关键词包含已停用项目")
    values = [item.keyword for item in selected]
    groups = (
        [[value] for value in values]
        if request.mode == DouyinKeywordBatchMode.separate
        else [values[index : index + 20] for index in range(0, len(values), 20)]
    )
    if request.mode == DouyinKeywordBatchMode.separate and len(groups) > 20:
        raise TrackValidationError("独立任务模式一次最多创建 20 个任务")

    tasks: list[CrawlTask] = []
    for group in groups:
        task_request = CrawlTaskCreate(
            track_id=track.id,
            crawl_type=DouyinCrawlType.search,
            keywords=group,
            max_awemes=request.max_awemes,
            fetch_comments=request.fetch_comments,
            fetch_sub_comments=request.fetch_sub_comments,
            max_comments_per_aweme=request.max_comments_per_aweme,
            request_delay_level=request.request_delay_level,
            publish_time=request.publish_time,
            media_processing_mode=(
                MediaProcessingMode.immediate
                if request.download_media
                else MediaProcessingMode.none
            ),
            download_media=request.download_media,
            translate_subtitles=request.translate_subtitles,
            account_id=request.account_id,
            account_pool_id=request.account_pool_id,
            account_strategy=request.account_strategy,
        )
        try:
            task = await task_manager.create(owner_id=actor_id, request=task_request)
        except ValueError as exc:
            raise TrackValidationError(str(exc)) from exc
        if task.track_id != track.id:
            raise TrackValidationError("任务创建后的赛道归属不一致")
        tasks.append(task)
    track.updated_at = get_datetime_utc()
    session.add(track)
    session.commit()
    return DouyinKeywordTaskBatchResult(
        data=build_tasks_public(session, tasks=tasks),
        count=len(tasks),
    )
