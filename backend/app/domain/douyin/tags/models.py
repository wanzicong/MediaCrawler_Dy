"""Business models and schemas for this bounded context."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.domain.common.models import get_datetime_utc


class DouyinTag(SQLModel, table=True):
    __tablename__ = "douyin_tag"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "normalized_name", name="uq_douyin_tag_owner_name"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    name: str = Field(max_length=100, index=True)
    normalized_name: str = Field(max_length=100)
    last_seen_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinAwemeTag(SQLModel, table=True):
    __tablename__ = "douyin_aweme_tag"
    __table_args__ = (
        UniqueConstraint(
            "aweme_record_id", "tag_id", name="uq_douyin_aweme_tag_record_tag"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    aweme_record_id: uuid.UUID = Field(
        foreign_key="douyin_aweme.id", nullable=False, ondelete="CASCADE", index=True
    )
    tag_id: uuid.UUID = Field(
        foreign_key="douyin_tag.id", nullable=False, ondelete="CASCADE", index=True
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinTagRefPublic(SQLModel):
    id: uuid.UUID
    name: str


class DouyinTagPublic(DouyinTagRefPublic):
    aweme_count: int
    task_count: int
    last_seen_at: datetime
    created_at: datetime


class DouyinTagsPublic(SQLModel):
    data: list[DouyinTagPublic]
    count: int


class DouyinTagSyncResult(SQLModel):
    aweme_count: int
    tag_count: int
    created_count: int
    binding_count: int


__all__ = [
    "DouyinTag",
    "DouyinAwemeTag",
    "DouyinTagRefPublic",
    "DouyinTagPublic",
    "DouyinTagsPublic",
    "DouyinTagSyncResult",
]
