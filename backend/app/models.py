import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import EmailStr, SecretStr, model_validator
from sqlalchemy import BigInteger, DateTime, Text, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    items: list["Item"] = Relationship(back_populates="owner", cascade_delete=True)


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# Shared properties
class ItemBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Properties to receive on item creation
class ItemCreate(ItemBase):
    pass


# Properties to receive on item update
class ItemUpdate(ItemBase):
    title: str | None = Field(default=None, min_length=1, max_length=255)  # type: ignore


# Database model, database table inferred from class name
class Item(ItemBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="items")


# Properties to return via API, id is always required
class ItemPublic(ItemBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime | None = None


class ItemsPublic(SQLModel):
    data: list[ItemPublic]
    count: int


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


class CrawlTaskShardStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    interrupted = "interrupted"
    cancelled = "cancelled"


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
    min_request_interval_seconds: float | None = Field(
        default=None, ge=0.2, le=60.0
    )
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
        UniqueConstraint(
            "pool_id", "account_id", name="uq_douyin_account_pool_member"
        ),
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


class DouyinRequestDelayLevel(str, Enum):
    fast = "fast"
    steady = "steady"
    ultra_steady = "ultra_steady"


class MediaProcessingMode(str, Enum):
    none = "none"
    immediate = "immediate"
    batch = "batch"


class MediaStorageBackend(str, Enum):
    local = "local"
    minio = "minio"


class MediaDownloadStatus(str, Enum):
    queued = "queued"
    downloading = "downloading"
    downloaded = "downloaded"
    failed = "failed"


class MediaMigrationStatus(str, Enum):
    idle = "idle"
    queued = "queued"
    uploading = "uploading"
    verifying = "verifying"
    switching = "switching"
    cleanup_pending = "cleanup_pending"
    completed = "completed"
    failed = "failed"


class SubtitleStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class CrawlTaskCreate(SQLModel):
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
        if self.download_media and self.media_processing_mode == MediaProcessingMode.none:
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


class DouyinMediaProcessRequest(SQLModel):
    media_storage: MediaStorageBackend | None = None
    translate_subtitles: bool = False
    force_retranslate: bool = False
    transcription_language: str = Field(default="auto", min_length=2, max_length=32)
    cookies: SecretStr | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def normalize_translation(self) -> "DouyinMediaProcessRequest":
        if self.force_retranslate:
            self.translate_subtitles = True
        return self


class DouyinMediaMigrationRequest(SQLModel):
    asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)


class DouyinLibraryMediaMigrationRequest(SQLModel):
    search: str | None = Field(default=None, max_length=200)
    task_id: uuid.UUID | None = None
    creator_hash: str | None = Field(default=None, max_length=64)
    tag_id: uuid.UUID | None = None
    subtitle_status: Literal[
        "all", "pending", "running", "completed", "failed"
    ] = "all"


class DouyinMediaMigrationAccepted(SQLModel):
    queued: int
    skipped: int
    message: str


class DouyinAwemeCommentCrawlRequest(SQLModel):
    browser_mode: DouyinBrowserMode | None = None
    cookies: SecretStr | None = Field(default=None, repr=False)
    fetch_sub_comments: bool = False
    max_comments_per_aweme: int = Field(default=10, ge=1, le=1000)
    concurrency: int = Field(default=1, ge=1, le=5)
    request_delay_level: DouyinRequestDelayLevel = DouyinRequestDelayLevel.fast
    request_interval_seconds: float = Field(default=1.0, ge=0.2, le=60.0)
    account_id: uuid.UUID | None = None


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


class CrawlTask(SQLModel, table=True):
    __tablename__ = "crawl_task"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
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
    account_id: uuid.UUID | None
    account_pool_id: uuid.UUID | None
    account_strategy: DouyinAccountPoolStrategy
    crawl_type: DouyinCrawlType
    status: CrawlTaskStatus
    request: dict[str, object]
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


