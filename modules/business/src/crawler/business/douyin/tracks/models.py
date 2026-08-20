"""抖音赛道限界上下文的业务模型与 API schema。

赛道（Track）是关键词与采集任务的分组载体，本模块定义赛道实体、
关键词/任务关联表以及赛道管理的请求与对外传输模型。
"""

import uuid
from datetime import datetime

from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.accounts.models import DouyinAccountPoolStrategy
from crawler.business.douyin.keywords.models import (
    DouyinKeywordBatchMode,
    DouyinKeywordPublic,
)
from crawler.business.douyin.tasks.models import (
    CrawlTaskStatus,
    DouyinRequestDelayLevel,
)
from pydantic import model_validator
from sqlalchemy import DateTime, Index, Text, UniqueConstraint, text
from sqlmodel import Field, SQLModel


class DouyinTrack(SQLModel, table=True):
    """赛道数据库实体：用户维度下关键词与采集任务的分组，每用户有唯一默认赛道。"""

    __tablename__ = "douyin_track"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "normalized_name", name="uq_douyin_track_owner_name"
        ),
        UniqueConstraint("id", "owner_id", name="uq_douyin_track_id_owner"),
        Index(
            "uq_douyin_track_owner_default",
            "owner_id",
            unique=True,
            postgresql_where=text("is_default"),
            sqlite_where=text("is_default = 1"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)  # 赛道 ID
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )  # 归属用户 ID
    name: str = Field(max_length=100)  # 赛道名称
    normalized_name: str = Field(max_length=100, index=True)  # 规范化名称（去空白折叠、小写），用于同用户下唯一判重
    description: str = Field(default="", max_length=1000)  # 赛道描述
    prompt: str = Field(default="", sa_type=Text)  # 赛道分析提示词
    enabled: bool = Field(default=True, index=True)  # 是否启用
    is_default: bool = Field(default=False, index=True)  # 是否为默认赛道（兜底归属，不可删除/停用/重命名）
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 创建时间
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 更新时间


