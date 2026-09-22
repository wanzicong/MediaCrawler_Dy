"""抖音账号与账号池路由：账号增删改查、浏览器登录会话、账号池管理及浏览器槽位查询。"""

import uuid
from typing import Any

from crawler.api.deps import CurrentUser, SessionDep
from crawler.business.common.models import Message
from crawler.business.douyin.accounts.models import (
    DouyinAccountBrowserBindRequest,
    DouyinAccountBrowserBindResult,
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
    DouyinLocalBrowserCreate,
    DouyinLocalBrowserPublic,
    DouyinLocalBrowsersPublic,
    DouyinLocalBrowserUpdate,
)
from crawler.business.douyin.accounts.service import (
    AccountConfigurationError,
    AccountInUseError,
    AccountLoginError,
    AccountNotFoundError,
    AccountPoolConflictError,
    AccountPoolMembershipError,
    AccountPoolNotFoundError,
    account_local_browsers,
    account_login_manager,
    account_public_values,
    bind_account_local_browsers,
    browser_slot_public_values,
    create_account,
    create_account_pool,
    create_local_browser,
    delete_local_browser,
    delete_owned_account,
    delete_owned_pool,
    get_owned_account,
    list_local_browsers,
    list_owned_accounts,
    list_owned_pools,
    update_account_pool,
    update_local_browser,
    update_owned_account,
)
from fastapi import APIRouter, HTTPException, Query, status

router = APIRouter(prefix="/douyin/accounts", tags=["douyin-accounts"])


