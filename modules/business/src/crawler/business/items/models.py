"""Item（示例条目）限界上下文的业务模型与 schema。"""

import uuid
from datetime import datetime

from crawler.business.common.models import get_datetime_utc
from crawler.business.identity.models import User
from sqlalchemy import DateTime
from sqlmodel import Field, Relationship, SQLModel


class ItemBase(SQLModel):
    """Item 公共字段基类，被创建/更新/公开等 schema 复用。"""

    title: str = Field(min_length=1, max_length=255)  # 条目标题
    description: str | None = Field(default=None, max_length=255)  # 条目描述，可空


class ItemCreate(ItemBase):
    """创建 Item 的入参模型。"""

    pass


class ItemUpdate(ItemBase):
    """更新 Item 的入参模型，字段均可选。"""

    title: str | None = Field(default=None, min_length=1, max_length=255)  # type: ignore


class Item(ItemBase, table=True):
    """Item 数据库实体（item 表）。"""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)  # 条目主键 UUID
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )  # 创建时间（UTC）
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )  # 所属用户 ID，外键关联 user.id，用户删除时级联删除
    owner: User | None = Relationship(back_populates="items")  # 所属用户对象


class ItemPublic(ItemBase):
    """对外返回的单条 Item 视图模型。"""

    id: uuid.UUID  # 条目主键 UUID
    owner_id: uuid.UUID  # 所属用户 ID
    created_at: datetime | None = None  # 创建时间


class ItemsPublic(SQLModel):
    """对外返回的 Item 分页列表模型。"""

    data: list[ItemPublic]  # 当前页条目列表
    count: int  # 符合条件的条目总数


__all__ = [
    "ItemBase",
    "ItemCreate",
    "ItemUpdate",
    "Item",
    "ItemPublic",
    "ItemsPublic",
]
