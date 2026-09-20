"""媒体下载/存储与远程字幕转写配置字段。"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr


class MediaFields(BaseModel):
    """媒体流水线与字幕转写（Whisper）配置。"""

    MEDIA_STORAGE_BACKEND: Literal["local", "minio"] = (
        "minio"  # 媒体存储后端：local 本地磁盘 / minio 对象存储
    )
    MEDIA_OUTPUT_DIR: Path = Path(
        "data/media"
    )  # 本地媒体文件输出目录（相对路径将拼接到仓库根目录）
    MEDIA_DOWNLOAD_TIMEOUT: float = 180.0  # 单个媒体文件下载超时时间（秒）
    MEDIA_DOWNLOAD_RETRIES: int = 3  # 媒体下载失败重试次数
    MEDIA_DOWNLOAD_CONCURRENCY: int = 4  # 媒体下载并发数（独立于浏览器风控并发）
    MEDIA_MIGRATION_CONCURRENCY: int = 4  # 历史媒体迁移并发数
    MEDIA_RETRY_BACKOFF_BASE_SECONDS: float = Field(
        default=2.0, gt=0
    )  # 媒体下载/转写失败后的退避起始秒数
    MEDIA_RETRY_BACKOFF_MULTIPLIER: float = Field(
        default=2.0, ge=1.0
    )  # 退避倍数：第 n 次重试等待 base × multiplier^(n-1)
    MEDIA_RETRY_BACKOFF_MAX_SECONDS: float = Field(
        default=5.0, gt=0
    )  # 单次退避等待上限（秒）
    MEDIA_MAX_SIZE_MB: int = 500  # 单个媒体文件大小上限（MB）
    MEDIA_SUBTITLE_PREFER_AUDIO: bool = (
        True  # 仅字幕任务优先下载作品原声音频（体积小得多）
    )
    MEDIA_SUBTITLE_MAX_SIZE_MB: int = (
        0  # 仅字幕任务的大小上限（MB）；0 表示沿用 MEDIA_MAX_SIZE_MB
    )
    MEDIA_SUBTITLE_DOWNLOAD_TIMEOUT: float = (
        0.0  # 仅字幕任务的单次下载超时（秒）；0 表示沿用 MEDIA_DOWNLOAD_TIMEOUT
    )
    MEDIA_SUBTITLE_DOWNLOAD_ATTEMPTS: int = (
        0  # 仅字幕任务的下载尝试次数；0 表示沿用 MEDIA_DOWNLOAD_RETRIES
    )
    MEDIA_PREVIEW_TTL_SECONDS: int = Field(
        default=300, ge=30, le=3600
    )  # 媒体预览（预签名 URL）有效期（秒）

    WHISPER_API_BASE_URL: str = (
        "http://127.0.0.1:9000"  # Whisper 转写服务的基础 URL（OpenAI 兼容接口）
    )
    WHISPER_API_KEY: SecretStr = SecretStr("")  # Whisper 转写服务 API Key
    WHISPER_API_MODEL: str = "whisper-1"  # Whisper 转写模型名
    WHISPER_API_MODEL_VERSION: str = ""  # Whisper 模型版本，可选
    WHISPER_API_TIMEOUT: float = 1800.0  # 单次转写请求超时时间（秒）
    WHISPER_API_TRUST_ENV: bool = False  # 转写 HTTP 客户端是否信任环境代理变量
    WHISPER_API_CONCURRENCY: int = 8  # 字幕转写并发数（默认 8，可由 config.yaml 覆盖）
    FFMPEG_BINARY: str = "ffmpeg"  # ffmpeg 可执行文件路径或命令名
    WHISPER_AUDIO_BITRATE_KBPS: int = Field(
        default=64, ge=32, le=192
    )  # 转写前音频重编码码率（kbps）
    WHISPER_AUDIO_PREPROCESS_TIMEOUT: float = Field(
        default=300.0, gt=0
    )  # 音频预处理（抽取/转码）超时时间（秒）
