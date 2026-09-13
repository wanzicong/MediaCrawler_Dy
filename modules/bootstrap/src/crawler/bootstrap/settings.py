"""应用运行时配置定义：基于 pydantic-settings 的集中式环境配置。

配置来源（优先级从高到低）：显式入参 > 环境变量 > .env.local > .env >
仓库根目录的 config.yaml > 代码默认值。`config.yaml` 只承载**结构化的业务
默认值**（浏览器槽位、风控档位与上限），密钥与连接串仍只从环境变量读取；
模块末尾实例化全局单例 settings。
"""

import os
import re
import secrets
import warnings
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    AnyUrl,
    BaseModel,
    BeforeValidator,
    EmailStr,
    Field,
    HttpUrl,
    PostgresDsn,
    SecretStr,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from typing_extensions import Self

# 仓库根目录：modules/bootstrap/src/crawler/bootstrap/settings.py 位于其下五层。
# 无论进程从哪个工作目录启动，配置解析结果都必须保持一致。
BASE_DIR = Path(__file__).resolve().parents[5]

# 需要解析为绝对路径的相对路径配置项（统一拼接到仓库根目录下）
_RELATIVE_PATH_FIELDS = (
    "DOUYIN_CDP_USER_DATA_DIR",
    "DOUYIN_LOCAL_CDP_USER_DATA_DIR",
    "DOUYIN_INTERACTION_SCREENSHOT_DIR",
    "MEDIA_OUTPUT_DIR",
)

