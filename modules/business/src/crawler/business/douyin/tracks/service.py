"""抖音赛道的写侧应用服务与领域逻辑。

负责赛道的创建、更新、强制清理、关键词追加/移除，以及基于赛道关键词
批量创建采集任务；读侧查询见 query_service。
"""

import json
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.comments.models import DouyinComment
from crawler.business.douyin.content.models import DouyinAweme, DouyinUserAction
from crawler.business.douyin.creators.models import (
    DouyinCreator,
    DouyinCreatorsPublic,
    DouyinCreatorTaskLink,
)
from crawler.business.douyin.creators.service import (
    CreatorValidationError,
    build_creator_public_rows,
    create_creators,
    parse_creator_targets,
)
from crawler.business.douyin.interactions.models import DouyinInteraction
from crawler.business.douyin.keywords.models import (
    DouyinKeyword,
    DouyinKeywordsPublic,
    DouyinKeywordTaskBatchResult,
    DouyinKeywordTaskLink,
)
from crawler.business.douyin.keywords.service import (
    ACTIVE_TASK_STATUSES,
    KeywordValidationError,
    build_keyword_public_rows,
    create_keywords,
    normalize_keyword,
)
from crawler.business.douyin.media.models import DouyinMediaAsset
from crawler.business.douyin.request_logs.models import DouyinRequestLog
from crawler.business.douyin.tags.models import DouyinAwemeTag, DouyinTag
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskPublic,
    CrawlTaskShard,
    CrawlTaskStatus,
    DouyinCrawlType,
)
from crawler.business.douyin.tracks.attribution import content_attributed_track_id
from crawler.business.douyin.tracks.bindings import (
    assign_keyword_track,
    assign_task_track,
    ensure_default_track,
)
from crawler.business.douyin.tracks.models import (
    DouyinTrack,
    DouyinTrackDetailPublic,
    DouyinTrackPublic,
    DouyinTrackTaskDefaults,
    DouyinTrackTaskRequest,
)
from sqlalchemy import or_, tuple_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, delete, func, select


class TrackServiceError(Exception):
    """赛道服务基础异常，由 HTTP 适配层统一翻译为错误响应。"""


class TrackNotFoundError(TrackServiceError):
    """赛道不存在或当前操作者无权访问。"""


class TrackPermissionDeniedError(TrackServiceError):
    """操作者对赛道没有执行该操作的权限。"""


class TrackValidationError(TrackServiceError):
    """赛道相关请求参数或业务规则校验失败。"""


class TrackConflictError(TrackServiceError):
    """赛道状态冲突（如重名、默认赛道保护、已停用）。"""


@dataclass(frozen=True, slots=True)
class TrackCleanupResult:
    """赛道业务数据强制清理结果。"""

    track_count: int
    keyword_count: int
    creator_count: int
    task_count: int
    aweme_count: int
    comment_count: int
    interaction_count: int
    stopped_task_count: int = 0


@dataclass(frozen=True, slots=True)
class TrackStopResult:
    """清理前冻结赛道并停止执行器的结果。"""

    stopped_task_count: int
    was_enabled: bool


@dataclass(frozen=True, slots=True)
class _TrackCleanupScope:
    """一次赛道清理在当前事务快照中的精确影响范围。"""

    affected_task_ids: set[uuid.UUID]
    deleted_task_ids: set[uuid.UUID]
    target_awemes: tuple[DouyinAweme, ...]
    rehome_targets: dict[uuid.UUID, uuid.UUID]


