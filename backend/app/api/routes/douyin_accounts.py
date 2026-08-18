import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, SessionDep
from app.application.douyin.accounts.service import (
    AccountConfigurationError,
    AccountInUseError,
    AccountLoginError,
    AccountNotFoundError,
    AccountPoolConflictError,
    AccountPoolMembershipError,
    AccountPoolNotFoundError,
    account_login_manager,
    account_public_values,
    create_account,
    create_account_pool,
    delete_owned_account,
    delete_owned_pool,
    get_owned_account,
    list_owned_accounts,
    list_owned_pools,
    remote_slot_public_values,
    update_account_pool,
    update_owned_account,
)
from app.domain.common.models import Message
from app.domain.douyin.accounts.models import (
    DouyinAccountCreate,
    DouyinAccountLoginSessionPublic,
    DouyinAccountPoolCreate,
    DouyinAccountPoolPublic,
    DouyinAccountPoolsPublic,
    DouyinAccountPoolUpdate,
    DouyinAccountPublic,
    DouyinAccountsPublic,
    DouyinAccountStatus,
    DouyinAccountUpdate,
    DouyinBrowserSlotPublic,
    DouyinBrowserSlotsPublic,
)

router = APIRouter(prefix="/douyin/accounts", tags=["douyin-accounts"])


@router.get("", response_model=DouyinAccountsPublic)
def list_accounts(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> Any:
    return list_owned_accounts(
        session,
        owner_id=current_user.id,
        skip=skip,
        limit=limit,
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


@router.post(
    "", response_model=DouyinAccountPublic, status_code=status.HTTP_201_CREATED
)
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
    try:
        account = update_owned_account(
            session,
            owner_id=current_user.id,
            account_id=account_id,
            request=request,
        )
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail="抖音账号不存在") from exc
    except AccountInUseError as exc:
        raise HTTPException(
            status_code=409, detail="账号正在执行任务，暂时不能停用"
        ) from exc
    except AccountConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DouyinAccountPublic(**account_public_values(account))


@router.delete("/by-id/{account_id}")
async def delete_account(
    session: SessionDep,
    current_user: CurrentUser,
    account_id: uuid.UUID,
) -> Message:
    try:
        await delete_owned_account(
            session,
            owner_id=current_user.id,
            account_id=account_id,
        )
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail="抖音账号不存在") from exc
    except AccountInUseError as exc:
        raise HTTPException(
            status_code=409, detail="账号正在执行任务，不能删除"
        ) from exc
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
    try:
        get_owned_account(
            session,
            owner_id=current_user.id,
            account_id=account_id,
        )
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail="抖音账号不存在") from exc
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
        message=(account.last_error or "浏览器已打开，请完成登录后点击验证登录"),
    )


@router.post("/by-id/{account_id}/verify", response_model=DouyinAccountPublic)
async def verify_account_login(
    session: SessionDep,
    current_user: CurrentUser,
    account_id: uuid.UUID,
) -> Any:
    try:
        get_owned_account(
            session,
            owner_id=current_user.id,
            account_id=account_id,
        )
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail="抖音账号不存在") from exc
    try:
        account = await account_login_manager.verify(
            owner_id=current_user.id, account_id=account_id
        )
    except (AccountLoginError, AccountConfigurationError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return DouyinAccountPublic(**account_public_values(account))


@router.get("/pools", response_model=DouyinAccountPoolsPublic)
def list_pools(session: SessionDep, current_user: CurrentUser) -> Any:
    return list_owned_pools(session, owner_id=current_user.id)


@router.post(
    "/pools",
    response_model=DouyinAccountPoolPublic,
    status_code=status.HTTP_201_CREATED,
)
def add_pool(
    request: DouyinAccountPoolCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    try:
        return create_account_pool(
            session,
            owner_id=current_user.id,
            request=request,
        )
    except AccountPoolMembershipError as exc:
        raise HTTPException(status_code=422, detail="账号池包含不存在的账号") from exc
    except AccountPoolConflictError as exc:
        raise HTTPException(status_code=422, detail="账号池名称已存在") from exc


@router.patch("/pools/{pool_id}", response_model=DouyinAccountPoolPublic)
def edit_pool(
    request: DouyinAccountPoolUpdate,
    session: SessionDep,
    current_user: CurrentUser,
    pool_id: uuid.UUID,
) -> Any:
    try:
        return update_account_pool(
            session,
            owner_id=current_user.id,
            pool_id=pool_id,
            request=request,
        )
    except AccountPoolNotFoundError as exc:
        raise HTTPException(status_code=404, detail="账号池不存在") from exc
    except AccountPoolMembershipError as exc:
        raise HTTPException(status_code=422, detail="账号池包含不存在的账号") from exc
    except AccountPoolConflictError as exc:
        raise HTTPException(status_code=422, detail="账号池名称已存在") from exc


@router.delete("/pools/{pool_id}")
def delete_pool(
    session: SessionDep,
    current_user: CurrentUser,
    pool_id: uuid.UUID,
) -> Message:
    try:
        delete_owned_pool(
            session,
            owner_id=current_user.id,
            pool_id=pool_id,
        )
    except AccountPoolNotFoundError as exc:
        raise HTTPException(status_code=404, detail="账号池不存在") from exc
    return Message(message="账号池已删除，账号本身不受影响")