class DouyinKeyword(SQLModel, table=True):
    __tablename__ = "douyin_keyword"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "normalized_keyword", name="uq_douyin_keyword_owner_value"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
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
        UniqueConstraint(
            "keyword_id", "task_id", name="uq_douyin_keyword_task_link"
        ),
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
    source: str = Field(
        default=DouyinKeywordSyncSource.automatic.value, max_length=32
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinKeywordPublic(SQLModel):
    id: uuid.UUID
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
    enabled: bool | None = None
    notes: str | None = Field(default=None, max_length=1000)


class DouyinKeywordSyncResult(SQLModel):
    task_count: int
    keyword_count: int
    created_count: int
    binding_count: int


class DouyinKeywordBatchTaskRequest(SQLModel):
    keyword_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
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
        if self.download_media and self.media_processing_mode == MediaProcessingMode.none:
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


class DouyinTrack(SQLModel, table=True):
    __tablename__ = "douyin_track"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "normalized_name", name="uq_douyin_track_owner_name"
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
        UniqueConstraint(
            "track_id", "keyword_id", name="uq_douyin_track_keyword_link"
        ),
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
    keyword_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
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


class DouyinTag(SQLModel, table=True):
    __tablename__ = "douyin_tag"
    __table_args__ = (
        UniqueConstraint("owner_id", "normalized_name", name="uq_douyin_tag_owner_name"),
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


class DouyinAwemesPublic(SQLModel):
    data: list[DouyinAwemePublic]
    count: int


class DouyinComment(SQLModel, table=True):
    __tablename__ = "douyin_comment"
    __table_args__ = (
        UniqueConstraint("task_id", "comment_id", name="uq_douyin_comment_task_comment"),
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


class DouyinMediaAsset(SQLModel, table=True):
    __tablename__ = "douyin_media_asset"
    __table_args__ = (
        UniqueConstraint("task_id", "aweme_id", name="uq_douyin_media_task_aweme"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(
        foreign_key="crawl_task.id", nullable=False, ondelete="CASCADE", index=True
    )
    aweme_id: str = Field(max_length=128, index=True)
    source_url: str = Field(default="", sa_type=Text)
    local_path: str = Field(default="", sa_type=Text)
    storage_backend: str = Field(
        default=MediaStorageBackend.local.value, max_length=32, index=True
    )
    storage_bucket: str = Field(default="", max_length=255)
    object_key: str = Field(default="", sa_type=Text)
    status: str = Field(
        default=MediaDownloadStatus.queued.value, max_length=32, index=True
    )
    progress: int = Field(default=0, ge=0, le=100)
    attempt_count: int = 0
    mime_type: str = Field(default="", max_length=255)
    file_size: int = Field(default=0, sa_type=BigInteger)
    sha256: str = Field(default="", max_length=64)
    error: str | None = Field(default=None, sa_type=Text)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    migration_status: str = Field(
        default=MediaMigrationStatus.idle.value, max_length=32, index=True
    )
    migration_progress: int = Field(default=0, ge=0, le=100)
    migration_attempt_count: int = 0
    migration_error: str | None = Field(default=None, sa_type=Text)
    migration_started_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    migration_finished_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinSubtitle(SQLModel, table=True):
    __tablename__ = "douyin_subtitle"
    __table_args__ = (UniqueConstraint("asset_id", name="uq_douyin_subtitle_asset"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    asset_id: uuid.UUID = Field(
        foreign_key="douyin_media_asset.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    task_id: uuid.UUID = Field(
        foreign_key="crawl_task.id", nullable=False, ondelete="CASCADE", index=True
    )
    aweme_id: str = Field(max_length=128, index=True)
    status: str = Field(default=SubtitleStatus.pending.value, max_length=32, index=True)
    progress: int = Field(default=0, ge=0, le=100)
    attempt_count: int = 0
    requested_backend: str = Field(default="api", max_length=32)
    actual_backend: str = Field(default="", max_length=32)
    model: str = Field(default="", max_length=255)
    language: str = Field(default="", max_length=32)
    duration_seconds: float = 0.0
    full_text: str = Field(default="", sa_type=Text)
    segments_json: str = Field(default="[]", sa_type=Text)
    error: str | None = Field(default=None, sa_type=Text)
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


class DouyinSubtitlePublic(SQLModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    task_id: uuid.UUID
    aweme_id: str
    status: SubtitleStatus
    progress: int
    attempt_count: int
    requested_backend: str
    actual_backend: str
    model: str
    language: str
    duration_seconds: float
    full_text: str
    segments: list[dict[str, object]]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class DouyinMediaAssetPublic(SQLModel):
    id: uuid.UUID
    task_id: uuid.UUID
    aweme_id: str
    storage_backend: MediaStorageBackend
    status: MediaDownloadStatus
    progress: int
    attempt_count: int
    mime_type: str
    file_size: int
    sha256: str
    error: str | None
    download_available: bool
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    migration_status: MediaMigrationStatus
    migration_progress: int
    migration_attempt_count: int
    migration_error: str | None
    migration_started_at: datetime | None
    migration_finished_at: datetime | None
    subtitle: DouyinSubtitlePublic | None


class DouyinMediaAssetsPublic(SQLModel):
    data: list[DouyinMediaAssetPublic]
    count: int


class DouyinWorkPublic(SQLModel):
    aweme: DouyinAwemePublic
    persisted_comment_count: int
    media: DouyinMediaAssetPublic | None
    tags: list[DouyinTagRefPublic] = Field(default_factory=list)


class DouyinWorksPublic(SQLModel):
    data: list[DouyinWorkPublic]
    count: int


class DouyinCreatorOptionPublic(SQLModel):
    creator_hash: str
    nickname: str
    work_count: int


class DouyinCreatorOptionsPublic(SQLModel):
    data: list[DouyinCreatorOptionPublic]
    count: int


class DouyinCommentExportRequest(SQLModel):
    aweme_ids: list[str] = Field(min_length=1, max_length=1000)


class DouyinSubtitleExportFormat(str, Enum):
    txt = "txt"
    srt = "srt"
    vtt = "vtt"


class DouyinSubtitleExportRequest(SQLModel):
    aweme_ids: list[str] = Field(min_length=1, max_length=1000)
    format: DouyinSubtitleExportFormat = DouyinSubtitleExportFormat.srt


class DouyinMediaSummaryPublic(SQLModel):
    total: int
    queued: int
    downloading: int
    downloaded: int
    download_failed: int
    subtitle_pending: int
    subtitle_running: int
    subtitle_completed: int
    subtitle_failed: int
    local_downloaded: int
    minio_downloaded: int
    migration_queued: int
    migration_running: int
    migration_cleanup_pending: int
    migration_completed: int
    migration_failed: int


class DouyinMediaRetryRequest(SQLModel):
    asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)
    retry_downloads: bool = True
    retry_subtitles: bool = True
    force_retranslate: bool = False


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class ApiOperationDocPublic(SQLModel):
    method: str
    path: str
    summary: str
    description: str
    operation_id: str
    tags: list[str]
    auth_required: bool
    parameters: list[dict[str, Any]]
    request_body: dict[str, Any] | None
    response_codes: list[str]


class McpToolDocPublic(SQLModel):
    name: str
    title: str | None
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None


class IntegrationDocsPublic(SQLModel):
    api_title: str
    api_version: str
    api_openapi_url: str
    api_swagger_url: str
    api_operations: list[ApiOperationDocPublic]
    api_operation_count: int
    mcp_server_name: str
    mcp_streamable_http_url: str
    mcp_health_url: str
    mcp_stdio_command: str
    mcp_http_command: str
    mcp_tools: list[McpToolDocPublic]
    mcp_tool_count: int
