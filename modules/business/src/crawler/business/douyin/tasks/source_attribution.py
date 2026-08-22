"""抖音任务与作品的来源归因及按赛道来源筛选。

关键词、作者与任务的绑定关系已经由各自的关联表维护。本模块只负责把这些
关系组装成列表展示字段和可复用的筛选条件，不向数据库增加重复的来源字段。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.creators.models import (
    DouyinCreator,
    DouyinCreatorTaskLink,
)
from crawler.business.douyin.keywords.models import (
    DouyinKeyword,
    DouyinKeywordTaskLink,
)
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    DouyinCrawlType,
    DouyinSourceOptionPublic,
    DouyinSourceOptionsPublic,
    DouyinSourceType,
)
from crawler.business.douyin.tracks.models import DouyinTrack
from crawler.business.errors import InvalidRequestError, ResourceNotFoundError
from sqlalchemy import func, or_
from sqlmodel import Session, col, select


@dataclass(frozen=True, slots=True)
class ResolvedSourceFilter:
    """已校验的关键词/作者来源筛选条件。"""

    source_type: DouyinSourceType
    source_id: uuid.UUID
    track_id: uuid.UUID
    task_ids: frozenset[uuid.UUID]
    normalized_name: str | None = None
    creator_hash: str | None = None


@dataclass(frozen=True, slots=True)
class _SourceName:
    id: uuid.UUID
    name: str
    normalized_name: str | None = None
    creator_hash: str | None = None


def _normalize(value: str) -> str:
    """按关键词库的业务规则归一化用于比较的文本。"""

    return " ".join(value.strip().casefold().split())


def _clean_names(values: list[str]) -> list[str]:
    """清理并去重展示名称，避免任务卡片被重复来源撑高。"""

    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            output.append(cleaned)
    return output


def _format_source_label(source_type: DouyinSourceType, names: list[str]) -> str:
    """生成列表中统一使用的来源文案。"""

    if source_type == DouyinSourceType.keyword:
        prefix = "关键词"
    elif source_type == DouyinSourceType.creator:
        prefix = "作者"
    elif source_type == DouyinSourceType.mixed:
        prefix = "关键词/作者"
    else:
        return names[0] if names else "指定作品"
    if not names:
        return f"{prefix}任务"
    visible = "、".join(names[:3])
    if len(names) > 3:
        visible = f"{visible} 等 {len(names)} 项"
    return f"{prefix}：{visible}"


def _source_values(
    source_type: DouyinSourceType, names: list[str]
) -> dict[str, object]:
    """返回任务/作品/互动模型可直接展开的来源字段。"""

    names = _clean_names(names)
    return {
        "source_type": source_type,
        "source_names": names,
        "source_label": _format_source_label(source_type, names),
    }


def _task_source_rows(
    session: Session, task_ids: list[uuid.UUID]
) -> tuple[
    dict[uuid.UUID, list[_SourceName]],
    dict[uuid.UUID, list[_SourceName]],
]:
    """批量读取任务绑定的关键词与作者。"""

    keyword_rows: dict[uuid.UUID, list[_SourceName]] = {}
    if task_ids:
        rows = session.exec(
            select(
                DouyinKeywordTaskLink.task_id,
                DouyinKeyword.id,
                DouyinKeyword.keyword,
                DouyinKeyword.normalized_keyword,
            )
            .join(
                DouyinKeyword,
                col(DouyinKeyword.id) == col(DouyinKeywordTaskLink.keyword_id),
            )
            .where(col(DouyinKeywordTaskLink.task_id).in_(set(task_ids)))
            .order_by(DouyinKeyword.keyword)
        ).all()
        for task_id, source_id, name, normalized_name in rows:
            keyword_rows.setdefault(task_id, []).append(
                _SourceName(
                    id=source_id,
                    name=name,
                    normalized_name=normalized_name,
                )
            )

    creator_rows: dict[uuid.UUID, list[_SourceName]] = {}
    if task_ids:
        rows = session.exec(
            select(
                DouyinCreatorTaskLink.task_id,
                DouyinCreator.id,
                DouyinCreator.nickname,
                DouyinCreator.creator_hash,
            )
            .join(
                DouyinCreator,
                col(DouyinCreator.id) == col(DouyinCreatorTaskLink.creator_id),
            )
            .where(col(DouyinCreatorTaskLink.task_id).in_(set(task_ids)))
            .order_by(DouyinCreator.nickname)
        ).all()
        for task_id, source_id, nickname, creator_hash in rows:
            creator_rows.setdefault(task_id, []).append(
                _SourceName(
                    id=source_id,
                    name=(nickname or "").strip() or "未命名作者",
                    creator_hash=creator_hash,
                )
            )
    return keyword_rows, creator_rows


def _request_values(task: CrawlTask, key: str) -> list[str]:
    """从历史任务快照读取兼容性回退值。"""

    try:
        request = json.loads(task.request_json)
    except json.JSONDecodeError:
        return []
    values = request.get(key) if isinstance(request, dict) else None
    return (
        [str(value).strip() for value in values if str(value).strip()]
        if isinstance(values, list)
        else []
    )


def _task_source_values(
    task: CrawlTask,
    keywords: list[_SourceName],
    creators: list[_SourceName],
) -> dict[str, object]:
    """按任务绑定与历史请求快照推导统一来源。"""

    keyword_names = [item.name for item in keywords]
    if not keyword_names and task.crawl_type == DouyinCrawlType.search.value:
        keyword_names = _request_values(task, "keywords")
    creator_names = [item.name for item in creators]
    if (
        task.crawl_type
        in {
            DouyinCrawlType.creator.value,
            DouyinCrawlType.creator_from_aweme.value,
        }
        and not creator_names
    ):
        # 不能把 sec_uid/主页 ID 回显成作者名称；作品归因时再用作者昵称补齐。
        creator_names = []

    if keyword_names and creator_names:
        return _source_values(DouyinSourceType.mixed, [*keyword_names, *creator_names])
    if keyword_names:
        return _source_values(DouyinSourceType.keyword, keyword_names)
    if creator_names or task.crawl_type in {
        DouyinCrawlType.creator.value,
        DouyinCrawlType.creator_from_aweme.value,
    }:
        return _source_values(DouyinSourceType.creator, creator_names)
    other_labels = {
        DouyinCrawlType.detail.value: "指定作品",
        DouyinCrawlType.liked.value: "账号点赞",
        DouyinCrawlType.collected.value: "账号收藏",
    }
    return _source_values(
        DouyinSourceType.task,
        [other_labels.get(task.crawl_type, "采集任务")],
    )


def build_task_source_values(
    session: Session, tasks: list[CrawlTask]
) -> dict[uuid.UUID, dict[str, object]]:
    """批量构造任务来源字段，返回 task_id 到字段字典的映射。"""

    if not tasks:
        return {}
    task_ids = [task.id for task in tasks]
    keyword_rows, creator_rows = _task_source_rows(session, task_ids)
    return {
        task.id: _task_source_values(
            task,
            keyword_rows.get(task.id, []),
            creator_rows.get(task.id, []),
        )
        for task in tasks
    }


def build_aweme_source_values(
    session: Session, awemes: list[DouyinAweme]
) -> dict[uuid.UUID, dict[str, object]]:
    """按作品实际命中的关键词/作者构造作品来源字段。"""

    if not awemes:
        return {}
    task_ids = list({aweme.task_id for aweme in awemes})
    tasks = session.exec(
        select(CrawlTask).where(col(CrawlTask.id).in_(set(task_ids)))
    ).all()
    tasks_by_id = {task.id: task for task in tasks}
    keyword_rows, creator_rows = _task_source_rows(session, task_ids)
    task_sources = build_task_source_values(session, list(tasks))
    output: dict[uuid.UUID, dict[str, object]] = {}
    for aweme in awemes:
        task = tasks_by_id.get(aweme.task_id)
        if task is None:
            output[aweme.id] = _source_values(DouyinSourceType.task, ["采集任务"])
            continue
        task_keywords = keyword_rows.get(task.id, [])
        task_creators = creator_rows.get(task.id, [])
        marker = aweme.source_keyword.strip()
        normalized_marker = _normalize(marker)
        keyword = next(
            (
                item
                for item in task_keywords
                if item.normalized_name == normalized_marker
            ),
            None,
        )
        if keyword is not None or (
            task.crawl_type == DouyinCrawlType.search.value and marker
        ):
            output[aweme.id] = _source_values(
                DouyinSourceType.keyword,
                [keyword.name if keyword is not None else marker],
            )
            continue

        creator = next(
            (
                item
                for item in task_creators
                if item.creator_hash
                and item.creator_hash in {aweme.creator_hash, aweme.sec_uid}
            ),
            None,
        )
        if (
            creator is None
            and task_creators
            and task.crawl_type
            in {
                DouyinCrawlType.creator.value,
                DouyinCrawlType.creator_from_aweme.value,
            }
        ):
            creator = task_creators[0]
        if creator is not None or task.crawl_type in {
            DouyinCrawlType.creator.value,
            DouyinCrawlType.creator_from_aweme.value,
        }:
            output[aweme.id] = _source_values(
                DouyinSourceType.creator,
                [
                    creator.name
                    if creator is not None
                    else (aweme.nickname.strip() or "未命名作者")
                ],
            )
            continue

        output[aweme.id] = dict(
            task_sources.get(
                task.id, _source_values(DouyinSourceType.task, ["采集任务"])
            )
        )
    return output


def resolve_source_filter(
    session: Session,
    *,
    owner_id: uuid.UUID | None,
    track_id: uuid.UUID | None,
    source_type: DouyinSourceType | None,
    source_id: uuid.UUID | None,
) -> ResolvedSourceFilter | None:
    """校验来源筛选项，并解析出可用于内容列表的任务集合。"""

    if source_type is None and source_id is None:
        return None
    if source_type is None or source_id is None:
        raise InvalidRequestError("来源类型和来源项必须同时提供")
    if track_id is None:
        raise InvalidRequestError("选择关键词或作者前必须先选择赛道")
    if source_type not in {DouyinSourceType.keyword, DouyinSourceType.creator}:
        raise InvalidRequestError("来源筛选只支持关键词或作者")
    track = session.get(DouyinTrack, track_id)
    if track is None or (owner_id is not None and track.owner_id != owner_id):
        raise ResourceNotFoundError("赛道不存在或无权访问")

    if source_type == DouyinSourceType.keyword:
        keyword = session.get(DouyinKeyword, source_id)
        if (
            keyword is None
            or keyword.track_id != track_id
            or (owner_id is not None and keyword.owner_id != owner_id)
        ):
            raise ResourceNotFoundError("关键词不存在或不属于所选赛道")
        task_ids = session.exec(
            select(DouyinKeywordTaskLink.task_id).where(
                DouyinKeywordTaskLink.keyword_id == source_id
            )
        ).all()
        return ResolvedSourceFilter(
            source_type=source_type,
            source_id=source_id,
            track_id=track_id,
            task_ids=frozenset(task_ids),
            normalized_name=keyword.normalized_keyword,
        )

    creator = session.get(DouyinCreator, source_id)
    if (
        creator is None
        or creator.track_id != track_id
        or (owner_id is not None and creator.owner_id != owner_id)
    ):
        raise ResourceNotFoundError("作者不存在或不属于所选赛道")
    task_ids = session.exec(
        select(DouyinCreatorTaskLink.task_id).where(
            DouyinCreatorTaskLink.creator_id == source_id
        )
    ).all()
    return ResolvedSourceFilter(
        source_type=source_type,
        source_id=source_id,
        track_id=track_id,
        task_ids=frozenset(task_ids),
        creator_hash=creator.creator_hash,
    )


def source_aweme_conditions(
    resolved: ResolvedSourceFilter,
) -> list[Any]:
    """返回作品/评论查询可复用的来源条件。"""

    conditions: list[Any] = [
        col(DouyinAweme.task_id).in_(set(resolved.task_ids)),
    ]
    if resolved.source_type == DouyinSourceType.keyword:
        assert resolved.normalized_name is not None
        normalized = func.lower(
            func.regexp_replace(
                func.btrim(col(DouyinAweme.source_keyword)),
                r"\s+",
                " ",
                "g",
            )
        )
        conditions.append(normalized == resolved.normalized_name)
    else:
        assert resolved.creator_hash is not None
        conditions.append(
            or_(
                col(DouyinAweme.creator_hash) == resolved.creator_hash,
                col(DouyinAweme.sec_uid) == resolved.creator_hash,
            )
        )
    return conditions


def list_source_options(
    session: Session,
    *,
    owner_id: uuid.UUID | None,
    track_id: uuid.UUID,
) -> DouyinSourceOptionsPublic:
    """只列出指定赛道下的关键词/作者来源选项。"""

    track = session.get(DouyinTrack, track_id)
    if track is None or (owner_id is not None and track.owner_id != owner_id):
        raise ResourceNotFoundError("赛道不存在或无权访问")
    keyword_statement = (
        select(
            DouyinKeyword.id,
            DouyinKeyword.keyword,
            func.count(col(DouyinKeywordTaskLink.id)),
        )
        .outerjoin(
            DouyinKeywordTaskLink,
            col(DouyinKeywordTaskLink.keyword_id) == col(DouyinKeyword.id),
        )
        .where(DouyinKeyword.track_id == track_id)
        .group_by(col(DouyinKeyword.id), col(DouyinKeyword.keyword))
    )
    creator_statement = (
        select(
            DouyinCreator.id,
            DouyinCreator.nickname,
            func.count(col(DouyinCreatorTaskLink.id)),
        )
        .outerjoin(
            DouyinCreatorTaskLink,
            col(DouyinCreatorTaskLink.creator_id) == col(DouyinCreator.id),
        )
        .where(DouyinCreator.track_id == track_id)
        .group_by(col(DouyinCreator.id), col(DouyinCreator.nickname))
    )
    if owner_id is not None:
        keyword_statement = keyword_statement.where(DouyinKeyword.owner_id == owner_id)
        creator_statement = creator_statement.where(DouyinCreator.owner_id == owner_id)
    options = [
        DouyinSourceOptionPublic(
            id=source_id,
            source_type=DouyinSourceType.keyword,
            name=name,
            usage_count=int(count),
        )
        for source_id, name, count in session.exec(keyword_statement).all()
    ]
    options.extend(
        DouyinSourceOptionPublic(
            id=source_id,
            source_type=DouyinSourceType.creator,
            name=(name or "未命名作者"),
            usage_count=int(count),
        )
        for source_id, name, count in session.exec(creator_statement).all()
    )
    options.sort(key=lambda item: (item.source_type.value, item.name.casefold()))
    return DouyinSourceOptionsPublic(data=options, count=len(options))


__all__ = [
    "ResolvedSourceFilter",
    "build_aweme_source_values",
    "build_task_source_values",
    "list_source_options",
    "resolve_source_filter",
    "source_aweme_conditions",
]
