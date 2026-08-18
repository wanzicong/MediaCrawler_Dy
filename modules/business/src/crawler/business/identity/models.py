"""身份认证限界上下文的业务模型与 schema（用户、令牌、密码相关）。"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from crawler.business.common.models import get_datetime_utc
from pydantic import EmailStr
from sqlalchemy import DateTime
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from crawler.business.items.models import Item


class UserBase(SQLModel):
    """用户公共字段基类，被创建/更新/公开等 schema 复用。"""

    email: EmailStr = Field(
        unique=True, index=True, max_length=255
    )  # 登录邮箱，全局唯一
    is_active: bool = True  # 账号是否启用，禁用后无法登录
    is_superuser: bool = False  # 是否为超级管理员
    full_name: str | None = Field(default=None, max_length=255)  # 用户姓名/昵称，可空


class UserCreate(UserBase):
    """管理员创建用户时的入参模型。"""

    password: str = Field(min_length=8, max_length=128)  # 明文密码，入库前会被哈希


class UserRegister(SQLModel):
    """用户自助注册时的入参模型。"""

    email: EmailStr = Field(max_length=255)  # 注册邮箱
    password: str = Field(min_length=8, max_length=128)  # 明文密码
    full_name: str | None = Field(default=None, max_length=255)  # 用户姓名/昵称，可空


class UserUpdate(UserBase):
    """管理员更新用户时的入参模型，所有字段均可选。"""

    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore
    password: str | None = Field(
        default=None, min_length=8, max_length=128
    )  # 可选的新明文密码


class UserUpdateMe(SQLModel):
    """当前登录用户更新自身资料时的入参模型。"""

    full_name: str | None = Field(default=None, max_length=255)  # 新的姓名/昵称
    email: EmailStr | None = Field(default=None, max_length=255)  # 新的登录邮箱


class UpdatePassword(SQLModel):
    """修改密码入参模型。"""

    current_password: str = Field(
        min_length=8, max_length=128
    )  # 当前密码，用于校验身份
    new_password: str = Field(min_length=8, max_length=128)  # 新密码


class User(UserBase, table=True):
    """用户数据库实体（user 表）。"""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)  # 用户主键 UUID
    hashed_password: str  # 哈希后的密码（Argon2）
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )  # 账号创建时间（UTC）
    items: list["Item"] = Relationship(
        back_populates="owner", cascade_delete=True
    )  # 用户名下的 Item 列表，删除用户时级联删除


class UserPublic(UserBase):
    """对外返回的单用户视图模型（不含敏感字段）。"""

    id: uuid.UUID  # 用户主键 UUID
    created_at: datetime | None = None  # 账号创建时间


class UsersPublic(SQLModel):
    """对外返回的用户分页列表模型。"""

    data: list[UserPublic]  # 当前页用户列表
    count: int  # 符合条件的用户总数


class Token(SQLModel):
    """登录成功后返回的访问令牌模型。"""

    access_token: str  # JWT 访问令牌
    token_type: str = "bearer"  # 令牌类型，固定为 bearer


class TokenPayload(SQLModel):
    """JWT 令牌解析后的负载模型。"""

    sub: str | None = None  # 令牌主体，存放用户 ID


class NewPassword(SQLModel):
    """通过重置令牌设置新密码的入参模型。"""

    token: str  # 密码重置令牌
    new_password: str = Field(min_length=8, max_length=128)  # 新密码


__all__ = [
    "UserBase",
    "UserCreate",
    "UserRegister",
    "UserUpdate",
    "UserUpdateMe",
    "UpdatePassword",
    "User",
    "UserPublic",
    "UsersPublic",
    "Token",
    "TokenPayload",
    "NewPassword",
]