class DouyinTrackKeywordLink(SQLModel, table=True):
    """赛道-关键词关联表（遗留兼容表，与 keyword.track_id 保持一致镜像）。"""

    __tablename__ = "douyin_track_keyword_link"
    __table_args__ = (
        UniqueConstraint("track_id", "keyword_id", name="uq_douyin_track_keyword_link"),
        UniqueConstraint("keyword_id", name="uq_douyin_track_keyword_single_track"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)  # 关联记录 ID
    track_id: uuid.UUID = Field(
        foreign_key="douyin_track.id", nullable=False, ondelete="CASCADE", index=True
    )  # 赛道 ID
    keyword_id: uuid.UUID = Field(
        foreign_key="douyin_keyword.id", nullable=False, ondelete="CASCADE", index=True
    )  # 关键词 ID（一个关键词只能归属一个赛道）
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 关联创建时间


class DouyinTrackTaskLink(SQLModel, table=True):
    """赛道-任务关联表（遗留兼容表，与 task.track_id 保持一致镜像）。"""

    __tablename__ = "douyin_track_task_link"
    __table_args__ = (
        UniqueConstraint("track_id", "task_id", name="uq_douyin_track_task_link"),
        UniqueConstraint("task_id", name="uq_douyin_track_task_single_track"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)  # 关联记录 ID
    track_id: uuid.UUID = Field(
        foreign_key="douyin_track.id", nullable=False, ondelete="CASCADE", index=True
    )  # 赛道 ID
    task_id: uuid.UUID = Field(
        foreign_key="crawl_task.id", nullable=False, ondelete="CASCADE", index=True
    )  # 采集任务 ID（一个任务只能归属一个赛道）
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 关联创建时间


class DouyinTrackCreate(SQLModel):
    """创建赛道的请求模型。"""

    name: str = Field(min_length=1, max_length=100)  # 赛道名称
    description: str = Field(default="", max_length=1000)  # 赛道描述
    prompt: str = Field(default="", max_length=10000)  # 赛道分析提示词
    keywords: list[str] = Field(default_factory=list, max_length=200)  # 初始关键词列表


class DouyinTrackUpdate(SQLModel):
    """更新赛道的请求模型，各字段均为可选部分更新。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)  # 新名称
    description: str | None = Field(default=None, max_length=1000)  # 新描述
    prompt: str | None = Field(default=None, max_length=10000)  # 新提示词
    enabled: bool | None = None  # 启用/停用


class DouyinTrackKeywordAdd(SQLModel):
    """向赛道批量追加关键词的请求模型。"""

    keywords: list[str] = Field(min_length=1, max_length=200)  # 待追加的关键词列表


class DouyinTrackTaskRequest(SQLModel):
    """基于赛道关键词批量创建采集任务的请求模型。"""

    keyword_ids: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=1000,
        description=(
            "本次运行选中的赛道关键词 ID；省略或传空数组且未指定达人时，"
            "运行该赛道全部已启用关键词"
        ),
    )
    creator_ids: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=200,
        description=(
            "本次运行选中的赛道达人 ID；省略或传空数组时只运行关键词"
        ),
    )
    mode: DouyinKeywordBatchMode = DouyinKeywordBatchMode.combined  # 批量模式：合并或独立任务
    max_awemes: int = Field(default=30, ge=1, le=1000)  # 每个关键词最多采集的作品数
    fetch_comments: bool = True  # 是否采集评论
    fetch_sub_comments: bool = False  # 是否采集子评论
    max_comments_per_aweme: int = Field(default=10, ge=1, le=1000)  # 每个作品最多采集的评论数
    request_delay_level: DouyinRequestDelayLevel = DouyinRequestDelayLevel.steady  # 请求延迟档位
    publish_time: int = 0  # 发布时间筛选（0 不限、1 一天内、7 一周内、180 半年内）
    download_media: bool = False  # 是否下载媒体文件
    translate_subtitles: bool = False  # 是否翻译字幕（开启时强制下载媒体）
    account_id: uuid.UUID | None = None  # 指定执行账号 ID
    account_pool_id: uuid.UUID | None = None  # 指定账号池 ID
    account_strategy: DouyinAccountPoolStrategy = DouyinAccountPoolStrategy.least_loaded  # 账号池调度策略

    @model_validator(mode="after")
    def normalize_track_task(self) -> "DouyinTrackTaskRequest":
        """归一化并校验字段间组合约束。

        返回：
            归一化后的自身实例。

        异常：
            ValueError: 账号与账号池同时指定，或 publish_time 取值非法时抛出。
        """
        if not self.fetch_comments:
            self.fetch_sub_comments = False
        if self.translate_subtitles:
            self.download_media = True
        if self.account_id and self.account_pool_id:
            raise ValueError("账号和账号池只能选择一种")
        if self.publish_time not in {0, 1, 7, 180}:
            raise ValueError("publish_time 只能是 0、1、7 或 180")
        return self


class DouyinTrackPublic(SQLModel):
    """赛道概要（含聚合统计）的对外模型。"""

    id: uuid.UUID  # 赛道 ID
    name: str  # 赛道名称
    description: str  # 赛道描述
    enabled: bool  # 是否启用
    is_default: bool  # 是否为默认赛道
    keyword_count: int  # 关键词总数
    enabled_keyword_count: int  # 已启用关键词数
    task_count: int  # 任务总数
    active_task_count: int  # 进行中的任务数
    aweme_count: int  # 累计采集作品数
    comment_count: int  # 累计采集评论数
    last_task_id: uuid.UUID | None  # 最近一次任务 ID
    last_task_status: CrawlTaskStatus | None  # 最近一次任务状态
    last_run_at: datetime | None  # 最近一次任务发起时间
    created_at: datetime  # 创建时间
    updated_at: datetime  # 更新时间


class DouyinTrackDetailPublic(DouyinTrackPublic):
    """赛道详情的对外模型，额外包含分析提示词。"""

    prompt: str  # 赛道分析提示词


class DouyinTracksPublic(SQLModel):
    """赛道分页列表的对外模型。"""

    data: list[DouyinTrackPublic]  # 当前页数据
    count: int  # 满足条件的总条数


class DouyinTrackKeywordsPublic(SQLModel):
    """赛道关键词列表的对外模型。"""

    data: list[DouyinKeywordPublic]  # 关键词列表
    count: int  # 关键词总数


__all__ = [
    "DouyinTrack",
    "DouyinTrackKeywordLink",
    "DouyinTrackTaskLink",
    "DouyinTrackCreate",
    "DouyinTrackUpdate",
    "DouyinTrackKeywordAdd",
    "DouyinTrackTaskRequest",
    "DouyinTrackPublic",
    "DouyinTrackDetailPublic",
    "DouyinTracksPublic",
    "DouyinTrackKeywordsPublic",
]
