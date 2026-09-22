"""抖音内容分类限界上下文的业务模型与 API 契约。

分类是用户自建的「运营视角」标签体系，与平台话题标签（douyin_tag）不同：
它只管两件事——把视频和达人收纳进自己的分类树里，供筛选与批量操作使用。
刻意限制为**最多两级**：一级叫大类，二级挂在大类下面；选大类时带出其全部子类数据。
"""

import uuid
from datetime import datetime

from crawler.business.common.models import get_datetime_utc
from sqlalchemy import DateTime, ForeignKeyConstraint, UniqueConstraint
from sqlmodel import Field, SQLModel


class DouyinCategory(SQLModel, table=True):
    """内容分类节点（一级 parent_id 为空，二级挂在父节点下）。"""

    __tablename__ = "douyin_category"
    __table_args__ = (
        # (id, owner_id) 唯一约束是下面自引用复合外键的被引用目标：
        # Postgres 要求外键指向的列组必须有唯一约束，仅有主键 id 不满足。
        UniqueConstraint("id", "owner_id", name="uq_douyin_category_id_owner"),
        UniqueConstraint(
            "owner_id",
            "parent_id",
            "normalized_name",
            name="uq_douyin_category_owner_parent_name",
        ),
        ForeignKeyConstraint(
            ["parent_id", "owner_id"],
            ["douyin_category.id", "douyin_category.owner_id"],
            name="fk_douyin_category_parent_owner",
            ondelete="CASCADE",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    parent_id: uuid.UUID | None = Field(default=None, index=True)
    name: str = Field(max_length=100)
    normalized_name: str = Field(max_length=100)  # NFKC + casefold，同级去重用
    description: str = Field(default="", max_length=500)
    sort_order: int = Field(default=0)  # 同级排序，越小越靠前
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinVideoCategory(SQLModel, table=True):
    """视频-分类绑定：按平台作品号关联，跨任务有效。"""

    __tablename__ = "douyin_video_category"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "aweme_id", "category_id", name="uq_douyin_video_category"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    aweme_id: str = Field(max_length=64, index=True)  # 平台作品号
    category_id: uuid.UUID = Field(
        foreign_key="douyin_category.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinCreatorCategory(SQLModel, table=True):
    """达人-分类绑定。"""

    __tablename__ = "douyin_creator_category"
    __table_args__ = (
        UniqueConstraint(
            "creator_id", "category_id", name="uq_douyin_creator_category"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    creator_id: uuid.UUID = Field(
        foreign_key="douyin_creator.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    category_id: uuid.UUID = Field(
        foreign_key="douyin_category.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinCategoryPublic(SQLModel):
    """分类对外模型（扁平列表，前端按 parent_id 组树）。"""

    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    description: str
    sort_order: int
    level: int  # 1=大类，2=子类
    video_count: int  # 直接归类到本分类的视频数
    creator_count: int  # 直接归类到本分类的达人数
    created_at: datetime
    updated_at: datetime


class DouyinCategoriesPublic(SQLModel):
    """分类列表响应。"""

    data: list[DouyinCategoryPublic]
    count: int


class DouyinCategoryCreate(SQLModel):
    """新建分类请求体。"""

    name: str = Field(min_length=1, max_length=100)
    parent_id: uuid.UUID | None = None  # 为空表示一级大类，最多两级
    description: str = Field(default="", max_length=500)
    sort_order: int = 0


class DouyinCategoryUpdate(SQLModel):
    """更新分类请求体（字段全部可选）。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    parent_id: uuid.UUID | None = None
    description: str | None = Field(default=None, max_length=500)
    sort_order: int | None = None


class DouyinCategoryAssignRequest(SQLModel):
    """批量归类/取消归类请求体。"""

    aweme_ids: list[str] = Field(default_factory=list, max_length=1000)
    creator_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)


class DouyinCategoryAssignResult(SQLModel):
    """批量归类结果。"""

    category_id: uuid.UUID
    video_count: int  # 本次新增/移除的视频关联数
    creator_count: int  # 本次新增/移除的达人关联数


__all__ = [
    "DouyinCategory",
    "DouyinVideoCategory",
    "DouyinCreatorCategory",
    "DouyinCategoryPublic",
    "DouyinCategoriesPublic",
    "DouyinCategoryCreate",
    "DouyinCategoryUpdate",
    "DouyinCategoryAssignRequest",
    "DouyinCategoryAssignResult",
]
