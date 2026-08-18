"""uv workspace 模块架构的依赖方向规则。

workspace 构成一个 DAG：bootstrap <- browser <- douyin-client <- business <- api，
mcp 仅依赖 bootstrap。这些测试遍历每个模块的 AST，一旦出现反向跨越 DAG 的
import，或把入站框架引入必须保持传输层中立的分层，测试即失败。
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

# 各模块禁止 import 的 crawler.* 前缀（import 自身不受限）。
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
    # api -> crawler.mcp 单独处理：仅允许 system_docs 自省路由跨越该边界。
    "api": (),
    "mcp": (
        "crawler.browser",
        "crawler.douyin_client",
        "crawler.business",
        "crawler.api",
    ),
}

# 唯一登记的例外：system_docs 需要自省 MCP 工具元数据。
API_MCP_IMPORT_ALLOWLIST = {"routes/system_docs.py"}

# 各模块禁止 import 的第三方框架。
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

# 仅允许 storage 资源驱动直接调用 MinIO SDK。
BUSINESS_MINIO_ALLOWED_PREFIX = "resources/storage/"


@dataclass(frozen=True, order=True)
class ImportUse:
    """一条具体的 import 使用记录，用于精确比对豁免清单。"""

    file: str  # 发生 import 的相对文件路径
    module: str  # 被 import 的模块名
    names: tuple[str, ...]  # 被 import 的符号名（整体 import 时为 ("*",)）


# HTTP 适配层被豁免的既有持久化 import 清单。
# 刻意精确到符号级：即使是已豁免模块中新增一个 import 也会判定违规。
LEGACY_API_IMPORT_ALLOWLIST = {
    ImportUse("deps.py", "sqlmodel", ("Session",)),
    ImportUse("backend_pre_start.py", "sqlmodel", ("Session", "select")),
    ImportUse("backend_pre_start.py", "sqlalchemy", ("Engine",)),
    ImportUse("initial_data.py", "sqlmodel", ("Session",)),
    ImportUse("tests_pre_start.py", "sqlmodel", ("Session", "select")),
    ImportUse("tests_pre_start.py", "sqlalchemy", ("Engine",)),
}

API_PERSISTENCE_PACKAGES = {"sqlalchemy", "sqlmodel"}

# 运维入口脚本可以合法地自行开启会话；HTTP 适配层
# （routes、deps、router、app 组装）则不允许。
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
    """返回模块根目录下全部 .py 文件（按路径排序）。"""
    return sorted(MODULE_ROOTS[module].rglob("*.py"))


def _relative(module: str, path: Path) -> str:
    """返回文件相对模块根目录的 POSIX 风格路径。"""
    return path.relative_to(MODULE_ROOTS[module]).as_posix()


def _package_for(module: str, path: Path) -> str:
    """根据文件路径推导其所在的 Python 包名（用于解析相对 import）。"""
    relative = path.relative_to(MODULE_ROOTS[module].parent).with_suffix("")
    return ".".join(relative.parts[:-1])


def _resolve_import_from(node: ast.ImportFrom, package: str) -> str:
    """将 ImportFrom 节点解析为绝对模块名（处理相对 import）。"""
    module = node.module or ""
    if not node.level:
        return module
    relative_name = f"{'.' * node.level}{module}"
    return resolve_name(relative_name, package)


def _imported_modules(module: str, path: Path) -> set[str]:
    """解析文件 AST，返回其 import 的全部模块（含 from import 的符号级路径）。"""
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
    """返回模块内违反 crawler.* 依赖方向规则的 (文件, 被 import 模块) 列表。"""
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
    """返回模块内 import 被禁第三方框架的 ImportUse 集合。"""
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
    """返回 api 层全部 SQLAlchemy/SQLModel import 的 ImportUse 集合。"""
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
    """验证 bootstrap 不依赖任何其他 workspace 模块。"""
    assert not _violating_crawler_imports("bootstrap")


def test_browser_only_depends_on_bootstrap() -> None:
    """验证 browser 仅依赖 bootstrap。"""
    assert not _violating_crawler_imports("browser")


def test_douyin_client_stays_below_business() -> None:
    """验证 douyin_client 位于 business 之下，不反向依赖上层模块。"""
    assert not _violating_crawler_imports("douyin_client")


def test_business_does_not_depend_on_inbound_layers() -> None:
    """验证 business 不依赖 api/mcp 等入站分层。"""
    assert not _violating_crawler_imports("business")


def test_mcp_remains_an_http_gateway_instead_of_a_second_business_layer() -> None:
    """验证 mcp 保持 HTTP 网关定位，不反向依赖其他 workspace 模块。"""
    assert not _violating_crawler_imports("mcp")


def test_api_imports_mcp_only_through_system_docs() -> None:
    """验证 api 层仅允许 system_docs 路由 import crawler.mcp。"""
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
    """验证 bootstrap 与各适配层不 import 入站/基础设施框架，保持传输中立。"""
    for module in ("bootstrap", "browser", "douyin_client", "business", "mcp"):
        unexpected = _violating_third_party_imports(module)
        assert not unexpected, (
            f"{module} 层不得依赖入站/基础设施框架：{sorted(unexpected)}"
        )


def test_business_only_storage_driver_talks_to_minio() -> None:
    """验证 business 层仅 storage 资源驱动可直接使用 MinIO SDK/urllib3。"""
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
    """验证 api 层不直接依赖 MinIO/Playwright/ExecJS 等基础设施框架。"""
    unexpected = _violating_third_party_imports("api")
    assert not unexpected, (
        f"API 层不得依赖 MinIO/Playwright/ExecJS：{sorted(unexpected)}"
    )


def test_api_adds_no_direct_persistence_dependencies() -> None:
    """验证 api 层不新增豁免清单之外的 SQLAlchemy/SQLModel 依赖。"""
    unexpected = _api_persistence_imports() - LEGACY_API_IMPORT_ALLOWLIST
    assert not unexpected, (
        "API 层不得新增 SQLAlchemy/SQLModel 依赖；"
        f"请将以下逻辑下沉到 business service：{sorted(unexpected)}"
    )


def test_api_layer_does_not_access_persistence_directly() -> None:
    """验证 api 层不直接调用 session 持久化方法（查询与事务必须下沉 business service）。"""
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