# config.yaml 的扁平映射表：YAML 分段路径 → Settings 字段名。
# 这张表是 YAML 与配置项之间唯一的真源，架构测试会逐项验证「YAML 能设进去 +
# 环境变量能覆盖」，新增配置项时同步在这里登记即可。
_CONFIG_FIELD_MAP: tuple[tuple[str, str], ...] = (
    # 应用与认证（密钥仍只从环境变量读取，这里只登记非敏感项）
    ("app.project_name", "PROJECT_NAME"),
    ("app.environment", "ENVIRONMENT"),
    ("app.api_v1_str", "API_V1_STR"),
    ("app.frontend_host", "FRONTEND_HOST"),
    ("app.cors_origins", "BACKEND_CORS_ORIGINS"),
    ("app.access_token_expire_minutes", "ACCESS_TOKEN_EXPIRE_MINUTES"),
    ("app.sentry_dsn", "SENTRY_DSN"),
    ("app.first_superuser", "FIRST_SUPERUSER"),
    # 数据库与对象存储连接（口令留环境变量）
    ("database.server", "POSTGRES_SERVER"),
    ("database.port", "POSTGRES_PORT"),
    ("database.user", "POSTGRES_USER"),
    ("database.name", "POSTGRES_DB"),
    ("database.connect_timeout", "POSTGRES_CONNECT_TIMEOUT"),
    ("storage.endpoint", "MINIO_ENDPOINT"),
    ("storage.bucket", "MINIO_BUCKET"),
    ("storage.region", "MINIO_REGION"),
    ("storage.secure", "MINIO_SECURE"),
    # 邮件（口令留环境变量）
    ("email.smtp_host", "SMTP_HOST"),
    ("email.smtp_port", "SMTP_PORT"),
    ("email.smtp_user", "SMTP_USER"),
    ("email.smtp_tls", "SMTP_TLS"),
    ("email.smtp_ssl", "SMTP_SSL"),
    ("email.from_email", "EMAILS_FROM_EMAIL"),
    ("email.from_name", "EMAILS_FROM_NAME"),
    ("email.reset_token_expire_hours", "EMAIL_RESET_TOKEN_EXPIRE_HOURS"),
    ("email.test_user", "EMAIL_TEST_USER"),
    # MCP 网关登录（口令留环境变量）
    ("mcp.api_base_url", "MCP_API_BASE_URL"),
    ("mcp.api_username", "MCP_API_USERNAME"),
    # 浏览器：默认模式与本机 CDP 运行参数
    ("browser.default_mode", "DOUYIN_BROWSER_MODE"),
    ("browser.local.host", "DOUYIN_CDP_HOST"),
    ("browser.local.port", "DOUYIN_CDP_PORT"),
    ("browser.local.connect_existing", "DOUYIN_CDP_CONNECT_EXISTING"),
    ("browser.local.connect_timeout", "DOUYIN_CDP_CONNECT_TIMEOUT"),
    ("browser.local.browser_path", "DOUYIN_CDP_BROWSER_PATH"),
    ("browser.local.user_data_dir", "DOUYIN_CDP_USER_DATA_DIR"),
    ("browser.local.headless", "DOUYIN_CDP_HEADLESS"),
    ("browser.local.auto_close", "DOUYIN_CDP_AUTO_CLOSE"),
    ("browser.local.slot_count", "DOUYIN_LOCAL_CDP_SLOT_COUNT"),
    ("browser.local.port_base", "DOUYIN_LOCAL_CDP_PORT_BASE"),
    ("browser.local.slot_user_data_dir", "DOUYIN_LOCAL_CDP_USER_DATA_DIR"),
    # 浏览器：远程（容器）槽位
    ("browser.remote.host", "DOUYIN_REMOTE_CDP_HOST"),
    ("browser.remote.port", "DOUYIN_REMOTE_CDP_PORT"),
    ("browser.remote.viewer_url", "DOUYIN_REMOTE_VIEWER_URL"),
    ("browser.remote.legacy_slots_json", "DOUYIN_REMOTE_CDP_SLOTS"),
    # 账号登录会话与兼容项
    ("account.login_session_ttl_seconds", "DOUYIN_ACCOUNT_LOGIN_SESSION_TTL_SECONDS"),
    (
        "account.failure_cooldown_seconds",
        "DOUYIN_ACCOUNT_FAILURE_COOLDOWN_SECONDS",
    ),
    # 采集与风控上限
    ("crawl.request_timeout", "DOUYIN_REQUEST_TIMEOUT"),
    ("crawl.request_ssl_verify", "DOUYIN_REQUEST_SSL_VERIFY"),
    ("crawl.login_timeout", "DOUYIN_LOGIN_TIMEOUT"),
    ("crawl.account_wait_poll_seconds", "DOUYIN_ACCOUNT_WAIT_POLL_SECONDS"),
    ("risk_control.limits.max_active_tasks", "DOUYIN_MAX_ACTIVE_TASKS"),
    ("risk_control.limits.max_awemes_per_task", "DOUYIN_MAX_AWEMES_PER_TASK"),
    ("risk_control.limits.max_comments_per_aweme", "DOUYIN_MAX_COMMENTS_PER_AWEME"),
    # 互动风控
    ("interaction.daily_limit", "DOUYIN_INTERACTION_DAILY_LIMIT"),
    ("interaction.min_interval_seconds", "DOUYIN_INTERACTION_MIN_INTERVAL_SECONDS"),
    ("interaction.duplicate_window_hours", "DOUYIN_INTERACTION_DUPLICATE_WINDOW_HOURS"),
    ("interaction.max_attempts", "DOUYIN_INTERACTION_MAX_ATTEMPTS"),
    ("interaction.navigation_attempts", "DOUYIN_INTERACTION_NAVIGATION_ATTEMPTS"),
    ("interaction.screenshots.enabled", "DOUYIN_INTERACTION_SCREENSHOTS_ENABLED"),
    ("interaction.screenshots.dir", "DOUYIN_INTERACTION_SCREENSHOT_DIR"),
    ("interaction.screenshots.quality", "DOUYIN_INTERACTION_SCREENSHOT_QUALITY"),
    (
        "interaction.screenshots.timeout_seconds",
        "DOUYIN_INTERACTION_SCREENSHOT_TIMEOUT_SECONDS",
    ),
    (
        "interaction.timeouts.page_ready_seconds",
        "DOUYIN_INTERACTION_PAGE_READY_TIMEOUT_SECONDS",
    ),
    (
        "interaction.timeouts.comment_ready_seconds",
        "DOUYIN_INTERACTION_COMMENT_READY_TIMEOUT_SECONDS",
    ),
    (
        "interaction.timeouts.execution_seconds",
        "DOUYIN_INTERACTION_EXECUTION_TIMEOUT_SECONDS",
    ),
    # 媒体
    ("media.storage_backend", "MEDIA_STORAGE_BACKEND"),
    ("media.output_dir", "MEDIA_OUTPUT_DIR"),
    ("media.download.timeout", "MEDIA_DOWNLOAD_TIMEOUT"),
    ("media.download.retries", "MEDIA_DOWNLOAD_RETRIES"),
    ("media.download.concurrency", "MEDIA_DOWNLOAD_CONCURRENCY"),
    ("media.download.max_size_mb", "MEDIA_MAX_SIZE_MB"),
    ("media.migration_concurrency", "MEDIA_MIGRATION_CONCURRENCY"),
    ("media.preview_ttl_seconds", "MEDIA_PREVIEW_TTL_SECONDS"),
    ("media.retry_backoff.base_seconds", "MEDIA_RETRY_BACKOFF_BASE_SECONDS"),
    ("media.retry_backoff.multiplier", "MEDIA_RETRY_BACKOFF_MULTIPLIER"),
    ("media.retry_backoff.max_seconds", "MEDIA_RETRY_BACKOFF_MAX_SECONDS"),
    # 字幕转写与音频预处理（API Key 仍只从环境变量读取）
    ("subtitle.base_url", "WHISPER_API_BASE_URL"),
    ("subtitle.model", "WHISPER_API_MODEL"),
    ("subtitle.model_version", "WHISPER_API_MODEL_VERSION"),
    ("subtitle.timeout", "WHISPER_API_TIMEOUT"),
    ("subtitle.trust_env", "WHISPER_API_TRUST_ENV"),
    ("subtitle.concurrency", "WHISPER_API_CONCURRENCY"),
    ("subtitle.audio_bitrate_kbps", "WHISPER_AUDIO_BITRATE_KBPS"),
    ("subtitle.audio_preprocess_timeout", "WHISPER_AUDIO_PREPROCESS_TIMEOUT"),
    ("subtitle.ffmpeg_binary", "FFMPEG_BINARY"),
)

