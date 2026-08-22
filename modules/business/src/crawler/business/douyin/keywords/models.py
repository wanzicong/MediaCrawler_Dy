"""抖音关键词限界上下文的业务模型与 API 契约。

包含关键词表实体、关键词-任务关联表实体、关键词状态/同步来源/
批量模式枚举，以及关键词增删改查与批量建任务的请求/响应模型。
"""

import uuid
from datetime import datetime
from enum import Enum

from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.accounts.models import (
    DouyinAccountPoolStrategy,
    DouyinBrowserMode,
)
from crawler.business.douyin.media.models import (
    MediaProcessingMode,
    MediaStorageBackend,
)
from crawler.business.douyin.tasks.models import (
    CrawlTaskPublic,
    CrawlTaskStatus,
    DouyinLoginType,
    DouyinRequestDelayLevel,
)
from pydantic import model_validator
from sqlalchemy import DateTime, ForeignKeyConstraint, UniqueConstraint
from sqlmodel import Field, SQLModel


class DouyinKeywordStatus(str, Enum):
    """关键词处理状态（由关联任务状态聚合推导得出，不落库）。"""

    unprocessed = "unprocessed"  # 未处理：从未关联过任何任务
    active = "active"  # 进行中：存在排队/运行中的关联任务
    crawled = "crawled"  # 已采集：存在成功的关联任务
    failed = "failed"  # 失败：存在失败/取消/中断的关联任务且无进行中与成功任务


class DouyinKeywordSyncSource(str, Enum):
    """关键词-任务绑定的来源标识。"""

    automatic = "automatic"  # 自动：任务创建/执行时自动同步
    manual = "manual"  # 手动：用户在界面上手动触发同步
    history = "history"  # 历史：历史任务批量回填同步
    batch_task = "batch_task"  # 批量建任务：通过关键词批量创建任务时绑定


class DouyinKeywordBatchMode(str, Enum):
    """关键词批量建任务的分组模式。"""

    combined = "combined"  # 兼容旧客户端；服务端仍固定按一词一任务拆分
    separate = "separate"  # 每个关键词单独创建一个任务


