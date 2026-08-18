"""FastAPI 依赖注入定义：数据库会话、OAuth2 token 解析与当前用户鉴权依赖。"""

from collections.abc import Generator
from typing import Annotated

from crawler.bootstrap.database import engine
from crawler.bootstrap.settings import settings
from crawler.business.identity.models import User
from crawler.business.identity.service import (
    InactiveUserError,
    InvalidCredentialsError,
    resolve_token_user,
)
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)


def get_db() -> Generator[Session, None, None]:
    """请求级数据库会话依赖：请求结束后自动关闭会话。

    返回：
        一个绑定全局 engine 的 SQLModel Session 生成器。
    """
    with Session(engine) as session:
        yield session


# 数据库会话的 Annotated 依赖类型，供路由签名直接使用
SessionDep = Annotated[Session, Depends(get_db)]
# OAuth2 Bearer token 的 Annotated 依赖类型
TokenDep = Annotated[str, Depends(reusable_oauth2)]


def get_current_user(session: SessionDep, token: TokenDep) -> User:
    """解析 Bearer token 并返回对应的当前用户。

    参数：
        session: 数据库会话依赖。
        token: 请求头中携带的 OAuth2 access token。

    返回：
        token 对应的 User 实体。

    异常：
        HTTPException: 凭证无效（403）或用户已停用（400）。
    """
    try:
        return resolve_token_user(session=session, token=token)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        ) from exc
    except InactiveUserError as exc:
        raise HTTPException(status_code=400, detail="Inactive user") from exc


# 当前登录用户的 Annotated 依赖类型
CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_active_superuser(current_user: CurrentUser) -> User:
    """校验当前用户为超级管理员，用于受保护的管理接口。

    参数：
        current_user: 当前登录用户。

    返回：
        通过校验的 User 实体。

    异常：
        HTTPException: 用户不是超级管理员（403）。
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user