@router.get("", response_model=DouyinAccountsPublic)
def list_accounts(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> Any:
    """分页查询当前用户名下的抖音账号列表。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        skip: 分页偏移量。
        limit: 每页数量（1~100）。

    返回：
        账号列表与总数。
    """
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
    """查询当前用户可用的浏览器槽位列表（本机槽位与远程槽位）。

    返回：
        浏览器槽位列表与数量。
    """
    values = browser_slot_public_values(session, current_user.id)
    return DouyinBrowserSlotsPublic(
        data=[DouyinBrowserSlotPublic(**item) for item in values],
        count=len(values),
    )


@router.get("/local-browsers", response_model=DouyinLocalBrowsersPublic)
def list_local_browsers_route(
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """查询当前用户的本机浏览器实例（可自助增删的本地槽位）。

    首次访问会自动物化默认槽位（默认 4 个本机浏览器），之后以库内数据为准。

    返回：
        本机浏览器实例列表与总数（含绑定账号与 CDP 健康状态）。
    """
    return list_local_browsers(session, current_user.id)


@router.post(
    "/local-browsers",
    response_model=DouyinLocalBrowserPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_local_browser_route(
    session: SessionDep,
    current_user: CurrentUser,
    request: DouyinLocalBrowserCreate,
) -> Any:
    """新增一个本机浏览器实例；槽位名与 CDP 端口由服务端按空闲序号分配。

    异常：
        HTTPException: 422 槽位或端口冲突。
    """
    try:
        return create_local_browser(session, current_user.id, request)
    except AccountConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/local-browsers/{browser_id}", response_model=DouyinLocalBrowserPublic)
def update_local_browser_route(
    session: SessionDep,
    current_user: CurrentUser,
    browser_id: uuid.UUID,
    request: DouyinLocalBrowserUpdate,
) -> Any:
    """更新本机浏览器实例的展示名称或启用状态。

    异常：
        HTTPException: 404 实例不存在。
    """
    try:
        return update_local_browser(
            session, owner_id=current_user.id, browser_id=browser_id, request=request
        )
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/local-browsers/{browser_id}")
def delete_local_browser_route(
    session: SessionDep,
    current_user: CurrentUser,
    browser_id: uuid.UUID,
) -> Message:
    """删除本机浏览器实例；已被账号绑定（主槽位或多绑定）时拒绝删除。

    异常：
        HTTPException: 404 实例不存在、409 实例仍被账号绑定。
    """
    try:
        delete_local_browser(session, owner_id=current_user.id, browser_id=browser_id)
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AccountInUseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AccountConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Message(message="本机浏览器已删除")


@router.get(
    "/by-id/{account_id}/local-browsers", response_model=DouyinAccountBrowserBindResult
)
def list_account_local_browsers(
    session: SessionDep,
    current_user: CurrentUser,
    account_id: uuid.UUID,
) -> Any:
    """查询账号绑定的全部本机浏览器槽位（一个账号可以绑定多个）。

    异常：
        HTTPException: 404 账号不存在。
    """
    try:
        account = get_owned_account(
            session, owner_id=current_user.id, account_id=account_id
        )
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail="抖音账号不存在") from exc
    return DouyinAccountBrowserBindResult(
        account_id=account.id,
        slot_names=account_local_browsers(session, account=account),
    )


@router.put(
    "/by-id/{account_id}/local-browsers", response_model=DouyinAccountBrowserBindResult
)
def bind_account_local_browsers_route(
    session: SessionDep,
    current_user: CurrentUser,
    account_id: uuid.UUID,
    request: DouyinAccountBrowserBindRequest,
) -> Any:
    """覆盖式设置账号绑定的本机浏览器集合（首个槽位为主槽位）。

    异常：
        HTTPException: 404 账号不存在、422 账号非本机模式或槽位未配置/被占用。
    """
    try:
        account = get_owned_account(
            session, owner_id=current_user.id, account_id=account_id
        )
        return bind_account_local_browsers(
            session, account=account, slot_names=request.slot_names
        )
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail="抖音账号不存在") from exc
    except AccountConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "", response_model=DouyinAccountPublic, status_code=status.HTTP_201_CREATED
)
def add_account(
    request: DouyinAccountCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """为当前用户新增一个抖音账号。

    参数：
        request: 账号创建参数。
        session: 数据库会话依赖。
        current_user: 当前登录用户。

    返回：
        创建成功的账号信息。

    异常：
        HTTPException: 账号配置不合法（422）。
    """
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
    """更新当前用户名下指定的抖音账号。

    参数：
        request: 账号更新参数。
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        account_id: 目标账号 ID。

    返回：
        更新后的账号信息。

    异常：
        HTTPException: 账号不存在（404）、账号正在执行任务不能停用（409）、配置不合法（422）。
    """
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
    """删除当前用户名下指定的抖音账号及其独立浏览器 Profile。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        account_id: 目标账号 ID。

    返回：
        删除结果消息。

    异常：
        HTTPException: 账号不存在（404）或账号正在执行任务（409）。
    """
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
    """为指定账号发起浏览器登录会话：打开浏览器并返回可视化登录入口。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        account_id: 目标账号 ID。

    返回：
        登录会话信息（含 viewer_url 与过期时间），状态为 verifying。

    异常：
        HTTPException: 账号不存在（404）或登录会话启动失败（422）。
    """
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
    """验证指定账号的浏览器登录结果，登录成功后刷新账号状态。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        account_id: 目标账号 ID。

    返回：
        验证后的账号信息。

    异常：
        HTTPException: 账号不存在（404）或登录验证失败（409）。
    """
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
    """查询当前用户名下的全部账号池。

    返回：
        账号池列表。
    """
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
    """为当前用户创建账号池。

    参数：
        request: 账号池创建参数（名称、成员账号等）。
        session: 数据库会话依赖。
        current_user: 当前登录用户。

    返回：
        创建成功的账号池。

    异常：
        HTTPException: 成员账号不存在或名称冲突（422）。
    """
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
    """更新当前用户名下指定的账号池。

    参数：
        request: 账号池更新参数。
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        pool_id: 目标账号池 ID。

    返回：
        更新后的账号池。

    异常：
        HTTPException: 账号池不存在（404）、成员账号不存在或名称冲突（422）。
    """
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
    """删除当前用户名下指定的账号池（账号本身保留）。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        pool_id: 目标账号池 ID。

    返回：
        删除结果消息。

    异常：
        HTTPException: 账号池不存在（404）。
    """
    try:
        delete_owned_pool(
            session,
            owner_id=current_user.id,
            pool_id=pool_id,
        )
    except AccountPoolNotFoundError as exc:
        raise HTTPException(status_code=404, detail="账号池不存在") from exc
    return Message(message="账号池已删除，账号本身不受影响")
