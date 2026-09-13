"""应用与认证、邮件、MCP 网关三组配置字段。"""

import secrets
from typing import Annotated, Literal

from pydantic import (
    AnyUrl,
    BaseModel,
    BeforeValidator,
    EmailStr,
    HttpUrl,
    SecretStr,
    computed_field,
    model_validator,
)
from typing_extensions import Self

from .base import parse_cors


class AppFields(BaseModel):
    """应用身份、认证、邮件与 MCP 网关相关字段。"""

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

    PROJECT_NAME: str  # 项目名称（必填）
    SENTRY_DSN: HttpUrl | None = None  # Sentry DSN，可选；配置后启用错误上报

    # 邮件通知（口令走环境变量 SMTP_PASSWORD）
    SMTP_TLS: bool = True  # 是否使用 STARTTLS 加密 SMTP 连接
    SMTP_SSL: bool = False  # 是否使用 SSL/TLS 直连 SMTP
    SMTP_PORT: int = 587  # SMTP 服务端口
    SMTP_HOST: str | None = None  # SMTP 服务主机；为空则邮件功能不可用
    SMTP_USER: str | None = None  # SMTP 登录用户名
    SMTP_PASSWORD: str | None = None  # SMTP 登录密码
    EMAILS_FROM_EMAIL: EmailStr | None = None  # 发件人邮箱地址
    EMAILS_FROM_NAME: str | None = None  # 发件人显示名称；未配置时回退为项目名称
    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48  # 密码重置令牌有效期（小时）
    EMAIL_TEST_USER: EmailStr = "test@example.com"  # 测试用户的邮箱地址

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        """发件人名称缺省时回退为项目名称。"""
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        """是否已具备启用邮件功能所需的 SMTP 主机与发件人配置。"""
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    FIRST_SUPERUSER: EmailStr  # 初始超级管理员邮箱（必填）
    FIRST_SUPERUSER_PASSWORD: str  # 初始超级管理员密码（必填）

    # MCP 作为 API 网关，通过既有 FastAPI 登录接口完成认证（口令走环境变量）
    MCP_API_BASE_URL: str = (
        "http://127.0.0.1:8000/api/v1"  # MCP 调用的后端 API 基础地址
    )
    MCP_API_USERNAME: EmailStr | None = None  # MCP 登录账号（邮箱）
    MCP_API_PASSWORD: SecretStr | None = None  # MCP 登录密码
