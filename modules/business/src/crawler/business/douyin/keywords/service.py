import json
import uuid
from collections import defaultdict

from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.keywords.models import (
    DouyinKeyword,
    DouyinKeywordBatchMode,
    DouyinKeywordBatchTaskRequest,
    DouyinKeywordBulkCreateResult,
    DouyinKeywordPublic,
    DouyinKeywordStatus,
    DouyinKeywordSyncResult,
    DouyinKeywordSyncSource,
    DouyinKeywordTaskBatchResult,
    DouyinKeywordTaskLink,
)
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskStatus,
    DouyinCrawlType,
)
from crawler.business.douyin.tracks.models import DouyinTrack
from sqlmodel import Session, col, func, select

ACTIVE_TASK_STATUSES = {
    CrawlTaskStatus.queued.value,
    CrawlTaskStatus.waiting_login.value,
    CrawlTaskStatus.running.value,
    CrawlTaskStatus.processing_media.value,
    CrawlTaskStatus.cancelling.value,
}
FAILED_TASK_STATUSES = {
    CrawlTaskStatus.failed.value,
    CrawlTaskStatus.cancelled.value,
    CrawlTaskStatus.interrupted.value,
}


class KeywordServiceError(Exception):
    """Base error translated by the HTTP adapter."""


class KeywordNotFoundError(KeywordServiceError):
    pass


class KeywordPermissionDeniedError(KeywordServiceError):
    pass


class KeywordValidationError(KeywordServiceError, ValueError):
    pass


class KeywordConflictError(KeywordServiceError):
    pass


