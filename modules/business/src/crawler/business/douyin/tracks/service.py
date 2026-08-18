"""抖音赛道的写侧应用服务与领域逻辑。

负责赛道的创建、更新、删除（含记录迁移到默认赛道）、关键词追加/移除，
以及基于赛道关键词批量创建采集任务；读侧查询见 query_service。
"""

import uuid
from collections import defaultdict

from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.keywords.models import (
    DouyinKeyword,
    DouyinKeywordBatchMode,
    DouyinKeywordsPublic,
    DouyinKeywordTaskBatchResult,
)
from crawler.business.douyin.keywords.service import (
    ACTIVE_TASK_STATUSES,
    KeywordValidationError,
    build_keyword_public_rows,
    create_keywords,
)
from crawler.business.douyin.media.models import MediaProcessingMode
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskStatus,
    DouyinCrawlType,
)
from crawler.business.douyin.tracks.bindings import (
    assign_keyword_track,
    assign_task_track,
    ensure_default_track,
)
from crawler.business.douyin.tracks.models import (
    DouyinTrack,
    DouyinTrackDetailPublic,
    DouyinTrackPublic,
    DouyinTrackTaskRequest,
)
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select


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
    return DouyinTrackDetailPublic(**summary.model_dump(), prompt=track.prompt)


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
) -> DouyinTrackDetailPublic:
    """创建赛道并提交事务，返回赛道详情。"""
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
    """删除赛道并提交事务；其关键词与任务先迁移到默认赛道。

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
    _rehome_track_records(session, track=track)
    session.delete(track)
    session.commit()


def _rehome_track_records(session: Session, *, track: DouyinTrack) -> None:
    """把赛道下的关键词与任务全部迁移到默认赛道。"""
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
    """批量删除用户的赛道，返回实际删除数量；默认赛道在列时整体拒绝。

    异常：
        TrackConflictError: 待删集合中包含默认赛道。
    """
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
        TrackValidationError: 关键词为空、分组超限或任务参数校验失败。
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
