"""关键词库的读侧应用服务（查询服务）。

提供关键词列表的多条件筛选、内存排序与分页查询，以及
单个关键词关联任务列表查询，供 API 层直接调用。
"""

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
    category: str | None,
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
    """查询当前用户的关键词列表，支持筛选、排序与分页（在内存中完成排序分页）。

    参数：
        session: 数据库会话。
        owner_id: 当前用户 ID，仅返回其名下的关键词。
        search: 模糊搜索词（匹配关键词与备注）。
        track_id: 限定赛道 ID。
        keyword_status: 限定关键词状态，None 表示不过滤。
        enabled: 限定启用状态，None 表示不过滤。
        sort_by: 排序字段；status 按 进行中>失败>未处理>已采集 的业务优先级排序。
        sort_order: 排序方向（asc/desc）。
        skip: 分页偏移量。
        limit: 分页大小。

    返回：
        分页关键词列表与总数。

    异常：
        KeywordNotFoundError: 指定赛道不存在或无权访问。
    """
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
    if category is not None:
        normalized_category = category.strip().casefold()
        rows = [
            item for item in rows if item.category.casefold() == normalized_category
        ]
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
    """查询关键词关联的全部采集任务（按创建时间倒序）。

    参数：
        session: 数据库会话。
        keyword_id: 关键词 ID。
        actor_id: 当前操作用户 ID。
        is_superuser: 是否为超管（超管可查看任意用户的关键词）。

    返回：
        关联任务的公开模型列表。

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
    return build_tasks_public(
        session,
        tasks=keyword_tasks(session, keyword_id=item.id),
    )
