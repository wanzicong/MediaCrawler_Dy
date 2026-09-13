"""配置来源契约：config.yaml 只提供默认值，环境变量与 .env 始终优先。

把「谁覆盖谁」钉成可执行契约——YAML 缺失时回落代码默认、YAML 存在时提供默认值、
环境变量能压过 YAML，以及出厂 config.yaml 本身合法且档位名与 API 契约一致。
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml
from crawler.bootstrap.settings import (
    _CONFIG_FIELD_MAP,
    _CONFIG_SUBTREE_MAP,
    BASE_DIR,
    Settings,
    settings,
)
from crawler.business.douyin.accounts.models import DouyinAccountStatus
from crawler.business.douyin.tasks.models import DouyinRequestDelayLevel

# 不读 .env 时仍需满足的必填项
_REQUIRED = {
    "PROJECT_NAME": "config-contract",
    "POSTGRES_SERVER": "localhost",
    "POSTGRES_USER": "postgres",
    "POSTGRES_DB": "app_test",
    "FIRST_SUPERUSER": "config-contract@example.com",
    "FIRST_SUPERUSER_PASSWORD": "changethis",
}

# 只从环境变量读取的字段：密钥、连接串、环境标识与兼容项。
# 这张清单与 _CONFIG_FIELD_MAP 一起构成「配置来源全覆盖」契约——新增配置项必须
# 二选一登记，避免出现「既不在 YAML 映射、也没人声明它只能走 env」的野生字段。
_ENV_ONLY_FIELDS = frozenset(
    {
        "ACCESS_TOKEN_EXPIRE_MINUTES",
        "API_V1_STR",
        "BACKEND_CORS_ORIGINS",
        "DOUYIN_REMOTE_CDP_SLOTS",
        "EMAILS_FROM_EMAIL",
        "EMAILS_FROM_NAME",
        "EMAIL_RESET_TOKEN_EXPIRE_HOURS",
        "EMAIL_TEST_USER",
        "ENVIRONMENT",
        "FIRST_SUPERUSER",
        "FIRST_SUPERUSER_PASSWORD",
        "FRONTEND_HOST",
        "MCP_API_BASE_URL",
        "MCP_API_PASSWORD",
        "MCP_API_USERNAME",
        "MINIO_ACCESS_KEY",
        "MINIO_BUCKET",
        "MINIO_ENDPOINT",
        "MINIO_REGION",
        "MINIO_SECRET_KEY",
        "MINIO_SECURE",
        "POSTGRES_CONNECT_TIMEOUT",
        "POSTGRES_DB",
        "POSTGRES_PASSWORD",
        "POSTGRES_PORT",
        "POSTGRES_SERVER",
        "POSTGRES_USER",
        "PROJECT_NAME",
        "SECRET_KEY",
        "SENTRY_DSN",
        "SMTP_HOST",
        "SMTP_PASSWORD",
        "SMTP_PORT",
        "SMTP_SSL",
        "SMTP_TLS",
        "SMTP_USER",
        "TESTING",
        "WHISPER_API_KEY",
    }
)

# 用例会断言的、可能被本机环境变量污染的配置项
_WATCHED_ENV = tuple(field for _, field in _CONFIG_FIELD_MAP)


def _yaml_document(path: str, value: Any) -> str:
    """把 ``a.b.c: value`` 展开成嵌套 YAML 文档。"""
    payload: dict[str, Any] = {}
    cursor = payload
    segments = path.split(".")
    for segment in segments[:-1]:
        cursor = cursor.setdefault(segment, {})
    cursor[segments[-1]] = value
    return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)


def _sentinel(field_name: str) -> tuple[Any, str, Any, Any]:
    """按目标字段类型生成哨兵值。

    返回：
        (YAML 值, 环境变量字符串, YAML 生效后的期望值, 环境变量覆盖后的期望值)。
    """
    field = Settings.model_fields[field_name]
    annotation = field.annotation
    default = field.default
    literal_values = get_args(annotation)
    if literal_values and all(isinstance(item, str) for item in literal_values):
        # Literal 字段（如浏览器模式、存储后端）取一个与当前默认不同的合法值
        chosen = next(item for item in literal_values if item != default)
        return chosen, chosen, chosen, chosen
    if annotation is bool:
        return (
            not default,
            "true" if not default else "false",
            not default,
            not default,
        )
    if annotation is int:
        return default + 1, str(default + 1), default + 1, default + 1
    if annotation is float:
        return default + 1.0, str(default + 1.0), default + 1.0, default + 1.0
    if annotation is Path:
        return (
            "yaml-sentinel-dir",
            "env-sentinel-dir",
            BASE_DIR / "yaml-sentinel-dir",
            BASE_DIR / "env-sentinel-dir",
        )
    return "yaml-sentinel", "env-sentinel", "yaml-sentinel", "env-sentinel"


def _clear_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """清掉本机可能存在的同名环境变量，保证断言只反映 YAML 与代码默认值。"""
    for name in _WATCHED_ENV:
        monkeypatch.delenv(name, raising=False)


def _settings_with(monkeypatch: pytest.MonkeyPatch, config_path: Path) -> Settings:
    """按指定 config.yaml 构造 Settings；`_env_file=None` 表示不读 .env / .env.local。"""
    monkeypatch.setenv("CRAWLER_CONFIG_FILE", str(config_path))
    return Settings(_env_file=None, **_REQUIRED)


def _write_config(tmp_path: Path, body: str) -> Path:
    """把 YAML 片段写入临时 config.yaml 并返回路径。"""
    path = tmp_path / "config.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_yaml_provides_defaults_and_environment_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """验证 config.yaml 提供默认值，而环境变量可以覆盖它。"""
    config_path = _write_config(
        tmp_path,
        """
        browser:
          default_mode: local
        risk_control:
          limits:
            max_active_tasks: 3
          levels:
            fast: {interval_seconds: [0.3, 0.5]}
        """,
    )
    _clear_overrides(monkeypatch)

    configured = _settings_with(monkeypatch, config_path)
    assert configured.DOUYIN_BROWSER_MODE == "local"
    assert configured.DOUYIN_MAX_ACTIVE_TASKS == 3
    assert configured.RISK_CONTROL_LEVELS["fast"].interval_seconds == (0.3, 0.5)
    # YAML 没声明的上限沿用代码默认值
    assert configured.DOUYIN_MAX_AWEMES_PER_TASK == 1000

    monkeypatch.setenv("DOUYIN_MAX_ACTIVE_TASKS", "9")
    overridden = _settings_with(monkeypatch, config_path)
    assert overridden.DOUYIN_MAX_ACTIVE_TASKS == 9
    assert overridden.DOUYIN_BROWSER_MODE == "local"  # 未覆盖的项仍来自 YAML


def test_missing_config_file_falls_back_to_code_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """验证没有 config.yaml 时一切回落到代码默认（部署不因缺文件而失败）。"""
    _clear_overrides(monkeypatch)

    fallback = _settings_with(monkeypatch, tmp_path / "missing.yaml")

    assert fallback.DOUYIN_BROWSER_MODE == "remote"
    assert fallback.DOUYIN_MAX_ACTIVE_TASKS == 1
    assert fallback.DOUYIN_MAX_AWEMES_PER_TASK == 1000
    assert fallback.DOUYIN_MAX_COMMENTS_PER_AWEME == 1000
    assert fallback.RISK_CONTROL_LEVELS == {}
    assert fallback.BROWSER_SLOTS.local == []
    assert fallback.BROWSER_SLOTS.remote == []


def test_slots_are_parsed_from_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """验证槽位声明被解析：相对 Profile 目录解析到仓库根，禁用槽位保留标记。"""
    config_path = _write_config(
        tmp_path,
        """
        browser:
          slots:
            local:
              - {name: local-1, label: 本机一号, port: 9333, profile_dir: browser_data/douyin-local/local-1}
              - {name: local-2, port: 9334, enabled: false}
            remote:
              - {name: pool-1, host: douyin-browser-1, port: 9222}
        """,
    )
    _clear_overrides(monkeypatch)

    parsed = _settings_with(monkeypatch, config_path)

    first, disabled = parsed.BROWSER_SLOTS.local
    assert (first.name, first.label, first.port) == ("local-1", "本机一号", 9333)
    assert first.profile_dir == BASE_DIR / "browser_data/douyin-local/local-1"
    assert disabled.enabled is False
    remote = parsed.BROWSER_SLOTS.remote[0]
    assert (remote.name, remote.host, remote.port) == (
        "pool-1",
        "douyin-browser-1",
        9222,
    )


def test_shipped_config_file_is_valid_and_uses_known_delay_levels() -> None:
    """验证出厂 config.yaml 存在、可被解析，且档位名落在 API 契约的枚举内。"""
    config_path = BASE_DIR / "config.yaml"
    assert config_path.exists(), "仓库根目录必须提供 config.yaml"

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    levels = set((raw.get("risk_control") or {}).get("levels") or {})
    known = {level.value for level in DouyinRequestDelayLevel}
    assert levels, "出厂配置必须声明风控档位"
    assert levels <= known, f"config.yaml 出现未知档位：{sorted(levels - known)}"

    # 出厂配置的账号状态文案必须覆盖 API 契约里的全部状态
    account_status_labels = set(
        ((raw.get("ui") or {}).get("labels") or {}).get("account_status") or {}
    )
    known_statuses = {status.value for status in DouyinAccountStatus}
    assert account_status_labels == known_statuses, (
        "config.yaml 的 ui.labels.account_status 必须与账号状态枚举一一对应："
        f"缺少 {sorted(known_statuses - account_status_labels)}，"
        f"多余 {sorted(account_status_labels - known_statuses)}"
    )

    # 全局单例确实读到了该文件（说明挂载/路径正确）
    assert set(settings.RISK_CONTROL_LEVELS) == levels
    assert set(settings.UI_LABELS.account_status) == known_statuses


def test_config_sources_cover_every_settings_field() -> None:
    """验证每个配置项都被显式归类：要么能由 config.yaml 提供，要么声明为仅环境变量。"""
    mapped = {field for _, field in _CONFIG_FIELD_MAP} | {
        field for _, field in _CONFIG_SUBTREE_MAP
    }

    assert not (mapped & _ENV_ONLY_FIELDS), "同一字段不能既映射 YAML 又声明为仅环境变量"
    missing = set(Settings.model_fields) - mapped - _ENV_ONLY_FIELDS
    assert not missing, f"以下配置项没有登记来源：{sorted(missing)}"
    stale = mapped | _ENV_ONLY_FIELDS
    assert not (stale - set(Settings.model_fields)), (
        f"登记了不存在的配置项：{sorted(stale - set(Settings.model_fields))}"
    )


@pytest.mark.parametrize(
    ("yaml_path", "field_name"),
    _CONFIG_FIELD_MAP,
    ids=[path for path, _ in _CONFIG_FIELD_MAP],
)
def test_yaml_mapping_flows_and_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    yaml_path: str,
    field_name: str,
) -> None:
    """逐项验证映射表：YAML 能把值设进去，且同名环境变量仍然优先。"""
    yaml_value, env_value, expected_yaml, expected_env = _sentinel(field_name)
    config_path = _write_config(tmp_path, _yaml_document(yaml_path, yaml_value))
    # 清掉本机可能存在的所有映射项环境变量，保证第一次断言只反映 YAML
    for name in _WATCHED_ENV:
        monkeypatch.delenv(name, raising=False)

    assert (
        getattr(_settings_with(monkeypatch, config_path), field_name) == expected_yaml
    ), f"{yaml_path} 未映射到 {field_name}"

    monkeypatch.setenv(field_name, env_value)
    assert (
        getattr(_settings_with(monkeypatch, config_path), field_name) == expected_env
    ), f"{field_name} 的环境变量未能覆盖 config.yaml"
