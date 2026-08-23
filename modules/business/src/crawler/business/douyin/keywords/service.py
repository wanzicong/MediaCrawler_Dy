"""抖音关键词库的写侧应用服务。

覆盖关键词的增删改查、归一化与去重、关键词-任务绑定同步
（自动/手动/历史回填），以及基于关键词批量创建搜索采集任务。
服务层错误统一以 KeywordServiceError 体系抛出，由 HTTP 适配层翻译。
"""

import json
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.comments.models import DouyinComment
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.interactions.models import DouyinInteraction
from crawler.business.douyin.keywords.models import (
    DouyinKeyword,
    DouyinKeywordBatchTaskRequest,
    DouyinKeywordBulkCreateResult,
    DouyinKeywordPublic,
    DouyinKeywordStatus,
    DouyinKeywordSyncResult,
    DouyinKeywordSyncSource,
    DouyinKeywordTaskBatchResult,
    DouyinKeywordTaskLink,
)
from crawler.business.douyin.request_logs.models import DouyinRequestLog
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskStatus,
    DouyinCrawlType,
)
from crawler.business.douyin.tracks.models import DouyinTrack
from sqlmodel import Session, col, delete, func, select

# 视为「进行中」的任务状态集合，用于推导关键词的 active 状态
ACTIVE_TASK_STATUSES = {
    CrawlTaskStatus.queued.value,
    CrawlTaskStatus.waiting_login.value,
    CrawlTaskStatus.running.value,
    CrawlTaskStatus.processing_media.value,
    CrawlTaskStatus.cancelling.value,
}
# 视为「失败」的任务状态集合，用于推导关键词的 failed 状态
FAILED_TASK_STATUSES = {
    CrawlTaskStatus.failed.value,
    CrawlTaskStatus.cancelled.value,
    CrawlTaskStatus.interrupted.value,
}


class KeywordServiceError(Exception):
    """关键词服务错误基类，由 HTTP 适配层统一翻译为响应。"""


class KeywordNotFoundError(KeywordServiceError):
    """关键词（或关联资源）不存在，或按 not-found 语义屏蔽的无权访问。"""


class KeywordPermissionDeniedError(KeywordServiceError):
    """当前用户无权操作该关键词（属于其他用户且非超管）。"""


class KeywordValidationError(KeywordServiceError, ValueError):
    """关键词相关请求参数校验失败。"""


class KeywordConflictError(KeywordServiceError):
    """关键词操作与现有数据冲突（如词面重复、已有历史任务禁止改词等）。"""


@dataclass(frozen=True, slots=True)
class KeywordDeleteResult:
    """关键词及其独占任务数据的级联删除统计。"""

    keyword_count: int
    task_count: int
    aweme_count: int
    comment_count: int
    interaction_count: int
    shared_task_count: int


