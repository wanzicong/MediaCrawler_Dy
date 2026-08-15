"""Business models and schemas for this bounded context."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import SecretStr, model_validator
from sqlalchemy import BigInteger, DateTime, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.domain.common.models import get_datetime_utc


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
    track_id: uuid.UUID | None = None
    creator_hash: str | None = Field(default=None, max_length=64)
    tag_id: uuid.UUID | None = None
    subtitle_status: Literal["all", "pending", "running", "completed", "failed"] = "all"


class DouyinMediaMigrationAccepted(SQLModel):
    queued: int
    skipped: int
    message: str


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


__all__ = [
    "MediaProcessingMode",
    "MediaStorageBackend",
    "MediaDownloadStatus",
    "MediaMigrationStatus",
    "SubtitleStatus",
    "DouyinMediaProcessRequest",
    "DouyinMediaMigrationRequest",
    "DouyinLibraryMediaMigrationRequest",
    "DouyinMediaMigrationAccepted",
    "DouyinMediaAsset",
    "DouyinSubtitle",
    "DouyinSubtitlePublic",
    "DouyinMediaAssetPublic",
    "DouyinMediaAssetsPublic",
    "DouyinSubtitleExportFormat",
    "DouyinSubtitleExportRequest",
    "DouyinMediaSummaryPublic",
    "DouyinMediaRetryRequest",
]
