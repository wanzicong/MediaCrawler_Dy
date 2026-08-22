"""抖音赛道限界上下文的业务模型与 API schema。

赛道（Track）是关键词与采集任务的分组载体，本模块定义赛道实体、
关键词/任务关联表以及赛道管理的请求与对外传输模型。
"""

import uuid
from datetime import datetime

from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.accounts.models import (
    DouyinAccountPoolStrategy,
    DouyinBrowserMode,
)
from crawler.business.douyin.keywords.models import (
    DouyinKeywordBatchMode,
    DouyinKeywordPublic,
)
from crawler.business.douyin.media.models import (
    MediaProcessingMode,
    MediaStorageBackend,
)
from crawler.business.douyin.tasks.models import (
    CrawlTaskStatus,
    DouyinLoginType,
    DouyinRequestDelayLevel,
)
from pydantic import SecretStr, field_validator, model_validator
from sqlalchemy import JSON, DateTime, Index, Text, UniqueConstraint, text
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
    normalized_name: str = Field(
        max_length=100, index=True
    )  # 规范化名称（去空白折叠、小写），用于同用户下唯一判重
    description: str = Field(default="", max_length=1000)  # 赛道描述
    prompt: str = Field(default="", sa_type=Text)  # 赛道分析提示词
    default_task_config: dict[str, object] = Field(
        default_factory=dict, sa_type=JSON
    )  # 赛道级默认爬取参数（不含 Cookie，创建任务时可逐项覆盖）
    reply_templates: list[str] = Field(
        default_factory=list, sa_type=JSON
    )  # 赛道级视频评论/回复话术库
    keyword_categories: list[str] = Field(
        default_factory=list, sa_type=JSON
    )  # 赛道级关键词分类选项
    enabled: bool = Field(default=True, index=True)  # 是否启用
    is_default: bool = Field(
        default=False, index=True
    )  # 是否为默认赛道（兜底归属，不可删除/停用/重命名）
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


class DouyinTrackTaskDefaults(SQLModel):
    """赛道级默认爬取参数，与通用任务的风险控制和媒体参数保持一致。"""

    mode: DouyinKeywordBatchMode = DouyinKeywordBatchMode.separate  # 兼容字段
    start_page: int = Field(default=1, ge=1)  # 起始页码
    max_awemes: int = Field(default=10, ge=1, le=1000)  # 每个任务最多采集作品数
    fetch_comments: bool = True  # 是否采集一级评论
    fetch_sub_comments: bool = False  # 是否采集子评论
    max_comments_per_aweme: int = Field(default=10, ge=1, le=1000)  # 单作品评论上限
    concurrency: int = Field(default=1, ge=1, le=5)  # 单任务抓取并发
    request_delay_level: DouyinRequestDelayLevel = DouyinRequestDelayLevel.steady
    request_interval_seconds: float = Field(default=1.0, ge=0.2, le=60.0)
    task_interval_seconds: float | None = Field(
        default=None, ge=0.0, le=3600.0
    )  # 批量任务完成后的下一任务间隔；为空时沿用请求风控区间
    publish_time: int = 0  # 发布时间筛选
    browser_mode: DouyinBrowserMode | None = (
        DouyinBrowserMode.remote
    )  # 临时登录使用的浏览器模式
    media_processing_mode: MediaProcessingMode = (
        MediaProcessingMode.none
    )  # 媒体处理策略
    media_storage: MediaStorageBackend | None = (
        MediaStorageBackend.minio
    )  # 媒体存储后端
    download_media: bool = False  # 爬取完成后是否创建下载阶段
    translate_subtitles: bool = False  # 下载完成后是否转写字幕
    transcription_language: str = Field(default="auto", min_length=2, max_length=32)
    account_id: uuid.UUID | None = None  # 指定账号
    account_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    account_pool_id: uuid.UUID | None = None  # 指定账号池
    account_strategy: DouyinAccountPoolStrategy = DouyinAccountPoolStrategy.least_loaded

    @model_validator(mode="after")
    def normalize_defaults(self) -> "DouyinTrackTaskDefaults":
        """联动评论/媒体选项，并校验账号选择与发布时间。"""
        if not self.fetch_comments:
            object.__setattr__(self, "fetch_sub_comments", False)
        if self.translate_subtitles:
            object.__setattr__(self, "download_media", True)
        if (
            self.download_media
            and self.media_processing_mode == MediaProcessingMode.none
        ):
            object.__setattr__(
                self, "media_processing_mode", MediaProcessingMode.immediate
            )
        if not self.download_media:
            object.__setattr__(self, "translate_subtitles", False)
            object.__setattr__(self, "media_processing_mode", MediaProcessingMode.none)
        selection_count = sum(
            bool(value)
            for value in (self.account_id, self.account_ids, self.account_pool_id)
        )
        if selection_count > 1:
            raise ValueError("账号、多个账号和账号池只能选择一种")
        if self.publish_time not in {0, 1, 7, 180}:
            raise ValueError("publish_time 只能是 0、1、7 或 180")
        return self