def get_keyword_for_actor(
    session: Session,
    *,
    keyword_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> DouyinKeyword:
    """按 ID 获取关键词并校验操作者权限。

    参数：
        session: 数据库会话。
        keyword_id: 关键词 ID。
        actor_id: 当前操作用户 ID。
        is_superuser: 是否为超管（超管可操作任意用户的关键词）。

    返回：
        关键词实体。

    异常：
        KeywordNotFoundError: 关键词不存在。
        KeywordPermissionDeniedError: 关键词属于其他用户且非超管。
    """
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
    """按 ID 获取采集任务并校验操作者权限。

    参数：
        session: 数据库会话。
        task_id: 采集任务 ID。
        actor_id: 当前操作用户 ID。
        is_superuser: 是否为超管。

    返回：
        采集任务实体。

    异常：
        KeywordNotFoundError: 任务不存在。
        KeywordPermissionDeniedError: 任务属于其他用户且非超管。
    """
    task = session.get(CrawlTask, task_id)
    if task is None:
        raise KeywordNotFoundError("抖音任务不存在")
    if task.owner_id != actor_id and not is_superuser:
        raise KeywordPermissionDeniedError("Not enough permissions")
    return task


def normalize_keyword(value: str) -> str:
    """归一化关键词：去除首尾空白、压缩连续空白为单空格并转小写，用于去重比较。"""
    return " ".join(value.strip().split()).casefold()


def clean_keywords(values: list[str]) -> list[tuple[str, str]]:
    """清洗关键词列表：去空白、去重（按归一化值），返回 (原文, 归一化值) 对。

    参数：
        values: 用户输入的原始关键词列表。

    返回：
        (关键词原文, 归一化关键词) 元组列表，保持输入顺序。

    异常：
        KeywordValidationError: 关键词超过 200 字符，或清洗后无有效关键词。
    """
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


def _track_category(track: DouyinTrack, value: str) -> str:
    """把分类解析为赛道中已定义的规范显示值，空值表示不分类。"""
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        return ""
    for category in track.keyword_categories:
        if category.casefold() == cleaned.casefold():
            return category
    raise KeywordValidationError("关键词分类未在目标赛道中定义，请先维护赛道分类")


def create_keywords(
    session: Session,
    *,
    owner_id: uuid.UUID,
    values: list[str],
    notes: str = "",
    enabled: bool = True,
    category: str = "",
    track_id: uuid.UUID | None = None,
    move_existing: bool = True,
) -> tuple[list[DouyinKeyword], int, int]:
    """批量创建关键词（已存在则复用），并将关键词归属到目标赛道。

    参数：
        session: 数据库会话（本函数只 flush，不 commit）。
        owner_id: 归属用户 ID。
        values: 原始关键词列表。
        notes: 新建关键词写入的备注。
        enabled: 新建关键词的启用状态。
        track_id: 目标赛道 ID，None 时使用默认赛道。
        move_existing: 已存在的关键词是否允许移动到目标赛道。

    返回：
        三元组 (关键词实体列表, 新建数量, 复用已存在数量)。

    异常：
        KeywordNotFoundError: 目标赛道不存在或无权访问。
        KeywordConflictError: 目标赛道已停用。
        KeywordValidationError: 关键词清洗失败或其他参数非法。
    """
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
    resolved_category = _track_category(track, category)
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
                category=resolved_category,
                notes=notes.strip(),
                enabled=enabled,
            )
            session.add(item)
            session.flush()
            by_value[normalized] = item
            created += 1
        elif resolved_category:
            item.category = resolved_category
            session.add(item)
        if item.track_id != track.id and move_existing:
            assign_keyword_track(session, keyword=item, track=track)
        elif item.track_id == track.id:
            # 导入旧数据时修复遗留的兼容镜像关系。
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
    """在给定会话中同步任务关键词：创建/复用关键词并建立任务绑定。

    参数：
        session: 数据库会话（本函数只 flush，不 commit）。
        task_id: 采集任务 ID。
        owner_id: 归属用户 ID。
        values: 原始关键词列表；全部为空时直接返回 (0, 0)。
        track_id: 目标赛道 ID；None 时取任务自身的赛道。
        move_existing: 已存在的关键词是否允许移动到目标赛道。
        source: 绑定来源标识，写入关联记录。

    返回：
        二元组 (新建关键词数, 新建绑定数)。

    异常：
        KeywordValidationError: 任务不存在或不属于该用户。
    """
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
    """从任务请求快照（request_json）中解析出搜索关键词列表，解析失败返回空列表。"""
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
    """同步单个任务的关键词（不移动已有关键词的赛道归属）。

    参数：
        session: 数据库会话（本函数只 flush，不 commit）。
        task: 采集任务实体；无搜索关键词时直接返回 (0, 0, 0)。
        source: 绑定来源标识。

    返回：
        三元组 (有效关键词数, 新建关键词数, 新建绑定数)。
    """
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
    """回填同步用户全部历史搜索任务的关键词与绑定（来源标记为 history）。

    参数：
        session: 数据库会话（本函数只 flush，不 commit）。
        owner_id: 归属用户 ID。

    返回：
        四元组 (同步的任务数, 涉及的关键词数, 新建关键词数, 新建绑定数)。
    """
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
    """由关联任务状态集合推导关键词状态：有进行中则 active，有成功则 crawled，有失败则 failed，否则 unprocessed。"""
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
    """构建关键词公开模型列表，聚合赛道信息与任务/作品统计。

    绑定任务与作品统计跟随关键词当前赛道归属；任务自身仍保留创建时赛道，
    用于审计，不因关键词移动而改写历史任务。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 ID，仅返回其名下的关键词。
        search: 模糊搜索词（匹配关键词与备注），None 表示不过滤。
        track_id: 限定赛道 ID，None 表示不过滤。

    返回：
        关键词公开模型列表（未排序，排序由调用方负责）。

    异常：
        KeywordValidationError: 存在缺少赛道归属的历史遗留关键词数据。
    """
    statement = select(DouyinKeyword).where(DouyinKeyword.owner_id == owner_id)
    if track_id is not None:
        statement = statement.where(DouyinKeyword.track_id == track_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            col(DouyinKeyword.keyword).ilike(term)
            | col(DouyinKeyword.category).ilike(term)
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
            CrawlTask.owner_id == DouyinKeyword.owner_id,
        )
    ).all()
    tasks_by_keyword: dict[uuid.UUID, list[CrawlTask]] = defaultdict(list)
    for link, task in linked_rows:
        tasks_by_keyword[link.keyword_id].append(task)

    work_counts: dict[str, int] = defaultdict(int)
    for source_keyword, count in session.exec(
        select(
            DouyinAweme.source_keyword,
            func.count(col(DouyinAweme.id)),
        )
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
        .where(CrawlTask.owner_id == owner_id)
        .group_by(col(DouyinAweme.source_keyword))
    ).all():
        work_counts[normalize_keyword(source_keyword)] += int(count)

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
                category=keyword.category,
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
    category: str | None,
    notes: str | None,
) -> DouyinKeyword:
    """就地更新关键词的词面、启用状态与备注（本函数只 flush，不 commit）。

    参数：
        session: 数据库会话。
        item: 待更新的关键词实体。
        keyword: 新词面，None 表示不修改。
        enabled: 新启用状态，None 表示不修改。
        notes: 新备注，None 表示不修改。

    返回：
        更新后的关键词实体。

    异常：
        KeywordValidationError: 新词面清洗失败（超长或为空）。
        KeywordConflictError: 词面与其他关键词重复；或关键词已有历史
            任务/作品，禁止修改词面（应新建关键词并停用旧词）。
    """
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
    if category is not None:
        item.category = category
    if notes is not None:
        item.notes = notes.strip()
    item.updated_at = get_datetime_utc()
    session.add(item)
    session.flush()
    return item


