"""抖音账号应用服务。

覆盖账号与账号池的 CRUD、调度选择与租约管理，以及基于 CDP 浏览器的
登录会话（DouyinAccountLoginManager）的发起、验证与生命周期管理。
"""

import asyncio
import concurrent.futures
import json
import logging
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from crawler.bootstrap.database import engine
from crawler.bootstrap.settings import settings
from crawler.browser.session import (
    BrowserAutomationError,
    BrowserAutomationTimeoutError,
    CDPBrowserSession,
)
from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.accounts.models import (
    DouyinAccount,
    DouyinAccountCreate,
    DouyinAccountPool,
    DouyinAccountPoolCreate,
    DouyinAccountPoolMember,
    DouyinAccountPoolPublic,
    DouyinAccountPoolsPublic,
    DouyinAccountPoolStrategy,
    DouyinAccountPoolUpdate,
    DouyinAccountPublic,
    DouyinAccountsPublic,
    DouyinAccountStatus,
    DouyinAccountUpdate,
    DouyinBrowserMode,
)
from crawler.douyin_client.client import DouyinClient
from crawler.douyin_client.privacy import anonymize_account_id
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, select

logger = logging.getLogger(__name__)


def _page_navigation_warning(exc: BrowserAutomationError) -> str:
    # 将浏览器导航异常映射为面向用户的中文提示文案
    detail = str(exc)
    if "ERR_PROXY_CONNECTION_FAILED" in detail:
        return (
            "浏览器已连接，但抖音页面打开失败：容器代理不可用；"
            "请检查浏览器服务代理配置后重试"
        )
    if "ERR_NAME_NOT_RESOLVED" in detail:
        return "浏览器已连接，但抖音页面打开失败：域名解析失败"
    if "ERR_CONNECTION" in detail or "ERR_NETWORK" in detail:
        return "浏览器已连接，但抖音页面打开失败：网络连接异常"
    return "浏览器已连接，但抖音页面暂时无法打开；可在远程浏览器中手动重试"


class AccountConfigurationError(ValueError):
    """账号/槽位配置错误：如槽位未配置、配置非法或账号当前不可调度。"""

    pass


class AccountLoginError(RuntimeError):
    """账号登录/验证流程失败。"""

    pass


class AccountNotFoundError(LookupError):
    """目标账号不存在或不属于当前用户（不暴露他人账号的存在性）。"""


class AccountInUseError(RuntimeError):
    """目标账号仍存在执行中的任务租约，不能停用或删除。"""


class AccountPoolNotFoundError(LookupError):
    """目标账号池不存在或不属于当前用户。"""


class AccountPoolMembershipError(ValueError):
    """账号池成员包含不属于当前用户的账号。"""


class AccountPoolConflictError(ValueError):
    """账号池违反唯一性约束（如同名账号池）。"""


@dataclass(frozen=True)
class BrowserConnection:
    """浏览器连接参数：执行或登录时连接本地/远程 CDP 浏览器所需的信息。"""

    browser_mode: DouyinBrowserMode  # 浏览器运行模式
    remote_host: str | None = None  # 远程 CDP 主机地址
    remote_port: int | None = None  # 远程 CDP 端口
    viewer_url: str | None = None  # 远程浏览器可视化查看地址（noVNC 等）
    user_data_dir: Path | None = None  # 本地浏览器用户数据目录
    debug_port: int | None = None  # 本地浏览器 CDP 调试端口


@dataclass
class LoginHandle:
    """登录会话句柄：一次进行中的登录流程所持有的浏览器会话与过期时间。"""

    owner_id: uuid.UUID  # 账号归属用户 id
    account_id: uuid.UUID  # 账号 id
    browser: CDPBrowserSession  # 登录流程使用的 CDP 浏览器会话
    expires_at: datetime  # 会话过期时间（过期后自动关闭浏览器）


def account_public_values(account: DouyinAccount) -> dict[str, object]:
    """组装 DouyinAccountPublic 的字段字典，is_logged_in 由 identity_hash 推导。

    参数：
        account: 账号实体。
    返回：
        可直接用于构造 DouyinAccountPublic 的字段字典。
    """
    return {
        "id": account.id,
        "name": account.name,
        "browser_mode": account.browser_mode,
        "remote_slot": account.remote_slot,
        "status": account.status,
        "is_logged_in": bool(account.identity_hash),
        "weight": account.weight,
        "priority": account.priority,
        "concurrency_limit": account.concurrency_limit,
        "daily_task_limit": account.daily_task_limit,
        "tasks_today": account.tasks_today,
        "min_request_interval_seconds": account.min_request_interval_seconds,
        "active_leases": account.active_leases,
        "failure_streak": account.failure_streak,
        "cooldown_until": account.cooldown_until,
        "last_verified_at": account.last_verified_at,
        "last_used_at": account.last_used_at,
        "last_error": account.last_error,
        "enabled": account.enabled,
        "created_at": account.created_at,
        "updated_at": account.updated_at,
    }