class DouyinTrackCreate(SQLModel):
    """创建赛道的请求模型。"""

    name: str = Field(min_length=1, max_length=100)  # 赛道名称
    description: str = Field(default="", max_length=1000)  # 赛道描述
    prompt: str = Field(default="", max_length=10000)  # 赛道分析提示词
    keywords: list[str] = Field(default_factory=list, max_length=200)  # 初始关键词列表
    default_task_config: DouyinTrackTaskDefaults = Field(
        default_factory=DouyinTrackTaskDefaults
    )  # 后续从赛道启动任务时使用的默认参数
    reply_templates: list[str] = Field(default_factory=list, max_length=100)
    keyword_categories: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("reply_templates", "keyword_categories")
    @classmethod
    def validate_text_library(cls, values: list[str]) -> list[str]:
        """清洗赛道文本库：去空白、忽略大小写去重并限制单项长度。"""
        output: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = " ".join(value.strip().split())
            if not cleaned or cleaned.casefold() in seen:
                continue
            if len(cleaned) > 2200:
                raise ValueError("话术或分类单项长度不能超过 2200 个字符")
            seen.add(cleaned.casefold())
            output.append(cleaned)
        return output


class DouyinTrackUpdate(SQLModel):
    """更新赛道的请求模型，各字段均为可选部分更新。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)  # 新名称
    description: str | None = Field(default=None, max_length=1000)  # 新描述
    prompt: str | None = Field(default=None, max_length=10000)  # 新提示词
    enabled: bool | None = None  # 启用/停用
    default_task_config: DouyinTrackTaskDefaults | None = None  # 替换默认爬取参数
    reply_templates: list[str] | None = Field(default=None, max_length=100)
    keyword_categories: list[str] | None = Field(default=None, max_length=100)

    @field_validator("reply_templates", "keyword_categories")
    @classmethod
    def validate_text_library(cls, values: list[str] | None) -> list[str] | None:
        """复用创建模型的文本库清洗规则。"""
        if values is None:
            return None
        return DouyinTrackCreate.validate_text_library(values)


class DouyinTrackKeywordAdd(SQLModel):
    """向赛道批量追加关键词的请求模型。"""

    keywords: list[str] = Field(min_length=1, max_length=200)  # 待追加的关键词列表


class DouyinTrackTaskRequest(DouyinTrackTaskDefaults):
    """基于赛道关键词批量创建采集任务的请求模型。"""

    login_type: DouyinLoginType = DouyinLoginType.qrcode  # 本次运行登录方式
    cookies: SecretStr | None = Field(
        default=None, repr=False
    )  # 本次运行的一次性 Cookie（不写入赛道默认配置或任务记录）

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
        description=("本次运行选中的赛道达人 ID；省略或传空数组时只运行关键词"),
    )

    @model_validator(mode="after")
    def validate_runtime_credentials(self) -> "DouyinTrackTaskRequest":
        """校验赛道本次运行的临时凭据，并禁止与托管账号混用。"""
        has_cookies = bool(self.cookies and self.cookies.get_secret_value().strip())
        if has_cookies:
            self.login_type = DouyinLoginType.cookie
        if self.login_type == DouyinLoginType.cookie and not has_cookies:
            raise ValueError("cookie 登录必须提供 cookies")
        if has_cookies and any(
            (self.account_id, self.account_ids, self.account_pool_id)
        ):
            raise ValueError("选择已管理账号时不能再提交一次性 Cookie")
        return self


class DouyinTrackPublic(SQLModel):
    """赛道概要（含聚合统计）的对外模型。"""

    id: uuid.UUID  # 赛道 ID
    name: str  # 赛道名称
    description: str  # 赛道描述
    enabled: bool  # 是否启用
    is_default: bool  # 是否为默认赛道
    default_task_config: DouyinTrackTaskDefaults  # 赛道级默认爬取参数
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
    reply_templates: list[str]  # 赛道评论/回复话术库
    keyword_categories: list[str]  # 赛道关键词分类选项


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
    "DouyinTrackTaskDefaults",
    "DouyinTrackKeywordAdd",
    "DouyinTrackTaskRequest",
    "DouyinTrackPublic",
    "DouyinTrackDetailPublic",
    "DouyinTracksPublic",
    "DouyinTrackKeywordsPublic",
]
