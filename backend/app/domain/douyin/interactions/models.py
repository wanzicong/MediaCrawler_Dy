"""Business models and schemas for this bounded context."""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import SecretStr, model_validator
from sqlalchemy import DateTime, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.domain.common.models import get_datetime_utc


class DouyinInteractionType(str, Enum):
    video_comment = "video_comment"
    comment_reply = "comment_reply"
    creator_message = "creator_message"


class DouyinInteractionStatus(str, Enum):
    pending_confirmation = "pending_confirmation"
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    blocked = "blocked"
    needs_review = "needs_review"
    cancelled = "cancelled"


class DouyinInteractionCreate(SQLModel):
    task_id: uuid.UUID
    aweme_id: str = Field(min_length=1, max_length=128)
    account_id: uuid.UUID
    interaction_type: DouyinInteractionType
    target_comment_id: str | None = Field(default=None, max_length=128)
    content: SecretStr = Field(min_length=1, max_length=2200, repr=False)

    @model_validator(mode="after")
    def validate_target(self) -> "DouyinInteractionCreate":
        content = self.content.get_secret_value().strip()
        if not content:
            raise ValueError("互动内容不能为空")
        if (
            self.interaction_type == DouyinInteractionType.comment_reply
            and not self.target_comment_id
        ):
            raise ValueError("回复评论必须指定目标评论")
        if (
            self.interaction_type != DouyinInteractionType.comment_reply
            and self.target_comment_id
        ):
            raise ValueError("只有回复评论可以指定目标评论")
        return self


class DouyinInteractionPreflightPublic(SQLModel):
    allowed: bool
    failure_code: str | None = None
    message: str
    account_name: str
    remaining_daily_quota: int
    cooldown_until: datetime | None = None
    duplicate_interaction_id: uuid.UUID | None = None


class DouyinInteractionRetryRequest(SQLModel):
    confirm_not_sent: bool = False


class DouyinInteraction(SQLModel, table=True):
    __tablename__ = "douyin_interaction"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key", name="uq_douyin_interaction_idempotency_key"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
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
    account_name: str = Field(default="", max_length=80)
    aweme_id: str = Field(max_length=128, index=True)
    target_comment_id: str | None = Field(default=None, max_length=128, index=True)
    interaction_type: str = Field(max_length=32, index=True)
    content_encrypted: str = Field(sa_type=Text, repr=False)
    content_preview: str = Field(default="", max_length=160)
    content_hash: str = Field(max_length=64)
    idempotency_key: str = Field(max_length=64, index=True)
    status: str = Field(
        default=DouyinInteractionStatus.pending_confirmation.value,
        max_length=32,
        index=True,
    )
    failure_code: str | None = Field(default=None, max_length=64, index=True)
    error: str | None = Field(default=None, sa_type=Text)
    attempt_count: int = Field(default=0, ge=0)
    result_platform_id: str | None = Field(default=None, max_length=128)
    human_confirmed_at: datetime | None = Field(
        default=None,
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
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinInteractionEvent(SQLModel, table=True):
    __tablename__ = "douyin_interaction_event"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    interaction_id: uuid.UUID = Field(
        foreign_key="douyin_interaction.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    event: str = Field(max_length=64, index=True)
    from_status: str | None = Field(default=None, max_length=32)
    to_status: str = Field(max_length=32)
    detail: str | None = Field(default=None, max_length=1000)
    attempt_number: int = Field(default=0, ge=0)
    screenshot_path: str | None = Field(default=None, max_length=500, repr=False)
    screenshot_mime_type: str | None = Field(default=None, max_length=64)
    screenshot_size: int | None = Field(default=None, ge=0)
    screenshot_sha256: str | None = Field(default=None, max_length=64, repr=False)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinInteractionEventPublic(SQLModel):
    id: uuid.UUID
    event: str
    from_status: DouyinInteractionStatus | None
    to_status: DouyinInteractionStatus
    detail: str | None
    attempt_number: int
    has_screenshot: bool
    created_at: datetime


class DouyinInteractionPublic(SQLModel):
    id: uuid.UUID
    task_id: uuid.UUID
    account_id: uuid.UUID | None
    account_name: str
    aweme_id: str
    target_video_url: str
    target_comment_id: str | None
    target_comment_content: str | None
    interaction_type: DouyinInteractionType
    content_preview: str
    status: DouyinInteractionStatus
    failure_code: str | None
    error: str | None
    attempt_count: int
    result_platform_id: str | None
    human_confirmed_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    can_confirm: bool
    can_retry: bool
    can_cancel: bool


class DouyinInteractionDetailPublic(DouyinInteractionPublic):
    content: str
    events: list[DouyinInteractionEventPublic]


class DouyinInteractionsPublic(SQLModel):
    data: list[DouyinInteractionPublic]
    count: int


class DouyinInteractionQuotaPublic(SQLModel):
    account_id: uuid.UUID
    account_name: str
    daily_limit: int
    used_today: int
    remaining_today: int
    min_interval_seconds: float
    cooldown_until: datetime | None
    available: bool


__all__ = [
    "DouyinInteractionType",
    "DouyinInteractionStatus",
    "DouyinInteractionCreate",
    "DouyinInteractionPreflightPublic",
    "DouyinInteractionRetryRequest",
    "DouyinInteraction",
    "DouyinInteractionEvent",
    "DouyinInteractionEventPublic",
    "DouyinInteractionPublic",
    "DouyinInteractionDetailPublic",
    "DouyinInteractionsPublic",
    "DouyinInteractionQuotaPublic",
]
