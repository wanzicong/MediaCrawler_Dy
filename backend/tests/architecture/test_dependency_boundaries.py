"""Dependency rules for the target backend architecture.

The legacy API allowlist is an upper bound: removing an allowlisted dependency is
always valid, while adding a new symbol, module, or file requires moving that work
behind a domain service instead of expanding the allowlist.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from importlib.util import resolve_name
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "app"

FRAMEWORK_FORBIDDEN_PREFIXES = (
    "app.api",
    "app.application",
    "app.domain",
    "app.integrations",
    "app.mcp_server",
)
INTEGRATIONS_FORBIDDEN_PREFIXES = (
    "app.api",
    "app.application",
    "app.domain",
    "app.mcp_server",
)
DOMAIN_FORBIDDEN_PREFIXES = (
    "app.api",
    "app.application",
    "app.integrations",
    "app.mcp_server",
)
APPLICATION_FORBIDDEN_PREFIXES = (
    "app.api",
    "app.mcp_server",
)
APPLICATION_FORBIDDEN_PACKAGES = {"fastapi", "minio", "playwright", "starlette"}
MCP_FORBIDDEN_PREFIXES = (
    "app.application",
    "app.domain",
    "app.integrations",
)
API_FORBIDDEN_PACKAGES = {"minio", "playwright", "sqlalchemy", "sqlmodel"}


@dataclass(frozen=True, order=True)
class ImportUse:
    file: str
    module: str
    names: tuple[str, ...]


# Exact legacy imports that predate the layered refactor.  This is intentionally
# symbol-level: even an additional import from an already allowlisted module fails.
LEGACY_API_IMPORT_ALLOWLIST = {
    ImportUse("api/deps.py", "sqlmodel", ("Session",)),
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


def _python_files(package: str) -> list[Path]:
    package_root = APP_ROOT / package
    if not package_root.exists():
        return []
    return sorted(package_root.rglob("*.py"))


def _package_for(path: Path) -> str:
    relative = path.relative_to(APP_ROOT.parent).with_suffix("")
    return ".".join(relative.parts[:-1])


def _resolve_import_from(node: ast.ImportFrom, package: str) -> str:
    module = node.module or ""
    if not node.level:
        return module
    relative_name = f"{'.' * node.level}{module}"
    return resolve_name(relative_name, package)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = _package_for(path)
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


def _violating_internal_imports(
    package: str,
    forbidden_prefixes: tuple[str, ...],
) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    for path in _python_files(package):
        relative = path.relative_to(APP_ROOT).as_posix()
        for imported_module in _imported_modules(path):
            if any(
                imported_module == prefix or imported_module.startswith(f"{prefix}.")
                for prefix in forbidden_prefixes
            ):
                violations.append((relative, imported_module))
    return sorted(violations)


def _api_forbidden_imports() -> set[ImportUse]:
    violations: set[ImportUse] = set()
    for path in _python_files("api"):
        relative = path.relative_to(APP_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] in API_FORBIDDEN_PACKAGES:
                        violations.add(ImportUse(relative, alias.name, ("*",)))
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.split(".", 1)[0] in API_FORBIDDEN_PACKAGES
            ):
                violations.add(
                    ImportUse(
                        relative,
                        node.module,
                        tuple(sorted(alias.name for alias in node.names)),
                    )
                )
    return violations


def _application_forbidden_imports() -> set[ImportUse]:
    violations: set[ImportUse] = set()
    for path in _python_files("application"):
        relative = path.relative_to(APP_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] in APPLICATION_FORBIDDEN_PACKAGES:
                        violations.add(ImportUse(relative, alias.name, ("*",)))
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.split(".", 1)[0] in APPLICATION_FORBIDDEN_PACKAGES
            ):
                violations.add(
                    ImportUse(
                        relative,
                        node.module,
                        tuple(sorted(alias.name for alias in node.names)),
                    )
                )
    return violations


def test_framework_has_no_inward_business_dependencies() -> None:
    assert not _violating_internal_imports(
        "framework",
        FRAMEWORK_FORBIDDEN_PREFIXES,
    )


def test_integrations_do_not_depend_on_inbound_or_domain_layers() -> None:
    assert not _violating_internal_imports(
        "integrations",
        INTEGRATIONS_FORBIDDEN_PREFIXES,
    )


def test_domain_does_not_depend_on_orchestration_or_adapters() -> None:
    assert not _violating_internal_imports(
        "domain",
        DOMAIN_FORBIDDEN_PREFIXES,
    )


def test_application_does_not_depend_on_inbound_layers() -> None:
    assert not _violating_internal_imports(
        "application",
        APPLICATION_FORBIDDEN_PREFIXES,
    )


def test_application_does_not_import_http_or_storage_frameworks() -> None:
    unexpected = _application_forbidden_imports()
    assert not unexpected, (
        "Application 层必须使用 transport-neutral contracts，"
        "不得直接依赖 FastAPI/Starlette/MinIO/Playwright 类型："
        f"{sorted(unexpected)}"
    )


def test_mcp_remains_an_http_gateway_instead_of_a_second_business_layer() -> None:
    assert not _violating_internal_imports(
        "mcp_server",
        MCP_FORBIDDEN_PREFIXES,
    )


def test_api_adds_no_direct_infrastructure_dependencies() -> None:
    unexpected = _api_forbidden_imports() - LEGACY_API_IMPORT_ALLOWLIST
    assert not unexpected, (
        "API 层不得新增 SQLAlchemy/SQLModel/MinIO/Playwright 依赖；"
        f"请将以下逻辑下沉到 application service：{sorted(unexpected)}"
    )


def test_api_layer_does_not_access_persistence_directly() -> None:
    violations: list[tuple[str, int, str]] = []
    for path in _python_files("api"):
        relative = path.relative_to(APP_ROOT).as_posix()
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
        f"API 层只能调用 application service，不得直接查询或管理事务：{violations}"
    )