# config.yaml 中直接映射为结构化字段的子树（不逐字段拆平）
_CONFIG_SUBTREE_MAP: tuple[tuple[str, str], ...] = (
    ("browser.slots", "BROWSER_SLOTS"),
    ("risk_control.levels", "RISK_CONTROL_LEVELS"),
    ("ui.labels", "UI_LABELS"),
)


class BrowserSlotLocalConfig(BaseModel):
    """config.yaml 中声明的本机浏览器槽位。"""

    name: str = Field(min_length=1, max_length=64)  # 槽位名（账号绑定取值，如 local-1）
    label: str | None = Field(
        default=None, max_length=100
    )  # 展示名；缺省按「本机浏览器 N」推导
    port: int = Field(ge=1024, le=65535)  # 该槽位的 CDP 调试端口
    profile_dir: Path | None = (
        None  # 用户数据目录；缺省落在 DOUYIN_LOCAL_CDP_USER_DATA_DIR 下
    )
    enabled: bool = True  # 为 False 时不参与槽位列表与账号绑定

    @field_validator("profile_dir")
    @classmethod
    def _resolve_profile_dir(cls, value: Path | None) -> Path | None:
        """把相对 Profile 目录解析到仓库根目录下（与 .env 的相对路径规则一致）。"""
        if value is None or value.is_absolute():
            return value
        return BASE_DIR / value


