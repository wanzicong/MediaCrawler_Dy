"""「我的」模块的数据模型：账号维度的关注 / 点赞 / 收藏。

与作品库（跨任务、按平台作品号去重）不同，这里的数据**按账号归属**：
同一个作品可能被 A 账号点赞、又被 B 账号收藏，两条记录各自独立保存，
因为它们表达的是「这个账号做过什么」，是账号资产而不是平台事实。
"""

import uuid
from datetime import datetime

from crawler.business.common.models import get_datetime_utc
from sqlalchemy import BigInteger, DateTime, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class DouyinFollowing(SQLModel, table=True):
    """账号关注列表里的一位博主。"""

    __tablename__ = "douyin_following"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "uid_hash", name="uq_douyin_following_account_uid"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )  # 归属用户 id（租户隔离）
    account_id: uuid.UUID = Field(
        foreign_key="douyin_account.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )  # 采集该列表的抖音账号
    sec_uid: str = Field(max_length=256)  # 博主主页 sec_user_id（平台公开标识）
    uid_hash: str = Field(max_length=64, index=True)  # 脱敏身份哈希，账号内去重键
    nickname: str = Field(default="", max_length=255)  # 昵称
    avatar_url: str = Field(default="", max_length=1000)  # 头像
    signature: str = Field(default="", sa_type=Text)  # 个性签名
    follower_count: int = Field(default=0, sa_type=BigInteger)  # 粉丝数
    aweme_count: int = Field(default=0, sa_type=BigInteger)  # 主页作品数
    is_mutual: bool = Field(default=False, index=True)  # 是否互关
    source_task_id: uuid.UUID | None = Field(
        default=None, foreign_key="crawl_task.id", ondelete="SET NULL", index=True
    )  # 最近一次采集它的任务
    fetched_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 最近一次采集时间
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinAccountAweme(SQLModel, table=True):
    """账号点赞 / 收藏的作品（同一张表，用 kind 区分）。"""

    __tablename__ = "douyin_account_aweme"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "kind", "aweme_id", name="uq_douyin_account_aweme"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    account_id: uuid.UUID = Field(
        foreign_key="douyin_account.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    kind: str = Field(max_length=16, index=True)  # liked（点赞）/ collected（收藏）
    aweme_id: str = Field(max_length=64, index=True)  # 平台作品号
    title: str = Field(default="", sa_type=Text)  # 作品文案
    nickname: str = Field(default="", max_length=255)  # 作者昵称
    creator_hash: str = Field(default="", max_length=64, index=True)  # 作者脱敏标识
    cover_url: str = Field(default="", max_length=1000)  # 封面
    aweme_url: str = Field(default="", max_length=1000)  # 作品链接
    liked_count: int = Field(default=0, sa_type=BigInteger)  # 点赞数
    comment_count: int = Field(default=0, sa_type=BigInteger)  # 评论数
    collected_count: int = Field(default=0, sa_type=BigInteger)  # 收藏数
    share_count: int = Field(default=0, sa_type=BigInteger)  # 分享数
    published_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 作品发布时间
    source_task_id: uuid.UUID | None = Field(
        default=None, foreign_key="crawl_task.id", ondelete="SET NULL", index=True
    )
    fetched_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinFollowingPublic(SQLModel):
    """关注博主的对外模型。"""

    id: uuid.UUID
    account_id: uuid.UUID
    sec_uid: str
    uid_hash: str
    nickname: str
    avatar_url: str
    signature: str
    follower_count: int
    aweme_count: int
    is_mutual: bool
    in_creator_list: bool  # 是否已在达人名单里（前端据此决定「加入名单」按钮）
    fetched_at: datetime


class DouyinFollowingsPublic(SQLModel):
    """关注列表分页响应。"""

    data: list[DouyinFollowingPublic]
    count: int


class DouyinAccountAwemePublic(SQLModel):
    """账号点赞 / 收藏作品的对外模型。"""

    id: uuid.UUID
    account_id: uuid.UUID
    kind: str
    aweme_id: str
    title: str
    nickname: str
    creator_hash: str
    cover_url: str
    aweme_url: str
    liked_count: int
    comment_count: int
    collected_count: int
    share_count: int
    published_at: datetime | None
    fetched_at: datetime


class DouyinAccountAwemesPublic(SQLModel):
    """账号点赞 / 收藏作品分页响应。"""

    data: list[DouyinAccountAwemePublic]
    count: int


class DouyinMineSummaryPublic(SQLModel):
    """「我的」页概览：某账号的关注 / 点赞 / 收藏计数与最近采集时间。"""

    account_id: uuid.UUID
    following_count: int
    liked_count: int
    collected_count: int
    following_fetched_at: datetime | None
    likes_fetched_at: datetime | None
    collects_fetched_at: datetime | None


__all__ = [
    "DouyinFollowing",
    "DouyinFollowingPublic",
    "DouyinFollowingsPublic",
    "DouyinAccountAweme",
    "DouyinAccountAwemePublic",
    "DouyinAccountAwemesPublic",
    "DouyinMineSummaryPublic",
]
