"""身份域的事务性用例服务。

领域层拥有用户模型的定义，本模块负责其持久化编排（查询、校验、事务提交）。
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta

import jwt
from crawler.bootstrap.security import (
    ALGORITHM,
    create_access_token,
    get_password_hash,
    verify_password,
)
from crawler.bootstrap.settings import settings
from crawler.business.identity import mail
from crawler.business.identity.models import (
    TokenPayload,
    UpdatePassword,
    User,
    UserCreate,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)
from crawler.business.items.models import Item
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session, col, delete, func, select


class IdentityServiceError(Exception):
    """身份域用例中预期内失败的基类异常。"""


class EmailAlreadyExistsError(IdentityServiceError):
    """请求的邮箱已被其他用户占用。"""


class UserNotFoundError(IdentityServiceError):
    """请求的用户不存在。"""


class InsufficientPrivilegesError(IdentityServiceError):
    """操作者无权访问目标用户。"""


class SelfDeletionForbiddenError(IdentityServiceError):
    """超级管理员尝试删除自己的账号。"""


class IncorrectPasswordError(IdentityServiceError):
    """提供的当前密码不正确。"""


class PasswordReuseError(IdentityServiceError):
    """新密码与当前密码相同。"""


class InvalidCredentialsError(IdentityServiceError):
    """提供的邮箱/密码组合无效。"""


class InactiveUserError(IdentityServiceError):
    """通过认证的用户处于停用状态。"""


class InvalidResetTokenError(IdentityServiceError):
    """密码重置 token 无效或没有匹配的用户。"""


@dataclass(frozen=True)
class PasswordRecoveryContent:
    """与传输方式无关的密码找回邮件内容。"""

    html_content: str  # 邮件 HTML 正文
    subject: str  # 邮件主题


def create_user(*, session: Session, user_create: UserCreate) -> User:
    """创建用户：对明文密码哈希后落库并返回持久化后的实体。

    参数：
        session: 数据库会话。
        user_create: 用户创建入参（含明文密码）。

    返回：
        创建完成并刷新后的 User 实体。
    """
    db_obj = User.model_validate(
        user_create, update={"hashed_password": get_password_hash(user_create.password)}
    )
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def update_user(*, session: Session, db_user: User, user_in: UserUpdate) -> User:
    """按入参中已设置的字段更新用户；若包含新密码则重新哈希。

    参数：
        session: 数据库会话。
        db_user: 待更新的用户实体。
        user_in: 更新入参，仅未设置（unset）字段以外的内容会生效。

    返回：
        更新并刷新后的 User 实体。
    """
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data = {}
    if "password" in user_data:
        password = user_data["password"]
        hashed_password = get_password_hash(password)
        extra_data["hashed_password"] = hashed_password
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def get_user_by_email(*, session: Session, email: str) -> User | None:
    """按邮箱查询用户，不存在时返回 None。"""
    statement = select(User).where(User.email == email)
    return session.exec(statement).first()


def resolve_token_user(*, session: Session, token: str) -> User:
    """从访问 token 解析出处于启用状态的用户，不掺杂任何 HTTP 层概念。

    参数：
        session: 数据库会话。
        token: JWT 访问令牌。

    返回：
        token 对应的启用状态 User 实体。

    异常：
        InvalidCredentialsError: token 无法解析、负载不合法或用户不存在。
        InactiveUserError: 用户已被停用。
    """

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[ALGORITHM],
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError) as exc:
        raise InvalidCredentialsError from exc
    user = session.get(User, token_data.sub)
    if user is None:
        raise InvalidCredentialsError
    if not user.is_active:
        raise InactiveUserError
    return user


def create_private_user(
    *,
    session: Session,
    email: str,
    password: str,
    full_name: str,
) -> User:
    """保留的本地专用、不做校验的用户创建辅助函数。"""

    user = User(
        email=email,
        full_name=full_name,
        hashed_password=get_password_hash(password),
    )
    session.add(user)
    session.commit()
    return user


# Argon2 哈希，用于在账号不存在时做等额耗时的校验，拉平认证时间侧信道
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"


def authenticate(*, session: Session, email: str, password: str) -> User | None:
    """校验邮箱与密码，认证成功返回用户实体，失败返回 None。

    账号不存在时仍对 DUMMY_HASH 做一次校验，避免通过响应时间探测账号是否存在；
    若密码哈希算法参数已升级，则自动写入新哈希。

    参数：
        session: 数据库会话。
        email: 登录邮箱。
        password: 明文密码。

    返回：
        认证成功的 User 实体；认证失败返回 None。
    """
    db_user = get_user_by_email(session=session, email=email)
    if not db_user:
        verify_password(password, DUMMY_HASH)
        return None
    verified, updated_password_hash = verify_password(password, db_user.hashed_password)
    if not verified:
        return None
    if updated_password_hash:
        db_user.hashed_password = updated_password_hash
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
    return db_user


def list_users(*, session: Session, skip: int = 0, limit: int = 100) -> UsersPublic:
    """按创建时间倒序分页返回用户列表，与 API 暴露的顺序保持一致。"""

    count = session.exec(select(func.count()).select_from(User)).one()
    statement = (
        select(User).order_by(col(User.created_at).desc()).offset(skip).limit(limit)
    )
    users = list(session.exec(statement).all())
    return UsersPublic(data=users, count=count)


def create_managed_user(*, session: Session, user_in: UserCreate) -> User:
    """由管理员创建用户，并按配置发送可选的欢迎邮件。

    异常：
        EmailAlreadyExistsError: 邮箱已被占用。
    """

    if get_user_by_email(session=session, email=user_in.email) is not None:
        raise EmailAlreadyExistsError

    user = create_user(session=session, user_create=user_in)
    if settings.emails_enabled and user_in.email:
        email_data = mail.generate_new_account_email(
            email_to=user_in.email,
            username=user_in.email,
            password=user_in.password,
        )
        mail.send_email(
            email_to=user_in.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
    return user


def update_current_user(
    *, session: Session, current_user: User, user_in: UserUpdateMe
) -> User:
    """更新当前登录用户的资料，并强制校验邮箱唯一性。

    异常：
        EmailAlreadyExistsError: 新邮箱已被其他用户占用。
    """

    if user_in.email:
        existing_user = get_user_by_email(session=session, email=user_in.email)
        if existing_user is not None and existing_user.id != current_user.id:
            raise EmailAlreadyExistsError

    current_user.sqlmodel_update(user_in.model_dump(exclude_unset=True))
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return current_user


def update_current_password(
    *, session: Session, current_user: User, body: UpdatePassword
) -> None:
    """校验当前密码后更新当前登录用户的密码。

    异常：
        IncorrectPasswordError: 当前密码不正确。
        PasswordReuseError: 新密码与当前密码相同。
    """

    verified, _ = verify_password(body.current_password, current_user.hashed_password)
    if not verified:
        raise IncorrectPasswordError
    if body.current_password == body.new_password:
        raise PasswordReuseError

    current_user.hashed_password = get_password_hash(body.new_password)
    session.add(current_user)
    session.commit()


def delete_current_user(*, session: Session, current_user: User) -> None:
    """注销当前登录用户的账号；超级管理员不允许走此路径。

    异常：
        SelfDeletionForbiddenError: 超级管理员尝试删除自己的账号。
    """

    if current_user.is_superuser:
        raise SelfDeletionForbiddenError
    session.delete(current_user)
    session.commit()


def register_user(*, session: Session, user_in: UserRegister) -> User:
    """无需认证的自助注册入口。

    异常：
        EmailAlreadyExistsError: 邮箱已被占用。
    """

    if get_user_by_email(session=session, email=user_in.email) is not None:
        raise EmailAlreadyExistsError
    return create_user(
        session=session,
        user_create=UserCreate.model_validate(user_in),
    )


def get_visible_user(
    *, session: Session, current_user: User, user_id: uuid.UUID
) -> User:
    """返回目标用户，并保持既有的防止用户 ID 枚举的校验顺序。

    异常：
        InsufficientPrivilegesError: 普通用户访问他人信息（先于用户不存在的判断，防止枚举）。
        UserNotFoundError: 目标用户不存在。
    """

    user = session.get(User, user_id)
    if user == current_user:
        return current_user
    if not current_user.is_superuser:
        # 该校验有意放在“用户不存在”响应之前，
        # 以保持既有行为：防止普通用户通过响应差异枚举用户 ID
        raise InsufficientPrivilegesError
    if user is None:
        raise UserNotFoundError
    return user


def update_managed_user(
    *,
    session: Session,
    user_id: uuid.UUID,
    user_in: UserUpdate,
) -> User:
    """由管理员更新指定用户。

    异常：
        UserNotFoundError: 目标用户不存在。
        EmailAlreadyExistsError: 新邮箱已被其他用户占用。
    """

    db_user = session.get(User, user_id)
    if db_user is None:
        raise UserNotFoundError
    if user_in.email:
        existing_user = get_user_by_email(session=session, email=user_in.email)
        if existing_user is not None and existing_user.id != user_id:
            raise EmailAlreadyExistsError
    return update_user(session=session, db_user=db_user, user_in=user_in)


def delete_managed_user(
    *, session: Session, current_user: User, user_id: uuid.UUID
) -> None:
    """在一个事务内删除指定用户及其遗留的 Item 数据。

    异常：
        UserNotFoundError: 目标用户不存在。
        SelfDeletionForbiddenError: 尝试删除当前登录的管理员自身。
    """

    user = session.get(User, user_id)
    if user is None:
        raise UserNotFoundError
    if user == current_user:
        raise SelfDeletionForbiddenError

    session.exec(delete(Item).where(col(Item.owner_id) == user_id))
    session.delete(user)
    session.commit()


def issue_access_token(*, session: Session, email: str, password: str) -> str:
    """认证用户并签发 bearer 访问令牌。

    返回：
        JWT 访问令牌字符串。

    异常：
        InvalidCredentialsError: 邮箱/密码校验失败。
        InactiveUserError: 用户已被停用。
    """

    user = authenticate(session=session, email=email, password=password)
    if user is None:
        raise InvalidCredentialsError
    if not user.is_active:
        raise InactiveUserError
    return create_access_token(
        user.id,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def send_password_recovery_if_registered(*, session: Session, email: str) -> None:
    """若邮箱已注册则发送密码找回邮件；不泄露邮箱是否已注册这一事实。"""

    user = get_user_by_email(session=session, email=email)
    if user is None:
        return
    token = mail.generate_password_reset_token(email=email)
    email_data = mail.generate_reset_password_email(
        email_to=user.email,
        email=email,
        token=token,
    )
    mail.send_email(
        email_to=user.email,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )


def reset_password(*, session: Session, token: str, new_password: str) -> None:
    """使用密码重置 token 为处于启用状态的用户设置新密码。

    异常：
        InvalidResetTokenError: token 无效或没有匹配的用户。
        InactiveUserError: 用户已被停用。
    """

    email = mail.verify_password_reset_token(token=token)
    if not email:
        raise InvalidResetTokenError
    user = get_user_by_email(session=session, email=email)
    if user is None:
        raise InvalidResetTokenError
    if not user.is_active:
        raise InactiveUserError
    update_user(
        session=session,
        db_user=user,
        user_in=UserUpdate(password=new_password),
    )


def get_password_recovery_content(
    *, session: Session, email: str
) -> PasswordRecoveryContent:
    """为管理员专用的预览接口构建密码找回邮件内容。

    异常：
        UserNotFoundError: 邮箱对应的用户不存在。
    """

    user = get_user_by_email(session=session, email=email)
    if user is None:
        raise UserNotFoundError
    token = mail.generate_password_reset_token(email=email)
    email_data = mail.generate_reset_password_email(
        email_to=user.email,
        email=email,
        token=token,
    )
    return PasswordRecoveryContent(
        html_content=email_data.html_content,
        subject=email_data.subject,
    )


__all__ = [
    "DUMMY_HASH",
    "EmailAlreadyExistsError",
    "IdentityServiceError",
    "InactiveUserError",
    "IncorrectPasswordError",
    "InsufficientPrivilegesError",
    "InvalidCredentialsError",
    "InvalidResetTokenError",
    "PasswordRecoveryContent",
    "PasswordReuseError",
    "SelfDeletionForbiddenError",
    "UserNotFoundError",
    "authenticate",
    "create_managed_user",
    "create_private_user",
    "create_user",
    "delete_current_user",
    "delete_managed_user",
    "get_password_recovery_content",
    "get_user_by_email",
    "get_visible_user",
    "issue_access_token",
    "list_users",
    "register_user",
    "reset_password",
    "resolve_token_user",
    "send_password_recovery_if_registered",
    "update_current_password",
    "update_current_user",
    "update_managed_user",
    "update_user",
]