def _remote_slots() -> dict[str, dict[str, object]]:
    # 解析 DOUYIN_REMOTE_CDP_SLOTS JSON 配置为 {槽位名: 配置} 字典；配置非法时抛 AccountConfigurationError
    raw = settings.DOUYIN_REMOTE_CDP_SLOTS.strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AccountConfigurationError(
            "DOUYIN_REMOTE_CDP_SLOTS 不是有效 JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise AccountConfigurationError("DOUYIN_REMOTE_CDP_SLOTS 必须是对象")
    result: dict[str, dict[str, object]] = {}
    for name, value in payload.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(value, dict):
            raise AccountConfigurationError("远程浏览器槽位配置格式无效")
        result[name] = value
    return result


def remote_slot_public_values(
    session: Session, owner_id: uuid.UUID
) -> list[dict[str, object]]:
    """汇总默认槽位与全部已配置远程槽位的占用情况和健康探测结果。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 id（仅统计该用户的槽位占用）。
    返回：
        槽位状态字典列表，字段与 DouyinBrowserSlotPublic 一一对应。
    """
    accounts = session.exec(
        select(DouyinAccount).where(
            DouyinAccount.owner_id == owner_id,
            DouyinAccount.browser_mode == DouyinBrowserMode.remote.value,
        )
    ).all()
    occupied = {account.remote_slot: account for account in accounts}
    configured_slots: list[tuple[str | None, str, dict[str, object]]] = [
        (
            None,
            "Docker 默认槽位",
            {
                "host": settings.DOUYIN_REMOTE_CDP_HOST,
                "port": settings.DOUYIN_REMOTE_CDP_PORT,
                "viewer_url": settings.DOUYIN_REMOTE_VIEWER_URL,
            },
        )
    ]
    configured_slots.extend(
        (name, name, value) for name, value in sorted(_remote_slots().items())
    )
    checked_at = get_datetime_utc()

    def probe(config: dict[str, object]) -> dict[str, object]:
        # 单个槽位的 CDP 健康探测：请求 /json/list，返回页面数、活动页面与耗时
        host = str(config.get("host") or "").strip()
        try:
            port = int(str(config.get("port") or 0))
        except (TypeError, ValueError):
            port = 0
        if not host or not 1 <= port <= 65535:
            return {
                "cdp_healthy": False,
                "page_count": 0,
                "active_page_title": None,
                "active_page_url": None,
                "latency_ms": None,
            }
        started = time.perf_counter()
        try:
            response = httpx.get(
                f"http://{host}:{port}/json/list",
                headers={"Host": "localhost"},
                timeout=1.5,
                follow_redirects=False,
                trust_env=False,
            )
            response.raise_for_status()
            payload = response.json()
            pages = (
                [
                    item
                    for item in payload
                    if isinstance(item, dict) and item.get("type") == "page"
                ]
                if isinstance(payload, list)
                else []
            )
            active = pages[0] if pages else None
            raw_url = str(active.get("url") or "") if active else ""
            parsed = urlsplit(raw_url)
            safe_url = (
                urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
                if parsed.scheme in {"http", "https"}
                else None
            )
            return {
                "cdp_healthy": True,
                "page_count": len(pages),
                "active_page_title": (
                    str(active.get("title") or "").strip()[:200] or None
                    if active
                    else None
                ),
                "active_page_url": safe_url,
                "latency_ms": round((time.perf_counter() - started) * 1000),
            }
        except (httpx.HTTPError, ValueError, TypeError):
            return {
                "cdp_healthy": False,
                "page_count": 0,
                "active_page_title": None,
                "active_page_url": None,
                "latency_ms": None,
            }

    probe_results: list[dict[str, object]] = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(8, max(1, len(configured_slots)))
    ) as executor:
        probe_results = list(
            executor.map(lambda item: probe(item[2]), configured_slots)
        )

    result: list[dict[str, object]] = []
    for (name, label, config), health in zip(
        configured_slots, probe_results, strict=True
    ):
        account = occupied.get(name)
        host = str(config.get("host") or "").strip()
        try:
            port = int(str(config.get("port") or 0))
        except (TypeError, ValueError):
            port = 0
        configured = bool(host and 1 <= port <= 65535)
        result.append(
            {
                "name": name,
                "label": label,
                "is_default": name is None,
                "available": configured and account is None,
                "configured": configured,
                "viewer_available": bool(str(config.get("viewer_url") or "").strip()),
                "viewer_url": str(config.get("viewer_url") or "").strip() or None,
                "checked_at": checked_at,
                "occupied_account_id": account.id if account else None,
                "occupied_account_name": account.name if account else None,
                **health,
            }
        )
    return result


def _validate_remote_slot_assignment(
    session: Session,
    *,
    owner_id: uuid.UUID,
    remote_slot: str | None,
    exclude_account_id: uuid.UUID | None = None,
) -> None:
    # 校验远程槽位已配置且未被同用户其他账号占用（exclude_account_id 用于更新时排除自身）
    slots = _remote_slots()
    if remote_slot and remote_slot not in slots:
        raise AccountConfigurationError(f"远程浏览器槽位 {remote_slot} 未配置")
    filters = [
        DouyinAccount.owner_id == owner_id,
        DouyinAccount.browser_mode == DouyinBrowserMode.remote.value,
        DouyinAccount.remote_slot == remote_slot,
    ]
    if exclude_account_id is not None:
        filters.append(DouyinAccount.id != exclude_account_id)
    occupied = session.exec(select(DouyinAccount).where(*filters)).first()
    if occupied is not None:
        label = remote_slot or "默认"
        raise AccountConfigurationError(
            f"远程浏览器槽位 {label} 已绑定账号“{occupied.name}”"
        )