def keyword_tasks(session: Session, *, keyword_id: uuid.UUID) -> list[CrawlTask]:
    """查询关键词关联的全部任务（按创建时间倒序，仅含与关键词同归属用户的任务）。"""
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
    category: str,
    enabled: bool,
    track_id: uuid.UUID | None = None,
) -> DouyinKeywordBulkCreateResult:
    """批量创建关键词并提交事务，返回新建/复用统计与完整公开模型。

    参数：
        session: 数据库会话（本函数内部 commit）。
        owner_id: 归属用户 ID。
        values: 原始关键词列表。
        notes: 新建关键词写入的备注。
        enabled: 新建关键词的启用状态。
        track_id: 目标赛道 ID，None 时使用默认赛道。

    返回：
        批量创建结果（含关键词列表、新建数与复用数）。

    异常：
        KeywordNotFoundError: 目标赛道不存在或无权访问。
        KeywordConflictError: 目标赛道已停用。
        KeywordValidationError: 关键词清洗失败。
    """
    items, created, existing = create_keywords(
        session,
        owner_id=owner_id,
        values=values,
        notes=notes,
        category=category,
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
    category: str | None,
    notes: str | None,
) -> DouyinKeywordPublic:
    """编辑单条关键词（可调整赛道归属、词面、启用状态、备注）并提交事务。

    参数：
        session: 数据库会话（本函数内部 commit）。
        keyword_id: 关键词 ID。
        actor_id: 当前操作用户 ID。
        is_superuser: 是否为超管。
        keyword: 新词面，None 表示不修改。
        track_id: 目标赛道 ID；与当前赛道相同时忽略，None 表示不调整。
        enabled: 新启用状态，None 表示不修改。
        notes: 新备注，None 表示不修改。

    返回：
        更新后的关键词公开模型（含统计汇总）。

    异常：
        KeywordNotFoundError: 关键词不存在。
        KeywordPermissionDeniedError: 关键词属于其他用户且非超管。
        KeywordValidationError: 目标赛道非法或新词面校验失败。
        KeywordConflictError: 词面冲突或已有历史任务禁止改词。
    """
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
        if item.category:
            try:
                item.category = _track_category(track, item.category)
            except KeywordValidationError:
                item.category = ""
    current_track = session.get(DouyinTrack, item.track_id)
    if current_track is None:
        raise KeywordValidationError("关键词所属赛道不存在")
    resolved_category = (
        _track_category(current_track, category) if category is not None else None
    )
    item = update_keyword(
        session,
        item=item,
        keyword=keyword,
        enabled=enabled,
        category=resolved_category,
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
) -> KeywordDeleteResult:
    """删除单条关键词及其独占任务、作品、评论和互动数据。

    参数：
        session: 数据库会话（本函数内部 commit）。
        keyword_id: 关键词 ID。
        actor_id: 当前操作用户 ID。
        is_superuser: 是否为超管。

    异常：
        KeywordNotFoundError: 关键词不存在。
        KeywordPermissionDeniedError: 关键词属于其他用户且非超管。
    """
    item = get_keyword_for_actor(
        session,
        keyword_id=keyword_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    return _delete_keywords_with_related_data(session, keywords=[item])


def delete_keyword_batch(
    session: Session,
    *,
    owner_id: uuid.UUID,
    keyword_ids: list[uuid.UUID],
) -> KeywordDeleteResult:
    """批量删除当前用户名下的关键词及其独占关联数据。

    参数：
        session: 数据库会话（本函数内部 commit）。
        owner_id: 归属用户 ID，仅删除其名下的关键词。
        keyword_ids: 待删除的关键词 ID 列表。

    返回：
        实际级联删除统计（不属于该用户的 ID 被静默忽略）。
    """
    rows = session.exec(
        select(DouyinKeyword).where(
            DouyinKeyword.owner_id == owner_id,
            col(DouyinKeyword.id).in_(keyword_ids),
        )
    ).all()
    return _delete_keywords_with_related_data(session, keywords=rows)


def _delete_keywords_with_related_data(
    session: Session,
    *,
    keywords: Sequence[DouyinKeyword],
) -> KeywordDeleteResult:
    """原子删除关键词和仅由这些关键词拥有的任务数据。

    历史版本允许一个任务关联多个关键词。若任务仍关联未删除的关键词，则仅删除
    选中关键词及其绑定，保留共享任务，避免误删其他关键词的作品和评论。活动任务
    必须先取消，防止数据库记录删除后后台执行器继续回写。
    """
    if not keywords:
        return KeywordDeleteResult(0, 0, 0, 0, 0, 0)

    keyword_ids = {item.id for item in keywords}
    candidate_task_ids = set(
        session.exec(
            select(DouyinKeywordTaskLink.task_id).where(
                col(DouyinKeywordTaskLink.keyword_id).in_(keyword_ids)
            )
        ).all()
    )
    shared_task_ids: set[uuid.UUID] = set()
    if candidate_task_ids:
        shared_task_ids = set(
            session.exec(
                select(DouyinKeywordTaskLink.task_id).where(
                    col(DouyinKeywordTaskLink.task_id).in_(candidate_task_ids),
                    col(DouyinKeywordTaskLink.keyword_id).not_in(keyword_ids),
                )
            ).all()
        )
    deleted_task_ids = candidate_task_ids - shared_task_ids
    tasks = (
        list(
            session.exec(
                select(CrawlTask).where(col(CrawlTask.id).in_(deleted_task_ids))
            ).all()
        )
        if deleted_task_ids
        else []
    )
    active_tasks = [task for task in tasks if task.status in ACTIVE_TASK_STATUSES]
    if active_tasks:
        raise KeywordConflictError(
            f"选中关键词仍有 {len(active_tasks)} 个运行中任务，请先取消任务后再删除"
        )

    def related_count(model: Any) -> int:
        if not deleted_task_ids:
            return 0
        return int(
            session.exec(
                select(func.count())
                .select_from(model)
                .where(col(model.task_id).in_(deleted_task_ids))
            ).one()
        )

    aweme_count = related_count(DouyinAweme)
    comment_count = related_count(DouyinComment)
    interaction_count = related_count(DouyinInteraction)

    # 请求日志采用 SET NULL 以保留一般审计记录；本次是明确的彻底清理操作，故先删。
    if deleted_task_ids:
        session.exec(
            delete(DouyinRequestLog).where(
                col(DouyinRequestLog.task_id).in_(deleted_task_ids)
            )
        )
    for task in tasks:
        session.delete(task)
    for keyword in keywords:
        session.delete(keyword)
    session.commit()
    return KeywordDeleteResult(
        keyword_count=len(keywords),
        task_count=len(tasks),
        aweme_count=aweme_count,
        comment_count=comment_count,
        interaction_count=interaction_count,
        shared_task_count=len(shared_task_ids),
    )


def sync_keyword_task(
    session: Session,
    *,
    task_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> DouyinKeywordSyncResult:
    """手动同步单个任务的关键词并提交事务（来源标记为 manual）。

    参数：
        session: 数据库会话（本函数内部 commit）。
        task_id: 采集任务 ID。
        actor_id: 当前操作用户 ID。
        is_superuser: 是否为超管。

    返回：
        同步结果统计。

    异常：
        KeywordNotFoundError: 任务不存在。
        KeywordPermissionDeniedError: 任务属于其他用户且非超管。
        KeywordValidationError: 任务没有可同步的搜索关键词。
    """
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
    """回填同步当前用户全部历史搜索任务的关键词并提交事务。

    参数：
        session: 数据库会话（本函数内部 commit）。
        owner_id: 归属用户 ID。

    返回：
        同步结果统计（任务数、关键词数、新建数、绑定数）。
    """
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
    """基于选中关键词批量创建搜索采集任务。

    无论旧客户端提交 combined 还是 separate，每个关键词都创建一个独立任务，
    从业务层保证一个关键词采集任务只包含一个关键词。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 ID。
        request: 批量建任务请求体（关键词 ID 列表、模式与采集参数）。

    返回：
        新建任务的公开模型列表与数量。

    异常：
        KeywordNotFoundError: 部分关键词不存在或不属于该用户。
        KeywordConflictError: 选中的关键词包含已停用项目。
        KeywordValidationError: 跨赛道混合选择、数量超限或任务创建参数非法。
    """
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
    groups = [[value] for value in values]

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
            task_interval_seconds=request.task_interval_seconds,
            publish_time=request.publish_time,
            media_processing_mode=request.media_processing_mode,
            media_storage=request.media_storage,
            download_media=request.download_media,
            translate_subtitles=request.translate_subtitles,
            transcription_language=request.transcription_language,
            account_id=request.account_id,
            account_ids=request.account_ids,
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
