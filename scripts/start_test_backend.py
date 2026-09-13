"""Start an isolated backend for browser tests.

The script refreshes the dedicated test database before importing any crawler
module, applies migrations, seeds required identities, and then starts FastAPI.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _docker_command() -> list[str]:
    """返回可用的 docker CLI：Windows 侧没装 docker CLI 时退回 WSL 里的 docker。"""
    if shutil.which("docker"):
        return ["docker"]
    if shutil.which("wsl"):
        return ["wsl", "-e", "docker"]
    raise RuntimeError("找不到 docker CLI，也无法通过 wsl 调用 docker")


def _load_environment_file(path: Path, *, override: bool) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if override or name.strip() not in os.environ:
            os.environ[name.strip()] = value.strip().strip('"').strip("'")


def _test_environment() -> dict[str, str]:
    _load_environment_file(REPOSITORY_ROOT / ".env", override=False)
    _load_environment_file(REPOSITORY_ROOT / ".env.local", override=True)
    production_db = os.environ.get("POSTGRES_DB", "")
    test_db = os.environ.get("TEST_POSTGRES_DB", f"{production_db}_test")
    if test_db == production_db or not test_db.lower().endswith("_test"):
        raise RuntimeError(f"Refusing non-test database: {test_db!r}")

    environment = os.environ.copy()
    environment.update(
        {
            "TESTING": "true",
            "POSTGRES_DB": test_db,
            "POSTGRES_SERVER": "127.0.0.1",
            "POSTGRES_PORT": environment.get(
                "TEST_POSTGRES_PORT",
                environment.get("POSTGRES_HOST_PORT", "55432"),
            ),
            "FRONTEND_HOST": "http://127.0.0.1:5174",
            # Playwright captures the server process through a pipe. Force UTF-8
            # so Windows' legacy console encoding cannot break server startup.
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )
    return environment


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    environment = _test_environment()
    # 测试库刷新由 db 容器里的 pg_dump / pg_restore 完成（原 test-db-prepare 服务已移除）
    subprocess.run(
        [
            *_docker_command(),
            "compose",
            "-f",
            "compose.infra.yml",
            "exec",
            "-T",
            "db",
            "sh",
            "/usr/local/bin/prepare-test-database",
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
    )
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=REPOSITORY_ROOT / "modules/business",
        env=environment,
        check=True,
    )
    subprocess.run(
        ["uv", "run", "python", "-m", "crawler.api.initial_data"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=True,
    )
    subprocess.run(
        [
            "uv",
            "run",
            "uvicorn",
            "crawler.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
            "--workers",
            "1",
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=True,
    )


if __name__ == "__main__":
    main()
