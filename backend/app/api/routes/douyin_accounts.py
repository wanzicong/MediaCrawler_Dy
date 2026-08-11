import asyncio
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import (
    DouyinAccount,
    DouyinAccountCreate,
    DouyinAccountLoginSessionPublic,
    DouyinAccountPool,
    DouyinAccountPoolCreate,
    DouyinAccountPoolMember,
    DouyinAccountPoolPublic,
    DouyinAccountPoolsPublic,
    DouyinAccountPoolUpdate,
    DouyinAccountPublic,
    DouyinAccountsPublic,
    DouyinAccountStatus,
    DouyinAccountUpdate,
    DouyinBrowserSlotPublic,
    DouyinBrowserSlotsPublic,
    Message,
    get_datetime_utc,
)
from app.services.douyin_accounts import (
    AccountConfigurationError,
    AccountLoginError,
    account_login_manager,
    account_public_values,
    create_account,
    remote_slot_public_values,
    update_account,
)

router = APIRouter(prefix="/douyin/accounts", tags=["douyin-accounts"])


def _get_account(
    session: SessionDep, current_user: CurrentUser, account_id: uuid.UUID
) -> DouyinAccount:
    account = session.get(DouyinAccount, account_id)
    if account is None or account.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="抖音账号不存在")
    return account


def _get_pool(
    session: SessionDep, current_user: CurrentUser, pool_id: uuid.UUID
) -> DouyinAccountPool:
    pool = session.get(DouyinAccountPool, pool_id)
    if pool is None or pool.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="账号池不存在")
    return pool


def _pool_public(session: SessionDep, pool: DouyinAccountPool) -> DouyinAccountPoolPublic:
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
        accounts=[DouyinAccountPublic(**account_public_values(item)) for item in accounts],
        created_at=pool.created_at,
        updated_at=pool.updated_at,
    )


def _replace_pool_members(
    session: SessionDep,
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
            raise HTTPException(status_code=422, detail="账号池包含不存在的账号")
    existing = session.exec(
        select(DouyinAccountPoolMember).where(
            DouyinAccountPoolMember.pool_id == pool_id
        )
    ).all()
    for member in existing:
        session.delete(member)
    for account_id in unique_ids:
        session.add(DouyinAccountPoolMember(pool_id=pool_id, account_id=account_id))


@router.get("", response_model=DouyinAccountsPublic)
def list_accounts(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> Any:
    filters = [DouyinAccount.owner_id == current_user.id]
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


@router.get("/browser-slots", response_model=DouyinBrowserSlotsPublic)
def list_browser_slots(
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    values = remote_slot_public_values(session, current_user.id)
    return DouyinBrowserSlotsPublic(
        data=[DouyinBrowserSlotPublic(**item) for item in values],
        count=len(values),
    )


@router.post("", response_model=DouyinAccountPublic, status_code=status.HTTP_201_CREATED)
def add_account(
    request: DouyinAccountCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    try:
        account = create_account(session, current_user.id, request)
    except AccountConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DouyinAccountPublic(**account_public_values(account))


@router.patch("/by-id/{account_id}", response_model=DouyinAccountPublic)
def edit_account(
    request: DouyinAccountUpdate,
    session: SessionDep,
    current_user: CurrentUser,
    account_id: uuid.UUID,
) -> Any:
    account = _get_account(session, current_user, account_id)
    if account.active_leases and request.enabled is False:
        raise HTTPException(status_code=409, detail="账号正在执行任务，暂时不能停用")
    try:
        account = update_account(session, account, request)
    except AccountConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DouyinAccountPublic(**account_public_values(account))


@router.delete("/by-id/{account_id}")
async def delete_account(
    session: SessionDep,
    current_user: CurrentUser,
    account_id: uuid.UUID,
) -> Message:
    account = _get_account(session, current_user, account_id)
    if account.active_leases:
        raise HTTPException(status_code=409, detail="账号正在执行任务，不能删除")
    await account_login_manager.close(account.id)
    local_profile: Path | None = None
    if account.browser_mode == "local":
        root = (settings.DOUYIN_CDP_USER_DATA_DIR.resolve().parent / "accounts").resolve()
        candidate = (root / account.profile_key).resolve()
        if candidate.parent == root:
            local_profile = candidate
    session.delete(account)
    session.commit()
    if local_profile and local_profile.exists():
        await asyncio.to_thread(shutil.rmtree, local_profile)
    return Message(message="抖音账号及独立浏览器 Profile 已删除")


@router.post(
    "/by-id/{account_id}/login",
    response_model=DouyinAccountLoginSessionPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_account_login(
    session: SessionDep,
    current_user: CurrentUser,
    account_id: uuid.UUID,
) -> Any:
    _get_account(session, current_user, account_id)
    try:
        account, connection, expires_at = await account_login_manager.start(
            owner_id=current_user.id, account_id=account_id
        )
    except (AccountLoginError, AccountConfigurationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DouyinAccountLoginSessionPublic(
        account=DouyinAccountPublic(**account_public_values(account)),
        status=DouyinAccountStatus.verifying,
        browser_mode=connection.browser_mode,
        viewer_url=connection.viewer_url,
        expires_at=expires_at,
        message=(
            account.last_error
            or "浏览器已打开，请完成登录后点击验证登录"
        ),
    )


@router.post("/by-id/{account_id}/verify", response_model=DouyinAccountPublic)
async def verify_account_login(
    session: SessionDep,
    current_user: CurrentUser,
    account_id: uuid.UUID,
) -> Any:
    _get_account(session, current_user, account_id)
    try:
        account = await account_login_manager.verify(
            owner_id=current_user.id, account_id=account_id
        )
    except (AccountLoginError, AccountConfigurationError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return DouyinAccountPublic(**account_public_values(account))


@router.get("/pools", response_model=DouyinAccountPoolsPublic)
def list_pools(session: SessionDep, current_user: CurrentUser) -> Any:
    pools = session.exec(
        select(DouyinAccountPool)
        .where(DouyinAccountPool.owner_id == current_user.id)
        .order_by(col(DouyinAccountPool.created_at).desc())
    ).all()
    return DouyinAccountPoolsPublic(
        data=[_pool_public(session, pool) for pool in pools], count=len(pools)
    )


@router.post(
    "/pools", response_model=DouyinAccountPoolPublic, status_code=status.HTTP_201_CREATED
)
def add_pool(
    request: DouyinAccountPoolCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    pool = DouyinAccountPool(
        owner_id=current_user.id,
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
            owner_id=current_user.id,
            pool_id=pool.id,
            account_ids=request.account_ids,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail="账号池名称已存在") from exc
    session.refresh(pool)
    return _pool_public(session, pool)


@router.patch("/pools/{pool_id}", response_model=DouyinAccountPoolPublic)
def edit_pool(
    request: DouyinAccountPoolUpdate,
    session: SessionDep,
    current_user: CurrentUser,
    pool_id: uuid.UUID,
) -> Any:
    pool = _get_pool(session, current_user, pool_id)
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
                owner_id=current_user.id,
                pool_id=pool.id,
                account_ids=request.account_ids,
            )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail="账号池名称已存在") from exc
    session.refresh(pool)
    return _pool_public(session, pool)


@router.delete("/pools/{pool_id}")
def delete_pool(
    session: SessionDep,
    current_user: CurrentUser,
    pool_id: uuid.UUID,
) -> Message:
    pool = _get_pool(session, current_user, pool_id)
    session.delete(pool)
    session.commit()
    return Message(message="账号池已删除，账号本身不受影响")