class BrowserSlotRemoteConfig(BaseModel):
    """config.yaml 中声明的远程（容器）浏览器槽位。"""

    name: str = Field(min_length=1, max_length=64)  # 槽位名（账号绑定取值）
    label: str | None = Field(default=None, max_length=100)  # 展示名；缺省用槽位名
    host: str = Field(min_length=1, max_length=255)  # CDP 主机名或 IP
    port: int = Field(ge=1, le=65535)  # CDP 端口
    viewer_url: str | None = None  # noVNC 等可视化查看地址
    enabled: bool = True  # 为 False 时不参与槽位列表与账号绑定


class BrowserSlotsConfig(BaseModel):
    """浏览器槽位配置：显式声明优先，留空则回落到环境变量派生规则。"""

    local: list[BrowserSlotLocalConfig] = Field(default_factory=list)
    remote: list[BrowserSlotRemoteConfig] = Field(default_factory=list)


class RiskControlLevelConfig(BaseModel):
    """单个请求延迟档位的随机间隔区间（秒）。"""

    interval_seconds: tuple[float, float]

    @model_validator(mode="after")
    def _validate_interval(self) -> Self:
        """校验区间形状：0 < 下限 ≤ 上限。"""
        lower, upper = self.interval_seconds
        if lower <= 0 or upper < lower:
            raise ValueError("interval_seconds 必须是 [下限, 上限]，且 0 < 下限 ≤ 上限")
        return self


class UiLabelsConfig(BaseModel):
    """前端展示文案（可由 config.yaml 覆盖的字典）。

    目前只承载账号状态文案；前端会先按内置默认渲染，取到接口结果后再覆盖，
    因此这里缺键或接口失败都不会影响页面可用性。
    """

    account_status: dict[str, str] = Field(default_factory=dict)


def _config_file_path() -> Path:
    """config.yaml 的位置：CRAWLER_CONFIG_FILE 优先，默认在仓库根目录。"""
    override = os.getenv("CRAWLER_CONFIG_FILE")
    if override and override.strip():
        return Path(override.strip()).expanduser()
    return BASE_DIR / "config.yaml"


def _config_file_paths() -> tuple[Path, ...]:
    """配置文件列表：基础 config.yaml + 可选的 profile 覆盖文件。

    profile 依次取 ``CRAWLER_CONFIG_PROFILE``、``ENVIRONMENT``（默认 local），
    对应 ``config.<profile>.yaml``；文件存在时按**深层合并**覆盖基础配置的叶子键，
    不存在则忽略。与 Spring Boot 的 ``application-<profile>.yml`` 同构。
    """
    base = _config_file_path()
    profile = (
        os.getenv("CRAWLER_CONFIG_PROFILE") or os.getenv("ENVIRONMENT") or "local"
    ).strip()
    if not profile:
        return (base,)
    overlay = base.with_name(f"{base.stem}.{profile}{base.suffix}")
    return (base, overlay)


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """递归合并两个配置字典：同为对象时下钻，否则覆盖层优先。"""
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _load_yaml_config(files: tuple[Path, ...]) -> dict[str, Any]:
    """按顺序读取并深层合并 YAML 配置；缺失文件跳过，顶层必须是对象。

    参数：
        files: 配置文件路径（后者优先）。
    返回：
        合并后的配置字典。
    异常：
        ValueError: 文件内容不是 YAML 对象时抛出。
    """
    merged: dict[str, Any] = {}
    for path in files:
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"配置文件顶层必须是对象：{path}")
        merged = _deep_merge(merged, data)
    return merged


# 占位符解析结果：`${VAR}` 且环境变量缺失时表示「整项不设置」，交回代码默认值
_UNSET = object()

# `${VAR}` / `${VAR:默认值}`；默认值内允许出现除 `}` 以外的字符
_PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")


