"""「我的」模块的读写用例（关注 / 点赞 / 收藏）。

写入侧由采集任务调用（``save_followings`` / ``save_account_awemes``，按账号
幂等 upsert）；读取侧供前端「我的」页查询与概览统计使用。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.creators.models import DouyinCreator, DouyinCreatorPublic
from crawler.business.douyin.mine.models import (
    DouyinAccountAweme,
    DouyinAccountAwemePublic,
    DouyinAccountAwemesPublic,
    DouyinFollowing,
    DouyinFollowingPublic,
    DouyinFollowingsProfileSyncResult,
    DouyinFollowingsPromoteResult,
    DouyinFollowingsPublic,
    DouyinMineSummaryPublic,
)
from crawler.business.errors import ResourceNotFoundError
from sqlalchemy import ColumnElement, and_
from sqlmodel import Session, col, func, select

AccountAwemeKind = Literal["liked", "collected"]
# 「我的关注」可用的排序字段：前三个查关注表本身，后两个查达人名单侧
# （清洗后的主页信息），与达人列表的排序口径保持一致。
FollowingSortField = Literal[
    "fetched_at",
    "follower_count",
    "nickname",
    "profile_synced_at",
    "aweme_total_count",
]


def _require_account(
    session: Session, *, owner_id: uuid.UUID, account_id: uuid.UUID
) -> None:
    """校验账号属于当前用户；不存在时抛 ResourceNotFoundError。"""
    from crawler.business.douyin.accounts.models import DouyinAccount  # noqa: PLC0415

    account = session.get(DouyinAccount, account_id)
    if account is None or account.owner_id != owner_id:
        raise ResourceNotFoundError("抖音账号不存在或无权访问")


def _creator_hashes(session: Session, owner_id: uuid.UUID) -> set[str]:
    """当前用户达人名单里的 creator_hash 集合（用于标记「已在名单」）。"""
    return {
        value
        for value in session.exec(
            select(DouyinCreator.creator_hash).where(DouyinCreator.owner_id == owner_id)
        ).all()
        if value
    }


def _following_creator_join() -> ColumnElement[bool]:
    """关注表与达人名单的关联条件：同一用户下 sec_user_id 相同。"""
    return and_(
        col(DouyinCreator.owner_id) == col(DouyinFollowing.owner_id),
        col(DouyinCreator.sec_uid) == col(DouyinFollowing.sec_uid),
    )


def _creator_public_by_sec_uid(
    session: Session, *, owner_id: uuid.UUID, sec_uids: set[str]
) -> dict[str, DouyinCreatorPublic]:
    """批量取这些 sec_uid 对应达人的公开模型（复用达人列表的同一套口径）。"""
    if not sec_uids:
        return {}
    from crawler.business.douyin.creators.service import (  # noqa: PLC0415
        build_creator_public_rows,
    )

    rows = build_creator_public_rows(session, owner_id=owner_id, sec_uids=sec_uids)
    return {row.sec_uid: row for row in rows}


def _following_public(
    row: DouyinFollowing, creator: DouyinCreatorPublic | None
) -> DouyinFollowingPublic:
    """把关注实体转成对外模型；已在达人名单时带上达人侧的清洗结果。"""
    return DouyinFollowingPublic(
        id=row.id,
        account_id=row.account_id,
        sec_uid=row.sec_uid,
        uid_hash=row.uid_hash,
        nickname=row.nickname,
        avatar_url=row.avatar_url,
        signature=row.signature,
        follower_count=row.follower_count,
        aweme_count=row.aweme_count,
        is_mutual=row.is_mutual,
        in_creator_list=creator is not None,
        fetched_at=row.fetched_at,
        creator=creator,
    )


def _count_missing_profiles(
    session: Session, *, owner_id: uuid.UUID, account_id: uuid.UUID
) -> int:
    """还有多少关注没同步过主页信息（没进名单的也算没同步）。"""
    return int(
        session.exec(
            select(func.count())
            .select_from(DouyinFollowing)
            .outerjoin(DouyinCreator, _following_creator_join())
            .where(
                DouyinFollowing.owner_id == owner_id,
                DouyinFollowing.account_id == account_id,
                col(DouyinCreator.profile_synced_at).is_(None),
            )
        ).one()
    )


def _followings_public_by_ids(
    session: Session, *, owner_id: uuid.UUID, ids: list[uuid.UUID]
) -> list[DouyinFollowingPublic]:
    """按关注记录 ID 取对外模型（保持入参顺序），用于把本批处理结果回给前端。"""
    if not ids:
        return []
    rows = {
        row.id: row
        for row in session.exec(
            select(DouyinFollowing).where(col(DouyinFollowing.id).in_(set(ids)))
        ).all()
    }
    creators = _creator_public_by_sec_uid(
        session,
        owner_id=owner_id,
        sec_uids={row.sec_uid for row in rows.values()},
    )
    return [
        _following_public(rows[item], creators.get(rows[item].sec_uid))
        for item in ids
        if item in rows
    ]


def list_followings(
    session: Session,
    *,
    owner_id: uuid.UUID,
    account_id: uuid.UUID,
    search: str | None = None,
    sort_by: FollowingSortField = "fetched_at",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = 0,
    limit: int = 50,
) -> DouyinFollowingsPublic:
    """查询某账号的关注列表（按账号归属，支持搜索与排序分页）。

    关注列表接口只给得到平台脱敏昵称（形如「一***学」），清洗结果落在达人名单：
    所以这里与达人名单按 sec_user_id 关联，把已达人的公开模型作为 ``creator``
    一起返回，前端因此能用与「达人列表」完全一致的昵称、抖音号、粉丝数、主页
    更新时间来展示、搜索和操作这些博主。

    搜索同时覆盖关注表与达人侧字段（昵称 / 签名 / sec_uid / 脱敏哈希 / 抖音号 /
    备注），保证「按清洗后的名字搜得到」。
    """
    _require_account(session, owner_id=owner_id, account_id=account_id)
    join = _following_creator_join()
    filters: list[Any] = [
        DouyinFollowing.owner_id == owner_id,
        DouyinFollowing.account_id == account_id,
    ]
    if search and search.strip():
        term = f"%{search.strip()}%"
        filters.append(
            col(DouyinFollowing.nickname).ilike(term)
            | col(DouyinFollowing.signature).ilike(term)
            | col(DouyinFollowing.sec_uid).ilike(term)
            | col(DouyinFollowing.uid_hash).ilike(term)
            | col(DouyinCreator.nickname).ilike(term)
            | col(DouyinCreator.unique_id).ilike(term)
            | col(DouyinCreator.creator_hash).ilike(term)
            | col(DouyinCreator.notes).ilike(term)
        )
    count = session.exec(
        select(func.count())
        .select_from(DouyinFollowing)
        .outerjoin(DouyinCreator, join)
        .where(*filters)
    ).one()
    # 排序优先用达人名单里的清洗结果（真实昵称 / 主页粉丝数），没有才回落到关注表
    cleaned_nickname = func.coalesce(
        func.nullif(col(DouyinCreator.nickname), ""), col(DouyinFollowing.nickname)
    )
    effective_followers = func.coalesce(
        func.nullif(col(DouyinCreator.follower_count), 0),
        col(DouyinFollowing.follower_count),
    )
    sort_column = {
        "fetched_at": col(DouyinFollowing.fetched_at),
        "follower_count": effective_followers,
        "nickname": cleaned_nickname,
        "profile_synced_at": col(DouyinCreator.profile_synced_at),
        "aweme_total_count": col(DouyinCreator.aweme_total_count),
    }[sort_by]
    if sort_order == "asc":
        order = sort_column.asc()
        if sort_by == "profile_synced_at":
            # 「最近更新」正序＝最久没更新在前，从没更新过的排到最后（显式写出）
            order = order.nulls_last()
    else:
        order = sort_column.desc()
        if sort_by == "profile_synced_at":
            order = order.nulls_last()
    rows = session.exec(
        select(DouyinFollowing)
        .outerjoin(DouyinCreator, join)
        .where(*filters)
        .order_by(order, col(DouyinFollowing.id).asc())
        .offset(skip)
        .limit(limit)
    ).all()
    creators = _creator_public_by_sec_uid(
        session, owner_id=owner_id, sec_uids={row.sec_uid for row in rows}
    )
    return DouyinFollowingsPublic(
        data=[_following_public(row, creators.get(row.sec_uid)) for row in rows],
        count=count,
    )


def promote_followings_to_creators(
    session: Session,
    *,
    owner_id: uuid.UUID,
    account_id: uuid.UUID,
    following_ids: list[uuid.UUID] | None = None,
    search: str | None = None,
    track_id: uuid.UUID | None = None,
    notes: str = "",
    limit: int = 50,
) -> DouyinFollowingsPromoteResult:
    """把「我的关注」里尚未进入达人名单的博主按批加入达人名单。

    服务端对单次请求限流：本批最多处理 ``limit`` 位（上限 200），并在返回里给出
    ``remaining_count``，调用方按批续跑并在批次之间留出间隔即可完成全量加入。
    已在达人名单中的关注（按脱敏哈希比对）直接跳过，不会重复写入；无法解析出
    sec_uid 的脏数据同样跳过，避免一条坏记录让整批失败。

    参数：
        session: 数据库会话（本函数内部 commit）。
        owner_id: 归属用户 ID。
        account_id: 关注列表所属的托管账号 ID。
        following_ids: 只处理这些关注记录 ID（空列表表示按 ``search`` 批量处理）。
        search: 批量处理时的搜索词，与关注列表的筛选口径一致。
        track_id: 目标赛道 ID，None 表示默认赛道。
        notes: 新建达人写入的备注。
        limit: 本批最多加入多少位达人。

    返回：
        本批新建/复用数量与剩余待加入数量。

    异常：
        ResourceNotFoundError: 账号不存在或不属于当前用户。
    """
    from crawler.business.douyin.creators.service import (  # noqa: PLC0415
        create_creators,
    )
    from crawler.douyin_client import parse_creator_info  # noqa: PLC0415

    _require_account(session, owner_id=owner_id, account_id=account_id)
    filters: list[Any] = [
        DouyinFollowing.owner_id == owner_id,
        DouyinFollowing.account_id == account_id,
    ]
    if following_ids:
        filters.append(col(DouyinFollowing.id).in_(set(following_ids)))
    elif search and search.strip():
        term = f"%{search.strip()}%"
        filters.append(
            col(DouyinFollowing.nickname).ilike(term)
            | col(DouyinFollowing.signature).ilike(term)
        )
    rows = session.exec(
        select(DouyinFollowing)
        .where(*filters)
        .order_by(
            col(DouyinFollowing.follower_count).desc(),
            col(DouyinFollowing.id).asc(),
        )
    ).all()
    known = _creator_hashes(session, owner_id)
    candidates: list[str] = []
    for row in rows:
        if not row.sec_uid or row.uid_hash in known:
            continue
        try:
            sec_uid = parse_creator_info(row.sec_uid).sec_user_id
        except ValueError:
            continue
        if sec_uid and sec_uid not in candidates:
            candidates.append(sec_uid)
    batch_size = max(1, min(limit, 200))
    batch = candidates[:batch_size]
    if not batch:
        return DouyinFollowingsPromoteResult(
            added_count=0, existing_count=0, remaining_count=0
        )
    _, created, existing = create_creators(
        session,
        owner_id=owner_id,
        creators=batch,
        notes=notes,
        track_id=track_id,
        # 已在名单里的达人保留原赛道，不因本次加入而被挪走
        move_existing=False,
    )
    session.commit()
    return DouyinFollowingsPromoteResult(
        added_count=created,
        existing_count=existing,
        remaining_count=max(len(candidates) - len(batch), 0),
    )


async def sync_followings_profiles(
    session: Session,
    *,
    owner_id: uuid.UUID,
    account_id: uuid.UUID,
    following_ids: list[uuid.UUID] | None = None,
    track_id: uuid.UUID | None = None,
    notes: str = "",
    limit: int = 20,
    only_missing: bool = True,
) -> DouyinFollowingsProfileSyncResult:
    """清洗「我的关注」的主页信息（真实昵称 / 抖音号 / 粉丝数 / IP 属地等）。

    关注列表接口只给得到平台脱敏昵称，清洗动作落在达人名单（主页信息同步）。
    因此这里先把还没进名单的博主按 ``track_id`` 加入达人名单，再复用达人列表
    的「主页信息同步」逐位拉取主页资料写回达人表；清洗结果会通过 ``creator``
    出现在关注列表里，于是「我的关注」和「达人列表」展示、搜索、操作的是同一
    份数据。

    参数：
        session: 数据库会话（本函数内部 commit 加入名单的那部分写入）。
        owner_id: 归属用户 ID。
        account_id: 关注列表所属的托管账号 ID，也是清洗时使用的采集账号。
        following_ids: 只清洗这些关注记录（表格行内清洗）；为空表示按批清洗整个账号。
        track_id: 需要新建达人时的目标赛道，None 表示默认赛道。
        notes: 新建达人写入的备注。
        limit: 本批最多清洗多少位（服务端上限 200）。
        only_missing: 只清洗还没成功同步过主页信息的博主。

    返回：
        本批同步结果与剩余待清洗数量。

    异常：
        ResourceNotFoundError: 账号不存在或不属于当前用户。
        CreatorProfileSyncError: 没有可用账号，或账号登录态失效。
    """
    from crawler.business.douyin.creators.profile_sync import (  # noqa: PLC0415
        sync_creator_profiles,
    )
    from crawler.business.douyin.creators.service import (  # noqa: PLC0415
        create_creators,
    )
    from crawler.douyin_client import parse_creator_info  # noqa: PLC0415

    _require_account(session, owner_id=owner_id, account_id=account_id)
    join = _following_creator_join()
    filters: list[Any] = [
        DouyinFollowing.owner_id == owner_id,
        DouyinFollowing.account_id == account_id,
    ]
    if following_ids:
        filters.append(col(DouyinFollowing.id).in_(set(following_ids)))
    if only_missing:
        filters.append(col(DouyinCreator.profile_synced_at).is_(None))
    batch_size = max(1, min(limit, 200))
    rows = session.exec(
        select(DouyinFollowing, DouyinCreator)
        .outerjoin(DouyinCreator, join)
        .where(*filters)
        .order_by(
            col(DouyinCreator.profile_synced_at).asc().nulls_first(),
            col(DouyinFollowing.follower_count).desc(),
            col(DouyinFollowing.id).asc(),
        )
        .limit(batch_size)
    ).all()
    # 还没进名单的先加入名单：清洗结果只能落在达人名单里，不能绕过赛道归属
    pending: list[str] = []
    for row, creator in rows:
        if creator is not None or not row.sec_uid:
            continue
        try:
            sec_uid = parse_creator_info(row.sec_uid).sec_user_id
        except ValueError:
            continue
        if sec_uid and sec_uid not in pending:
            pending.append(sec_uid)
    promoted = 0
    if pending:
        _, promoted, _ = create_creators(
            session,
            owner_id=owner_id,
            creators=pending,
            notes=notes,
            track_id=track_id,
            # 已在名单里的达人保留原赛道，不因本次清洗被挪走
            move_existing=False,
        )
        session.commit()
    target_sec_uids = {row.sec_uid for row, _creator in rows if row.sec_uid}
    creator_ids = (
        list(
            session.exec(
                select(DouyinCreator.id).where(
                    DouyinCreator.owner_id == owner_id,
                    col(DouyinCreator.sec_uid).in_(target_sec_uids),
                )
            ).all()
        )
        if target_sec_uids
        else []
    )
    synced = 0
    failed = 0
    if creator_ids:
        result = await sync_creator_profiles(
            owner_id=owner_id,
            creator_ids=creator_ids,
            account_id=account_id,
            limit=len(creator_ids),
            # 本批范围已经在这里筛过（含 only_missing），这里按 ID 原样同步
            only_missing=False,
        )
        synced = int(result.synced_count)
        failed = int(result.failed_count)
    # 同步在独立 session 里写库，这里清一次身份映射，避免读到同步前的主页信息
    session.expire_all()
    remaining = (
        0
        if following_ids
        else _count_missing_profiles(session, owner_id=owner_id, account_id=account_id)
    )
    return DouyinFollowingsProfileSyncResult(
        synced_count=synced,
        failed_count=failed,
        promoted_count=promoted,
        remaining_count=remaining,
        data=_followings_public_by_ids(
            session, owner_id=owner_id, ids=[row.id for row, _creator in rows]
        ),
    )


def list_account_awemes(
    session: Session,
    *,
    owner_id: uuid.UUID,
    account_id: uuid.UUID,
    kind: AccountAwemeKind,
    search: str | None = None,
    sort_by: Literal["fetched_at", "liked_count", "published_at"] = "fetched_at",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = 0,
    limit: int = 50,
) -> DouyinAccountAwemesPublic:
    """查询某账号的点赞 / 收藏作品列表。"""
    _require_account(session, owner_id=owner_id, account_id=account_id)
    filters: list[Any] = [
        DouyinAccountAweme.owner_id == owner_id,
        DouyinAccountAweme.account_id == account_id,
        DouyinAccountAweme.kind == kind,
    ]
    if search and search.strip():
        term = f"%{search.strip()}%"
        filters.append(
            col(DouyinAccountAweme.title).ilike(term)
            | col(DouyinAccountAweme.nickname).ilike(term)
            | col(DouyinAccountAweme.aweme_id).ilike(term)
        )
    count = session.exec(
        select(func.count()).select_from(DouyinAccountAweme).where(*filters)
    ).one()
    sort_column = {
        "fetched_at": DouyinAccountAweme.fetched_at,
        "liked_count": DouyinAccountAweme.liked_count,
        "published_at": DouyinAccountAweme.published_at,
    }[sort_by]
    order = col(sort_column).asc() if sort_order == "asc" else col(sort_column).desc()
    rows = session.exec(
        select(DouyinAccountAweme)
        .where(*filters)
        .order_by(order, col(DouyinAccountAweme.id).asc())
        .offset(skip)
        .limit(limit)
    ).all()
    return DouyinAccountAwemesPublic(
        data=[
            DouyinAccountAwemePublic(
                id=row.id,
                account_id=row.account_id,
                kind=row.kind,
                aweme_id=row.aweme_id,
                title=row.title,
                nickname=row.nickname,
                creator_hash=row.creator_hash,
                cover_url=row.cover_url,
                aweme_url=row.aweme_url,
                liked_count=row.liked_count,
                comment_count=row.comment_count,
                collected_count=row.collected_count,
                share_count=row.share_count,
                published_at=row.published_at,
                fetched_at=row.fetched_at,
            )
            for row in rows
        ],
        count=count,
    )


def mine_summary(
    session: Session, *, owner_id: uuid.UUID, account_id: uuid.UUID
) -> DouyinMineSummaryPublic:
    """某账号的关注 / 点赞 / 收藏计数与最近采集时间。"""
    _require_account(session, owner_id=owner_id, account_id=account_id)
    following_count = session.exec(
        select(func.count())
        .select_from(DouyinFollowing)
        .where(
            DouyinFollowing.owner_id == owner_id,
            DouyinFollowing.account_id == account_id,
        )
    ).one()
    latest_following = session.exec(
        select(func.max(DouyinFollowing.fetched_at)).where(
            DouyinFollowing.owner_id == owner_id,
            DouyinFollowing.account_id == account_id,
        )
    ).one()

    def _count_and_latest(kind: str) -> tuple[int, datetime | None]:
        conditions = (
            DouyinAccountAweme.owner_id == owner_id,
            DouyinAccountAweme.account_id == account_id,
            DouyinAccountAweme.kind == kind,
        )
        total = session.exec(
            select(func.count()).select_from(DouyinAccountAweme).where(*conditions)
        ).one()
        latest = session.exec(
            select(func.max(DouyinAccountAweme.fetched_at)).where(*conditions)
        ).one()
        return int(total), latest

    liked_count, likes_fetched_at = _count_and_latest("liked")
    collected_count, collects_fetched_at = _count_and_latest("collected")
    return DouyinMineSummaryPublic(
        account_id=account_id,
        following_count=int(following_count),
        liked_count=liked_count,
        collected_count=collected_count,
        following_fetched_at=latest_following,
        likes_fetched_at=likes_fetched_at,
        collects_fetched_at=collects_fetched_at,
    )


def save_followings(
    session: Session,
    *,
    owner_id: uuid.UUID,
    account_id: uuid.UUID,
    items: list[dict[str, Any]],
    task_id: uuid.UUID | None = None,
) -> int:
    """把一批关注博主写进「我的关注」（按 account_id + uid_hash 幂等 upsert）。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 ID。
        account_id: 采集该列表的账号 ID。
        items: 每条含 uid_hash / sec_uid / nickname 等字段的扁平字典。
        task_id: 来源任务 ID（可追溯）。
    返回：
        本次写入（新增或更新）的记录数。
    """
    if not items:
        return 0
    now = get_datetime_utc()
    hashes = {str(item.get("uid_hash") or "") for item in items}
    hashes.discard("")
    existing = {
        row.uid_hash: row
        for row in session.exec(
            select(DouyinFollowing).where(
                DouyinFollowing.account_id == account_id,
                col(DouyinFollowing.uid_hash).in_(hashes),
            )
        ).all()
    }
    written = 0
    for item in items:
        uid_hash = str(item.get("uid_hash") or "")
        if not uid_hash:
            continue
        row = existing.get(uid_hash)
        if row is None:
            row = DouyinFollowing(
                owner_id=owner_id,
                account_id=account_id,
                uid_hash=uid_hash,
                sec_uid=str(item.get("sec_uid") or ""),
            )
        row.sec_uid = str(item.get("sec_uid") or row.sec_uid)
        row.nickname = str(item.get("nickname") or row.nickname)
        row.avatar_url = str(item.get("avatar_url") or row.avatar_url)
        row.signature = str(item.get("signature") or row.signature)
        row.follower_count = int(item.get("follower_count") or row.follower_count)
        row.aweme_count = int(item.get("aweme_count") or row.aweme_count)
        row.is_mutual = bool(item.get("is_mutual", row.is_mutual))
        row.source_task_id = task_id or row.source_task_id
        row.fetched_at = now
        session.add(row)
        written += 1
    session.commit()
    return written


def save_account_awemes(
    session: Session,
    *,
    owner_id: uuid.UUID,
    account_id: uuid.UUID,
    kind: AccountAwemeKind,
    items: list[dict[str, Any]],
    task_id: uuid.UUID | None = None,
) -> int:
    """把一批点赞/收藏作品写进「我的」（按 account_id + kind + aweme_id 幂等 upsert）。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 ID。
        account_id: 采集该列表的账号 ID。
        kind: liked（点赞）或 collected（收藏）。
        items: 每条含 aweme_id / title 等字段的扁平字典。
        task_id: 来源任务 ID。
    返回：
        本次写入（新增或更新）的记录数。
    """
    if not items:
        return 0
    now = get_datetime_utc()
    aweme_ids = {str(item.get("aweme_id") or "") for item in items}
    aweme_ids.discard("")
    existing = {
        row.aweme_id: row
        for row in session.exec(
            select(DouyinAccountAweme).where(
                DouyinAccountAweme.account_id == account_id,
                DouyinAccountAweme.kind == kind,
                col(DouyinAccountAweme.aweme_id).in_(aweme_ids),
            )
        ).all()
    }
    written = 0
    for item in items:
        aweme_id = str(item.get("aweme_id") or "")
        if not aweme_id:
            continue
        row = existing.get(aweme_id)
        if row is None:
            row = DouyinAccountAweme(
                owner_id=owner_id,
                account_id=account_id,
                kind=kind,
                aweme_id=aweme_id,
            )
        row.title = str(item.get("title") or row.title)
        row.nickname = str(item.get("nickname") or row.nickname)
        row.creator_hash = str(item.get("creator_hash") or row.creator_hash)
        row.cover_url = str(item.get("cover_url") or row.cover_url)
        row.aweme_url = str(item.get("aweme_url") or row.aweme_url)
        row.liked_count = int(item.get("liked_count") or row.liked_count)
        row.comment_count = int(item.get("comment_count") or row.comment_count)
        row.collected_count = int(item.get("collected_count") or row.collected_count)
        row.share_count = int(item.get("share_count") or row.share_count)
        published = item.get("published_at")
        if isinstance(published, datetime):
            row.published_at = published
        row.source_task_id = task_id or row.source_task_id
        row.fetched_at = now
        session.add(row)
        written += 1
    session.commit()
    return written


__all__ = [
    "AccountAwemeKind",
    "list_account_awemes",
    "list_followings",
    "mine_summary",
    "promote_followings_to_creators",
    "save_account_awemes",
    "save_followings",
]
