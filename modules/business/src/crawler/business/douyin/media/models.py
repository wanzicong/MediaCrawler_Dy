"""抖音媒体限界上下文的业务模型：状态枚举、SQLModel 表模型与对外视图 schema。"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Literal

from crawler.business.common.models import get_datetime_utc
from pydantic import SecretStr, model_validator
from sqlalchemy import BigInteger, DateTime, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class MediaProcessingMode(str, Enum):
    """媒体处理模式：控制采集任务中媒体下载/字幕处理的触发方式。"""

    none = "none"  # 不做媒体处理
    immediate = "immediate"  # 采集到作品后立即处理
    batch = "batch"  # 任务完成后批量处理


class MediaStorageBackend(str, Enum):
    """媒体存储后端。"""

    local = "local"  # 本地磁盘存储
    minio = "minio"  # MinIO 对象存储


class MediaDownloadStatus(str, Enum):
    """媒体资产下载状态机。"""

    queued = "queued"  # 已排队等待下载
    downloading = "downloading"  # 正在下载
    downloaded = "downloaded"  # 下载完成
    failed = "failed"  # 下载失败


class MediaMigrationStatus(str, Enum):
    """本地到 MinIO 的单向迁移状态机。"""

    idle = "idle"  # 未发起迁移
    queued = "queued"  # 已加入迁移队列
    uploading = "uploading"  # 正在上传到 MinIO
    verifying = "verifying"  # 正在校验远端副本完整性
    switching = "switching"  # 正在把资产记录切换到 MinIO 存储
    cleanup_pending = "cleanup_pending"  # 已切换，等待清理本地副本
    completed = "completed"  # 迁移完成
    failed = "failed"  # 迁移失败


class SubtitleStatus(str, Enum):
    """字幕转写状态机。"""

    pending = "pending"  # 等待转写
    running = "running"  # 正在转写
    completed = "completed"  # 转写完成
    failed = "failed"  # 转写失败


class DouyinMediaProcessRequest(SQLModel):
    """触发任务媒体处理（下载与可选字幕转写）的请求体。"""

    media_storage: MediaStorageBackend | None = (
        None  # 目标存储后端，None 表示使用系统默认配置
    )
    translate_subtitles: bool = False  # 下载完成后是否调用远程字幕 API 转写字幕
    force_retranslate: bool = False  # 是否强制重新转写（隐含开启 translate_subtitles）
    transcription_language: str = Field(
        default="auto", min_length=2, max_length=32
    )  # 转写语言，auto 表示自动识别
    cookies: SecretStr | None = Field(
        default=None, repr=False
    )  # 可选抖音 cookie，用于访问受限媒体资源

    @model_validator(mode="after")
    def normalize_translation(self) -> "DouyinMediaProcessRequest":
        """强制重译时自动开启字幕转写。"""
        if self.force_retranslate:
            self.translate_subtitles = True
        return self


class DouyinMediaMigrationRequest(SQLModel):
    """按资产 ID 列表触发本地到 MinIO 迁移的请求体。"""

    asset_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=1000
    )  # 待迁移的资产 ID 列表，为空表示任务内全部候选资产


class DouyinLibraryMediaMigrationRequest(SQLModel):
    """按媒体库筛选条件批量触发本地到 MinIO 迁移的请求体。"""

    search: str | None = Field(default=None, max_length=200)  # 关键词搜索
    task_id: uuid.UUID | None = None  # 限定采集任务
    track_id: uuid.UUID | None = None  # 限定关联的追踪对象
    creator_hash: str | None = Field(default=None, max_length=64)  # 限定创作者哈希
    tag_id: uuid.UUID | None = None  # 限定标签
    subtitle_status: Literal["all", "pending", "running", "completed", "failed"] = (
        "all"  # 按字幕状态筛选，all 表示不过滤
    )


class DouyinMediaMigrationAccepted(SQLModel):
    """迁移请求受理结果。"""

    queued: int  # 本次实际加入迁移队列的资产数
    skipped: int  # 因状态不符合或已在队列中而跳过的资产数
    message: str  # 面向用户的提示信息


class DouyinMediaAsset(SQLModel, table=True):
    """抖音媒体资产表：记录单个作品视频的下载状态、存储位置与迁移状态。"""

    __tablename__ = "douyin_media_asset"
    __table_args__ = (
        UniqueConstraint("task_id", "aweme_id", name="uq_douyin_media_task_aweme"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)  # 资产主键
    # 所属采集任务 ID，任务删除时级联删除
    task_id: uuid.UUID = Field(
        foreign_key="crawl_task.id", nullable=False, ondelete="CASCADE", index=True
    )
    aweme_id: str = Field(max_length=128, index=True)  # 抖音作品 ID
    source_url: str = Field(default="", sa_type=Text)  # 视频源下载地址
    local_path: str = Field(
        default="", sa_type=Text
    )  # 本地文件路径（local 后端时有效）
    # 存储后端：local / minio，见 MediaStorageBackend
    storage_backend: str = Field(
        default=MediaStorageBackend.local.value, max_length=32, index=True
    )
    storage_bucket: str = Field(default="", max_length=255)  # MinIO bucket 名称
    object_key: str = Field(default="", sa_type=Text)  # MinIO 对象 key
    # 下载状态，见 MediaDownloadStatus
    status: str = Field(
        default=MediaDownloadStatus.queued.value, max_length=32, index=True
    )
    progress: int = Field(default=0, ge=0, le=100)  # 下载进度（0-100）
    attempt_count: int = 0  # 下载尝试次数
    mime_type: str = Field(default="", max_length=255)  # 媒体 MIME 类型
    file_size: int = Field(default=0, sa_type=BigInteger)  # 文件大小（字节）
    sha256: str = Field(default="", max_length=64)  # 文件内容 SHA-256 摘要
    error: str | None = Field(default=None, sa_type=Text)  # 最近一次下载失败原因
    # 记录创建时间（UTC）
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    # 记录最近更新时间（UTC）
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    # 下载完成时间（UTC），未完成为 None
    completed_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    # 迁移状态，见 MediaMigrationStatus
    migration_status: str = Field(
        default=MediaMigrationStatus.idle.value, max_length=32, index=True
    )
    migration_progress: int = Field(default=0, ge=0, le=100)  # 迁移进度（0-100）
    migration_attempt_count: int = 0  # 迁移尝试次数
    migration_error: str | None = Field(
        default=None, sa_type=Text
    )  # 最近一次迁移失败原因
    # 迁移开始时间（UTC）
    migration_started_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    # 迁移结束时间（UTC）
    migration_finished_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinSubtitle(SQLModel, table=True):
    """抖音字幕表：记录媒体资产的字幕转写状态与结果（每个资产至多一条）。"""

    __tablename__ = "douyin_subtitle"
    __table_args__ = (UniqueConstraint("asset_id", name="uq_douyin_subtitle_asset"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)  # 字幕记录主键
    # 关联的媒体资产 ID，资产删除时级联删除
    asset_id: uuid.UUID = Field(
        foreign_key="douyin_media_asset.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    # 所属采集任务 ID，任务删除时级联删除
    task_id: uuid.UUID = Field(
        foreign_key="crawl_task.id", nullable=False, ondelete="CASCADE", index=True
    )
    aweme_id: str = Field(max_length=128, index=True)  # 抖音作品 ID（冗余便于查询）
    # 转写状态，见 SubtitleStatus
    status: str = Field(default=SubtitleStatus.pending.value, max_length=32, index=True)
    progress: int = Field(default=0, ge=0, le=100)  # 转写进度（0-100）
    attempt_count: int = 0  # 转写尝试次数
    requested_backend: str = Field(
        default="api", max_length=32
    )  # 请求使用的转写后端（当前仅支持远程 api）
    actual_backend: str = Field(default="", max_length=32)  # 实际完成转写的后端
    model: str = Field(default="", max_length=255)  # 实际使用的转写模型版本
    language: str = Field(default="", max_length=32)  # 识别出的语言代码
    duration_seconds: float = 0.0  # 音视频时长（秒）
    full_text: str = Field(default="", sa_type=Text)  # 完整转写文本
    segments_json: str = Field(
        default="[]", sa_type=Text
    )  # 分段字幕（JSON 数组，元素含 start/end/text）
    error: str | None = Field(default=None, sa_type=Text)  # 最近一次转写失败原因
    # 记录创建时间（UTC）
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    # 转写开始时间（UTC）
    started_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    # 转写结束时间（UTC）
    finished_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinSubtitlePublic(SQLModel):
    """字幕记录的对外只读视图（segments 已解析为对象列表）。"""

    id: uuid.UUID  # 字幕记录主键
    asset_id: uuid.UUID  # 关联的媒体资产 ID
    task_id: uuid.UUID  # 所属采集任务 ID
    aweme_id: str  # 抖音作品 ID
    status: SubtitleStatus  # 转写状态
    progress: int  # 转写进度（0-100）
    attempt_count: int  # 转写尝试次数
    requested_backend: str  # 请求使用的转写后端
    actual_backend: str  # 实际完成转写的后端
    model: str  # 实际使用的转写模型版本
    language: str  # 识别出的语言代码
    duration_seconds: float  # 音视频时长（秒）
    full_text: str  # 完整转写文本
    segments: list[dict[str, object]]  # 分段字幕列表（元素含 start/end/text）
    error: str | None  # 最近一次转写失败原因
    created_at: datetime  # 记录创建时间（UTC）
    started_at: datetime | None  # 转写开始时间（UTC）
    finished_at: datetime | None  # 转写结束时间（UTC）


class DouyinMediaAssetPublic(SQLModel):
    """媒体资产的对外只读视图，附带其字幕记录。"""

    id: uuid.UUID  # 资产主键
    task_id: uuid.UUID  # 所属采集任务 ID
    aweme_id: str  # 抖音作品 ID
    storage_backend: MediaStorageBackend  # 存储后端
    status: MediaDownloadStatus  # 下载状态
    progress: int  # 下载进度（0-100）
    attempt_count: int  # 下载尝试次数
    mime_type: str  # 媒体 MIME 类型
    file_size: int  # 文件大小（字节）
    sha256: str  # 文件内容 SHA-256 摘要
    error: str | None  # 最近一次下载失败原因
    download_available: bool  # 当前是否可下载（本地文件存在或远端对象就绪）
    created_at: datetime  # 记录创建时间（UTC）
    updated_at: datetime  # 记录最近更新时间（UTC）
    completed_at: datetime | None  # 下载完成时间（UTC）
    migration_status: MediaMigrationStatus  # 迁移状态
    migration_progress: int  # 迁移进度（0-100）
    migration_attempt_count: int  # 迁移尝试次数
    migration_error: str | None  # 最近一次迁移失败原因
    migration_started_at: datetime | None  # 迁移开始时间（UTC）
    migration_finished_at: datetime | None  # 迁移结束时间（UTC）
    subtitle: DouyinSubtitlePublic | None  # 关联的字幕记录，未转写时为 None


class DouyinMediaAssetsPublic(SQLModel):
    """媒体资产分页列表响应。"""

    data: list[DouyinMediaAssetPublic]  # 当前页资产列表
    count: int  # 符合条件的资产总数


class DouyinSubtitleExportFormat(str, Enum):
    """字幕导出格式。"""

    txt = "txt"  # 纯文本
    srt = "srt"  # SRT 字幕文件
    vtt = "vtt"  # WebVTT 字幕文件


class DouyinSubtitleExportRequest(SQLModel):
    """字幕批量导出请求体。"""

    aweme_ids: list[str] = Field(
        min_length=1, max_length=1000
    )  # 待导出的抖音作品 ID 列表
    format: DouyinSubtitleExportFormat = (
        DouyinSubtitleExportFormat.srt
    )  # 导出格式，默认 srt


class DouyinMediaSummaryPublic(SQLModel):
    """任务媒体处理概览：下载、字幕与迁移各状态的数量统计。"""

    total: int  # 媒体资产总数
    queued: int  # 排队待下载数
    downloading: int  # 下载中数
    downloaded: int  # 已下载数
    download_failed: int  # 下载失败数
    subtitle_pending: int  # 字幕等待转写数
    subtitle_running: int  # 字幕转写中数
    subtitle_completed: int  # 字幕转写完成数
    subtitle_failed: int  # 字幕转写失败数
    local_downloaded: int  # 已下载且存储在本地的资产数
    minio_downloaded: int  # 已下载且存储在 MinIO 的资产数
    migration_queued: int  # 迁移排队数
    migration_running: int  # 迁移执行中数（上传/校验/切换）
    migration_cleanup_pending: int  # 已切换待清理本地副本数
    migration_completed: int  # 迁移完成数
    migration_failed: int  # 迁移失败数


class DouyinMediaRetryRequest(SQLModel):
    """媒体下载/字幕失败重试请求体。"""

    asset_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=1000
    )  # 限定重试的资产 ID 列表，为空表示任务内全部候选
    retry_downloads: bool = True  # 是否重试失败的下载
    retry_subtitles: bool = True  # 是否重试失败的字幕转写
    force_retranslate: bool = False  # 是否对已完成的字幕强制重新转写


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
