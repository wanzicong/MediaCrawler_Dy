"""config.yaml 到 Settings 字段的映射表（数据表，不含逻辑）。

这张表是 YAML 与配置项之间唯一的真源：架构测试用它逐项验证「YAML 能设进去 +
环境变量能覆盖」，并与「仅环境变量字段」清单共同构成配置来源全覆盖契约。
新增配置项时：先在 ``crawler.bootstrap.config`` 对应域文件加字段，再到这里登记路径。
"""

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
    ("media.subtitle.prefer_audio", "MEDIA_SUBTITLE_PREFER_AUDIO"),
    ("media.subtitle.max_size_mb", "MEDIA_SUBTITLE_MAX_SIZE_MB"),
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
