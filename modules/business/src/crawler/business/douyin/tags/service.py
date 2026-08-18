"""抖音标签应用服务：从作品文案中提取话题标签、同步标签库，并提供归属鉴权后的查询用例。"""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime
from typing import Any

from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.tags.models import (
    DouyinAwemeTag,
    DouyinTag,
    DouyinTagPublic,
    DouyinTagsPublic,
    DouyinTagSyncResult,
)
from crawler.business.douyin.tasks.models import CrawlTask
from crawler.business.errors import PermissionDeniedError, ResourceNotFoundError
from sqlalchemy import delete, distinct
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col, func, select

# 话题标签匹配正则：# 之后捕获 1~100 个字符，遇到空白或中英文标点即终止
_TAG_PATTERN = re.compile(
    r"#([^#\s，。！？、；：,.!?;:|/\\()（）\[\]{}<>《》“”‘’\"'`~@￥$%^&*+=]{1,100})"
)


def normalize_tag_name(value: object) -> str:
    """归一化标签名：NFKC 规范化、去除首尾空白与前导 #，并截断至 100 字符。

    参数：
        value: 任意输入值，None 或非字符串值先转为字符串处理。
    返回：
        归一化后的标签名（最长 100 字符，可能为空串）。
    """
    name = unicodedata.normalize("NFKC", str(value or "")).strip().lstrip("#").strip()
    return name[:100]


def extract_hashtags(item: dict[str, Any] | str) -> list[str]:
    """从作品描述与 text_extra 中提取话题标签，按出现顺序去重（忽略大小写）。

    参数：
        item: 作品描述字符串，或包含 desc / text_extra 字段的作品原始字典。
    返回：
        归一化后的标签名列表；无标签时返回空列表。
    """
    if isinstance(item, str):
        description = item
        extras: list[Any] = []
    else:
        description = str(item.get("desc") or "")
        extras = item.get("text_extra") or []
        if not isinstance(extras, list):
            extras = []
    candidates = [match.group(1) for match in _TAG_PATTERN.finditer(description)]
    candidates.extend(
        extra.get("hashtag_name")
        for extra in extras
        if isinstance(extra, dict) and extra.get("hashtag_name")
    )
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        name = normalize_tag_name(candidate)
        normalized = name.casefold()
        if name and normalized not in seen:
            seen.add(normalized)
            result.append(name)
    return result


