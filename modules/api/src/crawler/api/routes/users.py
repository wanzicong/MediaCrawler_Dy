"""用户管理路由：用户列表、创建、个人资料/密码维护、注册与管理员的更新/删除操作。"""

import uuid
from typing import Any

from crawler.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)
from crawler.business.common.models import Message
from crawler.business.identity import service as identity_service
from crawler.business.identity.models import (
    UpdatePassword,
    UserCreate,
    UserPublic,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UsersPublic,
)
def read_users(session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
    """分页查询全部用户（仅超级管理员可用）。

    参数：
        session: 数据库会话依赖。
        skip: 分页偏移量。
        limit: 每页数量。

    返回：
        用户分页结果。
    """

    return identity_service.list_users(session=session, skip=skip, limit=limit)


@router.post(
    "/", dependencies=[Depends(get_current_active_superuser)], response_model=UserPublic
)
def create_user(*, session: SessionDep, user_in: UserCreate) -> Any:
    """由管理员创建新用户。

    参数：
        session: 数据库会话依赖。
        user_in: 用户创建参数。

    返回：
        创建成功的用户信息。

    异常：
        HTTPException: 邮箱已被注册（400）。
    """
    try:
        return identity_service.create_managed_user(session=session, user_in=user_in)
    except identity_service.EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        ) from exc


@router.patch("/me", response_model=UserPublic)
def update_user_me(
    *, session: SessionDep, user_in: UserUpdateMe, current_user: CurrentUser
) -> Any:
    """更新当前用户自己的资料。

    参数：
        session: 数据库会话依赖。
        user_in: 资料更新参数。
        current_user: 当前登录用户。

    返回：
        更新后的用户信息。

    异常：
        HTTPException: 邮箱已被占用（409）。
    """

    try:
        return identity_service.update_current_user(
            session=session,
            current_user=current_user,
            user_in=user_in,
        )
    except identity_service.EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409, detail="User with this email already exists"
        ) from exc


@router.patch("/me/password", response_model=Message)
def update_password_me(
    *, session: SessionDep, body: UpdatePassword, current_user: CurrentUser
) -> Any:
    """修改当前用户自己的密码。

    参数：
        session: 数据库会话依赖。
        body: 密码修改请求（当前密码与新密码）。
        current_user: 当前登录用户。

    返回：
        修改结果消息。

    异常：
        HTTPException: 当前密码错误（400）或新密码与当前密码相同（400）。
    """
    try:
        identity_service.update_current_password(
            session=session,
            current_user=current_user,
            body=body,
        )
    except identity_service.IncorrectPasswordError as exc:
        raise HTTPException(status_code=400, detail="Incorrect password") from exc
    except identity_service.PasswordReuseError as exc:
        raise HTTPException(
            status_code=400, detail="New password cannot be the same as the current one"
        ) from exc
    return Message(message="Password updated successfully")


@router.get("/me", response_model=UserPublic)
def read_user_me(current_user: CurrentUser) -> Any:
    """获取当前登录用户的信息。"""
    return current_user


@router.delete("/me", response_model=Message)
def delete_user_me(session: SessionDep, current_user: CurrentUser) -> Any:
    """注销当前用户自己的账号（超级管理员不允许自删）。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。

    返回：
        删除结果消息。

    异常：
        HTTPException: 超级管理员尝试删除自己（403）。
    """
    try:
        identity_service.delete_current_user(
            session=session,
            current_user=current_user,
        )
    except identity_service.SelfDeletionForbiddenError as exc:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        ) from exc
    return Message(message="User deleted successfully")


@router.post("/signup", response_model=UserPublic)
def register_user(session: SessionDep, user_in: UserRegister) -> Any:
    """开放注册：无需登录即可创建新用户。

    参数：
        session: 数据库会话依赖。
        user_in: 注册参数。

    返回：
        注册成功的用户信息。

    异常：
        HTTPException: 邮箱已被注册（400）。
    """
    try:
        return identity_service.register_user(session=session, user_in=user_in)
    except identity_service.EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system",
        ) from exc


@router.get("/{user_id}", response_model=UserPublic)
def read_user_by_id(
    user_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    """按 ID 获取指定用户（普通用户仅可查看自己）。

    参数：
        user_id: 目标用户 ID。
        session: 数据库会话依赖。
        current_user: 当前登录用户。

    返回：
        用户信息。

    异常：
        HTTPException: 权限不足（403）或用户不存在（404）。
    """
    try:
        return identity_service.get_visible_user(
            session=session,
            current_user=current_user,
            user_id=user_id,
        )
    except identity_service.InsufficientPrivilegesError as exc:
        raise HTTPException(
            status_code=403,
            detail="The user doesn't have enough privileges",
        ) from exc
    except identity_service.UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="User not found") from exc


@router.patch(
    "/{user_id}",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UserPublic,
)
def update_user(
    *,
    session: SessionDep,
    user_id: uuid.UUID,
    user_in: UserUpdate,
) -> Any:
    """由管理员更新指定用户（仅超级管理员可用）。

    参数：
        session: 数据库会话依赖。
        user_id: 目标用户 ID。
        user_in: 用户更新参数。

    返回：
        更新后的用户信息。

    异常：
        HTTPException: 用户不存在（404）或邮箱已被占用（409）。
    """

    try:
        return identity_service.update_managed_user(
            session=session,
            user_id=user_id,
            user_in=user_in,
        )
    except identity_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="The user with this id does not exist in the system",
        ) from exc
    except identity_service.EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409, detail="User with this email already exists"
        ) from exc


@router.delete("/{user_id}", dependencies=[Depends(get_current_active_superuser)])
def delete_user(
    session: SessionDep, current_user: CurrentUser, user_id: uuid.UUID
) -> Message:
    """由管理员删除指定用户（仅超级管理员可用，且不能删除自己）。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        user_id: 目标用户 ID。

    返回：
        删除结果消息。

    异常：
        HTTPException: 用户不存在（404）或超级管理员尝试删除自己（403）。
    """
    try:
        identity_service.delete_managed_user(
            session=session,
            current_user=current_user,
            user_id=user_id,
        )
    except identity_service.UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="User not found") from exc
    except identity_service.SelfDeletionForbiddenError as exc:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        ) from exc
    return Message(message="User deleted successfully")
