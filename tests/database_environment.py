"""Import-time environment bootstrap for database-isolated tests."""

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]


def _read_local_env(name: str) -> str | None:
    """Read one value without overriding an explicitly supplied environment."""
    for env_path in (ROOT_DIR / ".env.local", ROOT_DIR / ".env"):
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip().strip('"').strip("'")
    return None


def configure_test_database() -> None:
    """Switch settings to the dedicated test database before app imports."""
    production_db = os.getenv("POSTGRES_DB") or _read_local_env("POSTGRES_DB")
    if not production_db:
        raise RuntimeError("POSTGRES_DB is required before running tests")
    test_db = (
        os.getenv("TEST_POSTGRES_DB")
        or _read_local_env("TEST_POSTGRES_DB")
        or f"{production_db}_test"
    )
    if test_db == production_db or not test_db.lower().endswith("_test"):
        raise RuntimeError(
            "Tests require a dedicated database whose name ends with '_test'"
        )

    for name in ("POSTGRES_SERVER", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        value = os.getenv(name) or _read_local_env(name)
        if value:
            os.environ[name] = value

    server = os.environ.get("POSTGRES_SERVER", "")
    if server in {"localhost", "127.0.0.1", "::1"}:
        host_port = (
            os.getenv("TEST_POSTGRES_PORT")
            or _read_local_env("TEST_POSTGRES_PORT")
            or _read_local_env("POSTGRES_HOST_PORT")
        )
        if host_port:
            os.environ["POSTGRES_PORT"] = host_port

    os.environ["POSTGRES_DB"] = test_db
    os.environ["TESTING"] = "true"


configure_test_database()
