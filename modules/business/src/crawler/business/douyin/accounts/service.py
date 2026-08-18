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
    pass


class AccountLoginError(RuntimeError):
    pass


class AccountNotFoundError(LookupError):
    """The requested account is absent or does not belong to the owner."""


class AccountInUseError(RuntimeError):
    """The requested account currently owns one or more execution leases."""


class AccountPoolNotFoundError(LookupError):
    """The requested account pool is absent or does not belong to the owner."""


class AccountPoolMembershipError(ValueError):
    """An account pool references an account outside the owner's account set."""


class AccountPoolConflictError(ValueError):
    """An account pool violates a persistence uniqueness constraint."""


@dataclass(frozen=True)
class BrowserConnection:
    browser_mode: DouyinBrowserMode
    remote_host: str | None = None
    remote_port: int | None = None
    viewer_url: str | None = None
    user_data_dir: Path | None = None
    debug_port: int | None = None


@dataclass
class LoginHandle:
    owner_id: uuid.UUID
    account_id: uuid.UUID
    browser: CDPBrowserSession
    expires_at: datetime


def account_public_values(account: DouyinAccount) -> dict[str, object]:
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
    """Load an account without exposing another owner's account existence."""

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
    """Return one owner's accounts in the existing newest-first order."""

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
    """Authorize and update an account in one application use case."""

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
    """Delete an idle account and its isolated local browser profile."""

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
    """Load an account pool without exposing another owner's pool existence."""

    pool = session.get(DouyinAccountPool, pool_id)
    if pool is None or pool.owner_id != owner_id:
        raise AccountPoolNotFoundError
    return pool


def account_pool_public(
    session: Session, pool: DouyinAccountPool
) -> DouyinAccountPoolPublic:
    """Build the established pool response including ordered account summaries."""

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
    """Return all account pools owned by a user."""

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
    """Create a pool and replace its membership atomically."""

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
    """Authorize and update a pool and its optional member set atomically."""

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
    """Delete a pool without deleting its member accounts."""

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
                # Committing the rotation cursor expires every ORM instance in
                # this session. Refresh candidates before detaching them so the
                # async task runner can safely read the selected account.
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
    def __init__(self) -> None:
        self._handles: dict[uuid.UUID, LoginHandle] = {}
        self._lock = asyncio.Lock()

    async def start(
        self, *, owner_id: uuid.UUID, account_id: uuid.UUID
    ) -> tuple[DouyinAccount, BrowserConnection, Any]:
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
                # Douyin may render an authenticated page while its self-profile API is
                # temporarily blocked. Browser login markers are therefore the primary
                # session check; the profile API is still preferred for a new identity.
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
                    # Re-verification of a persisted profile must not fail only because
                    # the profile endpoint is unavailable. No cookie value is persisted.
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
        async with self._lock:
            handle = self._handles.pop(account_id, None)
            if handle:
                await handle.browser.close()

    async def shutdown(self) -> None:
        async with self._lock:
            handles = list(self._handles.values())
            self._handles.clear()
        await asyncio.gather(
            *(handle.browser.close() for handle in handles), return_exceptions=True
        )

    async def _expire_locked(self) -> None:
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


account_login_manager = DouyinAccountLoginManager()