def get_track_for_actor(
    session: Session,
    *,
    track_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> DouyinTrack:
    """按操作者可见性加载赛道，不存在或无权访问时抛出 TrackNotFoundError。"""
    item = session.get(DouyinTrack, track_id)
    if item is None or (item.owner_id != actor_id and not is_superuser):
        raise TrackNotFoundError("赛道不存在")
    return item


def normalize_track_name(value: str) -> tuple[str, str]:
    """规范化赛道名称：折叠首尾及中间空白，返回（显示名, 小写判重名）。

    异常：
        TrackValidationError: 名称为空时抛出。
    """
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
    default_task_config: DouyinTrackTaskDefaults | None = None,
    reply_templates: list[str] | None = None,
    keyword_categories: list[str] | None = None,
) -> DouyinTrack:
    """创建赛道并可选地追加初始关键词（不提交事务）。

    异常：
        TrackConflictError: 同名赛道已存在时抛出。
        TrackValidationError: 关键词校验失败时抛出。
    """
    ensure_default_track(session, owner_id=owner_id)
    cleaned_name, normalized_name = normalize_track_name(name)
    track = DouyinTrack(
        owner_id=owner_id,
        name=cleaned_name,
        normalized_name=normalized_name,
        description=description.strip(),
        prompt=prompt.strip(),
        default_task_config=(
            default_task_config or DouyinTrackTaskDefaults()
        ).model_dump(mode="json"),
        reply_templates=reply_templates or [],
        keyword_categories=keyword_categories or [],
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
    """向赛道批量追加关键词（复用关键词服务创建），不提交事务。

    返回：
        (新创建的关键词数, 关键词总数) 元组。

    异常：
        TrackConflictError: 赛道已停用时抛出。
        TrackValidationError: 关键词内容校验失败时抛出。
    """
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
    """查询赛道下全部关键词，按关键词文本排序。"""
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
    """构建带关键词/任务聚合统计的赛道概要行，默认赛道置顶、其余按更新时间倒序。"""
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
    attributed_track = content_attributed_track_id()
    aweme_counts = {
        row_track_id: int(count)
        for row_track_id, count in session.exec(
            select(
                attributed_track.label("attributed_track_id"),
                func.count(col(DouyinAweme.id)),
            )
            .join(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
            .where(CrawlTask.owner_id == owner_id)
            .group_by(attributed_track)
        ).all()
        if row_track_id is not None
    }
    comment_counts = {
        row_track_id: int(count)
        for row_track_id, count in session.exec(
            select(
                attributed_track.label("attributed_track_id"),
                func.count(col(DouyinComment.id)),
            )
            .join(
                DouyinAweme,
                (col(DouyinAweme.task_id) == col(DouyinComment.task_id))
                & (col(DouyinAweme.aweme_id) == col(DouyinComment.aweme_id)),
            )
            .join(CrawlTask, col(CrawlTask.id) == col(DouyinComment.task_id))
            .where(CrawlTask.owner_id == owner_id)
            .group_by(attributed_track)
        ).all()
        if row_track_id is not None
    }
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
                default_task_config=DouyinTrackTaskDefaults.model_validate(
                    track.default_task_config
                ),
                keyword_count=len(keywords),
                enabled_keyword_count=sum(item.enabled for item in keywords),
                task_count=len(tasks),
                active_task_count=sum(
                    item.status in ACTIVE_TASK_STATUSES for item in tasks
                ),
                aweme_count=aweme_counts.get(track.id, 0),
                comment_count=comment_counts.get(track.id, 0),
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
    """在赛道概要基础上补充提示词，构建赛道详情模型。"""
    summary = next(
        item
        for item in build_track_public_rows(
            session,
            owner_id=track.owner_id,
            track_id=track.id,
        )
        if item.id == track.id
    )
    return DouyinTrackDetailPublic(
        **summary.model_dump(),
        prompt=track.prompt,
        reply_templates=list(track.reply_templates),
        keyword_categories=list(track.keyword_categories),
    )


def build_track_keyword_rows(
    session: Session,
    *,
    track: DouyinTrack,
) -> DouyinKeywordsPublic:
    """构建赛道下关键词的对外列表（复用关键词读侧行构建）。"""
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
    default_task_config: DouyinTrackTaskDefaults | None = None,
    reply_templates: list[str] | None = None,
    keyword_categories: list[str] | None = None,
) -> DouyinTrackDetailPublic:
    """创建赛道并提交事务，返回赛道详情。"""
    track = create_track(
        session,
        owner_id=owner_id,
        name=name,
        description=description,
        prompt=prompt,
        keywords=keywords,
        default_task_config=default_task_config,
        reply_templates=reply_templates,
        keyword_categories=keyword_categories,
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
    default_task_config: DouyinTrackTaskDefaults | None = None,
    reply_templates: list[str] | None = None,
    keyword_categories: list[str] | None = None,
) -> DouyinTrackDetailPublic:
    """部分更新赛道并提交事务。

    默认赛道受保护：不能重命名、不能停用。

    异常：
        TrackNotFoundError: 赛道不存在或无权访问。
        TrackConflictError: 违反默认赛道保护或同名冲突。
    """
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
    if default_task_config is not None:
        track.default_task_config = default_task_config.model_dump(mode="json")
    if reply_templates is not None:
        track.reply_templates = list(reply_templates)
    if keyword_categories is not None:
        track.keyword_categories = list(keyword_categories)
    track.updated_at = get_datetime_utc()
    session.add(track)
    session.commit()
    return build_track_detail(session, track=track)


async def stop_track_tasks(
    session: Session,
    *,
    track_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
    allow_default: bool = True,
) -> TrackStopResult:
    """先冻结赛道任务准入，再停止其全部进程内执行器。

    不在当前进程运行的遗留活动状态不会阻止后续强制清理。
    """
    track = get_track_for_actor(
        session,
        track_id=track_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    if track.is_default and not allow_default:
        raise TrackConflictError("默认赛道不能删除")
    was_enabled = track.enabled
    if track.enabled:
        track.enabled = False
        track.updated_at = get_datetime_utc()
        session.add(track)
        session.commit()

    task_ids = _build_track_cleanup_scope(session, {track.id}).affected_task_ids
    if not task_ids:
        return TrackStopResult(0, was_enabled)

    # 延迟导入，避免各执行器与赛道写服务形成模块初始化环。
    from crawler.business.douyin.interactions.service import interaction_manager
    from crawler.business.douyin.media.migration import media_migration_manager
    from crawler.business.douyin.media.pipeline import media_manager
    from crawler.business.douyin.tasks.service import task_manager

    try:
        stopped = 0
        for task_id in task_ids:
            if await task_manager.cancel(task_id):
                stopped += 1
            await media_manager.cancel_task(task_id)
            await media_migration_manager.cancel_task(task_id)
        await interaction_manager.cancel_tasks(task_ids)
    except BaseException as exc:
        # 已经取消的采集/媒体/互动无法安全“反向恢复”，尤其互动写操作不能重放。
        # 因此失败时保持赛道冻结，允许用户重试删除/重置，避免重新准入造成并发写入。
        session.rollback()
        if isinstance(exc, Exception):
            raise TrackConflictError(
                "停止赛道任务失败，赛道已保持停用，请重试删除或重置"
            ) from exc
        raise
    session.expire_all()
    return TrackStopResult(stopped, was_enabled)


def delete_track_record(
    session: Session,
    *,
    track_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
    stopped_task_count: int = 0,
) -> TrackCleanupResult:
    """强制删除赛道及其关键词、达人、任务和全部任务结果。

    异常：
        TrackNotFoundError: 赛道不存在或无权访问。
        TrackConflictError: 默认赛道不能删除。
    """
    track = get_track_for_actor(
        session,
        track_id=track_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    if track.is_default:
        raise TrackConflictError("默认赛道不能删除")
    return _purge_track_records(
        session,
        tracks=[track],
        delete_tracks=True,
        stopped_task_count=stopped_task_count,
    )


def reset_track_record(
    session: Session,
    *,
    track_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
    stopped_task_count: int = 0,
    restore_enabled: bool | None = None,
) -> TrackCleanupResult:
    """清空赛道业务数据，但保留赛道及其配置。"""
    track = get_track_for_actor(
        session,
        track_id=track_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    if restore_enabled is not None:
        track.enabled = restore_enabled
        track.updated_at = get_datetime_utc()
        session.add(track)
    return _purge_track_records(
        session,
        tracks=[track],
        delete_tracks=False,
        stopped_task_count=stopped_task_count,
    )


def delete_track_batch(
    session: Session,
    *,
    actor_id: uuid.UUID,
    is_superuser: bool,
    track_ids: list[uuid.UUID],
    stopped_task_count: int = 0,
) -> TrackCleanupResult:
    """批量强制删除用户赛道及其全部业务数据。

    异常：
        TrackConflictError: 待删集合中包含默认赛道。
    """
    rows = get_deletable_tracks_for_actor(
        session,
        actor_id=actor_id,
        is_superuser=is_superuser,
        track_ids=track_ids,
    )
    return _purge_track_records(
        session,
        tracks=rows,
        delete_tracks=True,
        stopped_task_count=stopped_task_count,
    )


def get_deletable_tracks_for_actor(
    session: Session,
    *,
    actor_id: uuid.UUID,
    is_superuser: bool,
    track_ids: list[uuid.UUID],
) -> list[DouyinTrack]:
    """在停止任何任务前完整验证批量删除集合与操作权限。"""
    requested_ids = set(track_ids)
    statement = select(DouyinTrack).where(col(DouyinTrack.id).in_(requested_ids))
    if not is_superuser:
        statement = statement.where(DouyinTrack.owner_id == actor_id)
    rows = list(session.exec(statement.order_by(col(DouyinTrack.id))).all())
    if {row.id for row in rows} != requested_ids:
        raise TrackNotFoundError("部分赛道不存在或无权访问")
    if any(row.is_default for row in rows):
        raise TrackConflictError("默认赛道不能批量删除")
    return rows


def _build_track_cleanup_scope(
    session: Session, track_ids: set[uuid.UUID]
) -> _TrackCleanupScope:
    """按页面动态归属计算清理范围，并识别需要保留的跨赛道共享任务。"""
    if not track_ids:
        return _TrackCleanupScope(set(), set(), (), {})

    keyword_ids = set(
        session.exec(
            select(DouyinKeyword.id).where(col(DouyinKeyword.track_id).in_(track_ids))
        ).all()
    )
    creator_ids = set(
        session.exec(
            select(DouyinCreator.id).where(col(DouyinCreator.track_id).in_(track_ids))
        ).all()
    )
    owned_task_ids = set(
        session.exec(
            select(CrawlTask.id).where(col(CrawlTask.track_id).in_(track_ids))
        ).all()
    )
    if keyword_ids:
        owned_task_ids.update(
            session.exec(
                select(DouyinKeywordTaskLink.task_id).where(
                    col(DouyinKeywordTaskLink.keyword_id).in_(keyword_ids)
                )
            ).all()
        )
    if creator_ids:
        owned_task_ids.update(
            session.exec(
                select(DouyinCreatorTaskLink.task_id).where(
                    col(DouyinCreatorTaskLink.creator_id).in_(creator_ids)
                )
            ).all()
        )

    attributed_track = content_attributed_track_id()
    target_awemes = tuple(
        session.exec(
            select(DouyinAweme)
            .join(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
            .where(attributed_track.in_(track_ids))
        ).all()
    )
    target_aweme_ids = {item.id for item in target_awemes}
    affected_task_ids = owned_task_ids | {item.task_id for item in target_awemes}

    shared_task_ids: set[uuid.UUID] = set()
    if owned_task_ids:
        shared_task_ids.update(
            session.exec(
                select(DouyinKeywordTaskLink.task_id)
                .join(
                    DouyinKeyword,
                    col(DouyinKeyword.id) == col(DouyinKeywordTaskLink.keyword_id),
                )
                .where(
                    col(DouyinKeywordTaskLink.task_id).in_(owned_task_ids),
                    col(DouyinKeyword.track_id).not_in(track_ids),
                )
            ).all()
        )
        shared_task_ids.update(
            session.exec(
                select(DouyinCreatorTaskLink.task_id)
                .join(
                    DouyinCreator,
                    col(DouyinCreator.id) == col(DouyinCreatorTaskLink.creator_id),
                )
                .where(
                    col(DouyinCreatorTaskLink.task_id).in_(owned_task_ids),
                    col(DouyinCreator.track_id).not_in(track_ids),
                )
            ).all()
        )
        outside_aweme_statement = select(DouyinAweme.task_id).where(
            col(DouyinAweme.task_id).in_(owned_task_ids)
        )
        if target_aweme_ids:
            outside_aweme_statement = outside_aweme_statement.where(
                col(DouyinAweme.id).not_in(target_aweme_ids)
            )
        shared_task_ids.update(session.exec(outside_aweme_statement.distinct()).all())

    deleted_task_ids = owned_task_ids - shared_task_ids
    rehome_targets = _shared_task_rehome_targets(
        session,
        track_ids=track_ids,
        deleted_task_ids=deleted_task_ids,
    )
    return _TrackCleanupScope(
        affected_task_ids=affected_task_ids,
        deleted_task_ids=deleted_task_ids,
        target_awemes=target_awemes,
        rehome_targets=rehome_targets,
    )


def _shared_task_rehome_targets(
    session: Session,
    *,
    track_ids: set[uuid.UUID],
    deleted_task_ids: set[uuid.UUID],
) -> dict[uuid.UUID, uuid.UUID]:
    """为保留的共享任务选择一个仍存在的赛道，解除待删赛道外键。"""
    direct_task_ids = set(
        session.exec(
            select(CrawlTask.id).where(col(CrawlTask.track_id).in_(track_ids))
        ).all()
    )
    preserved_ids = direct_task_ids - deleted_task_ids
    if not preserved_ids:
        return {}

    targets: dict[uuid.UUID, uuid.UUID] = {}
    keyword_rows = session.exec(
        select(DouyinKeywordTaskLink.task_id, DouyinKeyword.track_id)
        .join(
            DouyinKeyword,
            col(DouyinKeyword.id) == col(DouyinKeywordTaskLink.keyword_id),
        )
        .where(
            col(DouyinKeywordTaskLink.task_id).in_(preserved_ids),
            col(DouyinKeyword.track_id).not_in(track_ids),
        )
        .order_by(
            col(DouyinKeywordTaskLink.task_id),
            col(DouyinKeyword.track_id),
        )
    ).all()
    for task_id, target_track_id in keyword_rows:
        targets.setdefault(task_id, target_track_id)
    creator_rows = session.exec(
        select(DouyinCreatorTaskLink.task_id, DouyinCreator.track_id)
        .join(
            DouyinCreator,
            col(DouyinCreator.id) == col(DouyinCreatorTaskLink.creator_id),
        )
        .where(
            col(DouyinCreatorTaskLink.task_id).in_(preserved_ids),
            col(DouyinCreator.track_id).not_in(track_ids),
        )
        .order_by(
            col(DouyinCreatorTaskLink.task_id),
            col(DouyinCreator.track_id),
        )
    ).all()
    for task_id, target_track_id in creator_rows:
        targets.setdefault(task_id, target_track_id)

    attributed_track = content_attributed_track_id()
    aweme_rows = session.exec(
        select(DouyinAweme.task_id, attributed_track.label("attributed_track_id"))
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
        .where(
            col(DouyinAweme.task_id).in_(preserved_ids),
            attributed_track.not_in(track_ids),
        )
        .distinct()
        .order_by(col(DouyinAweme.task_id), attributed_track)
    ).all()
    for task_id, target_track_id in aweme_rows:
        if target_track_id is not None:
            targets.setdefault(task_id, target_track_id)

    missing = preserved_ids - set(targets)
    if missing:
        raise TrackConflictError("共享任务缺少可保留的外部赛道归属，请重试")
    return targets


def _sanitize_preserved_request_json(
    request_json: str,
    *,
    removed_keywords: set[str],
    removed_creator_sec_uids: set[str],
    removed_aweme_ids: set[str],
    target_track_id: uuid.UUID | None,
) -> str:
    """返回移除已删目标后的任务/分片请求快照。"""
    try:
        payload = json.loads(request_json)
    except json.JSONDecodeError:
        return request_json
    if not isinstance(payload, dict):
        return request_json

    keyword_values = payload.get("keywords")
    if isinstance(keyword_values, list):
        payload["keywords"] = [
            value
            for value in keyword_values
            if normalize_keyword(str(value)) not in removed_keywords
        ]

    creator_values = payload.get("creator_ids")
    if isinstance(creator_values, list):
        retained_creators: list[Any] = []
        for value in creator_values:
            try:
                parsed = parse_creator_targets([str(value)])[0]
            except CreatorValidationError:
                parsed = str(value).strip()
            if parsed not in removed_creator_sec_uids:
                retained_creators.append(value)
        payload["creator_ids"] = retained_creators

    video_values = payload.get("video_ids")
    if isinstance(video_values, list) and removed_aweme_ids:
        payload["video_ids"] = [
            value
            for value in video_values
            if not any(aweme_id in str(value) for aweme_id in removed_aweme_ids)
        ]
    if target_track_id is not None:
        payload["track_id"] = str(target_track_id)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _reset_crawl_checkpoint(checkpoint_json: str) -> str:
    """清空共享任务的旧采集位置，避免目标裁剪后跳过剩余数据。"""
    try:
        payload = json.loads(checkpoint_json or "{}")
    except json.JSONDecodeError:
        return "{}"
    if not isinstance(payload, dict):
        return "{}"
    if payload.get("phase") == "crawl":
        payload["position"] = {}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _purge_track_records(
    session: Session,
    *,
    tracks: Sequence[DouyinTrack],
    delete_tracks: bool,
    stopped_task_count: int,
) -> TrackCleanupResult:
    """原子清理赛道拥有的任务、关键词、达人及任务级结果。"""
    if not tracks:
        return TrackCleanupResult(0, 0, 0, 0, 0, 0, 0, stopped_task_count)

    track_ids = {track.id for track in tracks}
    scope = _build_track_cleanup_scope(session, track_ids)
    deleted_task_ids = scope.deleted_task_ids
    rehome_targets = scope.rehome_targets
    tasks = list(
        session.exec(
            select(CrawlTask).where(col(CrawlTask.id).in_(deleted_task_ids))
        ).all()
    )
    task_ids = {task.id for task in tasks}
    keywords = list(
        session.exec(
            select(DouyinKeyword).where(col(DouyinKeyword.track_id).in_(track_ids))
        ).all()
    )
    creators = list(
        session.exec(
            select(DouyinCreator).where(col(DouyinCreator.track_id).in_(track_ids))
        ).all()
    )
    preserved_target_pairs = {
        (item.task_id, item.aweme_id)
        for item in scope.target_awemes
        if item.task_id not in task_ids
    }

    def related_condition(model: Any) -> Any | None:
        conditions: list[Any] = []
        if task_ids:
            conditions.append(col(model.task_id).in_(task_ids))
        if preserved_target_pairs:
            conditions.append(
                tuple_(col(model.task_id), col(model.aweme_id)).in_(
                    preserved_target_pairs
                )
            )
        if not conditions:
            return None
        return conditions[0] if len(conditions) == 1 else or_(*conditions)

    aweme_conditions: list[Any] = []
    if task_ids:
        aweme_conditions.append(col(DouyinAweme.task_id).in_(task_ids))
    target_aweme_record_ids = {item.id for item in scope.target_awemes}
    if target_aweme_record_ids:
        aweme_conditions.append(col(DouyinAweme.id).in_(target_aweme_record_ids))
    aweme_condition = (
        None
        if not aweme_conditions
        else (
            aweme_conditions[0]
            if len(aweme_conditions) == 1
            else or_(*aweme_conditions)
        )
    )

    def related_count(model: Any, condition: Any | None) -> int:
        if condition is None:
            return 0
        return int(
            session.exec(select(func.count()).select_from(model).where(condition)).one()
        )

    aweme_count = related_count(DouyinAweme, aweme_condition)
    comment_condition = related_condition(DouyinComment)
    interaction_condition = related_condition(DouyinInteraction)
    comment_count = related_count(DouyinComment, comment_condition)
    interaction_count = related_count(DouyinInteraction, interaction_condition)
    candidate_tag_ids = (
        set(
            session.exec(
                select(DouyinAwemeTag.tag_id)
                .join(
                    DouyinAweme,
                    col(DouyinAweme.id) == col(DouyinAwemeTag.aweme_record_id),
                )
                .where(aweme_condition)
            ).all()
        )
        if aweme_condition is not None
        else set()
    )

    # 请求日志默认在任务删除后保留；赛道强制删除/重置明确要求彻底清理。
    if scope.affected_task_ids:
        session.exec(
            delete(DouyinRequestLog).where(
                col(DouyinRequestLog.task_id).in_(scope.affected_task_ids)
            )
        )

    # 共享任务只删除当前赛道动态归属的作品级数据，保留其他赛道的结果。
    for model in (
        DouyinInteraction,
        DouyinMediaAsset,
        DouyinComment,
        DouyinUserAction,
    ):
        condition = related_condition(model)
        if condition is not None:
            session.exec(delete(model).where(condition))
    if aweme_condition is not None:
        session.exec(delete(DouyinAweme).where(aweme_condition))
    if candidate_tag_ids:
        session.exec(
            delete(DouyinTag).where(
                col(DouyinTag.id).in_(candidate_tag_ids),
                col(DouyinTag.id).not_in(select(DouyinAwemeTag.tag_id)),
            )
        )

    removed_keywords = {item.normalized_keyword for item in keywords}
    removed_creator_sec_uids = {item.sec_uid for item in creators}
    removed_aweme_ids_by_task: dict[uuid.UUID, set[str]] = defaultdict(set)
    for item in scope.target_awemes:
        removed_aweme_ids_by_task[item.task_id].add(item.aweme_id)
    preserved_task_ids = scope.affected_task_ids - task_ids
    preserved_tasks = (
        session.exec(
            select(CrawlTask).where(col(CrawlTask.id).in_(preserved_task_ids))
        ).all()
        if preserved_task_ids
        else []
    )
    if preserved_task_ids:
        # 分片是按旧目标集合生成的执行快照，无法精确拆分其历史计数与断点。
        # 删除后若用户重启共享任务，任务管理器会基于净化后的父请求重新创建。
        session.exec(
            delete(CrawlTaskShard).where(
                col(CrawlTaskShard.task_id).in_(preserved_task_ids)
            )
        )
    now = get_datetime_utc()
    for task in preserved_tasks:
        target_track_id = rehome_targets.get(task.id)
        removed_aweme_ids = removed_aweme_ids_by_task.get(task.id, set())
        task.request_json = _sanitize_preserved_request_json(
            task.request_json,
            removed_keywords=removed_keywords,
            removed_creator_sec_uids=removed_creator_sec_uids,
            removed_aweme_ids=removed_aweme_ids,
            target_track_id=target_track_id,
        )
        task.checkpoint_json = _reset_crawl_checkpoint(task.checkpoint_json)
        task.aweme_count = int(
            session.exec(
                select(func.count())
                .select_from(DouyinAweme)
                .where(DouyinAweme.task_id == task.id)
            ).one()
        )
        task.comment_count = int(
            session.exec(
                select(func.count())
                .select_from(DouyinComment)
                .where(DouyinComment.task_id == task.id)
            ).one()
        )
        task.action_count = int(
            session.exec(
                select(func.count())
                .select_from(DouyinUserAction)
                .where(DouyinUserAction.task_id == task.id)
            ).one()
        )
        if task.status in ACTIVE_TASK_STATUSES:
            task.status = CrawlTaskStatus.cancelled.value
            task.error = "所属赛道已删除或重置，任务已停止"
            task.finished_at = now
            task.qrcode_path = None
        if target_track_id is None:
            session.add(task)
            continue
        target_track = session.get(DouyinTrack, target_track_id)
        if target_track is None:
            raise TrackConflictError("共享任务目标赛道不存在，请重试")
        assign_task_track(session, task=task, track=target_track)
    for task in tasks:
        session.delete(task)
    for keyword in keywords:
        session.delete(keyword)
    for creator in creators:
        session.delete(creator)
    if delete_tracks:
        for track in tracks:
            session.delete(track)
    session.commit()
    return TrackCleanupResult(
        track_count=len(tracks) if delete_tracks else 0,
        keyword_count=len(keywords),
        creator_count=len(creators),
        task_count=len(tasks),
        aweme_count=aweme_count,
        comment_count=comment_count,
        interaction_count=interaction_count,
        stopped_task_count=stopped_task_count,
    )


def append_track_keyword_records(
    session: Session,
    *,
    track_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
    keywords: list[str],
) -> DouyinKeywordsPublic:
    """向赛道追加关键词并提交事务，返回赛道最新关键词列表。"""
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
    """把关键词从赛道移除（实际迁移到默认赛道）并提交事务。

    异常：
        TrackNotFoundError: 赛道不存在、无权访问或关键词关联不存在。
        TrackConflictError: 默认赛道不能直接移除关键词（关键词必须归属一个赛道）。
    """
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


def build_track_creator_rows(
    session: Session,
    *,
    track: DouyinTrack,
) -> DouyinCreatorsPublic:
    """构建赛道下达人的对外列表（复用达人读侧行构建）。"""
    rows = build_creator_public_rows(
        session, owner_id=track.owner_id, track_id=track.id
    )
    return DouyinCreatorsPublic(data=rows, count=len(rows))


def add_track_creators(
    session: Session,
    *,
    track: DouyinTrack,
    owner_id: uuid.UUID,
    values: list[str],
) -> tuple[int, int]:
    """向赛道批量追加达人（复用达人服务创建），不提交事务。

    返回：
        (新创建的达人数, 达人总数) 元组。

    异常：
        TrackConflictError: 赛道已停用时抛出。
        TrackValidationError: 达人目标校验失败时抛出。
    """
    if not track.enabled:
        raise TrackConflictError("赛道已停用，不能添加达人")
    try:
        creators, created, _ = create_creators(
            session,
            owner_id=owner_id,
            creators=values,
            notes=f"赛道：{track.name}",
            track_id=track.id,
        )
    except CreatorValidationError as exc:
        raise TrackValidationError(str(exc)) from exc
    track.updated_at = get_datetime_utc()
    session.add(track)
    session.flush()
    return created, len(creators)


def append_track_creator_records(
    session: Session,
    *,
    track_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
    creators: list[str],
) -> DouyinCreatorsPublic:
    """向赛道追加达人并提交事务，返回赛道最新达人列表。"""
    track = get_track_for_actor(
        session,
        track_id=track_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    add_track_creators(
        session,
        track=track,
        owner_id=track.owner_id,
        values=creators,
    )
    session.commit()
    return build_track_creator_rows(session, track=track)


def remove_track_creator_record(
    session: Session,
    *,
    track_id: uuid.UUID,
    creator_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> None:
    """把达人从赛道移除（实际迁移到默认赛道）并提交事务。

    异常：
        TrackNotFoundError: 赛道不存在、无权访问或达人关联不存在。
        TrackConflictError: 默认赛道不能直接移除达人（达人必须归属一个赛道）。
    """
    track = get_track_for_actor(
        session,
        track_id=track_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    creator = session.get(DouyinCreator, creator_id)
    if creator is None or creator.track_id != track_id:
        raise TrackNotFoundError("赛道达人关联不存在")
    if track.is_default:
        raise TrackConflictError("达人必须归属一个赛道，不能从默认赛道直接移除")
    fallback = ensure_default_track(session, owner_id=track.owner_id)
    creator.track_id = fallback.id
    session.add(creator)
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
    """基于赛道关键词批量创建采集任务。

    按批量模式把选中的关键词分组（独立模式一词一任务，合并模式每 20 词一组），
    逐组委托任务管理器创建搜索采集任务，最后更新赛道时间戳并提交事务。

    参数：
        session: 数据库会话。
        track_id: 赛道 ID。
        actor_id: 操作者用户 ID。
        is_superuser: 是否为超级管理员。
        request: 赛道任务请求参数。

    返回：
        批量创建的任务列表结果。

    异常：
        TrackNotFoundError: 赛道不存在、无权访问或关键词不属于该赛道。
        TrackPermissionDeniedError: 不能为其他用户的赛道创建任务。
        TrackConflictError: 赛道或选中关键词已停用。
        TrackValidationError: 关键词与达人皆为空、分组超限或任务参数校验失败。
    """
    from crawler.business.douyin.tasks.query_service import build_tasks_public
    from crawler.business.douyin.tasks.service import task_manager

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
    # 仅用本次请求显式提交的字段覆盖赛道默认值；关键词/达人选择始终来自
    # 当前操作，避免前端为展示默认值而被迫重复提交整套参数。
    request_payload = DouyinTrackTaskDefaults.model_validate(
        track.default_task_config
    ).model_dump(mode="json")
    # Cookie 只在当前调用链内以 SecretStr 传递；绝不写入赛道默认配置、
    # 普通序列化字典或任务公开请求。
    runtime_cookies = request.cookies
    submitted_payload = request.model_dump(mode="json", exclude={"cookies"})
    for field_name in request.model_fields_set:
        if field_name == "cookies":
            continue
        request_payload[field_name] = submitted_payload[field_name]
    request_payload["keyword_ids"] = submitted_payload["keyword_ids"]
    request_payload["creator_ids"] = submitted_payload["creator_ids"]
    if runtime_cookies is not None:
        request_payload["cookies"] = runtime_cookies
    request = DouyinTrackTaskRequest.model_validate(request_payload)
    available = track_keywords(session, track_id=track.id)
    by_id = {item.id: item for item in available}
    creator_ids = list(dict.fromkeys(request.creator_ids))
    selected_ids = list(dict.fromkeys(request.keyword_ids))
    if not selected_ids and not creator_ids:
        # 向后兼容：关键词与达人都未指定时，默认运行该赛道全部已启用关键词
        selected_ids = [item.id for item in available if item.enabled]
    if not selected_ids and not creator_ids:
        raise TrackValidationError("请至少选择关键词或达人")
    if any(item_id not in by_id for item_id in selected_ids):
        raise TrackNotFoundError("部分关键词不属于该赛道")
    selected = [by_id[item_id] for item_id in selected_ids]
    if any(not item.enabled for item in selected):
        raise TrackConflictError("选中的关键词包含已停用项目")
    values = [item.keyword for item in selected]
    # 兼容旧客户端继续提交 mode 字段，但任务组织方式固定为一词一任务。
    groups = [[value] for value in values]

    tasks: list[CrawlTask] = []
    for group in groups:
        task_request = CrawlTaskCreate(
            track_id=track.id,
            crawl_type=DouyinCrawlType.search,
            login_type=request.login_type,
            browser_mode=request.browser_mode,
            cookies=request.cookies,
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
            task = await task_manager.create(owner_id=actor_id, request=task_request)
        except ValueError as exc:
            raise TrackValidationError(str(exc)) from exc
        if task.track_id != track.id:
            raise TrackValidationError("任务创建后的赛道归属不一致")
        tasks.append(task)
    creator_public: list[Any] = []
    if creator_ids:
        _validate_track_creators(
            session,
            owner_id=actor_id,
            track_id=track.id,
            creator_ids=creator_ids,
        )
        creator_public = await _create_track_creator_tasks(
            session,
            owner_id=actor_id,
            track_id=track.id,
            creator_ids=creator_ids,
            request=request,
        )
    track.updated_at = get_datetime_utc()
    session.add(track)
    session.commit()
    public_tasks = build_tasks_public(session, tasks=tasks)
    public_tasks.extend(creator_public)
    return DouyinKeywordTaskBatchResult(
        data=public_tasks,
        count=len(public_tasks),
    )


def _validate_track_creators(
    session: Session,
    *,
    owner_id: uuid.UUID,
    track_id: uuid.UUID,
    creator_ids: list[uuid.UUID],
) -> None:
    """校验赛道运行选中的达人：存在、属于该赛道、启用且非待补全。

    在创建关键词任务之前先行校验，避免关键词任务已创建而达人校验
    失败导致的部分成功副作用。

    异常：
        TrackValidationError: 达人不存在、不属于该赛道或含待补全项目。
        TrackConflictError: 选中的达人包含已停用项目。
    """
    from crawler.business.douyin.creators.models import DouyinCreator

    rows = session.exec(
        select(DouyinCreator).where(
            DouyinCreator.owner_id == owner_id,
            col(DouyinCreator.id).in_(creator_ids),
        )
    ).all()
    by_id = {item.id: item for item in rows}
    if len(by_id) != len(creator_ids):
        raise TrackValidationError("部分达人不存在或无权访问")
    for creator_id in creator_ids:
        creator = by_id[creator_id]
        if creator.track_id != track_id:
            raise TrackValidationError("部分达人不在该赛道下")
        if not creator.enabled:
            raise TrackConflictError("选中的达人包含已停用项目")
        if creator.is_placeholder:
            raise TrackConflictError("选中的达人包含待补全项目，请先补全主页链接")


async def _create_track_creator_tasks(
    session: Session,
    *,
    owner_id: uuid.UUID,
    track_id: uuid.UUID,
    creator_ids: list[uuid.UUID],
    request: DouyinTrackTaskRequest,
) -> list[CrawlTaskPublic]:
    """为赛道运行的选中达人创建达人采集任务（每达人一个独立任务）。

    复用达人批量建任务服务做赛道归属校验，把达人侧的校验错误
    统一转译为赛道任务错误。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 ID。
        track_id: 目标赛道 ID。
        creator_ids: 选中的达人 ID（已去重）。
        request: 赛道任务请求（采集参数透传）。

    返回：
        新建的达人任务列表。
    """
    from crawler.business.douyin.creators.models import (
        DouyinCreatorBatchTaskRequest,
    )
    from crawler.business.douyin.creators.service import (
        CreatorConflictError,
        CreatorNotFoundError,
        CreatorValidationError,
        create_creator_crawl_tasks,
    )

    try:
        result = await create_creator_crawl_tasks(
            session,
            owner_id=owner_id,
            request=DouyinCreatorBatchTaskRequest(
                creator_ids=creator_ids,
                track_id=track_id,
                login_type=request.login_type,
                browser_mode=request.browser_mode,
                cookies=request.cookies,
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
            ),
        )
    except (
        CreatorNotFoundError,
        CreatorValidationError,
        CreatorConflictError,
    ) as exc:
        raise TrackValidationError(str(exc)) from exc
    return result.data