def resolve_account_browser(account: DouyinAccount) -> BrowserConnection:
    """按账号的浏览器模式解析出对应的 CDP 连接参数。

    本地模式使用独立的用户数据目录并按账号 id 派生调试端口；
    远程模式使用账号绑定的槽位配置，未绑定时回退到默认远程地址。

    参数：
        account: 账号实体。
    返回：
        BrowserConnection 连接参数。
    异常：
        AccountConfigurationError: 槽位未配置或主机/端口非法。
    """
    mode = DouyinBrowserMode(account.browser_mode)
    if mode == DouyinBrowserMode.local:
        profile_root = settings.DOUYIN_CDP_USER_DATA_DIR.resolve().parent / "accounts"
        return BrowserConnection(
            browser_mode=mode,
            user_data_dir=profile_root / account.profile_key,
            debug_port=settings.DOUYIN_CDP_PORT + (account.id.int % 500),
        )

    slots = _remote_slots()
    if account.remote_slot:
        slot = slots.get(account.remote_slot)
        if slot is None:
            raise AccountConfigurationError(
                f"远程浏览器槽位 {account.remote_slot} 未配置"
            )
        host = str(slot.get("host") or "").strip()
        try:
            port = int(str(slot.get("port") or 0))
        except (TypeError, ValueError) as exc:
            raise AccountConfigurationError("远程浏览器槽位端口无效") from exc
        viewer_url = str(slot.get("viewer_url") or "").strip() or None
        if not host or not 1 <= port <= 65535:
            raise AccountConfigurationError("远程浏览器槽位主机或端口无效")
        return BrowserConnection(mode, host, port, viewer_url)
    return BrowserConnection(
        mode,
        settings.DOUYIN_REMOTE_CDP_HOST,
        settings.DOUYIN_REMOTE_CDP_PORT,
        settings.DOUYIN_REMOTE_VIEWER_URL or None,
    )


def create_account(
    session: Session, owner_id: uuid.UUID, request: DouyinAccountCreate
) -> DouyinAccount:
    """创建抖音账号：校验槽位绑定后落库，profile_key 随机生成。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 id。
        request: 创建请求参数。
    返回：
        创建后的账号实体。
    异常：
        AccountConfigurationError: 槽位冲突/未配置，或名称、Profile 违反唯一约束。
    """
    if request.browser_mode == DouyinBrowserMode.remote:
        _validate_remote_slot_assignment(
            session,
            owner_id=owner_id,
            remote_slot=request.remote_slot,
        )
    elif request.remote_slot:
        raise AccountConfigurationError("本地浏览器账号不能设置远程槽位")

    account = DouyinAccount(
        owner_id=owner_id,
        name=request.name.strip(),
        browser_mode=request.browser_mode.value,
        profile_key=uuid.uuid4().hex,
        remote_slot=request.remote_slot,
        weight=request.weight,
        priority=request.priority,
        concurrency_limit=request.concurrency_limit,
        daily_task_limit=request.daily_task_limit,
        min_request_interval_seconds=request.min_request_interval_seconds,
    )
    session.add(account)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise AccountConfigurationError("账号名称或浏览器 Profile 已存在") from exc
    session.refresh(account)
    return account


def update_account(
    session: Session, account: DouyinAccount, request: DouyinAccountUpdate
) -> DouyinAccount:
    """更新账号：处理名称去空白、槽位变更校验，以及启停时的状态联动。

    参数：
        session: 数据库会话。
        account: 已完成归属校验的账号实体。
        request: 更新请求（仅显式传入的字段生效）。
    返回：
        更新后的账号实体。
    异常：
        AccountConfigurationError: 槽位冲突或名称违反唯一约束。
    """
    values = request.model_dump(exclude_unset=True)
    if "name" in values and values["name"] is not None:
        values["name"] = str(values["name"]).strip()
    if "remote_slot" in values:
        remote_slot = values["remote_slot"]
        if account.browser_mode != DouyinBrowserMode.remote.value and remote_slot:
            raise AccountConfigurationError("本地浏览器账号不能设置远程槽位")
        if account.browser_mode == DouyinBrowserMode.remote.value:
            _validate_remote_slot_assignment(
                session,
                owner_id=account.owner_id,
                remote_slot=remote_slot,
                exclude_account_id=account.id,
            )
    if "enabled" in values:
        enabled = bool(values["enabled"])
        values["status"] = (
            DouyinAccountStatus.login_required.value
            if enabled and not account.identity_hash
            else DouyinAccountStatus.ready.value
            if enabled
            else DouyinAccountStatus.disabled.value
        )
    values["updated_at"] = get_datetime_utc()
    account.sqlmodel_update(values)
    session.add(account)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise AccountConfigurationError("账号名称已存在") from exc
    session.refresh(account)
    return account


def get_owned_account(
    session: Session, *, owner_id: uuid.UUID, account_id: uuid.UUID
) -> DouyinAccount:
    """按 id 加载账号并校验归属，避免暴露他人账号的存在性。

    异常：
        AccountNotFoundError: 账号不存在或不属于该用户。
    """

    account = session.get(DouyinAccount, account_id)
    if account is None or account.owner_id != owner_id:
        raise AccountNotFoundError
    return account


