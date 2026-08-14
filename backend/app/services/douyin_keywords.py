import json
import uuid
from collections import defaultdict

from fastapi import HTTPException
from sqlmodel import Session, col, func, select

from app.models import (
    CrawlTask,
    CrawlTaskStatus,
    DouyinAweme,
    DouyinKeyword,
    DouyinKeywordPublic,
    DouyinKeywordStatus,
    DouyinKeywordSyncSource,
    DouyinKeywordTaskLink,
    get_datetime_utc,
)

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
            raise HTTPException(status_code=422, detail="关键词长度不能超过 200 个字符")
        seen.add(normalized)
        result.append((keyword, normalized))
    if not result:
        raise HTTPException(status_code=422, detail="请至少提供一个有效关键词")
    return result


def create_keywords(
    session: Session,
    *,
    owner_id: uuid.UUID,
    values: list[str],
    notes: str = "",
    enabled: bool = True,
) -> tuple[list[DouyinKeyword], int, int]:
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
                keyword=keyword,
                normalized_keyword=normalized,
                notes=notes.strip(),
                enabled=enabled,
            )
            session.add(item)
            session.flush()
            by_value[normalized] = item
            created += 1
        output.append(item)
    return output, created, len(output) - created


def sync_task_keywords_in_session(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID,
    values: list[str],
    source: DouyinKeywordSyncSource = DouyinKeywordSyncSource.automatic,
) -> tuple[int, int]:
    if not any(value.strip() for value in values):
        return 0, 0
    keywords, created, _ = create_keywords(
        session, owner_id=owner_id, values=values
    )
    existing_ids = set(
        session.exec(
            select(DouyinKeywordTaskLink.keyword_id).where(
                DouyinKeywordTaskLink.task_id == task_id,
                col(DouyinKeywordTaskLink.keyword_id).in_([item.id for item in keywords]),
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
    )
    return len(clean_keywords(values)), created, bound


def sync_history(
    session: Session, *, owner_id: uuid.UUID
) -> tuple[int, int, int, int]:
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
) -> list[DouyinKeywordPublic]:
    statement = select(DouyinKeyword).where(DouyinKeyword.owner_id == owner_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            col(DouyinKeyword.keyword).ilike(term)
            | col(DouyinKeyword.notes).ilike(term)
        )
    keywords = session.exec(statement).all()
    if not keywords:
        return []
    keyword_ids = [item.id for item in keywords]
    linked_rows = session.exec(
        select(DouyinKeywordTaskLink, CrawlTask)
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinKeywordTaskLink.task_id))
        .where(col(DouyinKeywordTaskLink.keyword_id).in_(keyword_ids))
    ).all()
    tasks_by_keyword: dict[uuid.UUID, list[CrawlTask]] = defaultdict(list)
    for link, task in linked_rows:
        tasks_by_keyword[link.keyword_id].append(task)

    work_counts: dict[str, int] = defaultdict(int)
    for source_keyword, count in session.exec(
        select(DouyinAweme.source_keyword, func.count(col(DouyinAweme.id)))
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
        .where(CrawlTask.owner_id == owner_id)
        .group_by(col(DouyinAweme.source_keyword))
    ).all():
        work_counts[normalize_keyword(source_keyword)] += int(count)

    output: list[DouyinKeywordPublic] = []
    for keyword in keywords:
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
                aweme_count=work_counts.get(keyword.normalized_keyword, 0),
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
                raise HTTPException(
                    status_code=409,
                    detail="关键词已有历史任务或作品，不能修改词面；可新建关键词并停用旧词",
                )
        conflict = session.exec(
            select(DouyinKeyword).where(
                DouyinKeyword.owner_id == item.owner_id,
                DouyinKeyword.normalized_keyword == cleaned[1],
                DouyinKeyword.id != item.id,
            )
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail="关键词已存在")
        item.keyword, item.normalized_keyword = cleaned
    if enabled is not None:
        item.enabled = enabled
    if notes is not None:
        item.notes = notes.strip()
    item.updated_at = get_datetime_utc()
    session.add(item)
    session.flush()
    return item


def keyword_tasks(
    session: Session, *, keyword_id: uuid.UUID
) -> list[CrawlTask]:
    return list(
        session.exec(
            select(CrawlTask)
            .join(
                DouyinKeywordTaskLink,
                col(DouyinKeywordTaskLink.task_id) == col(CrawlTask.id),
            )
            .where(DouyinKeywordTaskLink.keyword_id == keyword_id)
            .order_by(col(CrawlTask.created_at).desc())
        ).all()
    )
