import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import engine
from app.douyin.browser import CDPBrowserSession
from app.douyin.client import DouyinClient
from app.douyin.privacy import anonymize_account_id
from app.models import (
    DouyinAccount,
    DouyinAccountCreate,
    DouyinAccountPool,
    DouyinAccountPoolMember,
    DouyinAccountPoolStrategy,
    DouyinAccountStatus,
    DouyinAccountUpdate,
    DouyinBrowserMode,
    get_datetime_utc,
)

logger = logging.getLogger(__name__)


class AccountConfigurationError(ValueError):
    pass


class AccountLoginError(RuntimeError):
    pass


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
        raise AccountConfigurationError("DOUYIN_REMOTE_CDP_SLOTS 不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise AccountConfigurationError("DOUYIN_REMOTE_CDP_SLOTS 必须是对象")
    result: dict[str, dict[str, object]] = {}
    for name, value in payload.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(value, dict):
            raise AccountConfigurationError("远程浏览器槽位配置格式无效")
        result[name] = value
    return result


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
        slots = _remote_slots()
        if request.remote_slot and request.remote_slot not in slots:
            raise AccountConfigurationError(
                f"远程浏览器槽位 {request.remote_slot} 未配置"
            )
        occupied = session.exec(
            select(DouyinAccount).where(
                DouyinAccount.owner_id == owner_id,
                DouyinAccount.browser_mode == DouyinBrowserMode.remote.value,
                DouyinAccount.remote_slot == request.remote_slot,
                col(DouyinAccount.enabled).is_(True),
            )
        ).first()
        if occupied is not None:
            label = request.remote_slot or "默认"
            raise AccountConfigurationError(f"远程浏览器槽位 {label} 已绑定账号")
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
        if (account.cooldown_until is None or account.cooldown_until <= now)
        and (
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
    else:
        accounts.sort(
            key=lambda item: (
                item.active_leases / max(item.concurrency_limit, 1),
                item.tasks_today if item.usage_date == now.date() else 0,
                -item.priority,
                item.last_used_at or item.created_at,
            )
        )
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
        if pool_id:
            pool = session.get(DouyinAccountPool, pool_id)
            if pool is None or pool.owner_id != owner_id or not pool.enabled:
                raise AccountConfigurationError("账号池不存在或已停用")
            strategy = DouyinAccountPoolStrategy(pool.strategy)
            limit = pool.max_parallel_accounts
        accounts = eligible_accounts(
            session,
            owner_id=owner_id,
            account_ids=requested_ids or None,
            pool_id=pool_id,
            strategy=strategy,
            limit=limit,
        )
        if requested_ids and {item.id for item in accounts} != set(requested_ids):
            raise AccountConfigurationError(
                "所选账号未登录、已停用、冷却中或已达到并发/每日上限"
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
        if (
            account.status == DouyinAccountStatus.cooldown.value
            and (account.cooldown_until is None or account.cooldown_until <= now)
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
            or (account.cooldown_until is not None and account.cooldown_until > now)
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
            account.cooldown_until = now + timedelta(
                seconds=settings.DOUYIN_ACCOUNT_FAILURE_COOLDOWN_SECONDS
            )
            account.last_error = (error or "任务执行失败")[:1000]
        if not account.enabled:
            account.status = DouyinAccountStatus.disabled.value
        elif account.active_leases:
            account.status = DouyinAccountStatus.busy.value
        elif not success and account.failure_streak >= 3:
            account.status = DouyinAccountStatus.unhealthy.value
        elif not success:
            account.status = DouyinAccountStatus.cooldown.value
        else:
            account.status = DouyinAccountStatus.ready.value
        account.updated_at = now
        session.add(account)
        session.commit()


def reset_stale_account_leases() -> None:
    now = get_datetime_utc()
    with Session(engine) as session:
        accounts = session.exec(
            select(DouyinAccount).where(DouyinAccount.active_leases > 0)
        ).all()
        for account in accounts:
            account.active_leases = 0
            if not account.enabled:
                account.status = DouyinAccountStatus.disabled.value
            elif account.cooldown_until is not None and account.cooldown_until > now:
                account.status = DouyinAccountStatus.cooldown.value
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
                assert browser.page is not None
                try:
                    await browser.page.goto(
                        "https://www.douyin.com",
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )
                except PlaywrightTimeoutError:
                    logger.info("Account login page load timed out; DOM remains usable")
            except Exception:
                await browser.close()
                with Session(engine) as session:
                    account = session.get(DouyinAccount, account_id)
                    if account:
                        account.status = DouyinAccountStatus.unhealthy.value
                        account.last_error = "CDP 浏览器连接失败"
                        account.updated_at = get_datetime_utc()
                        session.add(account)
                        session.commit()
                raise

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
            if handle is None:
                with Session(engine) as session:
                    account = session.get(DouyinAccount, account_id)
                    if account is None or account.owner_id != owner_id:
                        raise AccountLoginError("账号不存在")
                    connection = resolve_account_browser(account)
                browser = CDPBrowserSession(
                    settings,
                    browser_mode=connection.browser_mode,
                    remote_host=connection.remote_host,
                    remote_port=connection.remote_port,
                    user_data_dir=connection.user_data_dir,
                    debug_port=connection.debug_port,
                )
                await browser.start()
                handle = LoginHandle(owner_id, account_id, browser, get_datetime_utc())
                temporary = True
            assert handle.browser.page is not None
            assert handle.browser.context is not None
            client = await DouyinClient.create(
                page=handle.browser.page,
                browser_context=handle.browser.context,
                timeout=settings.DOUYIN_REQUEST_TIMEOUT,
                verify_ssl=settings.DOUYIN_REQUEST_SSL_VERIFY,
            )
            try:
                if not await client.pong(
                    handle.browser.context, require_self_profile=True
                ):
                    raise AccountLoginError("尚未检测到有效的抖音登录状态")
                profile_response = await client.get_self_profile()
                raw_identity = _profile_identity(profile_response)
                if not raw_identity:
                    raise AccountLoginError("登录状态有效，但无法识别账号身份")
                identity_hash = anonymize_account_id(raw_identity, settings.SECRET_KEY)
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