def list_owned_accounts(
    session: Session,
    *,
    owner_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
) -> DouyinAccountsPublic:
    """按创建时间倒序返回某用户的账号分页列表。"""

    filters = [DouyinAccount.owner_id == owner_id]
    count = session.exec(
        select(func.count()).select_from(DouyinAccount).where(*filters)
    ).one()
    accounts = session.exec(
        select(DouyinAccount)
        .where(*filters)
        .order_by(col(DouyinAccount.created_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return DouyinAccountsPublic(
        data=[DouyinAccountPublic(**account_public_values(item)) for item in accounts],
        count=count,
    )


def update_owned_account(
    session: Session,
    *,
    owner_id: uuid.UUID,
    account_id: uuid.UUID,
    request: DouyinAccountUpdate,
) -> DouyinAccount:
    """先鉴权再更新的账号更新用例；存在执行中租约时禁止停用。

    异常：
        AccountNotFoundError: 账号不存在或不属于该用户。
        AccountInUseError: 账号存在执行中的租约却尝试停用。
    """

    account = get_owned_account(
        session,
        owner_id=owner_id,
        account_id=account_id,
    )
    if account.active_leases and request.enabled is False:
        raise AccountInUseError
    return update_account(session, account, request)


async def delete_owned_account(
    session: Session, *, owner_id: uuid.UUID, account_id: uuid.UUID
) -> None:
    """删除空闲账号：先关闭登录会话，再删除记录并清理本地浏览器 Profile 目录。

    异常：
        AccountNotFoundError: 账号不存在或不属于该用户。
        AccountInUseError: 账号存在执行中的租约。
    """

    account = get_owned_account(
        session,
        owner_id=owner_id,
        account_id=account_id,
    )
    if account.active_leases:
        raise AccountInUseError

    await account_login_manager.close(account.id)
    local_profile: Path | None = None
    if account.browser_mode == DouyinBrowserMode.local.value:
        root = (
            settings.DOUYIN_CDP_USER_DATA_DIR.resolve().parent / "accounts"
        ).resolve()
        candidate = (root / account.profile_key).resolve()
        if candidate.parent == root:
            local_profile = candidate

    session.delete(account)
    session.commit()
    if local_profile is not None and local_profile.exists():
        await asyncio.to_thread(shutil.rmtree, local_profile)


def get_owned_pool(
    session: Session, *, owner_id: uuid.UUID, pool_id: uuid.UUID
) -> DouyinAccountPool:
    """按 id 加载账号池并校验归属，避免暴露他人账号池的存在性。

    异常：
        AccountPoolNotFoundError: 账号池不存在或不属于该用户。
    """

    pool = session.get(DouyinAccountPool, pool_id)
    if pool is None or pool.owner_id != owner_id:
        raise AccountPoolNotFoundError
    return pool


def account_pool_public(
    session: Session, pool: DouyinAccountPool
) -> DouyinAccountPoolPublic:
    """组装账号池响应，成员账号按优先级降序、名称升序排列。"""

    accounts = session.exec(
        select(DouyinAccount)
        .join(
            DouyinAccountPoolMember,
            col(DouyinAccountPoolMember.account_id) == col(DouyinAccount.id),
        )
        .where(DouyinAccountPoolMember.pool_id == pool.id)
        .order_by(col(DouyinAccount.priority).desc(), col(DouyinAccount.name))
    ).all()
    return DouyinAccountPoolPublic(
        id=pool.id,
        name=pool.name,
        description=pool.description,
        strategy=pool.strategy,
        max_parallel_accounts=pool.max_parallel_accounts,
        enabled=pool.enabled,
        accounts=[
            DouyinAccountPublic(**account_public_values(account))
            for account in accounts
        ],
        created_at=pool.created_at,
        updated_at=pool.updated_at,
    )


def _replace_pool_members(
    session: Session,
    *,
    owner_id: uuid.UUID,
    pool_id: uuid.UUID,
    account_ids: list[uuid.UUID],
) -> None:
    # 全量替换账号池成员；成员须全部属于该用户，否则抛 AccountPoolMembershipError
    unique_ids = list(dict.fromkeys(account_ids))
    if unique_ids:
        owned = session.exec(
            select(DouyinAccount.id).where(
                DouyinAccount.owner_id == owner_id,
                col(DouyinAccount.id).in_(unique_ids),
            )
        ).all()
        if set(owned) != set(unique_ids):
            raise AccountPoolMembershipError

    existing = session.exec(
        select(DouyinAccountPoolMember).where(
            DouyinAccountPoolMember.pool_id == pool_id
        )
    ).all()
    for member in existing:
        session.delete(member)
    for account_id in unique_ids:
        session.add(DouyinAccountPoolMember(pool_id=pool_id, account_id=account_id))


def list_owned_pools(
    session: Session, *, owner_id: uuid.UUID
) -> DouyinAccountPoolsPublic:
    """返回某用户名下全部账号池（含成员账号摘要），按创建时间倒序。"""

    pools = session.exec(
        select(DouyinAccountPool)
        .where(DouyinAccountPool.owner_id == owner_id)
        .order_by(col(DouyinAccountPool.created_at).desc())
    ).all()
    return DouyinAccountPoolsPublic(
        data=[account_pool_public(session, pool) for pool in pools],
        count=len(pools),
    )


def create_account_pool(
    session: Session,
    *,
    owner_id: uuid.UUID,
    request: DouyinAccountPoolCreate,
) -> DouyinAccountPoolPublic:
    """创建账号池，并在同一事务内原子化写入成员集合。

    异常：
        AccountPoolMembershipError: 成员账号不属于该用户。
        AccountPoolConflictError: 账号池名称违反唯一约束。
    """

    pool = DouyinAccountPool(
        owner_id=owner_id,
        name=request.name.strip(),
        description=request.description.strip(),
        strategy=request.strategy.value,
        max_parallel_accounts=request.max_parallel_accounts,
    )
    session.add(pool)
    try:
        session.flush()
        _replace_pool_members(
            session,
            owner_id=owner_id,
            pool_id=pool.id,
            account_ids=request.account_ids,
        )
        session.commit()
    except AccountPoolMembershipError:
        session.rollback()
        raise
    except IntegrityError as exc:
        session.rollback()
        raise AccountPoolConflictError from exc
    session.refresh(pool)
    return account_pool_public(session, pool)


def update_account_pool(
    session: Session,
    *,
    owner_id: uuid.UUID,
    pool_id: uuid.UUID,
    request: DouyinAccountPoolUpdate,
) -> DouyinAccountPoolPublic:
    """鉴权后更新账号池；传入 account_ids 时在同一事务内全量替换成员。

    异常：
        AccountPoolNotFoundError: 账号池不存在或不属于该用户。
        AccountPoolMembershipError: 成员账号不属于该用户。
        AccountPoolConflictError: 账号池名称违反唯一约束。
    """

    pool = get_owned_pool(session, owner_id=owner_id, pool_id=pool_id)
    values = request.model_dump(exclude_unset=True, exclude={"account_ids"})
    if "strategy" in values and values["strategy"] is not None:
        values["strategy"] = values["strategy"].value
    if "name" in values and values["name"] is not None:
        values["name"] = str(values["name"]).strip()
    values["updated_at"] = get_datetime_utc()
    pool.sqlmodel_update(values)
    session.add(pool)
    try:
        session.flush()
        if request.account_ids is not None:
            _replace_pool_members(
                session,
                owner_id=owner_id,
                pool_id=pool.id,
                account_ids=request.account_ids,
            )
        session.commit()
    except AccountPoolMembershipError:
        session.rollback()
        raise
    except IntegrityError as exc:
        session.rollback()
        raise AccountPoolConflictError from exc
    session.refresh(pool)
    return account_pool_public(session, pool)


def delete_owned_pool(
    session: Session, *, owner_id: uuid.UUID, pool_id: uuid.UUID
) -> None:
    """删除账号池（仅删除池与成员关系，成员账号本身保留）。

    异常：
        AccountPoolNotFoundError: 账号池不存在或不属于该用户。
    """

    pool = get_owned_pool(session, owner_id=owner_id, pool_id=pool_id)
    session.delete(pool)
    session.commit()


def eligible_accounts(
    session: Session,
    *,
    owner_id: uuid.UUID,
    account_ids: list[uuid.UUID] | None = None,
    pool_id: uuid.UUID | None = None,
    strategy: DouyinAccountPoolStrategy = DouyinAccountPoolStrategy.least_loaded,
    limit: int = 20,
) -> list[DouyinAccount]:
    """筛选当前可调度的账号并按策略排序。

    过滤条件：已启用、状态为 ready/busy/cooldown、租约未达并发上限、
    未超每日任务上限（usage_date 跨天视为未超限）。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 id。
        account_ids: 可选，仅在这些账号中筛选。
        pool_id: 可选，仅在该账号池成员中筛选。
        strategy: 调度策略，决定排序方式。
        limit: 返回数量上限。
    返回：
        按策略排序后的候选账号列表（最多 limit 个）。
    """
    now = get_datetime_utc()
    query = select(DouyinAccount).where(
        DouyinAccount.owner_id == owner_id,
        col(DouyinAccount.enabled).is_(True),
        col(DouyinAccount.status).in_(
            [
                DouyinAccountStatus.ready.value,
                DouyinAccountStatus.busy.value,
                DouyinAccountStatus.cooldown.value,
            ]
        ),
        DouyinAccount.active_leases < DouyinAccount.concurrency_limit,
    )
    if account_ids:
        query = query.where(col(DouyinAccount.id).in_(account_ids))
    if pool_id:
        query = query.join(
            DouyinAccountPoolMember,
            col(DouyinAccountPoolMember.account_id) == col(DouyinAccount.id),
        ).where(DouyinAccountPoolMember.pool_id == pool_id)
    accounts = list(session.exec(query).all())
    accounts = [
        account
        for account in accounts
        if (
            account.usage_date != now.date()
            or account.tasks_today < account.daily_task_limit
        )
    ]
    if strategy == DouyinAccountPoolStrategy.weighted_round_robin:
        accounts.sort(
            key=lambda item: (
                -item.priority,
                (
                    (item.tasks_today if item.usage_date == now.date() else 0)
                    + item.active_leases
                )
                / max(item.weight, 1),
                item.last_used_at or item.created_at,
            )
        )
    elif strategy == DouyinAccountPoolStrategy.least_loaded:
        accounts.sort(
            key=lambda item: (
                item.active_leases / max(item.concurrency_limit, 1),
                item.tasks_today if item.usage_date == now.date() else 0,
                -item.priority,
                item.last_used_at or item.created_at,
            )
        )
    else:
        accounts.sort(key=lambda item: (item.created_at, str(item.id)))
    return accounts[:limit]


def select_task_accounts(
    *,
    owner_id: uuid.UUID,
    account_id: uuid.UUID | None,
    account_ids: list[uuid.UUID],
    pool_id: uuid.UUID | None,
    strategy: DouyinAccountPoolStrategy,
) -> list[DouyinAccount]:
    """为任务选择执行账号：校验池归属与可用性，应用调度策略后返回脱离会话的账号列表。

    round_robin 策略下会推进并持久化池的 rotation_cursor 游标。

    参数：
        owner_id: 归属用户 id。
        account_id: 可选，指定的单个执行账号。
        account_ids: 可选，指定的多个执行账号。
        pool_id: 可选，从该账号池中选取。
        strategy: 调度策略。
    返回：
        选中账号列表（已从会话 expunge，可跨会话安全读取）。
    异常：
        AccountConfigurationError: 账号池不存在/已停用，或指定账号未登录、
            已停用、达到并发/每日上限。
    """
    requested_ids = ([account_id] if account_id else []) + list(account_ids)
    with Session(engine) as session:
        limit = max(len(requested_ids), 1)
        pool: DouyinAccountPool | None = None
        if pool_id:
            pool = session.get(DouyinAccountPool, pool_id)
            if pool is None or pool.owner_id != owner_id or not pool.enabled:
                raise AccountConfigurationError("账号池不存在或已停用")
            limit = pool.max_parallel_accounts
        candidate_limit = 20 if pool is not None else limit
        accounts = eligible_accounts(
            session,
            owner_id=owner_id,
            account_ids=requested_ids or None,
            pool_id=pool_id,
            strategy=strategy,
            limit=candidate_limit,
        )
        if pool is not None and strategy == DouyinAccountPoolStrategy.round_robin:
            if accounts:
                offset = pool.rotation_cursor % len(accounts)
                accounts = accounts[offset:] + accounts[:offset]
                pool.rotation_cursor = (offset + min(limit, len(accounts))) % len(
                    accounts
                )
                session.add(pool)
                session.commit()
                # 提交轮询游标会使本会话内所有 ORM 实例过期，
                # 需在脱离会话前刷新候选账号，
                # 以便异步任务执行器安全读取所选账号
                for account in accounts:
                    session.refresh(account)
            accounts = accounts[:limit]
        else:
            accounts = accounts[:limit]
        if requested_ids and {item.id for item in accounts} != set(requested_ids):
            raise AccountConfigurationError(
                "所选账号未登录、已停用或已达到并发/每日上限"
            )
        for account in accounts:
            session.expunge(account)
        return accounts


def reserve_account(account_id: uuid.UUID) -> DouyinAccount:
    """以行锁方式占用一个账号租约：跨天重置计数、解除冷却，租约数与今日任务数 +1。

    参数：
        account_id: 目标账号 id。
    返回：
        脱离会话的账号快照（状态已置为 busy）。
    异常：
        AccountConfigurationError: 账号不存在或当前不可调度。
    """
    now = get_datetime_utc()
    with Session(engine) as session:
        account = session.exec(
            select(DouyinAccount)
            .where(DouyinAccount.id == account_id)
            .with_for_update()
        ).first()
        if account is None:
            raise AccountConfigurationError("账号不存在")
        if account.usage_date != now.date():
            account.usage_date = now.date()
            account.tasks_today = 0
        if account.status == DouyinAccountStatus.cooldown.value:
            account.status = DouyinAccountStatus.ready.value
            account.cooldown_until = None
        if (
            not account.enabled
            or account.status
            not in {
                DouyinAccountStatus.ready.value,
                DouyinAccountStatus.busy.value,
            }
            or account.active_leases >= account.concurrency_limit
            or account.tasks_today >= account.daily_task_limit
        ):
            raise AccountConfigurationError("账号当前不可调度")
        account.active_leases += 1
        account.tasks_today += 1
        account.status = DouyinAccountStatus.busy.value
        account.last_used_at = now
        account.updated_at = now
        session.add(account)
        session.commit()
        session.refresh(account)
        session.expunge(account)
        return account


def release_account(
    account_id: uuid.UUID, *, success: bool, error: str | None = None
) -> None:
    """释放账号租约并按执行结果更新状态。

    成功时清零失败计数；失败时累计失败数并记录错误信息，
    连续失败达到 3 次将账号置为 unhealthy。

    参数：
        account_id: 目标账号 id（账号不存在时静默返回）。
        success: 任务是否执行成功。
        error: 失败原因，截断至 1000 字符入库。
    """
    now = get_datetime_utc()
    with Session(engine) as session:
        account = session.exec(
            select(DouyinAccount)
            .where(DouyinAccount.id == account_id)
            .with_for_update()
        ).first()
        if account is None:
            return
        account.active_leases = max(account.active_leases - 1, 0)
        if success:
            account.failure_streak = 0
            account.cooldown_until = None
            account.last_error = None
        else:
            account.failure_streak += 1
            account.cooldown_until = None
            account.last_error = (error or "任务执行失败")[:1000]
        if not account.enabled:
            account.status = DouyinAccountStatus.disabled.value
        elif account.active_leases:
            account.status = DouyinAccountStatus.busy.value
        elif not success and account.failure_streak >= 3:
            account.status = DouyinAccountStatus.unhealthy.value
        elif not success:
            account.status = DouyinAccountStatus.ready.value
        else:
            account.status = DouyinAccountStatus.ready.value
        account.updated_at = now
        session.add(account)
        session.commit()


def reset_stale_account_leases() -> None:
    """清理残留租约（服务启动时调用）：租约清零、解除冷却，并按登录态与启用状态恢复账号状态。"""
    now = get_datetime_utc()
    with Session(engine) as session:
        accounts = session.exec(
            select(DouyinAccount).where(
                or_(
                    col(DouyinAccount.active_leases) > 0,
                    col(DouyinAccount.status) == DouyinAccountStatus.cooldown.value,
                    col(DouyinAccount.cooldown_until).is_not(None),
                )
            )
        ).all()
        for account in accounts:
            account.active_leases = 0
            account.cooldown_until = None
            if not account.enabled:
                account.status = DouyinAccountStatus.disabled.value
            elif account.identity_hash:
                account.status = DouyinAccountStatus.ready.value
            else:
                account.status = DouyinAccountStatus.login_required.value
            account.updated_at = now
            session.add(account)
        session.commit()


class DouyinAccountLoginManager:
    """登录会话管理器：以内存句柄表维护进行中的登录流程（浏览器会话 + 过期时间）。

    所有公开操作经异步锁串行化，防止同一账号并发开启多个登录会话；
    句柄过期后由 _expire_locked 自动关闭浏览器回收资源。
    """

    def __init__(self) -> None:
        """初始化句柄表与异步互斥锁。"""
        self._handles: dict[uuid.UUID, LoginHandle] = {}
        self._lock = asyncio.Lock()

    async def start(
        self, *, owner_id: uuid.UUID, account_id: uuid.UUID
    ) -> tuple[DouyinAccount, BrowserConnection, Any]:
        """开启登录会话：校验账号可登录，连接浏览器并打开抖音首页，登记带 TTL 的句柄。

        同账号已有会话时先关闭旧会话再新建。浏览器连接失败会将账号置为
        unhealthy；页面导航失败仅记录提示文案，会话仍可继续（用户可在
        远程浏览器中手动重试）。

        参数：
            owner_id: 归属用户 id。
            account_id: 账号 id。
        返回：
            (账号, 浏览器连接信息, 过期时间) 元组。
        异常：
            AccountLoginError: 账号不存在/已停用/正在执行任务，或 CDP 浏览器连接失败。
        """
        async with self._lock:
            await self._expire_locked()
            existing = self._handles.pop(account_id, None)
            if existing:
                await existing.browser.close()
            with Session(engine) as session:
                account = session.get(DouyinAccount, account_id)
                if account is None or account.owner_id != owner_id:
                    raise AccountLoginError("账号不存在")
                if not account.enabled:
                    raise AccountLoginError("账号已停用")
                if account.active_leases:
                    raise AccountLoginError("账号正在执行任务，暂时不能重新登录")
                connection = resolve_account_browser(account)
                account.status = DouyinAccountStatus.verifying.value
                account.last_error = None
                account.updated_at = get_datetime_utc()
                session.add(account)
                session.commit()
                session.refresh(account)

            browser = CDPBrowserSession(
                settings,
                browser_mode=connection.browser_mode,
                remote_host=connection.remote_host,
                remote_port=connection.remote_port,
                user_data_dir=connection.user_data_dir,
                debug_port=connection.debug_port,
            )
            try:
                await browser.start()
            except Exception as exc:
                await browser.close()
                with Session(engine) as session:
                    account = session.get(DouyinAccount, account_id)
                    if account:
                        account.status = DouyinAccountStatus.unhealthy.value
                        account.last_error = "CDP 浏览器连接失败，请检查对应槽位容器"
                        account.updated_at = get_datetime_utc()
                        session.add(account)
                        session.commit()
                raise AccountLoginError(
                    "CDP 浏览器连接失败，请检查对应槽位容器"
                ) from exc

            assert browser.page is not None
            navigation_warning: str | None = None
            try:
                await browser.page.goto(
                    "https://www.douyin.com",
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
            except BrowserAutomationTimeoutError:
                logger.info("Account login page load timed out; DOM remains usable")
            except BrowserAutomationError as exc:
                navigation_warning = _page_navigation_warning(exc)
                logger.warning(
                    "Account browser connected but login page navigation failed: %s",
                    navigation_warning,
                )

            if navigation_warning:
                with Session(engine) as session:
                    refreshed_account = session.get(DouyinAccount, account_id)
                    if refreshed_account is not None:
                        refreshed_account.status = DouyinAccountStatus.verifying.value
                        refreshed_account.last_error = navigation_warning
                        refreshed_account.updated_at = get_datetime_utc()
                        session.add(refreshed_account)
                        session.commit()
                        session.refresh(refreshed_account)
                        session.expunge(refreshed_account)
                        account = refreshed_account

            expires_at = get_datetime_utc() + timedelta(
                seconds=settings.DOUYIN_ACCOUNT_LOGIN_SESSION_TTL_SECONDS
            )
            self._handles[account_id] = LoginHandle(
                owner_id=owner_id,
                account_id=account_id,
                browser=browser,
                expires_at=expires_at,
            )
            return account, connection, expires_at

    async def verify(
        self, *, owner_id: uuid.UUID, account_id: uuid.UUID
    ) -> DouyinAccount:
        """验证登录结果：检测登录态并识别身份哈希，成功后账号置为 ready。

        无进行中的登录会话时会临时连接浏览器进行复验。以浏览器登录标记
        作为会话有效性的主要判断；个人资料接口仅用于识别新身份，已入库
        身份在接口不可用时允许复用旧哈希。同一用户下身份哈希必须唯一。

        参数：
            owner_id: 归属用户 id。
            account_id: 账号 id。
        返回：
            验证通过的账号实体。
        异常：
            AccountLoginError: 未检测到登录态、身份识别失败、身份与他人账号
                重复或浏览器连接失败（失败后账号置为 unhealthy）。
        """
        async with self._lock:
            await self._expire_locked()
            handle = self._handles.get(account_id)
            temporary = False
            if handle is not None and handle.owner_id != owner_id:
                raise AccountLoginError("账号不存在")
            with Session(engine) as session:
                stored_account = session.get(DouyinAccount, account_id)
                if stored_account is None or stored_account.owner_id != owner_id:
                    raise AccountLoginError("账号不存在")
                existing_identity_hash = stored_account.identity_hash
            if handle is None:
                connection = resolve_account_browser(stored_account)
                browser = CDPBrowserSession(
                    settings,
                    browser_mode=connection.browser_mode,
                    remote_host=connection.remote_host,
                    remote_port=connection.remote_port,
                    user_data_dir=connection.user_data_dir,
                    debug_port=connection.debug_port,
                )
                try:
                    await browser.start()
                except Exception as exc:
                    await browser.close()
                    message = "CDP 浏览器连接失败，请检查对应槽位容器"
                    self._record_verification_failure(
                        owner_id=owner_id,
                        account_id=account_id,
                        message=message,
                    )
                    raise AccountLoginError(message) from exc
                handle = LoginHandle(owner_id, account_id, browser, get_datetime_utc())
                temporary = True
            assert handle.browser.page is not None
            assert handle.browser.context is not None
            if temporary:
                try:
                    await handle.browser.page.goto(
                        "https://www.douyin.com",
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                except BrowserAutomationTimeoutError:
                    logger.info(
                        "Account verification page load timed out; DOM remains usable"
                    )
                except BrowserAutomationError as exc:
                    message = _page_navigation_warning(exc)
                    self._record_verification_failure(
                        owner_id=owner_id,
                        account_id=account_id,
                        message=message,
                    )
                    await handle.browser.close()
                    raise AccountLoginError(message) from exc
            client = await DouyinClient.create(
                page=handle.browser.page,
                browser_context=handle.browser.context,
                timeout=settings.DOUYIN_REQUEST_TIMEOUT,
                verify_ssl=settings.DOUYIN_REQUEST_SSL_VERIFY,
            )
            try:
                # 抖音可能出现页面已登录但个人资料接口暂时被限流的情况，
                # 因此以浏览器登录标记作为会话有效性的主要判断依据；
                # 对于新身份仍优先使用个人资料接口
                if not await client.pong(handle.browser.context):
                    raise AccountLoginError("尚未检测到有效的抖音登录状态")
                try:
                    profile_response = await client.get_self_profile()
                except Exception:
                    profile_response = {}
                raw_identity = _profile_identity(profile_response)
                if raw_identity:
                    identity_hash = anonymize_account_id(
                        raw_identity, settings.SECRET_KEY
                    )
                elif existing_identity_hash:
                    # 已入库账号的复验不应仅因资料接口不可用而失败；
                    # 此处不会持久化任何 cookie 值
                    identity_hash = existing_identity_hash
                else:
                    raise AccountLoginError(
                        "已检测到登录状态，但暂时无法识别新账号身份，请刷新抖音页面后重试"
                    )
            except AccountLoginError as exc:
                self._record_verification_failure(
                    owner_id=owner_id,
                    account_id=account_id,
                    message=str(exc),
                )
                raise
            finally:
                await client.close()
                if temporary:
                    await handle.browser.close()

            with Session(engine) as session:
                account = session.get(DouyinAccount, account_id)
                if account is None or account.owner_id != owner_id:
                    raise AccountLoginError("账号不存在")
                duplicate = session.exec(
                    select(DouyinAccount).where(
                        DouyinAccount.owner_id == owner_id,
                        DouyinAccount.identity_hash == identity_hash,
                        DouyinAccount.id != account_id,
                    )
                ).first()
                if duplicate:
                    raise AccountLoginError("该抖音账号已在账号管理中")
                account.identity_hash = identity_hash
                account.status = DouyinAccountStatus.ready.value
                account.failure_streak = 0
                account.cooldown_until = None
                account.last_error = None
                account.last_verified_at = get_datetime_utc()
                account.updated_at = get_datetime_utc()
                session.add(account)
                session.commit()
                session.refresh(account)

            persistent = self._handles.pop(account_id, None)
            if persistent:
                await persistent.browser.close()
            return account

    @staticmethod
    def _record_verification_failure(
        *, owner_id: uuid.UUID, account_id: uuid.UUID, message: str
    ) -> None:
        # 记录验证失败：账号置为 unhealthy 并写入错误信息（账号不存在时静默返回）
        with Session(engine) as session:
            account = session.get(DouyinAccount, account_id)
            if account is None or account.owner_id != owner_id:
                return
            account.status = DouyinAccountStatus.unhealthy.value
            account.last_error = message
            account.updated_at = get_datetime_utc()
            session.add(account)
            session.commit()

    async def close(self, account_id: uuid.UUID) -> None:
        """关闭并移除指定账号的登录句柄（无句柄时静默返回）。"""
        async with self._lock:
            handle = self._handles.pop(account_id, None)
            if handle:
                await handle.browser.close()

    async def shutdown(self) -> None:
        """关闭全部登录句柄（服务停机时调用），单个关闭失败不影响其余句柄。"""
        async with self._lock:
            handles = list(self._handles.values())
            self._handles.clear()
        await asyncio.gather(
            *(handle.browser.close() for handle in handles), return_exceptions=True
        )

    async def _expire_locked(self) -> None:
        # 清理已过期的登录句柄并关闭其浏览器；须在持有 self._lock 时调用
        now = get_datetime_utc()
        expired = [
            account_id
            for account_id, handle in self._handles.items()
            if handle.expires_at <= now
        ]
        for account_id in expired:
            handle = self._handles.pop(account_id)
            await handle.browser.close()


def _profile_identity(payload: dict[str, Any]) -> str:
    # 从抖音个人资料接口响应中提取用户身份标识（uid / sec_uid / sec_user_id），提取不到返回空串
    data = payload.get("data")
    profile = (
        payload.get("user")
        or payload.get("user_info")
        or (data.get("user") if isinstance(data, dict) else None)
        or (data.get("user_info") if isinstance(data, dict) else None)
        or data
    )
    if not isinstance(profile, dict):
        return ""
    return str(
        profile.get("uid") or profile.get("sec_uid") or profile.get("sec_user_id") or ""
    ).strip()


# 全局单例：进程内共享的登录会话管理器
account_login_manager = DouyinAccountLoginManager()
