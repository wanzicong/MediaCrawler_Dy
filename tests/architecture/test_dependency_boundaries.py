"""Dependency rules for the uv workspace module architecture.

The workspace is a DAG: bootstrap <- browser <- douyin-client <- business <- api,
with mcp depending on bootstrap only.  These tests walk the AST of every module
and fail on any import that crosses the DAG backwards or pulls an inbound
framework into a layer that must stay transport-neutral.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from importlib.util import resolve_name
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

MODULE_ROOTS = {
    "bootstrap": REPO_ROOT / "modules" / "bootstrap" / "src" / "crawler" / "bootstrap",
    "browser": REPO_ROOT / "modules" / "browser" / "src" / "crawler" / "browser",
    "douyin_client": REPO_ROOT
    / "modules"
    / "douyin-client"
    / "src"
    / "crawler"
    / "douyin_client",
    "business": REPO_ROOT / "modules" / "business" / "src" / "crawler" / "business",
    "api": REPO_ROOT / "modules" / "api" / "src" / "crawler" / "api",
    "mcp": REPO_ROOT / "modules" / "mcp" / "src" / "crawler" / "mcp",
}

# crawler.* prefixes each module must never import (self-imports are fine).
FORBIDDEN_CRAWLER_PREFIXES = {
    "bootstrap": (
        "crawler.browser",
        "crawler.douyin_client",
        "crawler.business",
        "crawler.api",
        "crawler.mcp",
    ),
    "browser": (
        "crawler.douyin_client",
        "crawler.business",
        "crawler.api",
        "crawler.mcp",
    ),
    "douyin_client": ("crawler.business", "crawler.api", "crawler.mcp"),
    "business": ("crawler.api", "crawler.mcp"),
    # api -> crawler.mcp is handled separately: only the system_docs
    # introspection route may cross that boundary.
    "api": (),
    "mcp": (
        "crawler.browser",
        "crawler.douyin_client",
        "crawler.business",
        "crawler.api",
    ),
}

# The single registered exception: system_docs introspects MCP tool metadata.
API_MCP_IMPORT_ALLOWLIST = {"routes/system_docs.py"}

# Third-party frameworks each module must never import.
FORBIDDEN_PACKAGES = {
    "bootstrap": {"fastapi", "starlette", "playwright", "minio", "execjs", "uvicorn"},
    "browser": {"fastapi", "starlette", "minio", "execjs", "sqlmodel", "sqlalchemy"},
    "douyin_client": {
        "fastapi",
        "starlette",
        "minio",
        "sqlmodel",
        "sqlalchemy",
        "uvicorn",
    },
    "business": {"fastapi", "starlette", "playwright", "execjs", "uvicorn"},
    "api": {"minio", "playwright", "execjs"},
    "mcp": {"fastapi", "sqlmodel", "sqlalchemy", "minio", "playwright", "execjs"},
}

# Only the storage resource driver may talk to the MinIO SDK directly.
BUSINESS_MINIO_ALLOWED_PREFIX = "resources/storage/"


@dataclass(frozen=True, order=True)
class ImportUse:
    file: str
    module: str
    names: tuple[str, ...]


# Exact persistence imports the HTTP adapter layer is grandfathered into.
# Symbol-level on purpose: even an additional import from an already
# allowlisted module fails the check.
LEGACY_API_IMPORT_ALLOWLIST = {
    ImportUse("deps.py", "sqlmodel", ("Session",)),
    ImportUse("backend_pre_start.py", "sqlmodel", ("Session", "select")),
    ImportUse("backend_pre_start.py", "sqlalchemy", ("Engine",)),
    ImportUse("initial_data.py", "sqlmodel", ("Session",)),
    ImportUse("tests_pre_start.py", "sqlmodel", ("Session", "select")),
    ImportUse("tests_pre_start.py", "sqlalchemy", ("Engine",)),
}

API_PERSISTENCE_PACKAGES = {"sqlalchemy", "sqlmodel"}

# Operational entry scripts legitimately open their own sessions; the HTTP
# adapter surface (routes, deps, router, app assembly) must not.
API_SESSION_CHECK_EXCLUDED = {
    "backend_pre_start.py",
    "initial_data.py",
    "tests_pre_start.py",
}

FORBIDDEN_SESSION_METHODS = {
    "add",
    "commit",
    "delete",
    "exec",
    "execute",
    "flush",
    "get",
    "refresh",
    "rollback",
}


def _python_files(module: str) -> list[Path]:
    return sorted(MODULE_ROOTS[module].rglob("*.py"))


def _relative(module: str, path: Path) -> str:
    return path.relative_to(MODULE_ROOTS[module]).as_posix()


def _package_for(module: str, path: Path) -> str:
    relative = path.relative_to(MODULE_ROOTS[module].parent).with_suffix("")
    return ".".join(relative.parts[:-1])


def _resolve_import_from(node: ast.ImportFrom, package: str) -> str:
    module = node.module or ""
    if not node.level:
        return module
    relative_name = f"{'.' * node.level}{module}"
    return resolve_name(relative_name, package)


def _imported_modules(module: str, path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = _package_for(module, path)
    modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_import_from(node, package)
            if base:
                modules.add(base)
                modules.update(f"{base}.{alias.name}" for alias in node.names)
    return modules


def _violating_crawler_imports(module: str) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    forbidden = FORBIDDEN_CRAWLER_PREFIXES[module]
    for path in _python_files(module):
        for imported_module in _imported_modules(module, path):
            if any(
                imported_module == prefix or imported_module.startswith(f"{prefix}.")
                for prefix in forbidden
            ):
                violations.append((_relative(module, path), imported_module))
    return sorted(violations)


def _violating_third_party_imports(module: str) -> set[ImportUse]:
    violations: set[ImportUse] = set()
    forbidden = FORBIDDEN_PACKAGES[module]
    for path in _python_files(module):
        relative = _relative(module, path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] in forbidden:
                        violations.add(ImportUse(relative, alias.name, ("*",)))
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.split(".", 1)[0] in forbidden
            ):
                violations.add(
                    ImportUse(
                        relative,
                        node.module,
                        tuple(sorted(alias.name for alias in node.names)),
                    )
                )
    return violations


def _api_persistence_imports() -> set[ImportUse]:
    violations: set[ImportUse] = set()
    for path in _python_files("api"):
        relative = _relative("api", path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] in API_PERSISTENCE_PACKAGES:
                        violations.add(ImportUse(relative, alias.name, ("*",)))
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.split(".", 1)[0] in API_PERSISTENCE_PACKAGES
            ):
                violations.add(
                    ImportUse(
                        relative,
                        node.module,
                        tuple(sorted(alias.name for alias in node.names)),
                    )
                )
    return violations


def test_bootstrap_depends_on_no_other_workspace_module() -> None:
    assert not _violating_crawler_imports("bootstrap")


def test_browser_only_depends_on_bootstrap() -> None:
    assert not _violating_crawler_imports("browser")


def test_douyin_client_stays_below_business() -> None:
    assert not _violating_crawler_imports("douyin_client")


def test_business_does_not_depend_on_inbound_layers() -> None:
    assert not _violating_crawler_imports("business")


def test_mcp_remains_an_http_gateway_instead_of_a_second_business_layer() -> None:
    assert not _violating_crawler_imports("mcp")


def test_api_imports_mcp_only_through_system_docs() -> None:
    violations: list[str] = []
    for path in _python_files("api"):
        relative = _relative("api", path)
        if relative in API_MCP_IMPORT_ALLOWLIST:
            continue
        for imported_module in _imported_modules("api", path):
            if imported_module == "crawler.mcp" or imported_module.startswith(
                "crawler.mcp."
            ):
                violations.append(f"{relative} -> {imported_module}")
    assert not violations, (
        f"API 层只有 system_docs 可以自省 MCP 工具元数据：{sorted(violations)}"
    )


def test_bootstrap_and_adapters_stay_transport_neutral() -> None:
    for module in ("bootstrap", "browser", "douyin_client", "business", "mcp"):
        unexpected = _violating_third_party_imports(module)
        assert not unexpected, (
            f"{module} 层不得依赖入站/基础设施框架：{sorted(unexpected)}"
        )


def test_business_only_storage_driver_talks_to_minio() -> None:
    violations: set[ImportUse] = set()
    for path in _python_files("business"):
        relative = _relative("business", path)
        if relative.startswith(BUSINESS_MINIO_ALLOWED_PREFIX):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] in {"minio", "urllib3"}:
                        violations.add(ImportUse(relative, alias.name, ("*",)))
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.split(".", 1)[0] in {"minio", "urllib3"}
            ):
                violations.add(
                    ImportUse(
                        relative,
                        node.module,
                        tuple(sorted(alias.name for alias in node.names)),
                    )
                )
    assert not violations, (
        f"MinIO SDK 只允许出现在 resources/storage 驱动中：{sorted(violations)}"
    )


def test_api_adds_no_direct_infrastructure_dependencies() -> None:
    unexpected = _violating_third_party_imports("api")
    assert not unexpected, (
        f"API 层不得依赖 MinIO/Playwright/ExecJS：{sorted(unexpected)}"
    )


def test_api_adds_no_direct_persistence_dependencies() -> None:
    unexpected = _api_persistence_imports() - LEGACY_API_IMPORT_ALLOWLIST
    assert not unexpected, (
        "API 层不得新增 SQLAlchemy/SQLModel 依赖；"
        f"请将以下逻辑下沉到 business service：{sorted(unexpected)}"
    )


def test_api_layer_does_not_access_persistence_directly() -> None:
    violations: list[tuple[str, int, str]] = []
    for path in _python_files("api"):
        relative = _relative("api", path)
        if relative in API_SESSION_CHECK_EXCLUDED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "session"
                and node.func.attr in FORBIDDEN_SESSION_METHODS
            ):
                violations.append((relative, node.lineno, node.func.attr))

    assert not violations, (
        f"API 层只能调用 business service，不得直接查询或管理事务：{violations}"
    )
