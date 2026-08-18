"""抖音标签限界上下文的业务模型与 schema：话题标签实体及作品-标签绑定关系。"""

import uuid
from datetime import datetime

from crawler.business.common.models import get_datetime_utc
from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class DouyinTag(SQLModel, table=True):
    """抖音话题标签实体：按用户隔离，归一化名称在同一用户内唯一。"""

    __tablename__ = "douyin_tag"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "normalized_name", name="uq_douyin_tag_owner_name"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)  # 标签主键
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )  # 归属用户 id（外键 user.id，级联删除）
    name: str = Field(max_length=100, index=True)  # 标签显示名（保留原始书写形态）
    normalized_name: str = Field(
        max_length=100
    )  # 归一化标签名（NFKC + 去 # + casefold），用于去重
    last_seen_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 最近一次在作品中出现的时间（UTC）
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 创建时间（UTC）


class DouyinAwemeTag(SQLModel, table=True):
    """作品-标签绑定关系实体：记录作品与标签的多对多关联。"""

    __tablename__ = "douyin_aweme_tag"
    __table_args__ = (
        UniqueConstraint(
            "aweme_record_id", "tag_id", name="uq_douyin_aweme_tag_record_tag"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)  # 绑定关系主键
    aweme_record_id: uuid.UUID = Field(
        foreign_key="douyin_aweme.id", nullable=False, ondelete="CASCADE", index=True
    )  # 作品记录 id（外键 douyin_aweme.id，级联删除）
    tag_id: uuid.UUID = Field(
        foreign_key="douyin_tag.id", nullable=False, ondelete="CASCADE", index=True
    )  # 标签 id（外键 douyin_tag.id，级联删除）
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 绑定时间（UTC）


class DouyinTagRefPublic(SQLModel):
    """标签引用模型：仅含 id 与名称，用于嵌套展示。"""

    id: uuid.UUID  # 标签 id
    name: str  # 标签显示名


class DouyinTagPublic(DouyinTagRefPublic):
    """标签详情响应模型：在引用基础上附带关联统计。"""

    aweme_count: int  # 关联作品数
    task_count: int  # 关联采集任务数
    last_seen_at: datetime  # 最近一次出现时间
    created_at: datetime  # 创建时间


class DouyinTagsPublic(SQLModel):
    """标签分页列表响应。"""

    data: list[DouyinTagPublic]  # 当前页标签列表
    count: int  # 满足条件的标签总数


class DouyinTagSyncResult(SQLModel):
    """标签历史同步结果统计。"""

    aweme_count: int  # 本次扫描的作品数
    tag_count: int  # 本次发现的不同标签数（按归一化名去重）
    created_count: int  # 新建标签数
    binding_count: int  # 新建作品-标签绑定数


__all__ = [
    "DouyinTag",
    "DouyinAwemeTag",
    "DouyinTagRefPublic",
    "DouyinTagPublic",
    "DouyinTagsPublic",
    "DouyinTagSyncResult",
]
