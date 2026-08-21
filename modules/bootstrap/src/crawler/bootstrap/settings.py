"""应用运行时配置定义：基于 pydantic-settings 的集中式环境配置。

从仓库根目录的 .env / .env.local 读取配置，覆盖 API、数据库、抖音 CDP 浏览器、
媒体存储、字幕转写、MCP、邮件等全部子系统；模块末尾实例化全局单例 settings。
"""

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

# 仓库根目录：modules/bootstrap/src/crawler/bootstrap/settings.py 位于其下五层。
# 无论进程从哪个工作目录启动，配置解析结果都必须保持一致。
BASE_DIR = Path(__file__).resolve().parents[5]

# 需要解析为绝对路径的相对路径配置项（统一拼接到仓库根目录下）
_RELATIVE_PATH_FIELDS = (
    "DOUYIN_CDP_USER_DATA_DIR",
    "DOUYIN_INTERACTION_SCREENSHOT_DIR",
    "MEDIA_OUTPUT_DIR",
)


def parse_cors(v: Any) -> list[str] | str:
    """解析 CORS 来源配置：兼容逗号分隔字符串与 JSON 列表两种写法。

    参数：
        v: 原始配置值，可为逗号分隔字符串、JSON 数组字符串或列表。

    返回：
        拆分后的来源列表，或原样返回的值（交由后续校验处理）。

    异常：
        ValueError: 值既不是字符串也不是列表时抛出。
    """
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    """全局应用配置，所有配置项均可被同名环境变量覆盖。"""

    model_config = SettingsConfigDict(
        # 先加载纳入版本管理的默认值，再加载可选的、被 Git 忽略的本地私密配置。
        env_file=(BASE_DIR / ".env", BASE_DIR / ".env.local"),
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"  # API v1 路由前缀
    SECRET_KEY: str = secrets.token_urlsafe(
        32
    )  # JWT 签名密钥；默认随机生成，生产环境必须用环境变量固定
    # 60 分钟 * 24 小时 * 8 天 = 8 天
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 访问令牌有效期（分钟），默认 8 天
    FRONTEND_HOST: str = (
        "http://localhost:5173"  # 前端地址，用于拼接 CORS 来源与邮件链接
    )
    ENVIRONMENT: Literal["local", "staging", "production"] = (
        "local"  # 运行环境，影响默认密钥的校验策略
    )

    # 额外允许的后端 CORS 来源，支持逗号分隔字符串或 JSON 列表
    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        """全部 CORS 来源：后端来源去除尾部斜杠后追加前端地址。"""
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST
        ]

    PROJECT_NAME: str  # 项目名称（必填，无默认值）
    SENTRY_DSN: HttpUrl | None = None  # Sentry DSN，可选；配置后启用错误上报

    # 抖音采集器：浏览器自动化仅使用 CDP。应用绝不回退到
    # chromium.launch() 或 launch_persistent_context()。
    DOUYIN_BROWSER_MODE: Literal["local", "remote"] = (
        "remote"  # 浏览器模式：remote 远程 CDP，local 本机浏览器
    )
    DOUYIN_CDP_HOST: str = "127.0.0.1"  # CDP 调试主机地址；本地模式下必须是本机地址
    DOUYIN_CDP_PORT: int = 9222  # CDP 调试端口
    DOUYIN_CDP_CONNECT_EXISTING: bool = (
        False  # 为 True 时附加到已开启 CDP 的既有浏览器，不再代为启动
    )
    DOUYIN_CDP_CONNECT_TIMEOUT: float = 60.0  # 等待 CDP 浏览器就绪/连接的超时时间（秒）
    DOUYIN_CDP_BROWSER_PATH: str = (
        ""  # 浏览器可执行文件路径；为空时自动探测本机 Chrome/Edge
    )
    DOUYIN_CDP_USER_DATA_DIR: Path = Path(
        "browser_data/douyin"
    )  # 本地浏览器用户数据目录（相对路径将拼接到仓库根目录）
    DOUYIN_CDP_HEADLESS: bool = False  # 本地启动浏览器时是否使用无头模式
    DOUYIN_CDP_AUTO_CLOSE: bool = True  # 会话结束时是否自动关闭由会话托管的浏览器进程
    # 原生（非容器）后端默认走浏览器容器映射到本机回环地址的端口；
    # compose.browser.yml 会用 Docker DNS 端点覆盖这两项配置。
    DOUYIN_REMOTE_CDP_HOST: str = "127.0.0.1"  # 远程 CDP 浏览器主机名或 IP
    DOUYIN_REMOTE_CDP_PORT: int = 9223  # 远程 CDP 浏览器端口
    # 可选的命名浏览器槽位 JSON 对象。示例：
    # {"account-1":{"host":"127.0.0.1","port":9223,"viewer_url":"http://127.0.0.1:6081/vnc.html?autoconnect=1&resize=scale"}}
    DOUYIN_REMOTE_CDP_SLOTS: str = (
        ""  # 命名浏览器槽位配置（JSON 字符串），空串表示不启用多槽位
    )
    DOUYIN_REMOTE_VIEWER_URL: str = "http://127.0.0.1:6081/vnc.html?autoconnect=1&resize=scale"  # 远程浏览器 noVNC 查看器地址，用于前端展示实时画面
    # 账号登录会话的有效期（秒），取值 60~3600，默认 900（15 分钟）
    DOUYIN_ACCOUNT_LOGIN_SESSION_TTL_SECONDS: int = Field(default=900, ge=60, le=3600)
    # 仅为向后兼容保留的环境配置项。账号失败仍会被记录并可将账号标记为不健康，
    # 但不再使账号进入基于时间的冷却状态。
    DOUYIN_ACCOUNT_FAILURE_COOLDOWN_SECONDS: int = Field(
        default=0, ge=0, le=86400
    )  # 账号失败冷却时长（秒），默认 0 表示不冷却
    DOUYIN_LOGIN_TIMEOUT: float = 600.0  # 扫码/账号登录流程的整体超时时间（秒）
    DOUYIN_REQUEST_TIMEOUT: float = 60.0  # 抖音接口单次请求超时时间（秒）
    DOUYIN_MAX_ACTIVE_TASKS: int = 1  # 同时运行的采集任务数上限
    DOUYIN_MAX_AWEMES_PER_TASK: int = 1000  # 单个任务最多采集的视频（aweme）数量
    DOUYIN_MAX_COMMENTS_PER_AWEME: int = 1000  # 单条视频最多采集的评论数量
    DOUYIN_REQUEST_SSL_VERIFY: bool = True  # 请求抖音接口时是否校验 SSL 证书
    DOUYIN_INTERACTION_DAILY_LIMIT: int = Field(
        default=50, ge=1, le=1000
    )  # 互动操作每日上限
    DOUYIN_INTERACTION_MIN_INTERVAL_SECONDS: float = Field(
        default=0.0, ge=0.0, le=3600.0
    )  # 两次互动操作之间的最小间隔（秒），0 表示不限制
    DOUYIN_INTERACTION_DUPLICATE_WINDOW_HOURS: int = Field(
        default=24, ge=1, le=720
    )  # 互动去重窗口（小时），窗口内对同一目标的重复操作将被拦截
    DOUYIN_INTERACTION_MAX_ATTEMPTS: int = Field(
        default=3, ge=1, le=10
    )  # 单次互动操作的最大重试次数
    DOUYIN_INTERACTION_SCREENSHOTS_ENABLED: bool = True  # 是否在互动过程中保存截图证据
    DOUYIN_INTERACTION_SCREENSHOT_DIR: Path = Path(
        "data/interaction-screenshots"
    )  # 互动截图保存目录（相对路径将拼接到仓库根目录）
    DOUYIN_INTERACTION_SCREENSHOT_QUALITY: int = Field(
        default=65, ge=30, le=90
    )  # 互动截图 JPEG 质量
    DOUYIN_INTERACTION_SCREENSHOT_TIMEOUT_SECONDS: float = Field(
        default=5.0, ge=1.0, le=15.0
    )  # 单次截图操作超时时间（秒）
    DOUYIN_INTERACTION_PAGE_READY_TIMEOUT_SECONDS: float = Field(
        default=45.0, ge=10.0, le=120.0
    )  # 等待互动目标页面就绪的超时时间（秒）
    DOUYIN_INTERACTION_NAVIGATION_ATTEMPTS: int = Field(
        default=3, ge=1, le=5
    )  # 页面导航失败时的最大尝试次数
    DOUYIN_INTERACTION_COMMENT_READY_TIMEOUT_SECONDS: float = Field(
        default=30.0, ge=5.0, le=90.0
    )  # 等待评论区就绪的超时时间（秒）
    DOUYIN_INTERACTION_EXECUTION_TIMEOUT_SECONDS: float = Field(
        default=300.0, ge=30.0, le=600.0
    )  # 单次互动执行的整体超时时间（秒）

    # 媒体下载与远程字幕转写/翻译流水线。
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
    MEDIA_MAX_SIZE_MB: int = 500  # 单个媒体文件大小上限（MB）
    MEDIA_PREVIEW_TTL_SECONDS: int = Field(
        default=300, ge=30, le=3600
    )  # 媒体预览（预签名 URL）有效期（秒）
    MINIO_ENDPOINT: str = "127.0.0.1:9000"  # MinIO 服务地址（host:port）
    MINIO_ACCESS_KEY: SecretStr = SecretStr("mediacrawler")  # MinIO 访问密钥
    MINIO_SECRET_KEY: SecretStr = SecretStr("mediacrawler-secret")  # MinIO 秘密密钥
    MINIO_SECURE: bool = False  # 是否通过 HTTPS 连接 MinIO
    MINIO_BUCKET: str = "douyin-media"  # MinIO 存储桶名称
    MINIO_REGION: str = ""  # MinIO 区域，可选
    WHISPER_API_BASE_URL: str = (
        "http://127.0.0.1:9000"  # Whisper 转写服务的基础 URL（OpenAI 兼容接口）
    )
    WHISPER_API_KEY: SecretStr = SecretStr("")  # Whisper 转写服务 API Key
    WHISPER_API_MODEL: str = "whisper-1"  # Whisper 转写模型名
    WHISPER_API_MODEL_VERSION: str = ""  # Whisper 模型版本，可选
    WHISPER_API_TIMEOUT: float = 1800.0  # 单次转写请求超时时间（秒）
    WHISPER_API_TRUST_ENV: bool = False  # 转写 HTTP 客户端是否信任环境代理变量
    WHISPER_API_CONCURRENCY: int = 5  # 字幕转写并发数
    FFMPEG_BINARY: str = "ffmpeg"  # ffmpeg 可执行文件路径或命令名
    WHISPER_AUDIO_BITRATE_KBPS: int = Field(
        default=64, ge=32, le=192
    )  # 转写前音频重编码码率（kbps）
    WHISPER_AUDIO_PREPROCESS_TIMEOUT: float = Field(
        default=300.0, gt=0
    )  # 音频预处理（抽取/转码）超时时间（秒）

    # MCP 作为 API 网关，通过既有 FastAPI 登录接口完成认证。
    MCP_API_BASE_URL: str = (
        "http://127.0.0.1:8000/api/v1"  # MCP 调用的后端 API 基础地址
    )
    MCP_API_USERNAME: EmailStr | None = None  # MCP 登录账号（邮箱）
    MCP_API_PASSWORD: SecretStr | None = None  # MCP 登录密码
    POSTGRES_SERVER: str  # PostgreSQL 主机地址（必填）
    POSTGRES_PORT: int = 5432  # PostgreSQL 端口
    POSTGRES_USER: str  # PostgreSQL 用户名（必填）
    POSTGRES_PASSWORD: str = ""  # PostgreSQL 密码
    POSTGRES_DB: str = ""  # PostgreSQL 数据库名

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        """由 PostgreSQL 各项配置拼接出的 SQLAlchemy 数据库连接 URI。"""
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    SMTP_TLS: bool = True  # 是否使用 STARTTLS 加密 SMTP 连接
    SMTP_SSL: bool = False  # 是否使用 SSL/TLS 直连 SMTP
    SMTP_PORT: int = 587  # SMTP 服务端口
    SMTP_HOST: str | None = None  # SMTP 服务主机；为空则邮件功能不可用
    SMTP_USER: str | None = None  # SMTP 登录用户名
    SMTP_PASSWORD: str | None = None  # SMTP 登录密码
    EMAILS_FROM_EMAIL: EmailStr | None = None  # 发件人邮箱地址
    EMAILS_FROM_NAME: str | None = None  # 发件人显示名称；未配置时回退为项目名称

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        """发件人名称缺省时回退为项目名称。"""
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48  # 密码重置令牌有效期（小时）

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        """是否已具备启用邮件功能所需的 SMTP 主机与发件人配置。"""
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    EMAIL_TEST_USER: EmailStr = "test@example.com"  # 测试用户的邮箱地址
    FIRST_SUPERUSER: EmailStr  # 初始超级管理员邮箱（必填）
    FIRST_SUPERUSER_PASSWORD: str  # 初始超级管理员密码（必填）

    @model_validator(mode="after")
    def _resolve_relative_paths(self) -> Self:
        """将相对路径配置项统一解析为基于仓库根目录的绝对路径。"""
        for field_name in _RELATIVE_PATH_FIELDS:
            value = getattr(self, field_name)
            if not value.is_absolute():
                setattr(self, field_name, BASE_DIR / value)
        return self

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        """检查敏感配置是否仍为占位符 "changethis"。

        local 环境仅发出警告，其他环境直接拒绝启动。

        参数：
            var_name: 配置项名称，用于报错信息。
            value: 配置项当前值。

        异常：
            ValueError: 非 local 环境下仍使用占位符时抛出。
        """
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
        """对全部敏感配置执行占位符检查，防止带着默认密钥部署。"""
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        return self


# 全局配置单例，进程启动时即完成加载与校验
settings = Settings()  # type: ignore
