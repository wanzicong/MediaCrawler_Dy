"""Business models and schemas for this bounded context."""

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
from pydantic import SecretStr, model_validator
from sqlalchemy import DateTime, ForeignKeyConstraint, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class DouyinCrawlType(str, Enum):
    search = "search"
    detail = "detail"
    creator = "creator"
    creator_from_aweme = "creator_from_aweme"
    liked = "liked"
    collected = "collected"


class DouyinLoginType(str, Enum):
    qrcode = "qrcode"
    cookie = "cookie"


class CrawlTaskShardStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    interrupted = "interrupted"
    cancelled = "cancelled"


class CrawlTaskStatus(str, Enum):
    queued = "queued"
    waiting_login = "waiting_login"
    running = "running"
    processing_media = "processing_media"
    cancelling = "cancelling"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    interrupted = "interrupted"


class CrawlTaskPhase(str, Enum):
    crawl = "crawl"
    media = "media"
    completed = "completed"


class DouyinRequestDelayLevel(str, Enum):
    fast = "fast"
    steady = "steady"
    ultra_steady = "ultra_steady"


class CrawlTaskCreate(SQLModel):
    track_id: uuid.UUID | None = None
    crawl_type: DouyinCrawlType = DouyinCrawlType.search
    login_type: DouyinLoginType = DouyinLoginType.qrcode
    browser_mode: DouyinBrowserMode | None = None
    cookies: SecretStr | None = Field(default=None, repr=False)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    video_ids: list[str] = Field(default_factory=list, max_length=1000)
    creator_ids: list[str] = Field(default_factory=list, max_length=100)
    start_page: int = Field(default=1, ge=1)
    max_awemes: int = Field(default=10, ge=1, le=1000)
    fetch_comments: bool = True
    fetch_sub_comments: bool = False
    max_comments_per_aweme: int = Field(default=10, ge=1, le=1000)
    concurrency: int = Field(default=1, ge=1, le=5)
    request_delay_level: DouyinRequestDelayLevel = DouyinRequestDelayLevel.fast
    request_interval_seconds: float = Field(default=1.0, ge=0.2, le=60.0)
    publish_time: int = 0
    media_processing_mode: MediaProcessingMode = MediaProcessingMode.none
    media_storage: MediaStorageBackend | None = None
    download_media: bool = False
    translate_subtitles: bool = False
    transcription_language: str = Field(default="auto", min_length=2, max_length=32)
    account_id: uuid.UUID | None = None
    account_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    account_pool_id: uuid.UUID | None = None
    account_strategy: DouyinAccountPoolStrategy = DouyinAccountPoolStrategy.least_loaded

    @model_validator(mode="after")
    def validate_crawl_target(self) -> "CrawlTaskCreate":
        if self.cookies and self.cookies.get_secret_value().strip():
            self.login_type = DouyinLoginType.cookie
        if self.login_type == DouyinLoginType.cookie and not (
            self.cookies and self.cookies.get_secret_value().strip()
        ):
            raise ValueError("cookie 登录必须提供 cookies")
        if self.crawl_type == DouyinCrawlType.search and not any(
            value.strip() for value in self.keywords
        ):
            raise ValueError("search 模式必须提供 keywords")
        if self.crawl_type == DouyinCrawlType.detail and not any(
            value.strip() for value in self.video_ids
        ):
            raise ValueError("detail 模式必须提供 video_ids")
        if self.crawl_type == DouyinCrawlType.creator and not any(
            value.strip() for value in self.creator_ids
        ):
            raise ValueError("creator 模式必须提供 creator_ids")
        if self.crawl_type == DouyinCrawlType.creator_from_aweme and not any(
            value.strip() for value in self.video_ids
        ):
            raise ValueError("creator_from_aweme 模式必须提供 video_ids")
        if self.publish_time not in {0, 1, 7, 180}:
            raise ValueError("publish_time 只能是 0、1、7 或 180")
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
        selection_count = sum(
            bool(value)
            for value in (self.account_id, self.account_ids, self.account_pool_id)
        )
        if selection_count > 1:
            raise ValueError("账号、多个账号和账号池只能选择一种")
        if self.cookies and selection_count:
            raise ValueError("选择已管理账号时不能再提交一次性 Cookie")
        return self

    def public_request(self) -> dict[str, object]:
        payload = self.model_dump(mode="json", exclude={"cookies"})
        payload["request_interval_range_seconds"] = list(
            self.request_interval_range_seconds()
        )
        return payload

    def request_interval_range_seconds(self) -> tuple[float, float]:
        preset_min, preset_max = {
            DouyinRequestDelayLevel.fast: (1.0, 2.0),
            DouyinRequestDelayLevel.steady: (3.0, 6.0),
            DouyinRequestDelayLevel.ultra_steady: (6.0, 12.0),
        }[self.request_delay_level]
        minimum = max(preset_min, self.request_interval_seconds)
        maximum = max(preset_max, minimum * 1.2)
        return round(minimum, 3), round(maximum, 3)


