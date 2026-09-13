"""抖音账号应用服务。

覆盖账号与账号池的 CRUD、调度选择与租约管理，以及基于 CDP 浏览器的
登录会话（DouyinAccountLoginManager）的发起、验证与生命周期管理。
"""

import asyncio
import concurrent.futures
import json
import logging
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from crawler.bootstrap.database import engine
from crawler.bootstrap.settings import settings
from crawler.browser.facade import (
    BrowserAutomationError,
    BrowserAutomationTimeoutError,
    BrowserSessionSpec,
    CDPBrowserSession,
    probe_cdp_pages,
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
from crawler.business.douyin.adapters.service import (
    DouyinLoginApi,
    open_douyin_client,
)
from crawler.douyin_client import anonymize_account_id
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
        "slot": account.slot,
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


def local_slot_name(index: int) -> str:
    """返回第 index 个（从 1 起）本机浏览器槽位的槽位名。"""
    return f"local-{index}"


def _local_slots() -> dict[str, dict[str, object]]:
    """生成本机浏览器槽位注册表 ``{槽位名: {host, port, user_data_dir}}``。

    槽位数量由 ``DOUYIN_LOCAL_CDP_SLOT_COUNT`` 决定（默认 4 个本机浏览器），
    槽位名为 local-1 … local-N；第 n 个槽位占用 CDP 端口
    ``DOUYIN_LOCAL_CDP_PORT_BASE + n - 1``，Profile 目录为
    ``DOUYIN_LOCAL_CDP_USER_DATA_DIR/<槽位名>``。

    返回：
        槽位名到槽位配置的字典；未启用本机槽位时为空。
    """
    root = settings.DOUYIN_LOCAL_CDP_USER_DATA_DIR.resolve()
    return {
        local_slot_name(index): {
            "host": settings.DOUYIN_CDP_HOST,
            "port": settings.DOUYIN_LOCAL_CDP_PORT_BASE + index - 1,
            "user_data_dir": root / local_slot_name(index),
        }
        for index in range(1, settings.DOUYIN_LOCAL_CDP_SLOT_COUNT + 1)
    }


def _slot_registry(browser_mode: DouyinBrowserMode) -> dict[str, dict[str, object]]:
    # 按运行模式取槽位注册表：本机槽位来自配置生成，远程槽位来自环境 JSON
    if browser_mode == DouyinBrowserMode.local:
        return _local_slots()
    return _remote_slots()


def _slot_mode_label(browser_mode: DouyinBrowserMode) -> str:
    # 槽位在面向用户文案中的模式前缀
    return "本机浏览器" if browser_mode == DouyinBrowserMode.local else "远程浏览器"


def browser_slot_public_values(
    session: Session, owner_id: uuid.UUID
) -> list[dict[str, object]]:
    """汇总本机槽位与远程槽位的占用情况和健康探测结果。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 id（仅统计该用户的槽位占用）。
    返回：
        槽位状态字典列表（本机槽位在前、远程槽位在后），
        字段与 DouyinBrowserSlotPublic 一一对应。
    """
    accounts = session.exec(
        select(DouyinAccount).where(DouyinAccount.owner_id == owner_id)
    ).all()
    occupied = {(account.browser_mode, account.slot): account for account in accounts}
    configured_slots: list[
        tuple[DouyinBrowserMode, str | None, str, dict[str, object]]
    ] = [
        (
            DouyinBrowserMode.local,
            name,
            f"本机浏览器 {name.removeprefix('local-')}",
            config,
        )
        for name, config in _local_slots().items()
    ]
    configured_slots.append(
        (
            DouyinBrowserMode.remote,
            None,
            "Docker 默认槽位",
            {
                "host": settings.DOUYIN_REMOTE_CDP_HOST,
                "port": settings.DOUYIN_REMOTE_CDP_PORT,
                "viewer_url": settings.DOUYIN_REMOTE_VIEWER_URL,
            },
        )
    )
    configured_slots.extend(
        (DouyinBrowserMode.remote, name, name, value)
        for name, value in sorted(_remote_slots().items())
    )
    checked_at = get_datetime_utc()

    def probe(config: dict[str, object]) -> dict[str, object]:
        # 单个槽位的 CDP 健康探测：解析主机/端口后委托 browser 门面能力
        host = str(config.get("host") or "").strip()
        try:
            port = int(str(config.get("port") or 0))
        except (TypeError, ValueError):
            port = 0
        return probe_cdp_pages(host, port)

    probe_results: list[dict[str, object]] = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(8, max(1, len(configured_slots)))
    ) as executor:
        probe_results = list(
            executor.map(lambda item: probe(item[3]), configured_slots)
        )

    result: list[dict[str, object]] = []
    for (browser_mode, name, label, config), health in zip(
        configured_slots, probe_results, strict=True
    ):
        account = occupied.get((browser_mode.value, name))
        host = str(config.get("host") or "").strip()
        try:
            port = int(str(config.get("port") or 0))
        except (TypeError, ValueError):
            port = 0
        configured = bool(host and 1 <= port <= 65535)
        result.append(
            {
                "browser_mode": browser_mode,
                "name": name,
                "label": label,
                "is_default": browser_mode == DouyinBrowserMode.remote and name is None,
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


def _validate_slot_assignment(
    session: Session,
    *,
    owner_id: uuid.UUID,
    browser_mode: DouyinBrowserMode,
    slot: str | None,
    exclude_account_id: uuid.UUID | None = None,
) -> None:
    # 校验槽位已配置且未被同用户同模式下的其他账号占用
    # （exclude_account_id 用于更新时排除自身）
    mode_label = _slot_mode_label(browser_mode)
    if slot is None and browser_mode == DouyinBrowserMode.local:
        # 未绑定槽位的本机账号各自使用独立 Profile 目录，可以共存；
        # 远程的 None 代表 Docker 默认槽位，仍受独占约束
        return
    slots = _slot_registry(browser_mode)
    if slot and slot not in slots:
        raise AccountConfigurationError(f"{mode_label}槽位 {slot} 未配置")
    filters = [
        DouyinAccount.owner_id == owner_id,
        DouyinAccount.browser_mode == browser_mode.value,
        DouyinAccount.slot == slot,
    ]
    if exclude_account_id is not None:
        filters.append(DouyinAccount.id != exclude_account_id)
    occupied = session.exec(select(DouyinAccount).where(*filters)).first()
    if occupied is not None:
        label = slot or "默认"
        raise AccountConfigurationError(
            f"{mode_label}槽位 {label} 已绑定账号“{occupied.name}”"
        )


def resolve_account_browser(account: DouyinAccount) -> BrowserSessionSpec:
    """按账号的浏览器模式解析出对应的 CDP 连接参数。

    本地模式优先使用账号绑定的本机槽位（独立 Profile 目录 + 槽位调试端口，
    会话结束后保留浏览器进程供后续复用）；未绑定槽位的历史账号沿用账号
    独立用户数据目录与按账号 id 派生的调试端口；
    远程模式使用账号绑定的槽位配置，未绑定时回退到默认远程地址。

    参数：
        account: 账号实体。
    返回：
        BrowserSessionSpec 连接参数。
    异常：
        AccountConfigurationError: 槽位未配置或主机/端口非法。
    """
    mode = DouyinBrowserMode(account.browser_mode)
    if mode == DouyinBrowserMode.local:
        slots = _local_slots()
        if account.slot:
            slot = slots.get(account.slot)
            if slot is None:
                raise AccountConfigurationError(f"本机浏览器槽位 {account.slot} 未配置")
            user_data_dir = slot.get("user_data_dir")
            port = int(str(slot.get("port") or 0))
            if not isinstance(user_data_dir, Path) or not 1 <= port <= 65535:
                raise AccountConfigurationError("本机浏览器槽位配置无效")
            return BrowserSessionSpec(
                browser_mode=account.browser_mode,
                slot_name=account.slot,
                user_data_dir=user_data_dir,
                debug_port=port,
                keep_alive=True,
            )
        profile_root = settings.DOUYIN_CDP_USER_DATA_DIR.resolve().parent / "accounts"
        return BrowserSessionSpec(
            browser_mode=account.browser_mode,
            user_data_dir=profile_root / account.profile_key,
            debug_port=settings.DOUYIN_CDP_PORT + (account.id.int % 500),
        )

    slots = _remote_slots()
    if account.slot:
        slot = slots.get(account.slot)
        if slot is None:
            raise AccountConfigurationError(f"远程浏览器槽位 {account.slot} 未配置")
        host = str(slot.get("host") or "").strip()
        try:
            port = int(str(slot.get("port") or 0))
        except (TypeError, ValueError) as exc:
            raise AccountConfigurationError("远程浏览器槽位端口无效") from exc
        viewer_url = str(slot.get("viewer_url") or "").strip() or None
        if not host or not 1 <= port <= 65535:
            raise AccountConfigurationError("远程浏览器槽位主机或端口无效")
        return BrowserSessionSpec(
            browser_mode=account.browser_mode,
            slot_name=account.slot,
            remote_host=host,
            remote_port=port,
            viewer_url=viewer_url,
        )
    return BrowserSessionSpec(
        browser_mode=account.browser_mode,
        remote_host=settings.DOUYIN_REMOTE_CDP_HOST,
        remote_port=settings.DOUYIN_REMOTE_CDP_PORT,
        viewer_url=settings.DOUYIN_REMOTE_VIEWER_URL or None,
    )


def local_account_profile_dir(account: DouyinAccount) -> Path | None:
    """返回本机账号受管的 Profile 目录；非本机模式或路径越界时返回 None。

    绑定槽位的账号以槽位 Profile 目录（``local-N``）承载登录态，未绑定槽位
    的历史账号使用独立的 ``accounts/<profile_key>`` 目录。返回值一定落在
    受管根目录的直接子级，调用方据此安全清理。

    参数：
        account: 账号实体。
    返回：
        Profile 目录，或 None（非本机模式 / 槽位未配置 / 路径越界）。
    """
    if account.browser_mode != DouyinBrowserMode.local.value:
        return None
    if account.slot:
        slot = _local_slots().get(account.slot)
        user_data_dir = slot.get("user_data_dir") if slot else None
        if not isinstance(user_data_dir, Path):
            return None
        root = settings.DOUYIN_LOCAL_CDP_USER_DATA_DIR.resolve()
        candidate = user_data_dir.resolve()
    else:
        root = (
            settings.DOUYIN_CDP_USER_DATA_DIR.resolve().parent / "accounts"
        ).resolve()
        candidate = (root / account.profile_key).resolve()
    return candidate if candidate.parent == root else None


def create_account(
    session: Session, owner_id: uuid.UUID, request: DouyinAccountCreate
) -> DouyinAccount:
    """创建抖音账号：校验槽位绑定后落库，profile_key 随机生成。

    本机模式绑定本机槽位（默认 local-1 … local-4），远程模式绑定远程槽位；
    同一用户下同一模式的同一槽位只能被一个账号占用。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 id。
        request: 创建请求参数。
    返回：
        创建后的账号实体。
    异常：
        AccountConfigurationError: 槽位冲突/未配置，或名称、Profile 违反唯一约束。
    """
    _validate_slot_assignment(
        session,
        owner_id=owner_id,
        browser_mode=request.browser_mode,
        slot=request.slot,
    )

    account = DouyinAccount(
        owner_id=owner_id,
        name=request.name.strip(),
        browser_mode=request.browser_mode.value,
        profile_key=uuid.uuid4().hex,
        slot=request.slot,
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
    if "slot" in values:
        # 浏览器模式不支持变更，槽位只在本账号当前的模式注册表内校验
        _validate_slot_assignment(
            session,
            owner_id=account.owner_id,
            browser_mode=DouyinBrowserMode(account.browser_mode),
            slot=values["slot"],
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

    本机槽位账号清理的是槽位 Profile 目录，使槽位可以被下一个账号以干净
    的登录态重新绑定。

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
    local_profile = local_account_profile_dir(account)

    session.delete(account)
    session.commit()
    if local_profile is not None and local_profile.exists():
        # 槽位浏览器若仍在运行，Windows 会因文件占用而留下残留 Profile；
        # 尽力清理并告警，避免下一个账号复用上一个账号的登录态。
        await asyncio.to_thread(shutil.rmtree, local_profile, ignore_errors=True)
        if local_profile.exists():
            logger.warning("本机浏览器 Profile 目录未能完全清理: %s", local_profile)


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
            (
                account.usage_date != now.date()
                or account.tasks_today < account.daily_task_limit
            )
            and not (
                account.status == DouyinAccountStatus.cooldown.value
                and account.cooldown_until is not None
                and account.cooldown_until > now
            )
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
            requested = session.exec(
                select(DouyinAccount).where(
                    DouyinAccount.owner_id == owner_id,
                    col(DouyinAccount.id).in_(requested_ids),
                )
            ).all()
            permanent_invalid = len(requested) != len(set(requested_ids)) or any(
                not item.enabled
                or not item.identity_hash
                or item.status
                not in {
                    DouyinAccountStatus.ready.value,
                    DouyinAccountStatus.busy.value,
                    DouyinAccountStatus.cooldown.value,
                }
                for item in requested
            )
            if permanent_invalid:
                raise AccountConfigurationError("所选账号不存在、未登录或已停用")
            raise AccountConfigurationError("所选账号当前不可调度，请等待可用容量")
        for account in accounts:
            session.expunge(account)
        return accounts


def reserve_accounts(account_ids: list[uuid.UUID]) -> list[DouyinAccount]:
    """在同一事务中原子占用一组账号，避免账号池并发选择后的部分失败。

    全部账号都可调度时才提交租约；任一账号不可调度会整体回滚，不留下
    半组租约或错误的 active_leases。返回顺序与 account_ids 一致。
    """
    ordered_ids = list(dict.fromkeys(account_ids))
    if not ordered_ids:
        return []
    now = get_datetime_utc()
    with Session(engine) as session:
        rows = session.exec(
            select(DouyinAccount)
            .where(col(DouyinAccount.id).in_(ordered_ids))
            .order_by(col(DouyinAccount.id))
            .with_for_update()
        ).all()
        by_id = {account.id: account for account in rows}
        if len(by_id) != len(ordered_ids):
            raise AccountConfigurationError("账号不存在")
        selected = [by_id[account_id] for account_id in ordered_ids]
        for account in selected:
            if account.usage_date != now.date():
                account.usage_date = now.date()
                account.tasks_today = 0
            if account.status == DouyinAccountStatus.cooldown.value and (
                account.cooldown_until is None or account.cooldown_until <= now
            ):
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
                or (
                    account.status == DouyinAccountStatus.cooldown.value
                    and account.cooldown_until is not None
                    and account.cooldown_until > now
                )
            ):
                raise AccountConfigurationError("账号当前不可调度")
        for account in selected:
            account.active_leases += 1
            account.tasks_today += 1
            account.status = DouyinAccountStatus.busy.value
            account.last_used_at = now
            account.updated_at = now
            session.add(account)
        session.commit()
        for account in selected:
            session.refresh(account)
            session.expunge(account)
        return selected


def reserve_account(account_id: uuid.UUID) -> DouyinAccount:
    """以行锁方式占用一个账号租约：跨天重置计数、解除冷却，租约数与今日任务数 +1。

    参数：
        account_id: 目标账号 id。
    返回：
        脱离会话的账号快照（状态已置为 busy）。
    异常：
        AccountConfigurationError: 账号不存在或当前不可调度。
    """
    return reserve_accounts([account_id])[0]


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
    ) -> tuple[DouyinAccount, BrowserSessionSpec, Any]:
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

            browser = CDPBrowserSession.from_spec(settings, connection)
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

            navigation_warning: str | None = None
            try:
                await browser.open("https://www.douyin.com")
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

        浏览器窗口被用户关闭或进程退出后，内存里的登录句柄可能已经失效：
        此时先丢弃失效句柄并重建会话，再把浏览器/驱动异常统一转成
        ``AccountLoginError``（HTTP 409），不让底层异常漏成 500。

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
            if handle is not None and not handle.browser.is_usable():
                # 用户关掉浏览器窗口、浏览器进程退出后，内存句柄还在但已不可用；
                # 必须丢弃并重建会话，否则后续取 cookie 会抛 TargetClosedError
                await self._discard_handle(account_id, handle)
                handle = None
            with Session(engine) as session:
                stored_account = session.get(DouyinAccount, account_id)
                if stored_account is None or stored_account.owner_id != owner_id:
                    raise AccountLoginError("账号不存在")
                existing_identity_hash = stored_account.identity_hash
            if handle is None:
                connection = resolve_account_browser(stored_account)
                browser = CDPBrowserSession.from_spec(settings, connection)
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
            if temporary:
                try:
                    await handle.browser.open("https://www.douyin.com")
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
            try:
                client = await open_douyin_client(
                    page=handle.browser.browser_page,
                    settings=settings,
                )
            except Exception as exc:
                # 会话在「可用性检查」与「实际取页面」之间失效（竞态），
                # 或抖音客户端初始化失败：转成业务错误，不能漏成 500
                message = "浏览器会话已失效，请重新点击「登录」后再验证"
                logger.warning(
                    "Login session unusable while building client: %s",
                    type(exc).__name__,
                )
                self._record_verification_failure(
                    owner_id=owner_id,
                    account_id=account_id,
                    message=message,
                )
                if temporary:
                    await handle.browser.close()
                raise AccountLoginError(message) from exc
            api = DouyinLoginApi(client=client)
            try:
                # 抖音可能出现页面已登录但个人资料接口暂时被限流的情况，
                # 因此以浏览器登录标记作为会话有效性的主要判断依据；
                # 对于新身份仍优先使用个人资料接口
                if not await api.verify_login():
                    if not handle.browser.is_usable():
                        # 浏览器在验证过程中被关闭/退出：这是会话问题，不是账号未登录，
                        # 否则用户会误以为要重新扫码
                        raise AccountLoginError(
                            "验证时浏览器会话已中断，请重新点击「登录」后再验证"
                        )
                    raise AccountLoginError("尚未检测到有效的抖音登录状态")
                try:
                    profile_response = await api.get_self_profile()
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
            except Exception as exc:
                # 页面/浏览器在验证过程中失效（窗口被关、CDP 断开、驱动退出等）：
                # 统一转成业务错误，不能让底层异常漏成 500
                message = "验证过程中浏览器会话中断，请重新点击「登录」后再验证"
                logger.warning(
                    "Account verification aborted by browser error: %s",
                    type(exc).__name__,
                    exc_info=True,
                )
                self._record_verification_failure(
                    owner_id=owner_id,
                    account_id=account_id,
                    message=message,
                )
                raise AccountLoginError(message) from exc
            finally:
                await api.aclose()
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

    async def _discard_handle(self, account_id: uuid.UUID, handle: LoginHandle) -> None:
        """丢弃一个失效/过期的登录句柄：先摘除登记，再尽力关闭其浏览器会话。

        须在持有 ``self._lock`` 时调用；关闭失败只记 debug 日志，不影响调用方
        继续用新建的会话完成验证。

        参数：
            account_id: 账号 id。
            handle: 待丢弃的句柄。
        """
        self._handles.pop(account_id, None)
        try:
            await handle.browser.close()
        except Exception:
            logger.debug("Failed to close stale login session", exc_info=True)

    async def close(self, account_id: uuid.UUID) -> None:
        """关闭并移除指定账号的登录句柄（无句柄时静默返回）。"""
        async with self._lock:
            handle = self._handles.get(account_id)
            if handle is not None:
                await self._discard_handle(account_id, handle)

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
            await self._discard_handle(account_id, self._handles[account_id])


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