def _expand_placeholders(value: Any) -> Any:
    """递归展开配置里的 ``${ENV:默认值}`` 占位符（与 Spring 的写法一致）。

    - ``${VAR}``：环境变量缺失时返回 ``_UNSET``（调用方跳过该项，用代码默认值）；
    - ``${VAR:默认}``：环境变量缺失时用默认值；
    - 混合字符串（如 ``prefix-${VAR}``）中的缺失变量替换为空串。

    参数：
        value: 配置值（字符串、字典、列表或其它原样返回）。
    返回：
        展开后的值；整项占位符且变量缺失时返回 ``_UNSET``。
    """
    if isinstance(value, str):
        whole = _PLACEHOLDER_PATTERN.fullmatch(value)
        if whole is not None:
            name, default = whole.group(1), whole.group(2)
            resolved = os.getenv(name)
            if resolved is not None:
                return resolved
            return default if default is not None else _UNSET

        def replace(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            return os.getenv(name, default if default is not None else "")

        return _PLACEHOLDER_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {key: _expand_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_placeholders(item) for item in value]
    return value


def _resolve_yaml_path(raw: dict[str, Any], path: str) -> Any:
    """按点号路径读取 YAML 值；任一层缺失或不是对象时返回 None。

    参数：
        raw: YAML 解析结果。
        path: 形如 ``browser.local.port`` 的分段路径。
    返回：
        命中的值；未命中返回 None。
    """
    current: Any = raw
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


class _ProjectConfigSource(PydanticBaseSettingsSource):
    """把 config.yaml（可叠加 profile 覆盖文件）映射成 Settings 字段。

    本数据源排在环境变量与 .env 之后，因此 YAML 只提供**默认值**，同名项仍以
    「环境变量 > .env.local > .env > config.yaml > 代码默认值」生效；YAML 内部
    支持 ``${ENV:默认值}`` 占位符引用环境变量，便于把「配置全貌」写在一处而
    不把密钥落进文件。
    """

    def __init__(self, settings_cls: type[BaseSettings], files: tuple[Path, ...]):
        """记录待读取的配置文件列表。

        参数：
            settings_cls: 目标 Settings 类。
            files: 按优先级排列的配置文件（后者覆盖前者）。
        """
        super().__init__(settings_cls)
        self._files = files

    def get_field_value(
        self, field: Any, field_name: str
    ) -> tuple[Any, str, bool]:  # pragma: no cover - 抽象方法，取值为空
        """本数据源按映射表整体取值，不走逐字段查询。"""
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        """读取 YAML、展开占位符并按映射表翻译成 Settings 字段。

        空字符串与未命中的占位符都视为「未设置」，交回代码默认值
        （与 pydantic-settings 的 env_ignore_empty 语义一致）。
        """
        raw = _expand_placeholders(_load_yaml_config(self._files))
        if not isinstance(raw, dict):  # pragma: no cover - 加载阶段已校验
            return {}
        payload: dict[str, Any] = {}
        for yaml_path, field_name in _CONFIG_FIELD_MAP:
            value = _resolve_yaml_path(raw, yaml_path)
            if value is None or value is _UNSET or value == "":
                continue
            payload[field_name] = value
        for yaml_path, field_name in _CONFIG_SUBTREE_MAP:
            value = _resolve_yaml_path(raw, yaml_path)
            if value:
                payload[field_name] = value
        return payload


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

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """在 .env 之后、密钥文件之前插入 config.yaml。

        顺序即优先级：环境变量显式覆盖 > 显式入参 > .env.local > .env >
        config.yaml > 代码默认值；config.yaml 缺失时该数据源返回空字典。
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _ProjectConfigSource(settings_cls, _config_file_paths()),
            file_secret_settings,
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
    TESTING: bool = False  # 测试进程标记；启用时强制连接独立的 *_test 数据库

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
    # 本机浏览器槽位：本机可同时托管多个独立 Profile 的 Chrome/Edge，
    # 每个槽位独占绑定一个账号（与远程槽位同一套槽位/绑定语义）。
    # 槽位名为 local-1 … local-N，端口自 DOUYIN_LOCAL_CDP_PORT_BASE 起递增，
    # Profile 落在 DOUYIN_LOCAL_CDP_USER_DATA_DIR/<槽位名> 下。
    DOUYIN_LOCAL_CDP_SLOT_COUNT: int = Field(
        default=4, ge=0, le=32
    )  # 本机浏览器槽位数量，默认 4 个；0 表示不启用本机槽位
    DOUYIN_LOCAL_CDP_PORT_BASE: int = Field(
        default=9333, ge=1024, le=65000
    )  # 本机槽位 CDP 调试端口起始值（第 n 个槽位为 base + n - 1）
    DOUYIN_LOCAL_CDP_USER_DATA_DIR: Path = Path(
        "browser_data/douyin-local"
    )  # 本机槽位 Profile 根目录（相对路径将拼接到仓库根目录）
    # 原生（非容器）后端默认走浏览器容器映射到本机回环地址的端口；
    # compose.yml 会用 Docker DNS 端点覆盖这两项配置。
    DOUYIN_REMOTE_CDP_HOST: str = "127.0.0.1"  # 远程 CDP 浏览器主机名或 IP
    DOUYIN_REMOTE_CDP_PORT: int = 9223  # 远程 CDP 浏览器端口
    # 可选的命名浏览器槽位 JSON 对象。示例：
    # {"account-1":{"host":"127.0.0.1","port":9223,"viewer_url":"http://127.0.0.1:6081/vnc.html?autoconnect=1&resize=scale"}}
    DOUYIN_REMOTE_CDP_SLOTS: str = (
        ""  # 命名浏览器槽位配置（JSON 字符串），空串表示不启用多槽位
    )
    DOUYIN_REMOTE_VIEWER_URL: str = "http://127.0.0.1:6081/vnc.html?autoconnect=1&resize=scale"  # 远程浏览器 noVNC 查看器地址，用于前端展示实时画面
    # config.yaml 承载的结构化业务默认值（YAML 排在环境变量与 .env 之后）
    BROWSER_SLOTS: BrowserSlotsConfig = (
        BrowserSlotsConfig()
    )  # 显式声明的本机/远程槽位；留空回落到上面的派生规则
    RISK_CONTROL_LEVELS: dict[str, RiskControlLevelConfig] = Field(
        default_factory=dict
    )  # 覆盖延迟档位的随机间隔区间（键为 fast / steady / ultra_steady 等档位名）
    UI_LABELS: UiLabelsConfig = (
        UiLabelsConfig()
    )  # 前端展示文案（字典）；缺键时前端用内置默认
    # 账号登录会话的有效期（秒），取值 60~3600，默认 900（15 分钟）
    DOUYIN_ACCOUNT_LOGIN_SESSION_TTL_SECONDS: int = Field(default=900, ge=60, le=3600)
    # 仅为向后兼容保留的环境配置项。账号失败仍会被记录并可将账号标记为不健康，
    # 但不再使账号进入基于时间的冷却状态。
    DOUYIN_ACCOUNT_FAILURE_COOLDOWN_SECONDS: int = Field(
        default=0, ge=0, le=86400
    )  # 账号失败冷却时长（秒），默认 0 表示不冷却
    DOUYIN_LOGIN_TIMEOUT: float = 600.0  # 扫码/账号登录流程的整体超时时间（秒）
    DOUYIN_REQUEST_TIMEOUT: float = 60.0  # 抖音接口单次请求超时时间（秒）
    DOUYIN_ACCOUNT_WAIT_POLL_SECONDS: float = Field(
        default=2.0, gt=0
    )  # 等待账号/账号池出现调度容量时的轮询间隔（秒）
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
    POSTGRES_CONNECT_TIMEOUT: int = Field(
        default=5, ge=1, le=60
    )  # 建连超时（秒）；数据库不可达时快速失败，而非长时间挂起请求

    @model_validator(mode="after")
    def _protect_production_database_from_tests(self) -> Self:
        """测试进程只能连接名称以 ``_test`` 结尾的独立数据库。"""
        if self.TESTING and not self.POSTGRES_DB.lower().endswith("_test"):
            raise ValueError(
                "TESTING=true requires POSTGRES_DB to end with '_test'; "
                "refusing to run tests against a user database"
            )
        return self

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