def get_keyword_for_actor(
    session: Session,
    *,
    keyword_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> DouyinKeyword:
    item = session.get(DouyinKeyword, keyword_id)
    if item is None:
        raise KeywordNotFoundError("关键词不存在")
    if item.owner_id != actor_id and not is_superuser:
        raise KeywordPermissionDeniedError("Not enough permissions")
    return item


def get_task_for_actor(
    session: Session,
    *,
    task_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> CrawlTask:
    task = session.get(CrawlTask, task_id)
    if task is None:
        raise KeywordNotFoundError("抖音任务不存在")
    if task.owner_id != actor_id and not is_superuser:
        raise KeywordPermissionDeniedError("Not enough permissions")
    return task


def normalize_keyword(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def clean_keywords(values: list[str]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in values:
        keyword = " ".join(raw.strip().split())
        normalized = normalize_keyword(keyword)
        if not normalized or normalized in seen:
            continue
        if len(keyword) > 200:
            raise KeywordValidationError("关键词长度不能超过 200 个字符")
        seen.add(normalized)
        result.append((keyword, normalized))
    if not result:
        raise KeywordValidationError("请至少提供一个有效关键词")
    return result


def create_keywords(
    session: Session,
    *,
    owner_id: uuid.UUID,
    values: list[str],
    notes: str = "",
    enabled: bool = True,
    track_id: uuid.UUID | None = None,
    move_existing: bool = True,
) -> tuple[list[DouyinKeyword], int, int]:
    from crawler.business.douyin.tracks.bindings import (
        assign_keyword_track,
        resolve_track,
    )

    try:
        track = resolve_track(session, owner_id=owner_id, track_id=track_id)
    except ValueError as exc:
        message = str(exc)
        if "不存在" in message or "无权访问" in message:
            raise KeywordNotFoundError(message) from exc
        if "停用" in message:
            raise KeywordConflictError(message) from exc
        raise KeywordValidationError(message) from exc
    cleaned = clean_keywords(values)
    existing_rows = session.exec(
        select(DouyinKeyword).where(
            DouyinKeyword.owner_id == owner_id,
            col(DouyinKeyword.normalized_keyword).in_([item[1] for item in cleaned]),
        )
    ).all()
    by_value = {item.normalized_keyword: item for item in existing_rows}
    created = 0
    output: list[DouyinKeyword] = []
    for keyword, normalized in cleaned:
        item = by_value.get(normalized)
        if item is None:
            item = DouyinKeyword(
                owner_id=owner_id,
                track_id=track.id,
                keyword=keyword,
                normalized_keyword=normalized,
                notes=notes.strip(),
                enabled=enabled,
            )
            session.add(item)
            session.flush()
            by_value[normalized] = item
            created += 1
        if item.track_id != track.id and move_existing:
            assign_keyword_track(session, keyword=item, track=track)
        elif item.track_id == track.id:
            # Repair the legacy compatibility mirror when importing old data.
            from crawler.business.douyin.tracks.bindings import sync_keyword_link

            sync_keyword_link(session, keyword=item, track=track)
        output.append(item)
    return output, created, len(output) - created


def sync_task_keywords_in_session(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID,
    values: list[str],
    track_id: uuid.UUID | None = None,
    move_existing: bool = True,
    source: DouyinKeywordSyncSource = DouyinKeywordSyncSource.automatic,
) -> tuple[int, int]:
    if not any(value.strip() for value in values):
        return 0, 0
    if track_id is None:
        task = session.get(CrawlTask, task_id)
        if task is None or task.owner_id != owner_id:
            raise KeywordValidationError("抖音任务不存在或无权访问")
        track_id = task.track_id
    keywords, created, _ = create_keywords(
        session,
        owner_id=owner_id,
        values=values,
        track_id=track_id,
        move_existing=move_existing,
    )
    existing_ids = set(
        session.exec(
            select(DouyinKeywordTaskLink.keyword_id).where(
                DouyinKeywordTaskLink.task_id == task_id,
                col(DouyinKeywordTaskLink.keyword_id).in_(
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
            DouyinKeywordTaskLink(
                keyword_id=keyword.id,
                task_id=task_id,
                source=source.value,
            )
        )
        bound += 1
    session.flush()
    return created, bound


def task_keywords(task: CrawlTask) -> list[str]:
    try:
        request = json.loads(task.request_json)
    except json.JSONDecodeError:
        return []
    values = request.get("keywords") if isinstance(request, dict) else None
    return [str(item) for item in values] if isinstance(values, list) else []


def sync_task(
    session: Session,
    *,
    task: CrawlTask,
    source: DouyinKeywordSyncSource,
) -> tuple[int, int, int]:
    values = task_keywords(task)
    if not values:
        return 0, 0, 0
    created, bound = sync_task_keywords_in_session(
        session,
        task_id=task.id,
        owner_id=task.owner_id,
        values=values,
        source=source,
        move_existing=False,
    )
    return len(clean_keywords(values)), created, bound


def sync_history(session: Session, *, owner_id: uuid.UUID) -> tuple[int, int, int, int]:
    tasks = session.exec(
        select(CrawlTask).where(
            CrawlTask.owner_id == owner_id,
            CrawlTask.crawl_type == "search",
        )
    ).all()
    keyword_count = 0
    created_count = 0
    binding_count = 0
    synced_tasks = 0
    for task in tasks:
        count, created, bound = sync_task(
            session, task=task, source=DouyinKeywordSyncSource.history
        )
        if count:
            synced_tasks += 1
            keyword_count += count
            created_count += created
            binding_count += bound
    return synced_tasks, keyword_count, created_count, binding_count


def _status_for(tasks: list[CrawlTask]) -> DouyinKeywordStatus:
    statuses = {task.status for task in tasks}
    if statuses & ACTIVE_TASK_STATUSES:
        return DouyinKeywordStatus.active
    if CrawlTaskStatus.succeeded.value in statuses:
        return DouyinKeywordStatus.crawled
    if statuses & FAILED_TASK_STATUSES:
        return DouyinKeywordStatus.failed
    return DouyinKeywordStatus.unprocessed


def build_keyword_public_rows(
    session: Session,
    *,
    owner_id: uuid.UUID,
    search: str | None = None,
    track_id: uuid.UUID | None = None,
) -> list[DouyinKeywordPublic]:
    statement = select(DouyinKeyword).where(DouyinKeyword.owner_id == owner_id)
    if track_id is not None:
        statement = statement.where(DouyinKeyword.track_id == track_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            col(DouyinKeyword.keyword).ilike(term)
            | col(DouyinKeyword.notes).ilike(term)
        )
    keywords = session.exec(statement).all()
    if not keywords:
        return []
    if any(item.track_id is None for item in keywords):
        raise KeywordValidationError("关键词缺少赛道归属，请先执行数据迁移")
    keyword_ids = [item.id for item in keywords]
    tracks = {
        item.id: item
        for item in session.exec(
            select(DouyinTrack).where(
                col(DouyinTrack.id).in_(
                    {item.track_id for item in keywords if item.track_id is not None}
                )
            )
        ).all()
    }
    linked_rows = session.exec(
        select(DouyinKeywordTaskLink, CrawlTask)
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinKeywordTaskLink.task_id))
        .join(
            DouyinKeyword,
            col(DouyinKeyword.id) == col(DouyinKeywordTaskLink.keyword_id),
        )
        .where(
            col(DouyinKeywordTaskLink.keyword_id).in_(keyword_ids),
            CrawlTask.track_id == DouyinKeyword.track_id,
            CrawlTask.owner_id == DouyinKeyword.owner_id,
        )
    ).all()
    tasks_by_keyword: dict[uuid.UUID, list[CrawlTask]] = defaultdict(list)
    for link, task in linked_rows:
        tasks_by_keyword[link.keyword_id].append(task)

    work_counts: dict[tuple[uuid.UUID, str], int] = defaultdict(int)
    for task_track_id, source_keyword, count in session.exec(
        select(
            CrawlTask.track_id,
            DouyinAweme.source_keyword,
            func.count(col(DouyinAweme.id)),
        )
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
        .where(CrawlTask.owner_id == owner_id)
        .group_by(col(CrawlTask.track_id), col(DouyinAweme.source_keyword))
    ).all():
        if task_track_id is None:
            continue
        work_counts[(task_track_id, normalize_keyword(source_keyword))] += int(count)

    output: list[DouyinKeywordPublic] = []
    for keyword in keywords:
        assert keyword.track_id is not None
        track = tracks[keyword.track_id]
        tasks = tasks_by_keyword.get(keyword.id, [])
        ordered = sorted(tasks, key=lambda item: item.created_at, reverse=True)
        last_task = ordered[0] if ordered else None
        completed_dates = [
            task.finished_at or task.created_at
            for task in tasks
            if task.status
            in {
                CrawlTaskStatus.succeeded.value,
                *FAILED_TASK_STATUSES,
            }
        ]
        output.append(
            DouyinKeywordPublic(
                id=keyword.id,
                track_id=track.id,
                track_name=track.name,
                track_is_default=track.is_default,
                keyword=keyword.keyword,
                enabled=keyword.enabled,
                notes=keyword.notes,
                status=_status_for(tasks),
                task_count=len(tasks),
                active_task_count=sum(
                    task.status in ACTIVE_TASK_STATUSES for task in tasks
                ),
                success_task_count=sum(
                    task.status == CrawlTaskStatus.succeeded.value for task in tasks
                ),
                failed_task_count=sum(
                    task.status in FAILED_TASK_STATUSES for task in tasks
                ),
                aweme_count=work_counts.get(
                    (keyword.track_id, keyword.normalized_keyword), 0
                ),
                last_task_id=last_task.id if last_task else None,
                last_task_status=(
                    CrawlTaskStatus(last_task.status) if last_task else None
                ),
                last_crawled_at=max(completed_dates) if completed_dates else None,
                created_at=keyword.created_at,
                updated_at=keyword.updated_at,
            )
        )
    return output


def update_keyword(
    session: Session,
    *,
    item: DouyinKeyword,
    keyword: str | None,
    enabled: bool | None,
    notes: str | None,
) -> DouyinKeyword:
    if keyword is not None:
        cleaned = clean_keywords([keyword])[0]
        if cleaned[1] != item.normalized_keyword:
            has_history = (
                session.exec(
                    select(DouyinKeywordTaskLink.id)
                    .where(DouyinKeywordTaskLink.keyword_id == item.id)
                    .limit(1)
                ).first()
                is not None
            )
            if not has_history:
                source_keywords = session.exec(
                    select(DouyinAweme.source_keyword)
                    .join(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
                    .where(CrawlTask.owner_id == item.owner_id)
                    .distinct()
                ).all()
                has_history = any(
                    normalize_keyword(source_keyword) == item.normalized_keyword
                    for source_keyword in source_keywords
                )
            if has_history:
                raise KeywordConflictError(
                    "关键词已有历史任务或作品，不能修改词面；可新建关键词并停用旧词"
                )
        conflict = session.exec(
            select(DouyinKeyword).where(
                DouyinKeyword.owner_id == item.owner_id,
                DouyinKeyword.normalized_keyword == cleaned[1],
                DouyinKeyword.id != item.id,
            )
        ).first()
        if conflict:
            raise KeywordConflictError("关键词已存在")
        item.keyword, item.normalized_keyword = cleaned
    if enabled is not None:
        item.enabled = enabled
    if notes is not None:
        item.notes = notes.strip()
    item.updated_at = get_datetime_utc()
    session.add(item)
    session.flush()
    return item


def keyword_tasks(session: Session, *, keyword_id: uuid.UUID) -> list[CrawlTask]:
    return list(
        session.exec(
            select(CrawlTask)
            .join(
                DouyinKeywordTaskLink,
                col(DouyinKeywordTaskLink.task_id) == col(CrawlTask.id),
            )
            .join(
                DouyinKeyword,
                col(DouyinKeyword.id) == col(DouyinKeywordTaskLink.keyword_id),
            )
            .where(
                DouyinKeywordTaskLink.keyword_id == keyword_id,
                CrawlTask.owner_id == DouyinKeyword.owner_id,
            )
            .order_by(col(CrawlTask.created_at).desc())
        ).all()
    )


def create_keyword_batch(
    session: Session,
    *,
    owner_id: uuid.UUID,
    values: list[str],
    notes: str,
    enabled: bool,
    track_id: uuid.UUID | None = None,
) -> DouyinKeywordBulkCreateResult:
    items, created, existing = create_keywords(
        session,
        owner_id=owner_id,
        values=values,
        notes=notes,
        enabled=enabled,
        track_id=track_id,
    )
    session.commit()
    rows = build_keyword_public_rows(session, owner_id=owner_id)
    by_id = {item.id: item for item in rows}
    return DouyinKeywordBulkCreateResult(
        data=[by_id[item.id] for item in items],
        created_count=created,
        existing_count=existing,
    )


def edit_keyword_record(
    session: Session,
    *,
    keyword_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
    keyword: str | None,
    track_id: uuid.UUID | None,
    enabled: bool | None,
    notes: str | None,
) -> DouyinKeywordPublic:
    item = get_keyword_for_actor(
        session,
        keyword_id=keyword_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    if track_id is not None and track_id != item.track_id:
        from crawler.business.douyin.tracks.bindings import (
            assign_keyword_track,
            resolve_track,
        )

        try:
            track = resolve_track(
                session,
                owner_id=item.owner_id,
                track_id=track_id,
            )
        except ValueError as exc:
            raise KeywordValidationError(str(exc)) from exc
        assign_keyword_track(session, keyword=item, track=track)
    item = update_keyword(
        session,
        item=item,
        keyword=keyword,
        enabled=enabled,
        notes=notes,
    )
    owner_id = item.owner_id
    session.commit()
    return next(
        row
        for row in build_keyword_public_rows(session, owner_id=owner_id)
        if row.id == keyword_id
    )


def delete_keyword_record(
    session: Session,
    *,
    keyword_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> None:
    session.delete(
        get_keyword_for_actor(
            session,
            keyword_id=keyword_id,
            actor_id=actor_id,
            is_superuser=is_superuser,
        )
    )
    session.commit()


def delete_keyword_batch(
    session: Session,
    *,
    owner_id: uuid.UUID,
    keyword_ids: list[uuid.UUID],
) -> int:
    rows = session.exec(
        select(DouyinKeyword).where(
            DouyinKeyword.owner_id == owner_id,
            col(DouyinKeyword.id).in_(keyword_ids),
        )
    ).all()
    for row in rows:
        session.delete(row)
    session.commit()
    return len(rows)


def sync_keyword_task(
    session: Session,
    *,
    task_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> DouyinKeywordSyncResult:
    task = get_task_for_actor(
        session,
        task_id=task_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    keyword_count, created, bound = sync_task(
        session,
        task=task,
        source=DouyinKeywordSyncSource.manual,
    )
    if not keyword_count:
        raise KeywordValidationError("该任务没有可同步的搜索关键词")
    session.commit()
    return DouyinKeywordSyncResult(
        task_count=1,
        keyword_count=keyword_count,
        created_count=created,
        binding_count=bound,
    )


def sync_keyword_history(
    session: Session,
    *,
    owner_id: uuid.UUID,
) -> DouyinKeywordSyncResult:
    task_count, keyword_count, created, bound = sync_history(
        session,
        owner_id=owner_id,
    )
    session.commit()
    return DouyinKeywordSyncResult(
        task_count=task_count,
        keyword_count=keyword_count,
        created_count=created,
        binding_count=bound,
    )


async def create_keyword_crawl_tasks(
    session: Session,
    *,
    owner_id: uuid.UUID,
    request: DouyinKeywordBatchTaskRequest,
) -> DouyinKeywordTaskBatchResult:
    from crawler.business.douyin.tasks.query_service import build_tasks_public
    from crawler.business.douyin.tasks.service import task_manager

    unique_ids = list(dict.fromkeys(request.keyword_ids))
    keywords = session.exec(
        select(DouyinKeyword).where(
            DouyinKeyword.owner_id == owner_id,
            col(DouyinKeyword.id).in_(unique_ids),
        )
    ).all()
    by_id = {item.id: item for item in keywords}
    if len(by_id) != len(unique_ids):
        raise KeywordNotFoundError("部分关键词不存在或无权访问")
    if any(not by_id[item_id].enabled for item_id in unique_ids):
        raise KeywordConflictError("选中的关键词包含已停用项目")
    from crawler.business.douyin.tracks.bindings import resolve_track

    selected_track_ids = {by_id[item_id].track_id for item_id in unique_ids}
    if request.track_id is None:
        if len(selected_track_ids) != 1:
            raise KeywordValidationError(
                "不能跨赛道混合创建任务，请先选择同一赛道的关键词"
            )
        resolved_track_id = next(iter(selected_track_ids))
    else:
        resolved_track_id = request.track_id
        if selected_track_ids != {resolved_track_id}:
            raise KeywordValidationError("选中的关键词不全部属于指定赛道")
    track = resolve_track(
        session,
        owner_id=owner_id,
        track_id=resolved_track_id,
    )
    values = [by_id[item_id].keyword for item_id in unique_ids]
    if request.mode == DouyinKeywordBatchMode.separate:
        if len(values) > 20:
            raise KeywordValidationError("独立任务模式一次最多创建 20 个任务")
        groups = [[value] for value in values]
    else:
        groups = [values[index : index + 20] for index in range(0, len(values), 20)]

    tasks: list[CrawlTask] = []
    for group in groups:
        task_request = CrawlTaskCreate(
            track_id=track.id,
            crawl_type=DouyinCrawlType.search,
            login_type=request.login_type,
            browser_mode=request.browser_mode,
            keywords=group,
            start_page=request.start_page,
            max_awemes=request.max_awemes,
            fetch_comments=request.fetch_comments,
            fetch_sub_comments=request.fetch_sub_comments,
            max_comments_per_aweme=request.max_comments_per_aweme,
            concurrency=request.concurrency,
            request_delay_level=request.request_delay_level,
            request_interval_seconds=request.request_interval_seconds,
            publish_time=request.publish_time,
            media_processing_mode=request.media_processing_mode,
            media_storage=request.media_storage,
            download_media=request.download_media,
            translate_subtitles=request.translate_subtitles,
            transcription_language=request.transcription_language,
            account_id=request.account_id,
            account_pool_id=request.account_pool_id,
            account_strategy=request.account_strategy,
        )
        try:
            task = await task_manager.create(owner_id=owner_id, request=task_request)
        except ValueError as exc:
            raise KeywordValidationError(str(exc)) from exc
        if task.track_id != track.id:
            raise KeywordValidationError("任务创建后的赛道归属不一致")
        tasks.append(task)
    return DouyinKeywordTaskBatchResult(
        data=build_tasks_public(session, tasks=tasks),
        count=len(tasks),
    )
