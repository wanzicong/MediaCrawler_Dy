"""Business models and schemas for this bounded context."""

import uuid
from datetime import datetime

from pydantic import SecretStr
from sqlalchemy import DateTime, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.domain.common.models import get_datetime_utc
from app.domain.douyin.accounts.models import DouyinBrowserMode
from app.domain.douyin.content.models import DouyinAwemePublic
from app.domain.douyin.tasks.models import CrawlTaskStatus, DouyinRequestDelayLevel


class DouyinComment(SQLModel, table=True):
    __tablename__ = "douyin_comment"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "comment_id", name="uq_douyin_comment_task_comment"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(
        foreign_key="crawl_task.id", nullable=False, ondelete="CASCADE", index=True
    )
    comment_id: str = Field(max_length=128, index=True)
    aweme_id: str = Field(max_length=128, index=True)
    parent_comment_id: str = Field(default="0", max_length=128)
    content: str = Field(default="", sa_type=Text)
    create_time: int | None = None
    creator_hash: str = Field(default="", max_length=64)
    sec_uid: str = Field(default="", max_length=256)
    nickname: str = Field(default="", max_length=255)
    sub_comment_count: int = 0
    like_count: int = 0
    pictures: str = Field(default="", sa_type=Text)
    fetched_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinCommentPublic(SQLModel):
    id: uuid.UUID
    task_id: uuid.UUID
    comment_id: str
    aweme_id: str
    parent_comment_id: str
    content: str
    create_time: int | None
    creator_hash: str
    sec_uid: str
    nickname: str
    sub_comment_count: int
    like_count: int
    pictures: str
    fetched_at: datetime


class DouyinCommentsPublic(SQLModel):
    data: list[DouyinCommentPublic]
    count: int


class DouyinCommentLibraryItemPublic(SQLModel):
    comment: DouyinCommentPublic
    aweme: DouyinAwemePublic
    task_status: CrawlTaskStatus
    task_created_at: datetime


class DouyinCommentLibrarySummaryPublic(SQLModel):
    matched_count: int
    top_level_count: int
    reply_count: int
    picture_count: int
    total_like_count: int


class DouyinCommentLibraryPublic(SQLModel):
    data: list[DouyinCommentLibraryItemPublic]
    count: int
    summary: DouyinCommentLibrarySummaryPublic


class DouyinCommentSelectionExportRequest(SQLModel):
    comment_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class DouyinAwemeCommentCrawlRequest(SQLModel):
    browser_mode: DouyinBrowserMode | None = None
    cookies: SecretStr | None = Field(default=None, repr=False)
    fetch_sub_comments: bool = False
    max_comments_per_aweme: int = Field(default=10, ge=1, le=1000)
    concurrency: int = Field(default=1, ge=1, le=5)
    request_delay_level: DouyinRequestDelayLevel = DouyinRequestDelayLevel.fast
    request_interval_seconds: float = Field(default=1.0, ge=0.2, le=60.0)
    account_id: uuid.UUID | None = None


class DouyinCommentExportRequest(SQLModel):
    aweme_ids: list[str] = Field(min_length=1, max_length=1000)


__all__ = [
    "DouyinComment",
    "DouyinCommentPublic",
    "DouyinCommentsPublic",
    "DouyinCommentLibraryItemPublic",
    "DouyinCommentLibrarySummaryPublic",
    "DouyinCommentLibraryPublic",
    "DouyinCommentSelectionExportRequest",
    "DouyinAwemeCommentCrawlRequest",
    "DouyinCommentExportRequest",
]
