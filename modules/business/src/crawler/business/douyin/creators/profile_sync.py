"""达人主页信息同步：把粉丝数、作品数、签名、头像等主页基础信息回填到达人表。

抖音主页接口（``/aweme/v1/web/user/profile/other/``）需要登录态与请求签名，
因此这里复用「账号 + CDP 浏览器」的既有链路：挑一个可用账号，打开其浏览器会话，
逐个拉取达人主页资料并落库。同步是显式动作（前端「刷新达人信息」按钮），
按批处理、单批有上限，避免一次请求拖太久。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from crawler.bootstrap.database import engine
from crawler.bootstrap.settings import settings
from crawler.browser.facade import BrowserSessionSpec, CDPBrowserSession
from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.accounts.models import (
    DouyinAccount,
    DouyinAccountPoolStrategy,
)
from crawler.business.douyin.creators.models import (
    DouyinCreator,
    DouyinCreatorProfileSyncResult,
)
from crawler.business.douyin.creators.service import build_creator_public_rows
from sqlmodel import Session, col, select

logger = logging.getLogger(__name__)

_INDEX_URL = "https://www.douyin.com/"
# 同一个账号连续请求主页资料的间隔：抖音对短时间内的资料请求比较敏感
_REQUEST_INTERVAL_SECONDS = 1.2


class CreatorProfileSyncError(RuntimeError):
    """达人主页同步不可用（无账号、账号不可用等）。"""


def _pick_account(
    *, owner_id: uuid.UUID, account_id: uuid.UUID | None
) -> DouyinAccount:
    """挑一个可用账号用于同步达人资料。"""
    from crawler.business.douyin.accounts.service import (  # noqa: PLC0415
        select_task_accounts,
    )

    try:
        accounts = select_task_accounts(
            owner_id=owner_id,
            account_id=account_id,
            account_ids=[],
            pool_id=None,
            strategy=DouyinAccountPoolStrategy.least_loaded,
        )
    except Exception as exc:  # noqa: BLE001 - 统一收敛成可读错误
        raise CreatorProfileSyncError(f"无法选择采集账号：{exc}") from exc
    if not accounts:
        raise CreatorProfileSyncError("没有可用账号，请先在账号管理里登录一个账号")
    return accounts[0]


def _load_targets(
    session: Session,
    *,
    owner_id: uuid.UUID,
    creator_ids: list[uuid.UUID],
    limit: int,
    only_missing: bool,
) -> list[DouyinCreator]:
    """取出本批需要同步的达人：占位达人（无真实 sec_uid）跳过。"""
    statement = select(DouyinCreator).where(
        DouyinCreator.owner_id == owner_id,
        DouyinCreator.is_placeholder == False,  # noqa: E712 - SQLModel 表达式
    )
    if creator_ids:
        statement = statement.where(col(DouyinCreator.id).in_(creator_ids))
    if only_missing:
        statement = statement.where(col(DouyinCreator.profile_synced_at).is_(None))
    statement = statement.order_by(
        col(DouyinCreator.profile_synced_at).asc().nulls_first(),
        col(DouyinCreator.created_at).asc(),
    ).limit(limit)
    return list(session.exec(statement).all())


def _count_remaining(
    session: Session, *, owner_id: uuid.UUID, only_missing: bool
) -> int:
    """统计还有多少达人没同步过（供前端决定是否继续下一批）。"""
    statement = select(DouyinCreator).where(
        DouyinCreator.owner_id == owner_id,
        DouyinCreator.is_placeholder == False,  # noqa: E712 - SQLModel 表达式
        col(DouyinCreator.profile_synced_at).is_(None),
    )
    if not only_missing:
        statement = select(DouyinCreator).where(
            DouyinCreator.owner_id == owner_id,
            DouyinCreator.is_placeholder == False,  # noqa: E712
        )
    return len(session.exec(statement).all())


def apply_profile_payload(creator: DouyinCreator, payload: dict[str, Any]) -> str:
    """把主页接口返回写入达人实体，返回错误信息（空串表示成功）。"""
    user = payload.get("user")
    if not isinstance(user, dict):
        return "主页接口未返回 user 字段"
    creator.nickname = str(user.get("nickname") or creator.nickname)[:255]
    creator.follower_count = int(user.get("follower_count") or 0)
    creator.total_favorited = int(user.get("total_favorited") or 0)
    creator.aweme_total_count = int(user.get("aweme_count") or 0)
    creator.signature = str(user.get("signature") or "")[:1000]
    creator.unique_id = str(user.get("unique_id") or user.get("short_id") or "")[:128]
    creator.ip_location = str(user.get("ip_location") or "")[:128]
    avatar = user.get("avatar_larger") or user.get("avatar_thumb") or {}
    urls = avatar.get("url_list") if isinstance(avatar, dict) else None
    if isinstance(urls, list) and urls:
        creator.avatar_url = str(urls[-1])[:1000]
    creator.profile_synced_at = get_datetime_utc()
    creator.profile_error = ""
    creator.updated_at = get_datetime_utc()
    return ""


def _creator_by_sec_uid(
    session: Session, *, owner_id: uuid.UUID, sec_uid: str
) -> DouyinCreator | None:
    """按 (owner_id, sec_uid) 定位达人名单中的一条记录。"""
    return session.exec(
        select(DouyinCreator).where(
            DouyinCreator.owner_id == owner_id,
            DouyinCreator.sec_uid == sec_uid,
        )
    ).first()


def apply_profile_payload_for_sec_uid(
    *, owner_id: uuid.UUID, sec_uid: str, payload: dict[str, Any]
) -> str:
    """把一条主页接口响应写入达人名单，返回错误信息（空串表示成功）。

    与「刷新达人信息」共用同一套字段映射（``apply_profile_payload``），因此
    「达人详情」任务与手动刷新写出的字段完全一致。达人不在名单中时返回错误，
    而不是隐式新建：任务不应绕过达人名单与赛道归属。
    """
    with Session(engine) as session:
        creator = _creator_by_sec_uid(session, owner_id=owner_id, sec_uid=sec_uid)
        if creator is None:
            return "达人不在当前用户的达人名单中"
        error = apply_profile_payload(creator, payload)
        if error:
            creator.profile_error = error[:500]
            creator.updated_at = get_datetime_utc()
        session.add(creator)
        session.commit()
    return error


def record_profile_error(*, owner_id: uuid.UUID, sec_uid: str, error: str) -> None:
    """记录一次达人详情同步失败：只写失败原因，保留既有主页字段。"""
    with Session(engine) as session:
        creator = _creator_by_sec_uid(session, owner_id=owner_id, sec_uid=sec_uid)
        if creator is None:
            return
        creator.profile_error = error[:500]
        creator.updated_at = get_datetime_utc()
        session.add(creator)
        session.commit()


async def sync_creators_of_task(
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID,
    account_id: uuid.UUID | None = None,
    batch_size: int = 100,
) -> int:
    """补齐某个任务里「还没同步过主页信息」的达人；返回成功条数。

    只在任务创建时显式勾选了 ``sync_creator_profiles`` 才会被调用（任务级开关，
    默认关）。后台串行分批跑，失败只记日志、绝不影响任务本身；限速沿用
    ``sync_creator_profiles`` 的既有节奏（每位之间 1.2 秒，防风控）。

    参数：
        task_id: 采集任务 ID。
        owner_id: 归属用户 ID。
        account_id: 指定使用的账号；None 表示自动挑选。
        batch_size: 每批同步多少位达人。
    返回：
        本次成功同步的达人数量。
    """
    from crawler.business.douyin.creators.models import (  # noqa: PLC0415
        DouyinCreatorTaskLink,
    )

    with Session(engine) as session:
        missing_ids = list(
            session.exec(
                select(DouyinCreatorTaskLink.creator_id)
                .join(
                    DouyinCreator,
                    col(DouyinCreator.id) == col(DouyinCreatorTaskLink.creator_id),
                )
                .where(
                    DouyinCreatorTaskLink.task_id == task_id,
                    DouyinCreator.owner_id == owner_id,
                    col(DouyinCreator.profile_synced_at).is_(None),
                )
            ).all()
        )
    if not missing_ids:
        return 0
    synced = 0
    for start in range(0, len(missing_ids), max(1, batch_size)):
        batch = missing_ids[start : start + max(1, batch_size)]
        try:
            result = await sync_creator_profiles(
                owner_id=owner_id,
                creator_ids=list(batch),
                account_id=account_id,
                limit=len(batch),
                only_missing=True,
            )
        except Exception:  # noqa: BLE001 - 后台补资料失败不影响任务结果
            logger.exception("任务 %s 的达人主页信息补齐失败（后台，已忽略）", task_id)
            continue
        synced += int(result.synced_count)
    return synced


async def sync_creator_profiles(
    *,
    owner_id: uuid.UUID,
    creator_ids: list[uuid.UUID],
    account_id: uuid.UUID | None,
    limit: int,
    only_missing: bool,
) -> DouyinCreatorProfileSyncResult:
    """同步一批达人的主页基础信息。

    参数：
        owner_id: 当前用户 ID。
        creator_ids: 指定达人 ID 列表；为空表示按「最久没同步」优先取。
        account_id: 指定使用的采集账号；None 表示自动挑选。
        limit: 本批最多同步多少个达人。
        only_missing: 只同步从未同步过的达人。

    返回：
        本批同步结果（成功/失败数、剩余待同步数、涉及的达人明细）。

    异常：
        CreatorProfileSyncError: 没有可用账号或浏览器会话建立失败。
    """
    with Session(engine) as session:
        targets = _load_targets(
            session,
            owner_id=owner_id,
            creator_ids=creator_ids,
            limit=limit,
            only_missing=only_missing,
        )
        # 实体脱离会话后带出去做 IO，最后再回写
        for item in targets:
            session.expunge(item)
        account = _pick_account(owner_id=owner_id, account_id=account_id)

    if not targets:
        with Session(engine) as session:
            remaining = _count_remaining(
                session, owner_id=owner_id, only_missing=only_missing
            )
        return DouyinCreatorProfileSyncResult(
            synced_count=0, failed_count=0, remaining_count=remaining, data=[]
        )

    results: dict[uuid.UUID, str] = {}
    await _fetch_profiles(account=account, creators=targets, results=results)

    with Session(engine) as session:
        now = get_datetime_utc()
        for creator in targets:
            stored = session.get(DouyinCreator, creator.id)
            if stored is None:
                continue
            error = results.get(creator.id, "未执行")
            if error:
                stored.profile_error = error[:500]
                stored.updated_at = now
            else:
                # 同步成功的字段在 _fetch_profiles 里写回实体，这里逐个搬运
                stored.nickname = creator.nickname
                stored.follower_count = creator.follower_count
                stored.total_favorited = creator.total_favorited
                stored.aweme_total_count = creator.aweme_total_count
                stored.signature = creator.signature
                stored.avatar_url = creator.avatar_url
                stored.unique_id = creator.unique_id
                stored.ip_location = creator.ip_location
                stored.profile_synced_at = creator.profile_synced_at
                stored.profile_error = ""
                stored.updated_at = now
            session.add(stored)
        session.commit()
        remaining = _count_remaining(
            session, owner_id=owner_id, only_missing=only_missing
        )
        rows = build_creator_public_rows(session, owner_id=owner_id)
        wanted = {creator.id for creator in targets}
        data = [row for row in rows if row.id in wanted]

    synced = sum(1 for creator in targets if not results.get(creator.id))
    return DouyinCreatorProfileSyncResult(
        synced_count=synced,
        failed_count=len(targets) - synced,
        remaining_count=remaining,
        data=data,
    )


async def _fetch_profiles(
    *,
    account: DouyinAccount,
    creators: list[DouyinCreator],
    results: dict[uuid.UUID, str],
) -> None:
    """打开账号浏览器，逐个拉取达人主页资料，成功时把字段写进实体。"""
    from crawler.business.douyin.accounts.service import (  # noqa: PLC0415
        resolve_account_browser,
    )
    from crawler.business.douyin.adapters.service import (  # noqa: PLC0415
        DouyinLoginApi,
        open_douyin_client,
    )

    spec: BrowserSessionSpec = resolve_account_browser(account)
    session = CDPBrowserSession.from_spec(settings, spec)
    async with session as browser:
        await browser.open(_INDEX_URL)
        client = await open_douyin_client(page=browser.browser_page, settings=settings)
        try:
            logged_in = await DouyinLoginApi(client=client).verify_login()
            if not logged_in:
                raise CreatorProfileSyncError(
                    f"账号「{account.name}」登录已失效，请先重新登录"
                )
            for index, creator in enumerate(creators):
                try:
                    payload = await client.user_api.get_user_info(creator.sec_uid)
                    error = apply_profile_payload(creator, payload)
                except Exception as exc:  # noqa: BLE001 - 单个达人失败不影响整批
                    error = f"{type(exc).__name__}: {str(exc)[:160]}"
                results[creator.id] = error
                if index + 1 < len(creators):
                    await asyncio.sleep(_REQUEST_INTERVAL_SECONDS)
        finally:
            await client.close()


__all__ = [
    "CreatorProfileSyncError",
    "apply_profile_payload",
    "apply_profile_payload_for_sec_uid",
    "record_profile_error",
    "sync_creators_of_task",
    "sync_creator_profiles",
]
