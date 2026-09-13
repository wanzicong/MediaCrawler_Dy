"""config.yaml 数据源：文件定位、深层合并、占位符展开与字段映射。

本模块只做「把 YAML 变成一份扁平字段字典」，不含任何字段定义；映射表由调用方
（``crawler.bootstrap.settings``）传入，避免与字段定义互相依赖。
"""

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from .base import BASE_DIR

# 占位符解析结果：`${VAR}` 且环境变量缺失时表示「整项不设置」，交回代码默认值
UNSET = object()

# `${VAR}` / `${VAR:默认值}`；默认值内允许出现除 `}` 以外的字符
PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")


def config_file_path() -> Path:
    """基础配置文件位置：``CRAWLER_CONFIG_FILE`` 优先，默认在仓库根目录。"""
    override = os.getenv("CRAWLER_CONFIG_FILE")
    if override and override.strip():
        return Path(override.strip()).expanduser()
    return BASE_DIR / "config.yaml"


def config_file_paths() -> tuple[Path, ...]:
    """配置文件列表：基础 config.yaml + 可选的 profile 覆盖文件。

    profile 依次取 ``CRAWLER_CONFIG_PROFILE``、``ENVIRONMENT``（默认 local），
    对应 ``config.<profile>.yaml``；文件存在时按**深层合并**覆盖基础配置的叶子键，
    不存在则忽略。与 Spring Boot 的 ``application-<profile>.yml`` 同构。
    """
    base = config_file_path()
    profile = (
        os.getenv("CRAWLER_CONFIG_PROFILE") or os.getenv("ENVIRONMENT") or "local"
    ).strip()
    if not profile:
        return (base,)
    overlay = base.with_name(f"{base.stem}.{profile}{base.suffix}")
    return (base, overlay)


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """递归合并两个配置字典：同为对象时下钻，否则覆盖层优先。"""
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def load_yaml_config(files: tuple[Path, ...]) -> dict[str, Any]:
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
        merged = deep_merge(merged, data)
    return merged


def expand_placeholders(value: Any) -> Any:
    """递归展开配置里的 ``${ENV:默认值}`` 占位符（与 Spring 的写法一致）。

    - ``${VAR}``：环境变量缺失时返回 ``UNSET``（调用方跳过该项，用代码默认值）；
    - ``${VAR:默认}``：环境变量缺失时用默认值；
    - 混合字符串（如 ``prefix-${VAR}``）中的缺失变量替换为空串。

    参数：
        value: 配置值（字符串、字典、列表或其它原样返回）。
    返回：
        展开后的值；整项占位符且变量缺失时返回 ``UNSET``。
    """
    if isinstance(value, str):
        whole = PLACEHOLDER_PATTERN.fullmatch(value)
        if whole is not None:
            name, default = whole.group(1), whole.group(2)
            resolved = os.getenv(name)
            if resolved is not None:
                return resolved
            return default if default is not None else UNSET

        def replace(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            return os.getenv(name, default if default is not None else "")

        return PLACEHOLDER_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {key: expand_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_placeholders(item) for item in value]
    return value


def resolve_yaml_path(raw: dict[str, Any], path: str) -> Any:
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


class ProjectConfigSource(PydanticBaseSettingsSource):
    """把 config.yaml（可叠加 profile 覆盖文件）映射成 Settings 字段。

    本数据源排在环境变量与 .env 之后，因此 YAML 只提供**默认值**，同名项仍以
    「环境变量 > .env.local > .env > config.yaml > 代码默认值」生效；YAML 内部
    支持 ``${ENV:默认值}`` 占位符引用环境变量，便于把「配置全貌」写在一处而
    不把密钥落进文件。
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        files: tuple[Path, ...],
        field_map: tuple[tuple[str, str], ...],
        subtree_map: tuple[tuple[str, str], ...],
    ) -> None:
        """记录配置文件列表与字段映射表。

        参数：
            settings_cls: 目标 Settings 类。
            files: 按优先级排列的配置文件（后者覆盖前者）。
            field_map: ``(YAML 路径, Settings 字段名)`` 列表（标量字段）。
            subtree_map: 整棵子树直接映射为结构化字段的 ``(YAML 路径, 字段名)`` 列表。
        """
        super().__init__(settings_cls)
        self._files = files
        self._field_map = field_map
        self._subtree_map = subtree_map

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
        raw = expand_placeholders(load_yaml_config(self._files))
        if not isinstance(raw, dict):  # pragma: no cover - 加载阶段已校验
            return {}
        payload: dict[str, Any] = {}
        for yaml_path, field_name in self._field_map:
            value = resolve_yaml_path(raw, yaml_path)
            if value is None or value is UNSET or value == "":
                continue
            payload[field_name] = value
        for yaml_path, field_name in self._subtree_map:
            value = resolve_yaml_path(raw, yaml_path)
            if value:
                payload[field_name] = value
        return payload


__all__ = [
    "PLACEHOLDER_PATTERN",
    "UNSET",
    "ProjectConfigSource",
    "config_file_path",
    "config_file_paths",
    "deep_merge",
    "expand_placeholders",
    "load_yaml_config",
    "resolve_yaml_path",
]
