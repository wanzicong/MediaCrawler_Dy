import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import EmailStr, SecretStr, model_validator
from sqlalchemy import DateTime, Text, UniqueConstraint
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
    liked = "liked"
    collected = "collected"


class DouyinLoginType(str, Enum):
    qrcode = "qrcode"
    cookie = "cookie"


class CrawlTaskStatus(str, Enum):
    queued = "queued"
    waiting_login = "waiting_login"
    running = "running"
    cancelling = "cancelling"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    interrupted = "interrupted"


class CrawlTaskCreate(SQLModel):
    crawl_type: DouyinCrawlType = DouyinCrawlType.search
    login_type: DouyinLoginType = DouyinLoginType.qrcode
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
    request_interval_seconds: float = Field(default=1.0, ge=0.2, le=60.0)
    publish_time: int = 0

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
        if self.publish_time not in {0, 1, 7, 180}:
            raise ValueError("publish_time 只能是 0、1、7 或 180")
        if not self.fetch_comments:
            self.fetch_sub_comments = False
        return self

    def public_request(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"cookies"})


class CrawlTask(SQLModel, table=True):
    __tablename__ = "crawl_task"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    crawl_type: str = Field(max_length=32, index=True)
    status: str = Field(default=CrawlTaskStatus.queued.value, max_length=32, index=True)
    request_json: str = Field(sa_type=Text)
    aweme_count: int = 0
    comment_count: int = 0
    action_count: int = 0
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


class CrawlTaskPublic(SQLModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    crawl_type: DouyinCrawlType
    status: CrawlTaskStatus
    request: dict[str, object]
    aweme_count: int
    comment_count: int
    action_count: int
    error: str | None
    has_qrcode: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class CrawlTasksPublic(SQLModel):
    data: list[CrawlTaskPublic]
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
