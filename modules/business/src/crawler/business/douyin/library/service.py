"""抖音作品库的读侧用例与授权校验服务。

覆盖作品库/任务内作品的多条件分页查询、创作者聚合选项、
以及从既有作品派生评论补采、作者采集任务的创建入口。
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from crawler.business.douyin.comments.models import (
    DouyinAwemeCommentCrawlRequest,
    DouyinComment,
)
from crawler.business.douyin.content.models import (
    DouyinAweme,
    DouyinAwemeCreatorCrawlRequest,
    DouyinAwemePublic,
    DouyinAwemesPublic,
    DouyinCreatorOptionPublic,
    DouyinCreatorOptionsPublic,
)
from crawler.business.douyin.library.models import DouyinWorkPublic, DouyinWorksPublic
from crawler.business.douyin.media.models import DouyinMediaAsset, DouyinSubtitle
from crawler.business.douyin.media.pipeline import media_public
from crawler.business.douyin.tags.models import (
    DouyinAwemeTag,
    DouyinTag,
    DouyinTagRefPublic,
)
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskPublic,
    DouyinCrawlType,
    DouyinLoginType,
)
from crawler.business.douyin.tasks.query_service import (
    build_tasks_public,
    require_task_access,
)
from crawler.business.douyin.tasks.service import task_manager
from crawler.business.errors import InvalidRequestError, ResourceNotFoundError
from sqlmodel import Session, col, func, select


def get_aweme_for_user(
    session: Session,
    *,
    task_id: uuid.UUID,
    aweme_id: str,
    owner_id: uuid.UUID | None,
) -> DouyinAweme:
    """按任务与作品号获取作品记录，并校验任务访问权限。

    参数：
        session: 数据库会话。
        task_id: 作品所属采集任务 ID。
        aweme_id: 作品号。
        owner_id: 数据归属用户 ID，用于租户隔离；None 表示超管不过滤。

    返回：
        匹配的作品实体。

    异常：
        ResourceNotFoundError: 任务无权访问，或作品在该任务下不存在。
    """
    require_task_access(session, task_id=task_id, owner_id=owner_id)
    aweme = session.exec(
        select(DouyinAweme).where(
            DouyinAweme.task_id == task_id,
            DouyinAweme.aweme_id == aweme_id,
        )
    ).first()
    if aweme is None:
        raise ResourceNotFoundError("Douyin aweme not found")
    return aweme


async def create_aweme_comment_recrawl_task(
    session: Session,
    *,
    source_task_id: uuid.UUID,
    aweme_id: str,
    source_owner_id: uuid.UUID | None,
    new_task_owner_id: uuid.UUID,
    request: DouyinAwemeCommentCrawlRequest,
) -> CrawlTaskPublic:
    """基于既有作品创建一个单作品评论补采任务。

    参数：
        session: 数据库会话。
        source_task_id: 来源任务 ID（作品所在任务）。
        aweme_id: 待补采评论的作品号。
        source_owner_id: 来源任务的归属用户 ID，用于读权限校验；None 表示超管。
        new_task_owner_id: 新建任务的归属用户 ID。
        request: 评论补采参数（浏览器模式、cookies、评论数量等）。

    返回：
        新创建的采集任务公开模型。

    异常：
        ResourceNotFoundError: 来源任务或作品不存在、无权访问。
        InvalidRequestError: 任务创建参数被任务管理器拒绝。
    """
    source_task = require_task_access(
        session,
        task_id=source_task_id,
        owner_id=source_owner_id,
    )
    aweme = get_aweme_for_user(
        session,
        task_id=source_task_id,
        aweme_id=aweme_id,
        owner_id=source_owner_id,
    )
    cookies = request.cookies.get_secret_value().strip() if request.cookies else ""
    crawl_request = CrawlTaskCreate(
        # 超管可以读取他人名下的来源作品，但派生任务绝不能
        # 继承属于其他用户的赛道归属。
        track_id=(
            source_task.track_id if source_task.owner_id == new_task_owner_id else None
        ),
        crawl_type=DouyinCrawlType.detail,
        login_type=(DouyinLoginType.cookie if cookies else DouyinLoginType.qrcode),
        browser_mode=request.browser_mode,
        cookies=cookies or None,
        video_ids=[aweme.aweme_id],
        max_awemes=1,
        fetch_comments=True,
        fetch_sub_comments=request.fetch_sub_comments,
        max_comments_per_aweme=request.max_comments_per_aweme,
        concurrency=request.concurrency,
        request_delay_level=request.request_delay_level,
        request_interval_seconds=request.request_interval_seconds,
        account_id=request.account_id,
    )
    try:
        task = await task_manager.create(
            owner_id=new_task_owner_id,
            request=crawl_request,
        )
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc
    return build_tasks_public(session, tasks=[task])[0]


async def create_aweme_creator_crawl_task(
    session: Session,
    *,
    source_task_id: uuid.UUID,
    aweme_id: str,
    source_owner_id: uuid.UUID | None,
    new_task_owner_id: uuid.UUID,
    request: DouyinAwemeCreatorCrawlRequest,
) -> CrawlTaskPublic:
    """基于既有作品创建一个「采集该作品作者主页作品」的任务。

    参数：
        session: 数据库会话。
        source_task_id: 来源任务 ID（作品所在任务）。
        aweme_id: 目标作者关联的作品号。
        source_owner_id: 来源任务的归属用户 ID，用于读权限校验；None 表示超管。
        new_task_owner_id: 新建任务的归属用户 ID。
        request: 作者采集参数（采集数量、评论开关、浏览器模式等）。

    返回：
        新创建的采集任务公开模型。

    异常：
        ResourceNotFoundError: 来源任务或作品不存在、无权访问。
        InvalidRequestError: 任务创建参数被任务管理器拒绝。
    """
    source_task = require_task_access(
        session,
        task_id=source_task_id,
        owner_id=source_owner_id,
    )
    aweme = get_aweme_for_user(
        session,
        task_id=source_task_id,
        aweme_id=aweme_id,
        owner_id=source_owner_id,
    )
    cookies = request.cookies.get_secret_value().strip() if request.cookies else ""
    crawl_request = CrawlTaskCreate(
        track_id=(
            source_task.track_id if source_task.owner_id == new_task_owner_id else None
        ),
        crawl_type=DouyinCrawlType.creator_from_aweme,
        login_type=(DouyinLoginType.cookie if cookies else DouyinLoginType.qrcode),
        browser_mode=request.browser_mode,
        cookies=cookies or None,
        video_ids=[aweme.aweme_id],
        max_awemes=request.max_awemes,
        fetch_comments=request.fetch_comments,
        fetch_sub_comments=request.fetch_sub_comments,
        max_comments_per_aweme=request.max_comments_per_aweme,
        concurrency=request.concurrency,
        request_delay_level=request.request_delay_level,
        request_interval_seconds=request.request_interval_seconds,
        account_id=request.account_id,
    )
    try:
        task = await task_manager.create(
            owner_id=new_task_owner_id,
            request=crawl_request,
        )
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc
    return build_tasks_public(session, tasks=[task])[0]


def _tag_map(
    session: Session, aweme_record_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[DouyinTagRefPublic]]:
    """批量查询作品记录的标签，返回 {作品记录ID: 标签列表} 映射（按标签名排序）。"""
    if not aweme_record_ids:
        return {}
    rows = session.exec(
        select(DouyinAwemeTag.aweme_record_id, DouyinTag)
        .join(DouyinTag, col(DouyinTag.id) == col(DouyinAwemeTag.tag_id))
        .where(col(DouyinAwemeTag.aweme_record_id).in_(set(aweme_record_ids)))
        .order_by(DouyinTag.name)
    ).all()
    result: dict[uuid.UUID, list[DouyinTagRefPublic]] = {}
    for aweme_record_id, tag in rows:
        result.setdefault(aweme_record_id, []).append(
            DouyinTagRefPublic(id=tag.id, name=tag.name)
        )
    return result


def _library_filters(
    *,
    owner_id: uuid.UUID | None,
    search: str | None,
    task_id: uuid.UUID | None,
    track_id: uuid.UUID | None,
    creator_hash: str | None,
    tag_id: uuid.UUID | None,
    download_status: str,
    subtitle_status: str,
    storage_backend: str,
) -> list[Any]:
    """组装作品库查询的 WHERE 条件列表；download/subtitle/storage 为 "all" 时不过滤。"""
    filters: list[Any] = []
    if owner_id is not None:
        filters.append(CrawlTask.owner_id == owner_id)
    if task_id:
        filters.append(DouyinAweme.task_id == task_id)
    if track_id:
        filters.append(CrawlTask.track_id == track_id)
    if creator_hash:
        # 同时匹配两种脱敏标识：creator_hash（uid 哈希，库内聚合视图）
        # 与 sec_uid（sec_user_id 哈希，达人名单深链），保证新旧入口兼容。
        filters.append(
            (DouyinAweme.creator_hash == creator_hash)
            | (DouyinAweme.sec_uid == creator_hash)
        )
    if tag_id:
        filters.append(
            col(DouyinAweme.id).in_(
                select(DouyinAwemeTag.aweme_record_id).where(
                    DouyinAwemeTag.tag_id == tag_id
                )
            )
        )
    if search and search.strip():
        term = f"%{search.strip()}%"
        filters.append(
            col(DouyinAweme.title).ilike(term)
            | col(DouyinAweme.description).ilike(term)
            | col(DouyinAweme.nickname).ilike(term)
            | col(DouyinAweme.aweme_id).ilike(term)
        )
    if download_status != "all":
        filters.append(DouyinMediaAsset.status == download_status)
    if subtitle_status != "all":
        filters.append(DouyinSubtitle.status == subtitle_status)
    if storage_backend != "all":
        filters.append(DouyinMediaAsset.storage_backend == storage_backend)
    return filters


def list_library_creators(
    session: Session,
    *,
    owner_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
    track_id: uuid.UUID | None,
    downloaded_status: str,
) -> DouyinCreatorOptionsPublic:
    """聚合作品库中的创作者选项（用于筛选下拉），按作品数倒序，最多 500 个。

    参数：
        session: 数据库会话。
        owner_id: 数据归属用户 ID，用于租户隔离；None 表示超管不过滤。
        task_id: 限定任务 ID。
        track_id: 限定赛道 ID。
        downloaded_status: 媒体资产下载状态过滤值。

    返回：
        创作者选项列表（creator_hash、昵称、作品数）与总数。

    异常：
        ResourceNotFoundError: 任务或赛道不存在、无权访问。
        InvalidRequestError: 指定任务不属于所选赛道。
    """
    if task_id:
        require_task_access(session, task_id=task_id, owner_id=owner_id)
    _require_track_filter(
        session,
        owner_id=owner_id,
        track_id=track_id,
        task_id=task_id,
    )
    filters: list[Any] = [
        DouyinMediaAsset.status == downloaded_status,
        DouyinAweme.creator_hash != "",
    ]
    if owner_id is not None:
        filters.append(CrawlTask.owner_id == owner_id)
    if task_id:
        filters.append(DouyinAweme.task_id == task_id)
    if track_id:
        filters.append(CrawlTask.track_id == track_id)
    rows = session.exec(
        select(
            DouyinAweme.creator_hash,
            DouyinAweme.nickname,
            func.count(col(DouyinAweme.id)).label("work_count"),
        )
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
        .join(
            DouyinMediaAsset,
            (col(DouyinMediaAsset.task_id) == col(DouyinAweme.task_id))
            & (col(DouyinMediaAsset.aweme_id) == col(DouyinAweme.aweme_id)),
        )
        .where(*filters)
        .group_by(DouyinAweme.creator_hash, DouyinAweme.nickname)
        .order_by(func.count(col(DouyinAweme.id)).desc(), DouyinAweme.nickname)
        .limit(500)
    ).all()
    return DouyinCreatorOptionsPublic(
        data=[
            DouyinCreatorOptionPublic(
                creator_hash=creator_hash,
                nickname=nickname or "匿名创作者",
                work_count=int(work_count),
            )
            for creator_hash, nickname, work_count in rows
        ],
        count=len(rows),
    )


def list_library_works(
    session: Session,
    *,
    owner_id: uuid.UUID | None,
    search: str | None,
    task_id: uuid.UUID | None,
    track_id: uuid.UUID | None,
    creator_hash: str | None,
    tag_id: uuid.UUID | None,
    download_status: str,
    subtitle_status: str,
    storage_backend: str,
    sort_by: Literal[
        "published_at",
        "liked_count",
        "comment_count",
        "collected_count",
        "persisted_comment_count",
        "downloaded_at",
        "file_size",
        "fetched_at",
    ],
    sort_order: Literal["asc", "desc"],
    skip: int,
    limit: int,
) -> DouyinWorksPublic:
    """作品库跨任务多条件分页查询，聚合媒体资产、字幕、标签与已存评论数。

    参数：
        session: 数据库会话。
        owner_id: 数据归属用户 ID，用于租户隔离；None 表示超管不过滤。
        search: 全局模糊搜索词（匹配标题/描述/作者昵称/作品号）。
        task_id: 限定任务 ID。
        track_id: 限定赛道 ID。
        creator_hash: 限定创作者脱敏标识。
        tag_id: 限定标签 ID。
        download_status: 下载状态过滤，"all" 表示不过滤。
        subtitle_status: 字幕状态过滤，"all" 表示不过滤。
        storage_backend: 存储后端过滤，"all" 表示不过滤。
        sort_by: 排序字段。
        sort_order: 排序方向（asc/desc）。
        skip: 分页偏移量。
        limit: 分页大小。

    返回：
        分页作品列表与总数。

    异常：
        ResourceNotFoundError: 任务或赛道不存在、无权访问。
        InvalidRequestError: 指定任务不属于所选赛道。
    """
    if task_id:
        require_task_access(session, task_id=task_id, owner_id=owner_id)
    _require_track_filter(
        session,
        owner_id=owner_id,
        track_id=track_id,
        task_id=task_id,
    )
    comment_counts = (
        select(
            DouyinComment.task_id,
            DouyinComment.aweme_id,
            func.count(col(DouyinComment.id)).label("persisted_comment_count"),
        )
        .group_by(col(DouyinComment.task_id), col(DouyinComment.aweme_id))
        .subquery()
    )
    persisted_count = func.coalesce(comment_counts.c.persisted_comment_count, 0).label(
        "persisted_comment_count"
    )
    filters = _library_filters(
        owner_id=owner_id,
        search=search,
        task_id=task_id,
        track_id=track_id,
        creator_hash=creator_hash,
        tag_id=tag_id,
        download_status=download_status,
        subtitle_status=subtitle_status,
        storage_backend=storage_backend,
    )
    base = (
        select(DouyinAweme.id)
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
        .outerjoin(
            DouyinMediaAsset,
            (col(DouyinMediaAsset.task_id) == col(DouyinAweme.task_id))
            & (col(DouyinMediaAsset.aweme_id) == col(DouyinAweme.aweme_id)),
        )
        .outerjoin(
            DouyinSubtitle,
            col(DouyinSubtitle.asset_id) == col(DouyinMediaAsset.id),
        )
        .where(*filters)
    )
    count = session.exec(select(func.count()).select_from(base.subquery())).one()
    sort_column = {
        "published_at": DouyinAweme.create_time,
        "liked_count": DouyinAweme.liked_count,
        "comment_count": DouyinAweme.comment_count,
        "collected_count": DouyinAweme.collected_count,
        "persisted_comment_count": persisted_count,
        "downloaded_at": DouyinMediaAsset.completed_at,
        "file_size": DouyinMediaAsset.file_size,
        "fetched_at": DouyinAweme.fetched_at,
    }[sort_by]
    order_expression = (
        col(sort_column).asc() if sort_order == "asc" else col(sort_column).desc()
    ).nulls_last()
    rows = session.exec(
        select(DouyinAweme, DouyinMediaAsset, DouyinSubtitle, persisted_count)
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
        .outerjoin(
            DouyinMediaAsset,
            (col(DouyinMediaAsset.task_id) == col(DouyinAweme.task_id))
            & (col(DouyinMediaAsset.aweme_id) == col(DouyinAweme.aweme_id)),
        )
        .outerjoin(
            DouyinSubtitle,
            col(DouyinSubtitle.asset_id) == col(DouyinMediaAsset.id),
        )
        .outerjoin(
            comment_counts,
            (comment_counts.c.task_id == DouyinAweme.task_id)
            & (comment_counts.c.aweme_id == DouyinAweme.aweme_id),
        )
        .where(*filters)
        .order_by(order_expression, col(DouyinAweme.fetched_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    tag_map = _tag_map(session, [aweme.id for aweme, *_ in rows])
    return DouyinWorksPublic(
        data=[
            DouyinWorkPublic(
                aweme=DouyinAwemePublic.model_validate(aweme),
                persisted_comment_count=int(saved_count),
                media=media_public(asset, subtitle) if asset else None,
                tags=tag_map.get(aweme.id, []),
            )
            for aweme, asset, subtitle, saved_count in rows
        ],
        count=count,
    )


def list_task_works(
    session: Session,
    *,
    task_id: uuid.UUID,
    search: str | None,
    tag_id: uuid.UUID | None,
    download_status: str | None,
    subtitle_status: str | None,
    storage_backend: str | None,
    sort_by: Literal[
        "published_at",
        "liked_count",
        "comment_count",
        "collected_count",
        "persisted_comment_count",
        "fetched_at",
    ],
    sort_order: Literal["asc", "desc"],
    skip: int,
    limit: int,
) -> DouyinWorksPublic:
    """查询单个任务下的作品分页列表，聚合媒体资产、字幕、标签与已存评论数。

    与 list_library_works 的差别：限定单一任务，且状态过滤参数为可选
    （None 表示不过滤），不做归属校验（调用方需先校验任务访问权限）。

    参数：
        session: 数据库会话。
        task_id: 采集任务 ID。
        search: 全局模糊搜索词（匹配标题/作者昵称/作品号）。
        tag_id: 限定标签 ID。
        download_status: 下载状态过滤，None 表示不过滤。
        subtitle_status: 字幕状态过滤，None 表示不过滤。
        storage_backend: 存储后端过滤，None 表示不过滤。
        sort_by: 排序字段。
        sort_order: 排序方向（asc/desc）。
        skip: 分页偏移量。
        limit: 分页大小。

    返回：
        分页作品列表与总数。
    """
    comment_counts = (
        select(
            DouyinComment.aweme_id,
            func.count(col(DouyinComment.id)).label("persisted_comment_count"),
        )
        .where(DouyinComment.task_id == task_id)
        .group_by(DouyinComment.aweme_id)
        .subquery()
    )
    persisted_count = func.coalesce(comment_counts.c.persisted_comment_count, 0).label(
        "persisted_comment_count"
    )
    filters: list[Any] = [DouyinAweme.task_id == task_id]
    if search and search.strip():
        term = f"%{search.strip()}%"
        filters.append(
            col(DouyinAweme.title).ilike(term)
            | col(DouyinAweme.nickname).ilike(term)
            | col(DouyinAweme.aweme_id).ilike(term)
        )
    if tag_id:
        filters.append(
            col(DouyinAweme.id).in_(
                select(DouyinAwemeTag.aweme_record_id).where(
                    DouyinAwemeTag.tag_id == tag_id
                )
            )
        )
    if download_status:
        filters.append(DouyinMediaAsset.status == download_status)
    if subtitle_status:
        filters.append(DouyinSubtitle.status == subtitle_status)
    if storage_backend:
        filters.append(DouyinMediaAsset.storage_backend == storage_backend)
    base = (
        select(DouyinAweme)
        .outerjoin(
            DouyinMediaAsset,
            (col(DouyinMediaAsset.task_id) == col(DouyinAweme.task_id))
            & (col(DouyinMediaAsset.aweme_id) == col(DouyinAweme.aweme_id)),
        )
        .outerjoin(
            DouyinSubtitle,
            col(DouyinSubtitle.asset_id) == col(DouyinMediaAsset.id),
        )
        .outerjoin(comment_counts, comment_counts.c.aweme_id == DouyinAweme.aweme_id)
        .where(*filters)
    )
    count = session.exec(select(func.count()).select_from(base.subquery())).one()
    sort_column = {
        "published_at": DouyinAweme.create_time,
        "liked_count": DouyinAweme.liked_count,
        "comment_count": DouyinAweme.comment_count,
        "collected_count": DouyinAweme.collected_count,
        "persisted_comment_count": persisted_count,
        "fetched_at": DouyinAweme.fetched_at,
    }[sort_by]
    order_expression = (
        col(sort_column).asc() if sort_order == "asc" else col(sort_column).desc()
    ).nulls_last()
    rows = session.exec(
        select(DouyinAweme, DouyinMediaAsset, DouyinSubtitle, persisted_count)
        .outerjoin(
            DouyinMediaAsset,
            (col(DouyinMediaAsset.task_id) == col(DouyinAweme.task_id))
            & (col(DouyinMediaAsset.aweme_id) == col(DouyinAweme.aweme_id)),
        )
        .outerjoin(
            DouyinSubtitle,
            col(DouyinSubtitle.asset_id) == col(DouyinMediaAsset.id),
        )
        .outerjoin(comment_counts, comment_counts.c.aweme_id == DouyinAweme.aweme_id)
        .where(*filters)
        .order_by(order_expression, col(DouyinAweme.fetched_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    tag_map = _tag_map(session, [aweme.id for aweme, *_ in rows])
    return DouyinWorksPublic(
        data=[
            DouyinWorkPublic(
                aweme=DouyinAwemePublic.model_validate(aweme),
                persisted_comment_count=int(saved_count),
                media=media_public(asset, subtitle) if asset else None,
                tags=tag_map.get(aweme.id, []),
            )
            for aweme, asset, subtitle, saved_count in rows
        ],
        count=count,
    )


def get_task_work(
    session: Session,
    *,
    task_id: uuid.UUID,
    aweme: DouyinAweme,
) -> DouyinWorkPublic:
    """获取单个作品的详情视图，聚合媒体资产、字幕、标签与已存评论数。

    参数：
        session: 数据库会话。
        task_id: 作品所属采集任务 ID。
        aweme: 已取出的作品实体（调用方负责权限校验与存在性检查）。

    返回：
        作品详情公开模型；无媒体资产时 media 为 None。
    """
    row = session.exec(
        select(DouyinMediaAsset, DouyinSubtitle)
        .outerjoin(
            DouyinSubtitle,
            col(DouyinSubtitle.asset_id) == col(DouyinMediaAsset.id),
        )
        .where(
            DouyinMediaAsset.task_id == task_id,
            DouyinMediaAsset.aweme_id == aweme.aweme_id,
        )
    ).first()
    saved_count = session.exec(
        select(func.count())
        .select_from(DouyinComment)
        .where(
            DouyinComment.task_id == task_id,
            DouyinComment.aweme_id == aweme.aweme_id,
        )
    ).one()
    asset, subtitle = row if row else (None, None)
    return DouyinWorkPublic(
        aweme=DouyinAwemePublic.model_validate(aweme),
        persisted_comment_count=saved_count,
        media=media_public(asset, subtitle) if asset else None,
        tags=_tag_map(session, [aweme.id]).get(aweme.id, []),
    )


def list_task_awemes(
    session: Session,
    *,
    task_id: uuid.UUID,
    sort_by: Literal[
        "published_at", "liked_count", "comment_count", "collected_count", "fetched_at"
    ],
    sort_order: Literal["asc", "desc"],
    skip: int,
    limit: int,
) -> DouyinAwemesPublic:
    """查询单个任务下的作品基础信息分页列表（不含媒体/标签聚合）。

    参数：
        session: 数据库会话。
        task_id: 采集任务 ID。
        sort_by: 排序字段。
        sort_order: 排序方向（asc/desc）。
        skip: 分页偏移量。
        limit: 分页大小。

    返回：
        分页作品基础信息列表与总数。
    """
    count = session.exec(
        select(func.count())
        .select_from(DouyinAweme)
        .where(DouyinAweme.task_id == task_id)
    ).one()
    sort_column = {
        "published_at": DouyinAweme.create_time,
        "liked_count": DouyinAweme.liked_count,
        "comment_count": DouyinAweme.comment_count,
        "collected_count": DouyinAweme.collected_count,
        "fetched_at": DouyinAweme.fetched_at,
    }[sort_by]
    order_expression = (
        col(sort_column).asc() if sort_order == "asc" else col(sort_column).desc()
    ).nulls_last()
    data = session.exec(
        select(DouyinAweme)
        .where(DouyinAweme.task_id == task_id)
        .order_by(order_expression, col(DouyinAweme.fetched_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return DouyinAwemesPublic(data=data, count=count)


def list_library_media_candidates(
    session: Session,
    *,
    owner_id: uuid.UUID | None,
    search: str | None,
    task_id: uuid.UUID | None,
    track_id: uuid.UUID | None,
    creator_hash: str | None,
    tag_id: uuid.UUID | None,
    downloaded_status: str,
    subtitle_status: str,
    local_backend: str,
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """按作品库筛选条件找出候选媒体资产，用于批量媒体操作（如迁移、重试）。

    参数：
        session: 数据库会话。
        owner_id: 数据归属用户 ID，用于租户隔离；None 表示超管不过滤。
        search: 全局模糊搜索词。
        task_id: 限定任务 ID。
        track_id: 限定赛道 ID。
        creator_hash: 限定创作者脱敏标识。
        tag_id: 限定标签 ID。
        downloaded_status: 下载状态过滤值。
        subtitle_status: 字幕状态过滤值。
        local_backend: 存储后端过滤值。

    返回：
        (任务ID, 媒体资产ID) 元组列表（去重）。

    异常：
        ResourceNotFoundError: 任务或赛道不存在、无权访问。
        InvalidRequestError: 指定任务不属于所选赛道。
    """
    if task_id:
        require_task_access(session, task_id=task_id, owner_id=owner_id)
    _require_track_filter(
        session,
        owner_id=owner_id,
        track_id=track_id,
        task_id=task_id,
    )
    filters = _library_filters(
        owner_id=owner_id,
        search=search,
        task_id=task_id,
        track_id=track_id,
        creator_hash=creator_hash,
        tag_id=tag_id,
        download_status=downloaded_status,
        subtitle_status=subtitle_status,
        storage_backend=local_backend,
    )
    return list(
        session.exec(
            select(DouyinMediaAsset.task_id, DouyinMediaAsset.id)
            .join(
                DouyinAweme,
                (col(DouyinAweme.task_id) == col(DouyinMediaAsset.task_id))
                & (col(DouyinAweme.aweme_id) == col(DouyinMediaAsset.aweme_id)),
            )
            .join(CrawlTask, col(CrawlTask.id) == col(DouyinMediaAsset.task_id))
            .outerjoin(
                DouyinSubtitle,
                col(DouyinSubtitle.asset_id) == col(DouyinMediaAsset.id),
            )
            .where(*filters)
            .distinct()
        ).all()
    )


def _require_track_filter(
    session: Session,
    *,
    owner_id: uuid.UUID | None,
    track_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
) -> None:
    """校验赛道筛选条件：赛道须存在且归当前用户所有，且与 task_id 筛选不冲突。"""
    if track_id is None:
        return
    from crawler.business.douyin.tracks.models import DouyinTrack

    track = session.get(DouyinTrack, track_id)
    if track is None or (owner_id is not None and track.owner_id != owner_id):
        raise ResourceNotFoundError("赛道不存在或无权访问")
    if task_id is not None:
        task = require_task_access(session, task_id=task_id, owner_id=owner_id)
        if task.track_id != track_id:
            raise InvalidRequestError("任务不属于所选赛道，请调整筛选条件")


__all__ = [
    "create_aweme_comment_recrawl_task",
    "create_aweme_creator_crawl_task",
    "get_aweme_for_user",
    "get_task_work",
    "list_library_creators",
    "list_library_media_candidates",
    "list_library_works",
    "list_task_awemes",
    "list_task_works",
    "require_task_access",
]
