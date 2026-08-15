"""Business models and schemas for this bounded context."""

import uuid
from datetime import datetime

from pydantic import model_validator
from sqlalchemy import DateTime, Index, Text, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from app.domain.common.models import get_datetime_utc
from app.domain.douyin.accounts.models import DouyinAccountPoolStrategy
from app.domain.douyin.keywords.models import (
    DouyinKeywordBatchMode,
    DouyinKeywordPublic,
)
from app.domain.douyin.tasks.models import CrawlTaskStatus, DouyinRequestDelayLevel


class DouyinTrack(SQLModel, table=True):
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

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    name: str = Field(max_length=100)
    normalized_name: str = Field(max_length=100, index=True)
    description: str = Field(default="", max_length=1000)
    prompt: str = Field(default="", sa_type=Text)
    enabled: bool = Field(default=True, index=True)
    is_default: bool = Field(default=False, index=True)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinTrackKeywordLink(SQLModel, table=True):
    __tablename__ = "douyin_track_keyword_link"
    __table_args__ = (
        UniqueConstraint("track_id", "keyword_id", name="uq_douyin_track_keyword_link"),
        UniqueConstraint("keyword_id", name="uq_douyin_track_keyword_single_track"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    track_id: uuid.UUID = Field(
        foreign_key="douyin_track.id", nullable=False, ondelete="CASCADE", index=True
    )
    keyword_id: uuid.UUID = Field(
        foreign_key="douyin_keyword.id", nullable=False, ondelete="CASCADE", index=True
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinTrackTaskLink(SQLModel, table=True):
    __tablename__ = "douyin_track_task_link"
    __table_args__ = (
        UniqueConstraint("track_id", "task_id", name="uq_douyin_track_task_link"),
        UniqueConstraint("task_id", name="uq_douyin_track_task_single_track"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    track_id: uuid.UUID = Field(
        foreign_key="douyin_track.id", nullable=False, ondelete="CASCADE", index=True
    )
    task_id: uuid.UUID = Field(
        foreign_key="crawl_task.id", nullable=False, ondelete="CASCADE", index=True
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinTrackCreate(SQLModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    prompt: str = Field(default="", max_length=10000)
    keywords: list[str] = Field(default_factory=list, max_length=200)


class DouyinTrackUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    prompt: str | None = Field(default=None, max_length=10000)
    enabled: bool | None = None


class DouyinTrackKeywordAdd(SQLModel):
    keywords: list[str] = Field(min_length=1, max_length=200)


class DouyinTrackTaskRequest(SQLModel):
    keyword_ids: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=200,
        description=(
            "本次运行选中的赛道关键词 ID；省略或传空数组时，运行该赛道全部已启用关键词"
        ),
    )
    mode: DouyinKeywordBatchMode = DouyinKeywordBatchMode.combined
    max_awemes: int = Field(default=30, ge=1, le=1000)
    fetch_comments: bool = True
    fetch_sub_comments: bool = False
    max_comments_per_aweme: int = Field(default=10, ge=1, le=1000)
    request_delay_level: DouyinRequestDelayLevel = DouyinRequestDelayLevel.steady
    publish_time: int = 0
    download_media: bool = False
    translate_subtitles: bool = False
    account_id: uuid.UUID | None = None
    account_pool_id: uuid.UUID | None = None
    account_strategy: DouyinAccountPoolStrategy = DouyinAccountPoolStrategy.least_loaded

    @model_validator(mode="after")
    def normalize_track_task(self) -> "DouyinTrackTaskRequest":
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
    id: uuid.UUID
    name: str
    description: str
    enabled: bool
    is_default: bool
    keyword_count: int
    enabled_keyword_count: int
    task_count: int
    active_task_count: int
    aweme_count: int
    comment_count: int
    last_task_id: uuid.UUID | None
    last_task_status: CrawlTaskStatus | None
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DouyinTrackDetailPublic(DouyinTrackPublic):
    prompt: str


class DouyinTracksPublic(SQLModel):
    data: list[DouyinTrackPublic]
    count: int


class DouyinTrackKeywordsPublic(SQLModel):
    data: list[DouyinKeywordPublic]
    count: int


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
