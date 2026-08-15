"""Business models and schemas for this bounded context."""

import uuid
from datetime import date, datetime
from enum import Enum

from sqlalchemy import DateTime, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.domain.common.models import get_datetime_utc


class DouyinBrowserMode(str, Enum):
    local = "local"
    remote = "remote"


class DouyinAccountStatus(str, Enum):
    login_required = "login_required"
    verifying = "verifying"
    ready = "ready"
    busy = "busy"
    cooldown = "cooldown"
    unhealthy = "unhealthy"
    disabled = "disabled"


class DouyinAccountPoolStrategy(str, Enum):
    least_loaded = "least_loaded"
    round_robin = "round_robin"
    weighted_round_robin = "weighted_round_robin"


class DouyinAccountCreate(SQLModel):
    name: str = Field(min_length=1, max_length=80)
    browser_mode: DouyinBrowserMode = DouyinBrowserMode.remote
    remote_slot: str | None = Field(default=None, max_length=64)
    weight: int = Field(default=1, ge=1, le=100)
    priority: int = Field(default=0, ge=-100, le=100)
    concurrency_limit: int = Field(default=1, ge=1, le=3)
    daily_task_limit: int = Field(default=100, ge=1, le=10000)
    min_request_interval_seconds: float = Field(default=1.0, ge=0.2, le=60.0)


class DouyinAccountUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    remote_slot: str | None = Field(default=None, max_length=64)
    weight: int | None = Field(default=None, ge=1, le=100)
    priority: int | None = Field(default=None, ge=-100, le=100)
    concurrency_limit: int | None = Field(default=None, ge=1, le=3)
    daily_task_limit: int | None = Field(default=None, ge=1, le=10000)
    min_request_interval_seconds: float | None = Field(default=None, ge=0.2, le=60.0)
    enabled: bool | None = None


class DouyinAccount(SQLModel, table=True):
    __tablename__ = "douyin_account"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_douyin_account_owner_name"),
        UniqueConstraint(
            "owner_id", "profile_key", name="uq_douyin_account_owner_profile"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    name: str = Field(max_length=80, index=True)
    browser_mode: str = Field(
        default=DouyinBrowserMode.remote.value, max_length=16, index=True
    )
    profile_key: str = Field(max_length=64)
    remote_slot: str | None = Field(default=None, max_length=64, index=True)
    status: str = Field(
        default=DouyinAccountStatus.login_required.value,
        max_length=32,
        index=True,
    )
    identity_hash: str = Field(default="", max_length=64)
    weight: int = Field(default=1, ge=1, le=100)
    priority: int = Field(default=0, ge=-100, le=100)
    concurrency_limit: int = Field(default=1, ge=1, le=3)
    daily_task_limit: int = Field(default=100, ge=1, le=10000)
    tasks_today: int = Field(default=0, ge=0)
    usage_date: date = Field(default_factory=date.today)
    min_request_interval_seconds: float = Field(default=1.0)
    active_leases: int = Field(default=0, ge=0)
    failure_streak: int = Field(default=0, ge=0)
    cooldown_until: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    last_verified_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    last_used_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    last_error: str | None = Field(default=None, sa_type=Text)
    enabled: bool = Field(default=True, index=True)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinAccountPublic(SQLModel):
    id: uuid.UUID
    name: str
    browser_mode: DouyinBrowserMode
    remote_slot: str | None
    status: DouyinAccountStatus
    is_logged_in: bool
    weight: int
    priority: int
    concurrency_limit: int
    daily_task_limit: int
    tasks_today: int
    min_request_interval_seconds: float
    active_leases: int
    failure_streak: int
    cooldown_until: datetime | None
    last_verified_at: datetime | None
    last_used_at: datetime | None
    last_error: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class DouyinAccountsPublic(SQLModel):
    data: list[DouyinAccountPublic]
    count: int


class DouyinBrowserSlotPublic(SQLModel):
    name: str | None
    label: str
    is_default: bool
    available: bool
    configured: bool
    viewer_available: bool
    viewer_url: str | None
    cdp_healthy: bool
    page_count: int
    active_page_title: str | None
    active_page_url: str | None
    latency_ms: int | None
    checked_at: datetime
    occupied_account_id: uuid.UUID | None
    occupied_account_name: str | None


class DouyinBrowserSlotsPublic(SQLModel):
    data: list[DouyinBrowserSlotPublic]
    count: int


class DouyinAccountPoolCreate(SQLModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    strategy: DouyinAccountPoolStrategy = DouyinAccountPoolStrategy.least_loaded
    max_parallel_accounts: int = Field(default=2, ge=1, le=20)
    account_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class DouyinAccountPoolUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    strategy: DouyinAccountPoolStrategy | None = None
    max_parallel_accounts: int | None = Field(default=None, ge=1, le=20)
    account_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)
    enabled: bool | None = None


class DouyinAccountPool(SQLModel, table=True):
    __tablename__ = "douyin_account_pool"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_douyin_account_pool_owner_name"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    name: str = Field(max_length=80, index=True)
    description: str = Field(default="", max_length=500)
    strategy: str = Field(
        default=DouyinAccountPoolStrategy.least_loaded.value, max_length=32
    )
    max_parallel_accounts: int = Field(default=2, ge=1, le=20)
    rotation_cursor: int = Field(default=0, ge=0)
    enabled: bool = Field(default=True, index=True)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinAccountPoolMember(SQLModel, table=True):
    __tablename__ = "douyin_account_pool_member"
    __table_args__ = (
        UniqueConstraint("pool_id", "account_id", name="uq_douyin_account_pool_member"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pool_id: uuid.UUID = Field(
        foreign_key="douyin_account_pool.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    account_id: uuid.UUID = Field(
        foreign_key="douyin_account.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinAccountPoolPublic(SQLModel):
    id: uuid.UUID
    name: str
    description: str
    strategy: DouyinAccountPoolStrategy
    max_parallel_accounts: int
    enabled: bool
    accounts: list[DouyinAccountPublic]
    created_at: datetime
    updated_at: datetime


class DouyinAccountPoolsPublic(SQLModel):
    data: list[DouyinAccountPoolPublic]
    count: int


class DouyinAccountLoginSessionPublic(SQLModel):
    account: DouyinAccountPublic
    status: DouyinAccountStatus
    browser_mode: DouyinBrowserMode
    viewer_url: str | None
    expires_at: datetime
    message: str


__all__ = [
    "DouyinBrowserMode",
    "DouyinAccountStatus",
    "DouyinAccountPoolStrategy",
    "DouyinAccountCreate",
    "DouyinAccountUpdate",
    "DouyinAccount",
    "DouyinAccountPublic",
    "DouyinAccountsPublic",
    "DouyinBrowserSlotPublic",
    "DouyinBrowserSlotsPublic",
    "DouyinAccountPoolCreate",
    "DouyinAccountPoolUpdate",
    "DouyinAccountPool",
    "DouyinAccountPoolMember",
    "DouyinAccountPoolPublic",
    "DouyinAccountPoolsPublic",
    "DouyinAccountLoginSessionPublic",
]