class DouyinKeyword(SQLModel, table=True):
    """关键词表实体，表示用户关键词库中的一个搜索关键词。

    以 (owner_id, normalized_keyword) 作为业务唯一键；track_id 与 owner_id
    通过复合外键保证关键词归属的赛道必须属于同一用户。
    """

    __tablename__ = "douyin_keyword"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "normalized_keyword", name="uq_douyin_keyword_owner_value"
        ),
        ForeignKeyConstraint(
            ["track_id", "owner_id"],
            ["douyin_track.id", "douyin_track.owner_id"],
            name="fk_douyin_keyword_track_owner",
            ondelete="NO ACTION",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4, primary_key=True
    )  # 主键，关键词 UUID
    owner_id: uuid.UUID = Field(  # 归属用户 ID，用户删除时级联删除
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    track_id: uuid.UUID = Field(nullable=False, index=True)  # 归属赛道 ID
    keyword: str = Field(max_length=200)  # 关键词原文（保留用户输入的大小写与空格）
    normalized_keyword: str = Field(
        max_length=200, index=True
    )  # 归一化后的关键词（去重比较用）
    enabled: bool = Field(
        default=True, index=True
    )  # 是否启用，停用的关键词不能用于批量建任务
    category: str = Field(default="", max_length=100, index=True)  # 赛道内分类
    notes: str = Field(default="", max_length=1000)  # 用户备注
    created_at: datetime = Field(  # 创建时间（UTC）
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    updated_at: datetime = Field(  # 最近更新时间（UTC）
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinKeywordTaskLink(SQLModel, table=True):
    """关键词-任务关联表实体，记录关键词与采集任务的多对多绑定关系。"""

    __tablename__ = "douyin_keyword_task_link"
    __table_args__ = (
        UniqueConstraint("keyword_id", "task_id", name="uq_douyin_keyword_task_link"),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4, primary_key=True
    )  # 主键，关联记录 UUID
    keyword_id: uuid.UUID = Field(  # 关键词 ID，关键词删除时级联删除
        foreign_key="douyin_keyword.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    task_id: uuid.UUID = Field(  # 采集任务 ID，任务删除时级联删除
        foreign_key="crawl_task.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    source: str = Field(
        default=DouyinKeywordSyncSource.automatic.value, max_length=32
    )  # 绑定来源，见 DouyinKeywordSyncSource
    created_at: datetime = Field(  # 绑定创建时间（UTC）
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinKeywordPublic(SQLModel):
    """关键词对外展示模型，聚合所属赛道信息与关联任务的统计汇总。"""

    id: uuid.UUID  # 关键词 UUID
    track_id: uuid.UUID  # 归属赛道 ID
    track_name: str  # 归属赛道名称
    track_is_default: bool  # 归属赛道是否为默认赛道
    keyword: str  # 关键词原文
    enabled: bool  # 是否启用
    category: str  # 赛道内分类
    notes: str  # 用户备注
    status: DouyinKeywordStatus  # 关键词处理状态（由关联任务状态聚合推导）
    task_count: int  # 关联任务总数
    active_task_count: int  # 进行中（排队/运行等）的关联任务数
    success_task_count: int  # 成功的关联任务数
    failed_task_count: int  # 失败/取消/中断的关联任务数
    aweme_count: int  # 该关键词采集到的作品总数
    last_task_id: uuid.UUID | None  # 最近一次关联任务 ID，无任务时为 None
    last_task_status: CrawlTaskStatus | None  # 最近一次关联任务状态，无任务时为 None
    last_crawled_at: datetime | None  # 最近一次任务完成时间，无完成任务时为 None
    created_at: datetime  # 关键词创建时间（UTC）
    updated_at: datetime  # 关键词最近更新时间（UTC）


class DouyinKeywordsPublic(SQLModel):
    """关键词分页列表响应模型。"""

    data: list[DouyinKeywordPublic]  # 当前页关键词列表
    count: int  # 满足条件的关键词总数


class DouyinKeywordBulkCreateRequest(SQLModel):
    """批量创建关键词请求体。"""

    keywords: list[str] = Field(min_length=1, max_length=500)  # 关键词列表，1~500 个
    track_id: uuid.UUID | None = None  # 目标赛道 ID，None 表示使用默认赛道
    notes: str = Field(default="", max_length=1000)  # 统一写入的备注
    category: str = Field(default="", max_length=100)  # 统一写入的赛道分类
    enabled: bool = True  # 创建后是否启用


class DouyinBulkDeleteRequest(SQLModel):
    """批量删除请求体（按记录 ID）。"""

    ids: list[uuid.UUID] = Field(
        min_length=1, max_length=500
    )  # 待删除的记录 ID，1~500 个


class DouyinKeywordBulkCreateResult(SQLModel):
    """批量创建关键词的结果响应。"""

    data: list[DouyinKeywordPublic]  # 本次涉及的关键词（含新建与已存在）
    created_count: int  # 实际新建数量
    existing_count: int  # 已存在（复用）的数量


class DouyinKeywordUpdate(SQLModel):
    """关键词更新请求体，所有字段可选，仅更新传入的字段。"""

    keyword: str | None = Field(
        default=None, min_length=1, max_length=200
    )  # 新关键词词面
    track_id: uuid.UUID | None = None  # 调整后的赛道 ID
    enabled: bool | None = None  # 启用/停用开关
    category: str | None = Field(default=None, max_length=100)  # 新分类
    notes: str | None = Field(default=None, max_length=1000)  # 新备注


class DouyinKeywordSyncResult(SQLModel):
    """关键词同步（单任务或历史回填）的结果统计。"""

    task_count: int  # 本次同步涉及的任务数
    keyword_count: int  # 本次同步涉及的关键词数
    created_count: int  # 新建关键词数
    binding_count: int  # 新建关键词-任务绑定数


class DouyinKeywordBatchTaskRequest(SQLModel):
    """关键词批量创建采集任务的请求体。"""

    keyword_ids: list[uuid.UUID] = Field(
        min_length=1, max_length=100
    )  # 选中的关键词 ID，1~100 个
    track_id: uuid.UUID | None = None  # 指定赛道 ID；None 时要求所选关键词同属一个赛道
    mode: DouyinKeywordBatchMode = DouyinKeywordBatchMode.separate  # 兼容字段
    login_type: DouyinLoginType = DouyinLoginType.qrcode  # 登录方式
    browser_mode: DouyinBrowserMode | None = None  # 浏览器运行模式，None 表示用系统默认
    start_page: int = Field(default=1, ge=1)  # 搜索起始页码
    max_awemes: int = Field(default=10, ge=1, le=1000)  # 单任务最大作品采集数
    fetch_comments: bool = True  # 是否采集评论
    fetch_sub_comments: bool = False  # 是否采集子评论（回复）
    max_comments_per_aweme: int = Field(
        default=10, ge=1, le=1000
    )  # 单作品最大评论采集数
    concurrency: int = Field(default=1, ge=1, le=5)  # 采集并发数
    request_delay_level: DouyinRequestDelayLevel = (
        DouyinRequestDelayLevel.fast
    )  # 请求延迟档位
    request_interval_seconds: float = Field(
        default=1.0, ge=0.2, le=60.0
    )  # 自定义请求间隔秒数
    task_interval_seconds: float | None = Field(
        default=None, ge=0.0, le=3600.0
    )  # 批量任务完成后的下一任务间隔；为空时沿用请求风控区间
    publish_time: int = 0  # 作品发布时间筛选：0 不限 / 1 一天内 / 7 一周内 / 180 半年内
    media_processing_mode: MediaProcessingMode = (
        MediaProcessingMode.none
    )  # 媒体处理模式
    media_storage: MediaStorageBackend | None = (
        None  # 媒体存储后端，None 表示用系统默认
    )
    download_media: bool = False  # 是否下载媒体文件
    translate_subtitles: bool = False  # 是否翻译字幕
    transcription_language: str = Field(
        default="auto", min_length=2, max_length=32
    )  # 字幕转写语言，auto 表示自动识别
    account_id: uuid.UUID | None = None  # 指定账号 ID（与账号池二选一）
    account_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=20
    )  # 指定多个账号并行分片
    account_pool_id: uuid.UUID | None = None  # 指定账号池 ID（与指定账号二选一）
    account_strategy: DouyinAccountPoolStrategy = (
        DouyinAccountPoolStrategy.least_loaded
    )  # 账号池调度策略

    @model_validator(mode="after")
    def normalize_options(self) -> "DouyinKeywordBatchTaskRequest":
        """归一化互斥/联动选项并校验取值合法性。

        规则：不采评论则不采子评论；翻译字幕必须先下载媒体；
        下载媒体而未指定处理模式时默认 immediate；不下载媒体则关闭
        字幕翻译并重置处理模式；账号与账号池互斥；publish_time 仅允许
        0/1/7/180。

        异常：
            ValueError: 账号与账号池同时指定，或 publish_time 取值非法。
        """
        if not self.fetch_comments:
            self.fetch_sub_comments = False
        if self.translate_subtitles:
            self.download_media = True
        if (
            self.download_media
            and self.media_processing_mode == MediaProcessingMode.none
        ):
            self.media_processing_mode = MediaProcessingMode.immediate
        if not self.download_media:
            self.translate_subtitles = False
            self.media_processing_mode = MediaProcessingMode.none
        if (
            sum(
                bool(value)
                for value in (self.account_id, self.account_ids, self.account_pool_id)
            )
            > 1
        ):
            raise ValueError("账号、多个账号和账号池只能选择一种")
        if self.publish_time not in {0, 1, 7, 180}:
            raise ValueError("publish_time 只能是 0、1、7 或 180")
        return self


class DouyinKeywordTaskBatchResult(SQLModel):
    """关键词批量建任务的结果响应。"""

    data: list[CrawlTaskPublic]  # 本次创建的采集任务列表
    count: int  # 创建的任务数


__all__ = [
    "DouyinKeywordStatus",
    "DouyinKeywordSyncSource",
    "DouyinKeywordBatchMode",
    "DouyinKeyword",
    "DouyinKeywordTaskLink",
    "DouyinKeywordPublic",
    "DouyinKeywordsPublic",
    "DouyinKeywordBulkCreateRequest",
    "DouyinBulkDeleteRequest",
    "DouyinKeywordBulkCreateResult",
    "DouyinKeywordUpdate",
    "DouyinKeywordSyncResult",
    "DouyinKeywordBatchTaskRequest",
    "DouyinKeywordTaskBatchResult",
]
