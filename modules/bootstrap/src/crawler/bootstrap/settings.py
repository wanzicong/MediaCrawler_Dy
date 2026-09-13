"""应用运行时配置定义：基于 pydantic-settings 的集中式环境配置。

配置来源（优先级从高到低）：显式入参 > 环境变量 > .env.local > .env >
仓库根目录的 config.yaml（可叠加 config.<profile>.yaml）> 代码默认值。
`config.yaml` 承载非密钥配置项并支持 ``${ENV:默认值}`` 占位符；密钥只从环境变量读取。

字段本身按域拆分在 ``crawler.bootstrap.config`` 包内（每个模块一个域），本模块只负责：
**组装字段 + 对齐 YAML 数据源 + 跨域校验 + 暴露全局单例 settings**。
"""

import warnings

from crawler.bootstrap.config.app_fields import AppFields
from crawler.bootstrap.config.base import BASE_DIR, RELATIVE_PATH_FIELDS
from crawler.bootstrap.config.browser_fields import (
    BrowserFields,
    BrowserSlotLocalConfig,
    BrowserSlotRemoteConfig,
    BrowserSlotsConfig,
)
from crawler.bootstrap.config.douyin_fields import DouyinFields, RiskControlLevelConfig
from crawler.bootstrap.config.field_map import (
    _CONFIG_FIELD_MAP,
    _CONFIG_SUBTREE_MAP,
)
from crawler.bootstrap.config.infra_fields import InfraFields
from crawler.bootstrap.config.media_fields import MediaFields
from crawler.bootstrap.config.ui_fields import UiFields, UiLabelsConfig
from crawler.bootstrap.config.yaml_source import ProjectConfigSource, config_file_paths
from pydantic import model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from typing_extensions import Self


class Settings(
    AppFields,
    InfraFields,
    BrowserFields,
    DouyinFields,
    MediaFields,
    UiFields,
    BaseSettings,
):
    """全局应用配置：字段按域拆分在 config 包，这里只做组装与跨域校验。"""

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
            ProjectConfigSource(
                settings_cls,
                config_file_paths(),
                _CONFIG_FIELD_MAP,
                _CONFIG_SUBTREE_MAP,
            ),
            file_secret_settings,
        )

    @model_validator(mode="after")
    def _protect_production_database_from_tests(self) -> Self:
        """测试进程只能连接名称以 ``_test`` 结尾的独立数据库。"""
        if self.TESTING and not self.POSTGRES_DB.lower().endswith("_test"):
            raise ValueError(
                "TESTING=true requires POSTGRES_DB to end with '_test'; "
                "refusing to run tests against a user database"
            )
        return self

    @model_validator(mode="after")
    def _resolve_relative_paths(self) -> Self:
        """将相对路径配置项统一解析为基于仓库根目录的绝对路径。"""
        for field_name in RELATIVE_PATH_FIELDS:
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

# 兼容既有导入路径：字段类与映射表仍可从 crawler.bootstrap.settings 取到
__all__ = [
    "BASE_DIR",
    "AppFields",
    "BrowserFields",
    "BrowserSlotLocalConfig",
    "BrowserSlotRemoteConfig",
    "BrowserSlotsConfig",
    "DouyinFields",
    "InfraFields",
    "MediaFields",
    "RiskControlLevelConfig",
    "Settings",
    "UiFields",
    "UiLabelsConfig",
    "settings",
]
