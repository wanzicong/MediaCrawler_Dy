"""测试运行时的数据库隔离防线。"""

import pytest
from crawler.bootstrap.settings import Settings, settings
from pydantic import ValidationError


def test_pytest_uses_dedicated_test_database() -> None:
    """pytest 不得连接用户正在使用的数据库。"""
    assert settings.TESTING is True
    assert settings.POSTGRES_DB.lower().endswith("_test")


def test_testing_mode_refuses_user_database() -> None:
    """即使调用方配置错误，应用设置层也必须拒绝用户数据库。"""
    with pytest.raises(ValidationError, match="requires POSTGRES_DB to end"):
        Settings(TESTING=True, POSTGRES_DB="app")  # type: ignore[call-arg]
