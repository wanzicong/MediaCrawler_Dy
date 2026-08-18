"""让静态架构测试独立于运行中的 PostgreSQL 服务。"""

from collections.abc import Generator

import pytest


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[None, None, None]:
    """覆盖集成测试套件的数据库初始化夹具，使静态架构测试无需真实数据库。"""

    yield
