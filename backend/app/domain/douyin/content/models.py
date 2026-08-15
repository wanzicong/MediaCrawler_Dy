"""Business models and schemas for this bounded context."""

import uuid
from datetime import datetime

from pydantic import SecretStr, model_validator
from sqlalchemy import DateTime, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.domain.common.models import get_datetime_utc
from app.domain.douyin.accounts.models import DouyinBrowserMode
from app.domain.douyin.tasks.models import DouyinRequestDelayLevel


class DouyinAweme(SQLModel, table=True):
    __tablename__ = "douyin_aweme"
    __table_args__ = (
        UniqueConstraint("task_id", "aweme_id", name="uq_douyin_aweme_task_aweme"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(
        foreign_key="crawl_task.id", nullable=False, ondelete="CASCADE", index=True
    )
    aweme_id: str = Field(max_length=128, index=True)
    aweme_type: str = Field(default="", max_length=32)
    title: str = Field(default="", sa_type=Text)
    description: str = Field(default="", sa_type=Text)
    create_time: int | None = None
    creator_hash: str = Field(default="", max_length=64)
    sec_uid: str = Field(default="", max_length=256)
    nickname: str = Field(default="", max_length=255)
    liked_count: int = 0
    collected_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    aweme_url: str = Field(default="", sa_type=Text)
    cover_url: str = Field(default="", sa_type=Text)
    video_download_url: str = Field(default="", sa_type=Text)
    music_download_url: str = Field(default="", sa_type=Text)
    note_download_url: str = Field(default="", sa_type=Text)
    source_keyword: str = Field(default="", max_length=512)
    fetched_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinAwemePublic(SQLModel):
    id: uuid.UUID
    task_id: uuid.UUID
    aweme_id: str
    aweme_type: str
    title: str
    description: str
    create_time: int | None
    creator_hash: str
    sec_uid: str
    nickname: str
    liked_count: int
    collected_count: int
    comment_count: int
    share_count: int
    aweme_url: str
    cover_url: str
    video_download_url: str
    music_download_url: str
    note_download_url: str
    source_keyword: str
    fetched_at: datetime


class DouyinAwemesPublic(SQLModel):
    data: list[DouyinAwemePublic]
    count: int


class DouyinUserAction(SQLModel, table=True):
    __tablename__ = "douyin_user_action"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "account_hash",
            "aweme_id",
            "action_type",
            name="uq_douyin_action_task_account_aweme_type",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(
        foreign_key="crawl_task.id", nullable=False, ondelete="CASCADE", index=True
    )
    account_hash: str = Field(max_length=64)
    aweme_id: str = Field(max_length=128, index=True)
    action_type: str = Field(max_length=32, index=True)
    observed_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinUserActionPublic(SQLModel):
    id: uuid.UUID
    task_id: uuid.UUID
    account_hash: str
    aweme_id: str
    action_type: str
    observed_at: datetime


class DouyinUserActionsPublic(SQLModel):
    data: list[DouyinUserActionPublic]
    count: int


class DouyinAwemeCreatorCrawlRequest(SQLModel):
    browser_mode: DouyinBrowserMode | None = None
    cookies: SecretStr | None = Field(default=None, repr=False)
    max_awemes: int = Field(default=20, ge=1, le=1000)
    fetch_comments: bool = False
    fetch_sub_comments: bool = False
    max_comments_per_aweme: int = Field(default=10, ge=1, le=1000)
    concurrency: int = Field(default=1, ge=1, le=5)
    request_delay_level: DouyinRequestDelayLevel = DouyinRequestDelayLevel.fast
    request_interval_seconds: float = Field(default=1.0, ge=0.2, le=60.0)
    account_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def normalize_creator_options(self) -> "DouyinAwemeCreatorCrawlRequest":
        if not self.fetch_comments:
            self.fetch_sub_comments = False
        return self


class DouyinCreatorOptionPublic(SQLModel):
    creator_hash: str
    nickname: str
    work_count: int


class DouyinCreatorOptionsPublic(SQLModel):
    data: list[DouyinCreatorOptionPublic]
    count: int


__all__ = [
    "DouyinAweme",
    "DouyinAwemePublic",
    "DouyinAwemesPublic",
    "DouyinUserAction",
    "DouyinUserActionPublic",
    "DouyinUserActionsPublic",
    "DouyinAwemeCreatorCrawlRequest",
    "DouyinCreatorOptionPublic",
    "DouyinCreatorOptionsPublic",
]
