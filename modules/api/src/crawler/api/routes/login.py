"""登录与密码管理路由：OAuth2 token 登录、token 校验、密码找回与重置。"""

from typing import Annotated, Any

from crawler.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from crawler.business.common.models import Message
from crawler.business.identity import service as identity_service
from crawler.business.identity.models import (
    NewPassword,
    Token,
    UserPublic,
)
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm

router = APIRouter(tags=["login"])


@router.post("/login/access-token")
def login_access_token(
    session: SessionDep, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]
) -> Token:
    """OAuth2 兼容的 token 登录：校验用户名/邮箱与密码并签发 access token。

    参数：
        session: 数据库会话依赖。
        form_data: OAuth2 密码模式表单（username 可填写用户名或邮箱）。

    返回：
        包含 access_token 的 Token 响应。

    异常：
        HTTPException: 账号或密码错误（400）或用户已停用（400）。
    """
    try:
        return Token(
            access_token=identity_service.issue_access_token(
                session=session,
                email=form_data.username,
                password=form_data.password,
            )
        )
    except identity_service.InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=400, detail="Incorrect username/email or password"
        ) from exc
    except identity_service.InactiveUserError as exc:
        raise HTTPException(status_code=400, detail="Inactive user") from exc


@router.post("/login/test-token", response_model=UserPublic)
def test_token(current_user: CurrentUser) -> Any:
    """测试 access token 是否有效：有效则返回当前用户信息。"""
    return current_user


@router.post("/password-recovery/{email}")
def recover_password(email: str, session: SessionDep) -> Message:
    """发起密码找回：若邮箱已注册则发送重置链接邮件。

    参数：
        email: 目标账号邮箱。
        session: 数据库会话依赖。

    返回：
        统一的提示消息。
    """
    # 始终返回相同响应，防止邮箱枚举攻击
    # 仅当用户真实存在时才发送邮件
    identity_service.send_password_recovery_if_registered(
        session=session,
        email=email,
    )
    return Message(
        message="If that email is registered, we sent a password recovery link"
    )


@router.post("/reset-password/")
def reset_password(session: SessionDep, body: NewPassword) -> Message:
    """凭找回邮件中的 token 重置密码。

    参数：
        session: 数据库会话依赖。
        body: 重置请求（token 与新密码）。

    返回：
        重置结果消息。

    异常：
        HTTPException: token 无效（400）或用户已停用（400）。
    """
    try:
        identity_service.reset_password(
            session=session,
            token=body.token,
            new_password=body.new_password,
        )
    except identity_service.InvalidResetTokenError as exc:
        # 不暴露用户是否存在——与无效 token 使用相同的错误提示
        raise HTTPException(status_code=400, detail="Invalid token") from exc
    except identity_service.InactiveUserError as exc:
        raise HTTPException(status_code=400, detail="Inactive user") from exc
    return Message(message="Password updated successfully")


@router.post(
    "/password-recovery-html-content/{email}",
    dependencies=[Depends(get_current_active_superuser)],
    response_class=HTMLResponse,
)
def recover_password_html_content(email: str, session: SessionDep) -> Any:
    """预览指定邮箱的密码找回邮件 HTML 内容（仅超级管理员可用）。

    参数：
        email: 目标账号邮箱。
        session: 数据库会话依赖。

    返回：
        邮件 HTML 响应（主题放在响应头中）。

    异常：
        HTTPException: 用户不存在（404）。
    """
    try:
        email_data = identity_service.get_password_recovery_content(
            session=session,
            email=email,
        )
    except identity_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="The user with this username does not exist in the system.",
        ) from exc

    return HTMLResponse(
        content=email_data.html_content, headers={"subject:": email_data.subject}
    )
