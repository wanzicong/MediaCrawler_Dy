import secrets
import warnings
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    AnyUrl,
    BeforeValidator,
    EmailStr,
    Field,
    HttpUrl,
    PostgresDsn,
    SecretStr,
    computed_field,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Load tracked defaults, then optional Git-ignored local secrets.
        env_file=("../.env", "../.env.local"),
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = secrets.token_urlsafe(32)
    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    FRONTEND_HOST: str = "http://localhost:5173"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST
        ]

    PROJECT_NAME: str
    SENTRY_DSN: HttpUrl | None = None

    # Douyin crawler: browser automation is CDP-only. The application never
    # falls back to chromium.launch() or launch_persistent_context().
    DOUYIN_BROWSER_MODE: Literal["local", "remote"] = "remote"
    DOUYIN_CDP_HOST: str = "127.0.0.1"
    DOUYIN_CDP_PORT: int = 9222
    DOUYIN_CDP_CONNECT_EXISTING: bool = False
    DOUYIN_CDP_CONNECT_TIMEOUT: float = 60.0
    DOUYIN_CDP_BROWSER_PATH: str = ""
    DOUYIN_CDP_USER_DATA_DIR: Path = Path("../browser_data/douyin")
    DOUYIN_CDP_HEADLESS: bool = False
    DOUYIN_CDP_AUTO_CLOSE: bool = True
    # Native backend defaults to the browser container's loopback-only host
    # mapping. compose.browser.yml overrides these with the Docker DNS endpoint.
    DOUYIN_REMOTE_CDP_HOST: str = "127.0.0.1"
    DOUYIN_REMOTE_CDP_PORT: int = 9223
    # Optional JSON object of named browser slots. Example:
    # {"account-1":{"host":"127.0.0.1","port":9223,"viewer_url":"http://127.0.0.1:6081/vnc.html?autoconnect=1&resize=scale"}}
    DOUYIN_REMOTE_CDP_SLOTS: str = ""
    DOUYIN_REMOTE_VIEWER_URL: str = (
        "http://127.0.0.1:6081/vnc.html?autoconnect=1&resize=scale"
    )
    DOUYIN_ACCOUNT_LOGIN_SESSION_TTL_SECONDS: int = Field(
        default=900, ge=60, le=3600
    )
    DOUYIN_ACCOUNT_FAILURE_COOLDOWN_SECONDS: int = Field(
        default=600, ge=60, le=86400
    )
    DOUYIN_LOGIN_TIMEOUT: float = 600.0
    DOUYIN_REQUEST_TIMEOUT: float = 60.0
    DOUYIN_MAX_ACTIVE_TASKS: int = 1
    DOUYIN_MAX_AWEMES_PER_TASK: int = 1000
    DOUYIN_MAX_COMMENTS_PER_AWEME: int = 1000
    DOUYIN_REQUEST_SSL_VERIFY: bool = True
    DOUYIN_INTERACTION_DAILY_LIMIT: int = Field(default=50, ge=1, le=1000)
    DOUYIN_INTERACTION_MIN_INTERVAL_SECONDS: float = Field(
        default=30.0, ge=1.0, le=3600.0
    )
    DOUYIN_INTERACTION_DUPLICATE_WINDOW_HOURS: int = Field(
        default=24, ge=1, le=720
    )
    DOUYIN_INTERACTION_MAX_ATTEMPTS: int = Field(default=3, ge=1, le=10)
    DOUYIN_INTERACTION_SCREENSHOTS_ENABLED: bool = True
    DOUYIN_INTERACTION_SCREENSHOT_DIR: Path = Path(
        "../data/interaction-screenshots"
    )
    DOUYIN_INTERACTION_SCREENSHOT_QUALITY: int = Field(
        default=65, ge=30, le=90
    )
    DOUYIN_INTERACTION_SCREENSHOT_TIMEOUT_SECONDS: float = Field(
        default=5.0, ge=1.0, le=15.0
    )
    DOUYIN_INTERACTION_PAGE_READY_TIMEOUT_SECONDS: float = Field(
        default=45.0, ge=10.0, le=120.0
    )
    DOUYIN_INTERACTION_NAVIGATION_ATTEMPTS: int = Field(
        default=3, ge=1, le=5
    )
    DOUYIN_INTERACTION_COMMENT_READY_TIMEOUT_SECONDS: float = Field(
        default=30.0, ge=5.0, le=90.0
    )

    # Media download and remote subtitle transcription/translation pipeline.
    MEDIA_STORAGE_BACKEND: Literal["local", "minio"] = "minio"
    MEDIA_OUTPUT_DIR: Path = Path("../data/media")
    MEDIA_DOWNLOAD_TIMEOUT: float = 180.0
    MEDIA_DOWNLOAD_RETRIES: int = 3
    MEDIA_DOWNLOAD_CONCURRENCY: int = 2
    MEDIA_MIGRATION_CONCURRENCY: int = 2
    MEDIA_MAX_SIZE_MB: int = 500
    MEDIA_PREVIEW_TTL_SECONDS: int = Field(default=300, ge=30, le=3600)
    MINIO_ENDPOINT: str = "127.0.0.1:9000"
    MINIO_ACCESS_KEY: SecretStr = SecretStr("mediacrawler")
    MINIO_SECRET_KEY: SecretStr = SecretStr("mediacrawler-secret")
    MINIO_SECURE: bool = False
    MINIO_BUCKET: str = "douyin-media"
    MINIO_REGION: str = ""
    WHISPER_API_BASE_URL: str = "http://127.0.0.1:9000"
    WHISPER_API_KEY: SecretStr = SecretStr("")
    WHISPER_API_MODEL: str = "whisper-1"
    WHISPER_API_MODEL_VERSION: str = ""
    WHISPER_API_TIMEOUT: float = 1800.0
    WHISPER_API_TRUST_ENV: bool = False
    WHISPER_API_CONCURRENCY: int = 5
    FFMPEG_BINARY: str = "ffmpeg"
    WHISPER_AUDIO_BITRATE_KBPS: int = Field(default=64, ge=32, le=192)
    WHISPER_AUDIO_PREPROCESS_TIMEOUT: float = Field(default=300.0, gt=0)

    # MCP is an API gateway and authenticates through the existing FastAPI login.
    MCP_API_BASE_URL: str = "http://127.0.0.1:8000/api/v1"
    MCP_API_USERNAME: EmailStr | None = None
    MCP_API_PASSWORD: SecretStr | None = None
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        return self


settings = Settings()  # type: ignore
