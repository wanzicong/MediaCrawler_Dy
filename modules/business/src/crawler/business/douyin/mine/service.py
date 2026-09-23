"""「我的」模块的读写用例（关注 / 点赞 / 收藏）。

写入侧由采集任务调用（``save_followings`` / ``save_account_awemes``，按账号
幂等 upsert）；读取侧供前端「我的」页查询与概览统计使用。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from crawler.business.douyin.creators.models import DouyinCreator
from crawler.business.douyin.mine.models import (
    DouyinAccountAweme,
    DouyinAccountAwemePublic,
    DouyinAccountAwemesPublic,
    DouyinFollowing,
    DouyinFollowingPublic,
    DouyinFollowingsPublic,
    DouyinMineSummaryPublic,
)
from crawler.business.errors import ResourceNotFoundError
from sqlmodel import Session, col, func, select

AccountAwemeKind = Literal["liked", "collected"]


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


def list_followings(
    session: Session,
    *,
    owner_id: uuid.UUID,
    account_id: uuid.UUID,
    search: str | None = None,
    sort_by: Literal["fetched_at", "follower_count", "nickname"] = "fetched_at",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = 0,
    limit: int = 50,
) -> DouyinFollowingsPublic:
    """查询某账号的关注列表（按账号归属，支持搜索与排序分页）。"""
    _require_account(session, owner_id=owner_id, account_id=account_id)
    filters: list[Any] = [
        DouyinFollowing.owner_id == owner_id,
        DouyinFollowing.account_id == account_id,
    ]
    if search and search.strip():
        term = f"%{search.strip()}%"
        filters.append(
            col(DouyinFollowing.nickname).ilike(term)
            | col(DouyinFollowing.signature).ilike(term)
        )
    count = session.exec(
        select(func.count()).select_from(DouyinFollowing).where(*filters)
    ).one()
    sort_column = {
        "fetched_at": DouyinFollowing.fetched_at,
        "follower_count": DouyinFollowing.follower_count,
        "nickname": DouyinFollowing.nickname,
    }[sort_by]
    order = col(sort_column).asc() if sort_order == "asc" else col(sort_column).desc()
    rows = session.exec(
        select(DouyinFollowing)
        .where(*filters)
        .order_by(order, col(DouyinFollowing.id).asc())
        .offset(skip)
        .limit(limit)
    ).all()
    known = _creator_hashes(session, owner_id)
    return DouyinFollowingsPublic(
        data=[
            DouyinFollowingPublic(
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
                in_creator_list=bool(row.uid_hash and row.uid_hash in known),
                fetched_at=row.fetched_at,
            )
            for row in rows
        ],
        count=count,
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


__all__ = [
    "AccountAwemeKind",
    "list_account_awemes",
    "list_followings",
    "mine_summary",
]
