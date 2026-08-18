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
    unprocessed = "unprocessed"
    active = "active"
    crawled = "crawled"
    failed = "failed"


class DouyinKeywordSyncSource(str, Enum):
    automatic = "automatic"
    manual = "manual"
    history = "history"
    batch_task = "batch_task"


class DouyinKeywordBatchMode(str, Enum):
    combined = "combined"
    separate = "separate"


class DouyinKeyword(SQLModel, table=True):
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

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    track_id: uuid.UUID = Field(nullable=False, index=True)
    keyword: str = Field(max_length=200)
    normalized_keyword: str = Field(max_length=200, index=True)
    enabled: bool = Field(default=True, index=True)
    notes: str = Field(default="", max_length=1000)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinKeywordTaskLink(SQLModel, table=True):
    __tablename__ = "douyin_keyword_task_link"
    __table_args__ = (
        UniqueConstraint("keyword_id", "task_id", name="uq_douyin_keyword_task_link"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    keyword_id: uuid.UUID = Field(
        foreign_key="douyin_keyword.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    task_id: uuid.UUID = Field(
        foreign_key="crawl_task.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    source: str = Field(default=DouyinKeywordSyncSource.automatic.value, max_length=32)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinKeywordPublic(SQLModel):
    id: uuid.UUID
    track_id: uuid.UUID
    track_name: str
    track_is_default: bool
    keyword: str
    enabled: bool
    notes: str
    status: DouyinKeywordStatus
    task_count: int
    active_task_count: int
    success_task_count: int
    failed_task_count: int
    aweme_count: int
    last_task_id: uuid.UUID | None
    last_task_status: CrawlTaskStatus | None
    last_crawled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DouyinKeywordsPublic(SQLModel):
    data: list[DouyinKeywordPublic]
    count: int


class DouyinKeywordBulkCreateRequest(SQLModel):
    keywords: list[str] = Field(min_length=1, max_length=500)
    track_id: uuid.UUID | None = None
    notes: str = Field(default="", max_length=1000)
    enabled: bool = True


class DouyinBulkDeleteRequest(SQLModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class DouyinKeywordBulkCreateResult(SQLModel):
    data: list[DouyinKeywordPublic]
    created_count: int
    existing_count: int


class DouyinKeywordUpdate(SQLModel):
    keyword: str | None = Field(default=None, min_length=1, max_length=200)
    track_id: uuid.UUID | None = None
    enabled: bool | None = None
    notes: str | None = Field(default=None, max_length=1000)


class DouyinKeywordSyncResult(SQLModel):
    task_count: int
    keyword_count: int
    created_count: int
    binding_count: int


class DouyinKeywordBatchTaskRequest(SQLModel):
    keyword_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    track_id: uuid.UUID | None = None
    mode: DouyinKeywordBatchMode = DouyinKeywordBatchMode.combined
    login_type: DouyinLoginType = DouyinLoginType.qrcode
    browser_mode: DouyinBrowserMode | None = None
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
    account_pool_id: uuid.UUID | None = None
    account_strategy: DouyinAccountPoolStrategy = DouyinAccountPoolStrategy.least_loaded

    @model_validator(mode="after")
    def normalize_options(self) -> "DouyinKeywordBatchTaskRequest":
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
        if self.account_id and self.account_pool_id:
            raise ValueError("账号和账号池只能选择一种")
        if self.publish_time not in {0, 1, 7, 180}:
            raise ValueError("publish_time 只能是 0、1、7 或 180")
        return self


class DouyinKeywordTaskBatchResult(SQLModel):
    data: list[CrawlTaskPublic]
    count: int


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
