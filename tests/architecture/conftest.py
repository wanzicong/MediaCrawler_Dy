"""Keep static architecture tests independent from the running PostgreSQL service."""

from collections.abc import Generator

import pytest


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[None, None, None]:
    """Override the integration-suite database bootstrap for static tests."""

    yield