class CrawlTaskResumeRequest(SQLModel):
    resume_crawl: bool | None = None
    resume_media: bool | None = None
    cookies: SecretStr | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def validate_resume_scope(self) -> "CrawlTaskResumeRequest":
        if self.resume_crawl is False and self.resume_media is False:
            raise ValueError("至少需要恢复爬取或媒体处理中的一项")
        return self


class CrawlTask(SQLModel, table=True):
    __tablename__ = "crawl_task"
    __table_args__ = (
        ForeignKeyConstraint(
            ["track_id", "owner_id"],
            ["douyin_track.id", "douyin_track.owner_id"],
            name="fk_crawl_task_track_owner",
            ondelete="NO ACTION",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    track_id: uuid.UUID = Field(nullable=False, index=True)
    account_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="douyin_account.id",
        nullable=True,
        ondelete="SET NULL",
        index=True,
    )
    account_pool_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="douyin_account_pool.id",
        nullable=True,
        ondelete="SET NULL",
        index=True,
    )
    account_strategy: str = Field(
        default=DouyinAccountPoolStrategy.least_loaded.value, max_length=32
    )
    crawl_type: str = Field(max_length=32, index=True)
    status: str = Field(default=CrawlTaskStatus.queued.value, max_length=32, index=True)
    request_json: str = Field(sa_type=Text)
    aweme_count: int = 0
    comment_count: int = 0
    action_count: int = 0
    checkpoint_json: str = Field(default="{}", sa_type=Text)
    resume_count: int = 0
    error: str | None = Field(default=None, sa_type=Text)
    qrcode_path: str | None = Field(default=None, sa_type=Text)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    started_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    last_resumed_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class CrawlTaskPublic(SQLModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    track_id: uuid.UUID
    track_name: str
    track_is_default: bool
    account_id: uuid.UUID | None
    account_pool_id: uuid.UUID | None
    account_strategy: DouyinAccountPoolStrategy
    crawl_type: DouyinCrawlType
    status: CrawlTaskStatus
    request: dict[str, object]
    display_title: str | None = None
    display_author: str | None = None
    display_aweme_id: str | None = None
    aweme_count: int
    comment_count: int
    action_count: int
    checkpoint_phase: CrawlTaskPhase
    resume_count: int
    can_resume_crawl: bool
    can_resume_media: bool
    error: str | None
    has_qrcode: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    last_resumed_at: datetime | None


class CrawlTasksPublic(SQLModel):
    data: list[CrawlTaskPublic]
    count: int


class CrawlTaskShard(SQLModel, table=True):
    __tablename__ = "crawl_task_shard"
    __table_args__ = (
        UniqueConstraint("task_id", "shard_index", name="uq_crawl_task_shard_index"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(
        foreign_key="crawl_task.id", nullable=False, ondelete="CASCADE", index=True
    )
    account_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="douyin_account.id",
        nullable=True,
        ondelete="SET NULL",
        index=True,
    )
    shard_index: int = Field(ge=0)
    status: str = Field(
        default=CrawlTaskShardStatus.queued.value, max_length=32, index=True
    )
    request_json: str = Field(sa_type=Text)
    checkpoint_json: str = Field(default="{}", sa_type=Text)
    aweme_count: int = 0
    comment_count: int = 0
    error: str | None = Field(default=None, sa_type=Text)
    started_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class CrawlTaskShardPublic(SQLModel):
    id: uuid.UUID
    task_id: uuid.UUID
    account_id: uuid.UUID | None
    account_name: str | None
    shard_index: int
    status: CrawlTaskShardStatus
    request: dict[str, object]
    aweme_count: int
    comment_count: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class CrawlTaskShardsPublic(SQLModel):
    data: list[CrawlTaskShardPublic]
    count: int


__all__ = [
    "DouyinCrawlType",
    "DouyinLoginType",
    "CrawlTaskShardStatus",
    "CrawlTaskStatus",
    "CrawlTaskPhase",
    "DouyinRequestDelayLevel",
    "CrawlTaskCreate",
    "CrawlTaskResumeRequest",
    "CrawlTask",
    "CrawlTaskPublic",
    "CrawlTasksPublic",
    "CrawlTaskShard",
    "CrawlTaskShardPublic",
    "CrawlTaskShardsPublic",
]