def sync_aweme_tags(
    session: Session,
    *,
    task_id: uuid.UUID,
    aweme_record_id: uuid.UUID,
    tag_names: list[str],
    seen_at: datetime | None = None,
) -> tuple[int, int]:
    """将一条作品记录的标签全量同步到标签库与绑定表。

    对标签执行幂等 upsert（新建或刷新 last_seen_at），补齐缺失的
    作品-标签绑定，并删除该作品已失效的绑定（即本次未出现的标签）。

    参数：
        session: 数据库会话（调用方负责提交）。
        task_id: 作品所属采集任务 id，用于推导标签归属用户。
        aweme_record_id: 作品记录 id。
        tag_names: 从作品中提取到的标签名列表。
        seen_at: 标签出现时间；默认取当前 UTC 时间。
    返回：
        (新建标签数, 新建绑定数) 元组。
    """
    owner_id = session.exec(
        select(CrawlTask.owner_id).where(CrawlTask.id == task_id)
    ).one()
    names = {
        normalized: name
        for name in tag_names
        if (normalized := normalize_tag_name(name).casefold())
    }
    existing_names = (
        set(
            session.exec(
                select(DouyinTag.normalized_name).where(
                    DouyinTag.owner_id == owner_id,
                    col(DouyinTag.normalized_name).in_(set(names)),
                )
            ).all()
        )
        if names
        else set()
    )
    now = seen_at or get_datetime_utc()
    tag_ids: list[uuid.UUID] = []
    for normalized, name in names.items():
        row = session.execute(
            insert(DouyinTag)
            .values(
                id=uuid.uuid4(),
                owner_id=owner_id,
                name=name,
                normalized_name=normalized,
                last_seen_at=now,
                created_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_douyin_tag_owner_name",
                set_={"name": name, "last_seen_at": now},
            )
            .returning(col(DouyinTag.id))
        ).one()
        tag_ids.append(row[0])

    existing_links = (
        set(
            session.exec(
                select(DouyinAwemeTag.tag_id).where(
                    DouyinAwemeTag.aweme_record_id == aweme_record_id,
                    col(DouyinAwemeTag.tag_id).in_(set(tag_ids)),
                )
            ).all()
        )
        if tag_ids
        else set()
    )
    for tag_id in tag_ids:
        session.execute(
            insert(DouyinAwemeTag)
            .values(
                id=uuid.uuid4(),
                aweme_record_id=aweme_record_id,
                tag_id=tag_id,
                created_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_douyin_aweme_tag_record_tag")
        )
    stale = delete(DouyinAwemeTag).where(
        col(DouyinAwemeTag.aweme_record_id) == aweme_record_id
    )
    if tag_ids:
        stale = stale.where(col(DouyinAwemeTag.tag_id).not_in(set(tag_ids)))
    session.execute(stale)
    return len(set(names) - existing_names), len(set(tag_ids) - existing_links)


def sync_tag_history(session: Session, *, owner_id: uuid.UUID) -> DouyinTagSyncResult:
    """重扫某用户名下全部已采集作品，从历史文案重建标签与绑定关系并提交事务。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 id。
    返回：
        DouyinTagSyncResult 同步统计结果。
    """
    rows = session.exec(
        select(DouyinAweme)
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
        .where(CrawlTask.owner_id == owner_id)
    ).all()
    created_count = 0
    binding_count = 0
    discovered: set[str] = set()
    for aweme in rows:
        names = extract_hashtags(aweme.description or aweme.title)
        discovered.update(name.casefold() for name in names)
        created, bound = sync_aweme_tags(
            session,
            task_id=aweme.task_id,
            aweme_record_id=aweme.id,
            tag_names=names,
            seen_at=aweme.fetched_at,
        )
        created_count += created
        binding_count += bound
    session.commit()
    return DouyinTagSyncResult(
        aweme_count=len(rows),
        tag_count=len(discovered),
        created_count=created_count,
        binding_count=binding_count,
    )


def build_tag_public_rows(
    session: Session,
    *,
    owner_id: uuid.UUID,
    task_id: uuid.UUID | None = None,
    track_id: uuid.UUID | None = None,
    search: str | None = None,
) -> list[DouyinTagPublic]:
    """按归属与可选筛选条件查询标签，并聚合关联作品数与任务数。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 id（强制隔离条件）。
        task_id: 可选，仅统计该任务关联的作品。
        track_id: 可选，仅统计该赛道下任务关联的作品。
        search: 可选，按标签显示名模糊搜索（忽略首尾空白）。
    返回：
        DouyinTagPublic 列表（未排序、未分页，由调用方处理）。
    """
    statement = (
        select(
            DouyinTag,
            func.count(distinct(col(DouyinAwemeTag.aweme_record_id))).label(
                "aweme_count"
            ),
            func.count(distinct(col(DouyinAweme.task_id))).label("task_count"),
        )
        .outerjoin(DouyinAwemeTag, col(DouyinAwemeTag.tag_id) == col(DouyinTag.id))
        .outerjoin(
            DouyinAweme,
            col(DouyinAweme.id) == col(DouyinAwemeTag.aweme_record_id),
        )
        .outerjoin(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
        .where(DouyinTag.owner_id == owner_id)
    )
    if task_id:
        statement = statement.where(DouyinAweme.task_id == task_id)
    if track_id:
        statement = statement.where(CrawlTask.track_id == track_id)
    if search and search.strip():
        statement = statement.where(col(DouyinTag.name).ilike(f"%{search.strip()}%"))
    rows = session.exec(statement.group_by(col(DouyinTag.id))).all()
    return [
        DouyinTagPublic(
            id=tag.id,
            name=tag.name,
            aweme_count=int(aweme_count),
            task_count=int(task_count),
            last_seen_at=tag.last_seen_at,
            created_at=tag.created_at,
        )
        for tag, aweme_count, task_count in rows
    ]


def list_tags_for_actor(
    session: Session,
    *,
    actor_id: uuid.UUID,
    is_superuser: bool,
    search: str | None,
    task_id: uuid.UUID | None,
    track_id: uuid.UUID | None,
    sort_by: str,
    sort_order: str,
    skip: int,
    limit: int,
) -> DouyinTagsPublic:
    """查询标签列表的完整用例：归属鉴权、筛选、排序与分页均留在应用服务层，不渗入 HTTP 适配层。

    参数：
        session: 数据库会话。
        actor_id: 当前操作者用户 id。
        is_superuser: 是否超级用户（可跨归属查看任务/赛道）。
        search: 标签名模糊搜索关键字。
        task_id: 可选，按采集任务筛选。
        track_id: 可选，按赛道筛选。
        sort_by: 排序字段（name / aweme_count / task_count / last_seen_at，默认 aweme_count）。
        sort_order: 排序方向（asc / desc）。
        skip: 分页偏移量。
        limit: 分页大小。
    返回：
        DouyinTagsPublic 分页结果，count 为筛选后的总数。
    异常：
        ResourceNotFoundError: 任务不存在，或赛道不存在/无权访问。
        PermissionDeniedError: 无权查看他人任务。
        InvalidRequestError: 指定任务不属于所选赛道。
    """

    task: CrawlTask | None = None
    if task_id:
        task = session.get(CrawlTask, task_id)
        if not task:
            raise ResourceNotFoundError("抖音任务不存在")
        if task.owner_id != actor_id and not is_superuser:
            raise PermissionDeniedError("Not enough permissions")

    from crawler.business.douyin.tracks.models import DouyinTrack

    track = session.get(DouyinTrack, track_id) if track_id else None
    if track_id and (
        track is None or (track.owner_id != actor_id and not is_superuser)
    ):
        raise ResourceNotFoundError("赛道不存在或无权访问")
    if task is not None and track is not None and task.track_id != track.id:
        from crawler.business.errors import InvalidRequestError

        raise InvalidRequestError("任务不属于所选赛道，请调整筛选条件")

    owner_id = (
        track.owner_id
        if track is not None
        else task.owner_id
        if task is not None
        else actor_id
    )

    rows = build_tag_public_rows(
        session,
        owner_id=owner_id,
        task_id=task_id,
        track_id=track_id,
        search=search,
    )

    def sort_key(item: DouyinTagPublic) -> str | int | float:
        # 排序键：按 sort_by 选择可比较的排序值，默认按关联作品数
        if sort_by == "name":
            return item.name.casefold()
        if sort_by == "task_count":
            return item.task_count
        if sort_by == "last_seen_at":
            return item.last_seen_at.timestamp()
        return item.aweme_count

    rows.sort(key=sort_key, reverse=sort_order == "desc")
    return DouyinTagsPublic(data=rows[skip : skip + limit], count=len(rows))
