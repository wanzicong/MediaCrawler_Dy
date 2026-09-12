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
    # G1：douyin_client 必须是零浏览器依赖的纯 API 层。
    "douyin_client": (
        "crawler.browser",
        "crawler.bootstrap",
        "crawler.business",
        "crawler.api",
        "crawler.mcp",
    ),
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
    # G1：playwright 不再属于 douyin_client 的依赖面。
    "douyin_client": {
        "fastapi",
        "starlette",
        "minio",
        "playwright",
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


# ===========================================================================
# 重构后的新边界（规格 §5 的 G1–G6、G16、G17、G19、G20；规格 §7 的对应测试名）
#
# 本节所有判定都写成「对显式输入求违规列表」的纯函数（root / 源码文本 / 路径），
# 而不是内联断言：这样每条规则都能用合成反例证明它会对违规输入报错，
# 不会退化成「永远为真」的空断言。
# ===========================================================================

# 各 workspace 模块的 import 包名前缀（用于解析包内相对 import）。
MODULE_PACKAGE_PREFIXES = {
    "bootstrap": "crawler.bootstrap",
    "browser": "crawler.browser",
    "douyin_client": "crawler.douyin_client",
    "business": "crawler.business",
    "api": "crawler.api",
    "mcp": "crawler.mcp",
}

# G3：上层（business/api/mcp）只允许这两个精确模块名。
BROWSER_FACADE_MODULES = frozenset({"crawler.browser", "crawler.browser.facade"})
# G4：上层只允许这一个精确模块名。
DOUYIN_CLIENT_FACADE_MODULE = "crawler.douyin_client"
UPPER_LAYER_MODULES = ("business", "api", "mcp")
# 规格 §2 冻结的门面出口数量（防止「两边都为空」让 G5 空转）。
BROWSER_FACADE_SIZE = 22

# G16：DouyinClient 的唯一合法构造点（相对 business 模块根）。
DOUYIN_CLIENT_CONSTRUCTION_ALLOWLIST = "douyin/adapters/service.py"

# G17：business/api/mcp 源码中不得出现的内部页面句柄名。
INTERNAL_HANDLE_NAME = "page_handle"

# G19：executor 行数硬上限 + interactions/ 允许出现的模块文件白名单
# （防止拆分后回流出 orchestrator.py 之类的聚合文件）。
MAX_EXECUTOR_LINES = 300
INTERACTION_MODULE_FILES = frozenset(
    {
        "__init__.py",
        "comment_locator.py",
        "executor.py",
        "models.py",
        "navigation.py",
        "page_controller.py",
        "panel.py",
        "reporting.py",
        "response_inspector.py",
        "selectors.py",
        "submit_flow.py",
        "verification.py",
    }
)

# G20：站点无关的内部层不得反向依赖抖音站点层。
UNDERLYING_BROWSER_LAYERS = ("session", "page", "connection", "errors")
SITE_LAYER_PACKAGES = ("crawler.browser.interactions", "crawler.browser.login")

# G11：已删除的旧路径（目录 + 全仓文本）。
LEGACY_BROWSER_DIRS = ("base", "runtime", "remote")
LEGACY_BROWSER_MODULE_PATHS = tuple(
    f"crawler.browser.{name}" for name in LEGACY_BROWSER_DIRS
)

# 构建产物与虚拟环境不参与架构判定。
_IGNORED_DIR_PARTS = frozenset({"__pycache__", ".venv", "node_modules"})


def _python_sources(root: Path) -> list[Path]:
    """返回 root 下全部 .py 源文件（忽略构建产物目录）。"""
    return sorted(
        path
        for path in root.rglob("*.py")
        if not _IGNORED_DIR_PARTS.intersection(path.parts)
    )


def _package_name(package_prefix: str, root: Path, path: Path) -> str:
    """按 root 相对路径推导文件所在包的绝对包名。"""
    parts = path.relative_to(root).parts[:-1]
    return ".".join((package_prefix, *parts))


def _iter_import_statements(path: Path, package: str) -> list[tuple[str, str, bool]]:
    """解析文件 AST，产出 (模块名, 符号名, 是否为整体 import)。

    `import a.b` → ("a.b", "*", True)；`from a.b import c` → ("a.b", "c", False)。
    包内相对 import 会按 package 解析为绝对模块名。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    statements: list[tuple[str, str, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            statements.extend((alias.name, "*", True) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_import_from(node, package)
            statements.extend((base, alias.name, False) for alias in node.names)
    return statements


def _crawler_import_violations(
    root: Path, *, package_prefix: str, forbidden: tuple[str, ...]
) -> list[tuple[str, str]]:
    """返回 root 下命中 forbidden 前缀的 (相对文件, 被 import 模块) 列表（G1/G2）。"""
    violations: list[tuple[str, str]] = []
    for path in _python_sources(root):
        relative = path.relative_to(root).as_posix()
        package = _package_name(package_prefix, root, path)
        for module, symbol, is_bare in _iter_import_statements(path, package):
            candidates = [module] if is_bare else [module, f"{module}.{symbol}"]
            for imported in candidates:
                if any(
                    imported == prefix or imported.startswith(f"{prefix}.")
                    for prefix in forbidden
                ):
                    violations.append((relative, imported))
    return sorted(set(violations))


def _third_party_violations(root: Path, forbidden: set[str]) -> set[ImportUse]:
    """返回 root 下 import 被禁第三方框架的 ImportUse 集合（G1）。"""
    violations: set[ImportUse] = set()
    for path in _python_sources(root):
        relative = path.relative_to(root).as_posix()
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


def _facade_import_violations(
    root: Path,
    *,
    package_prefix: str,
    guarded_prefix: str,
    allowed_modules: frozenset[str],
    symbol_pool: frozenset[str],
) -> list[tuple[str, str, str]]:
    """返回绕过门面取符号的 (相对文件, 模块名, 符号名) 明细（G3/G4/G13）。

    规则：以 guarded_prefix 开头的 `from ... import ...` 必须落在 allowed_modules
    里且每个符号都在 symbol_pool 中；以 `{guarded_prefix}.` 开头的整体
    `import ...` 一律违规（门面入口本身用 `from ... import ...`）。
    """
    violations: list[tuple[str, str, str]] = []
    for path in _python_sources(root):
        relative = path.relative_to(root).as_posix()
        package = _package_name(package_prefix, root, path)
        for module, symbol, is_bare in _iter_import_statements(path, package):
            if is_bare:
                if module.startswith(f"{guarded_prefix}."):
                    violations.append((relative, module, symbol))
                continue
            if module != guarded_prefix and not module.startswith(f"{guarded_prefix}."):
                continue
            if module not in allowed_modules or symbol not in symbol_pool:
                violations.append((relative, module, symbol))
    return sorted(set(violations))


def _facade_mirror_problems(root_module: object, facade_module: object) -> list[str]:
    """返回门面镜像（`__all__` 顺序 + 逐名同一对象）的不一致明细（G5）。"""

    def _all(module: object) -> list[str]:
        names = getattr(module, "__all__", ())
        return [str(name) for name in names]

    root_all = _all(root_module)
    facade_all = _all(facade_module)
    problems: list[str] = []
    if not facade_all:
        problems.append("门面 __all__ 为空：门面镜像规则会空转，必须显式暴露符号表")
    if len(root_all) != BROWSER_FACADE_SIZE:
        problems.append(
            f"crawler.browser.__all__ 应为 {BROWSER_FACADE_SIZE} 项：{len(root_all)}"
        )
    if root_all != facade_all:
        problems.append(
            f"crawler.browser.__all__ 与门面顺序/内容不一致：{root_all} != {facade_all}"
        )
    missing = object()
    for name in facade_all:
        if getattr(root_module, name, missing) is not getattr(
            facade_module, name, missing
        ):
            problems.append(f"{name} 在根镜像与门面中不是同一对象")
    return problems


def _root_init_import_problems(
    source: str, *, allowed_modules: frozenset[str], allowed_prefix: str | None
) -> list[str]:
    """返回模块根 `__init__.py` 的越界 import 明细（G6）。"""
    modules = [
        module for module, _symbol, _is_bare in _iter_import_statements_source(source)
    ]
    problems: list[str] = []
    if not modules:
        problems.append("模块根 __init__.py 没有 import 任何符号（规则会空转）")
    for module in modules:
        if module in allowed_modules:
            continue
        if allowed_prefix is not None and module.startswith(f"{allowed_prefix}."):
            continue
        problems.append(f"模块根只允许 import 自家门面，实际出现：{module}")
    return problems


def _iter_import_statements_source(source: str) -> list[tuple[str, str, bool]]:
    """对源码文本执行 `_iter_import_statements` 的等价解析（供 G6 与反例自检使用）。"""
    tree = ast.parse(source)
    statements: list[tuple[str, str, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            statements.extend((alias.name, "*", True) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            statements.extend(
                (node.module or "", alias.name, False) for alias in node.names
            )
    return statements


def _douyin_client_construction_problems(
    root: Path, *, allowed_relative: str
) -> list[tuple[str, int, str]]:
    """返回 business 中越界构造 DouyinClient 的 (相对文件, 行号, 调用写法) （G16）。"""
    problems: list[tuple[str, int, str]] = []
    for path in _python_sources(root):
        relative = path.relative_to(root).as_posix()
        if relative == allowed_relative:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            if isinstance(callee, ast.Name) and callee.id == "DouyinClient":
                problems.append((relative, node.lineno, "DouyinClient(...)"))
            elif (
                isinstance(callee, ast.Attribute)
                and callee.attr == "create"
                and isinstance(callee.value, ast.Name)
                and callee.value.id == "DouyinClient"
            ):
                problems.append((relative, node.lineno, "DouyinClient.create(...)"))
    return sorted(problems)


def _text_hits(root: Path, needle: str) -> list[tuple[str, int]]:
    """返回 root 下 .py 源码文本命中 needle 的 (相对文件, 行号) （G17）。"""
    hits: list[tuple[str, int]] = []
    for path in _python_sources(root):
        relative = path.relative_to(root).as_posix()
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if needle in line:
                hits.append((relative, lineno))
    return hits


def _executor_size_problems(path: Path, *, max_lines: int) -> list[str]:
    """返回 executor 行数超限明细（G19）。"""
    lines = len(path.read_text(encoding="utf-8").splitlines())
    if lines > max_lines:
        return [f"{path.name} 已达 {lines} 行，超过硬上限 {max_lines} 行"]
    return []


def _unexpected_files_problems(root: Path, *, allowed: frozenset[str]) -> list[str]:
    """返回 root 下不在白名单中的 .py 文件名（G19）。"""
    return sorted(
        path.name for path in _python_sources(root) if path.name not in allowed
    )


def _internal_site_layer_import_problems(root: Path) -> list[tuple[str, str]]:
    """返回 browser 内部层反向依赖站点层的 (相对文件, 被 import 模块) （G20）。"""
    problems: list[tuple[str, str]] = []
    for layer in UNDERLYING_BROWSER_LAYERS:
        layer_root = root / layer
        for path in _python_sources(layer_root):
            relative = path.relative_to(root).as_posix()
            package = _package_name(MODULE_PACKAGE_PREFIXES["browser"], root, path)
            for module, symbol, is_bare in _iter_import_statements(path, package):
                candidates = [module] if is_bare else [module, f"{module}.{symbol}"]
                for imported in candidates:
                    if any(
                        imported == site or imported.startswith(f"{site}.")
                        for site in SITE_LAYER_PACKAGES
                    ):
                        problems.append((relative, imported))
    return sorted(set(problems))


def test_douyin_client_has_no_playwright_dependency() -> None:
    """G1：douyin_client 是纯 API 层，全部 .py 的 AST 中不得出现 playwright import。"""
    assert "playwright" in FORBIDDEN_PACKAGES["douyin_client"], (
        "FORBIDDEN_PACKAGES['douyin_client'] 必须显式登记 playwright"
    )
    violations = _third_party_violations(
        MODULE_ROOTS["douyin_client"], FORBIDDEN_PACKAGES["douyin_client"]
    )
    assert not violations, (
        f"douyin_client 不得依赖 playwright 等入站/基础设施框架：{sorted(violations)}"
    )


def test_douyin_client_never_imports_browser() -> None:
    """G1：douyin_client 全部 .py 不得出现 crawler.browser 前缀的 import。"""
    violations = _crawler_import_violations(
        MODULE_ROOTS["douyin_client"],
        package_prefix=MODULE_PACKAGE_PREFIXES["douyin_client"],
        forbidden=FORBIDDEN_CRAWLER_PREFIXES["douyin_client"],
    )
    browser_violations = [
        item for item in violations if item[1].startswith("crawler.browser")
    ]
    assert not browser_violations, (
        "douyin_client 必须零浏览器依赖（浏览器能力只能经 SessionContext 注入）："
        f"{browser_violations}"
    )


def test_douyin_client_never_imports_bootstrap() -> None:
    """G1：douyin_client 不得 import crawler.bootstrap（迁移前的用法已随 executor 迁出）。"""
    assert "crawler.bootstrap" in FORBIDDEN_CRAWLER_PREFIXES["douyin_client"], (
        "FORBIDDEN_CRAWLER_PREFIXES['douyin_client'] 必须显式登记 crawler.bootstrap"
    )
    violations = _crawler_import_violations(
        MODULE_ROOTS["douyin_client"],
        package_prefix=MODULE_PACKAGE_PREFIXES["douyin_client"],
        forbidden=FORBIDDEN_CRAWLER_PREFIXES["douyin_client"],
    )
    bootstrap_violations = [
        item for item in violations if item[1].startswith("crawler.bootstrap")
    ]
    assert not bootstrap_violations, (
        f"douyin_client 不得依赖 bootstrap：{bootstrap_violations}"
    )


def test_browser_never_imports_douyin_client() -> None:
    """G2：browser 不反向依赖 douyin_client（结构化满足 SessionContext，不做 import）。"""
    assert "crawler.douyin_client" in FORBIDDEN_CRAWLER_PREFIXES["browser"]
    violations = _crawler_import_violations(
        MODULE_ROOTS["browser"],
        package_prefix=MODULE_PACKAGE_PREFIXES["browser"],
        forbidden=FORBIDDEN_CRAWLER_PREFIXES["browser"],
    )
    assert not violations, f"browser 不得依赖 douyin_client：{violations}"


def _browser_facade_symbols() -> frozenset[str]:
    """返回 browser 门面冻结的符号集合（门面 __all__ 是唯一真源）。"""
    from crawler.browser import facade as browser_facade

    return frozenset(browser_facade.__all__)


def _douyin_client_facade_symbols() -> frozenset[str]:
    """返回 douyin_client 门面冻结的符号集合。"""
    import crawler.douyin_client as douyin_client

    return frozenset(douyin_client.__all__)


def test_upper_layers_import_browser_only_through_facade() -> None:
    """G3：business/api/mcp 只能从 crawler.browser / crawler.browser.facade 取符号。"""
    symbols = _browser_facade_symbols()
    violations: list[tuple[str, str, str]] = []
    for module in UPPER_LAYER_MODULES:
        violations.extend(
            _facade_import_violations(
                MODULE_ROOTS[module],
                package_prefix=MODULE_PACKAGE_PREFIXES[module],
                guarded_prefix="crawler.browser",
                allowed_modules=BROWSER_FACADE_MODULES,
                symbol_pool=symbols,
            )
        )
    assert not violations, (
        "上层只能经 crawler.browser / crawler.browser.facade 门面取浏览器能力，"
        f"以下 (文件, 模块, 符号) 越界：{violations}"
    )


def test_upper_layers_import_douyin_client_only_through_facade() -> None:
    """G4：business/api/mcp 只能从 crawler.douyin_client 精确模块名取符号。"""
    symbols = _douyin_client_facade_symbols()
    violations: list[tuple[str, str, str]] = []
    for module in UPPER_LAYER_MODULES:
        violations.extend(
            _facade_import_violations(
                MODULE_ROOTS[module],
                package_prefix=MODULE_PACKAGE_PREFIXES[module],
                guarded_prefix=DOUYIN_CLIENT_FACADE_MODULE,
                allowed_modules=frozenset({DOUYIN_CLIENT_FACADE_MODULE}),
                symbol_pool=symbols,
            )
        )
    assert not violations, (
        "上层只能经 crawler.douyin_client 门面取 API 能力，"
        f"以下 (文件, 模块, 符号) 越界：{violations}"
    )


def test_browser_root_facade_mirrors_the_facade() -> None:
    """G5：crawler.browser 与 crawler.browser.facade 的 __all__ 顺序一致且逐名同一对象。"""
    import crawler.browser as browser_root
    import crawler.browser.facade as browser_facade

    problems = _facade_mirror_problems(browser_root, browser_facade)
    assert not problems, f"门面镜像被破坏：{problems}"


def test_browser_root_init_only_imports_its_facade() -> None:
    """G6：模块根 __init__.py 只 import 自家门面，不直连内部实现路径。"""
    browser_init = MODULE_ROOTS["browser"] / "__init__.py"
    problems = _root_init_import_problems(
        browser_init.read_text(encoding="utf-8"),
        allowed_modules=frozenset({"crawler.browser.facade"}),
        allowed_prefix=None,
    )
    assert not problems, f"browser 模块根只能 import crawler.browser.facade：{problems}"

    client_init = MODULE_ROOTS["douyin_client"] / "__init__.py"
    client_problems = _root_init_import_problems(
        client_init.read_text(encoding="utf-8"),
        allowed_modules=frozenset(),
        allowed_prefix="crawler.douyin_client",
    )
    assert not client_problems, (
        f"douyin_client 模块根只能 import crawler.douyin_client.*：{client_problems}"
    )


def test_business_only_constructs_douyin_client_in_adapter() -> None:
    """G16：business 下 DouyinClient( / DouyinClient.create( 只能出现在适配器内。"""
    problems = _douyin_client_construction_problems(
        MODULE_ROOTS["business"],
        allowed_relative=DOUYIN_CLIENT_CONSTRUCTION_ALLOWLIST,
    )
    assert not problems, (
        "DouyinClient 的唯一装配点是 "
        f"{DOUYIN_CLIENT_CONSTRUCTION_ALLOWLIST}，以下 (文件, 行号, 调用) 越界：{problems}"
    )


def test_business_never_references_internal_page_handle() -> None:
    """G17：business/api/mcp 源码文本不得出现 page_handle（内部句柄不出门面）。"""
    hits: list[tuple[str, str, int]] = []
    for module in UPPER_LAYER_MODULES:
        hits.extend(
            (module, relative, lineno)
            for relative, lineno in _text_hits(
                MODULE_ROOTS[module], INTERNAL_HANDLE_NAME
            )
        )
    assert not hits, f"上层不得触碰 browser 内部句柄 {INTERNAL_HANDLE_NAME!r}：{hits}"


def test_internal_layers_do_not_import_site_layers() -> None:
    """G20：browser 的 session/page/connection/errors 不得反向依赖 interactions/login。"""
    problems = _internal_site_layer_import_problems(MODULE_ROOTS["browser"])
    assert not problems, (
        f"browser 站点无关层不得依赖抖音站点层（interactions/login）：{problems}"
    )


def test_interaction_executor_stays_a_thin_orchestrator() -> None:
    """G19：executor ≤ 300 行，且 interactions/ 不回流聚合文件。"""
    executor = MODULE_ROOTS["browser"] / "interactions" / "executor.py"
    size_problems = _executor_size_problems(executor, max_lines=MAX_EXECUTOR_LINES)
    assert not size_problems, size_problems

    unexpected = _unexpected_files_problems(
        MODULE_ROOTS["browser"] / "interactions", allowed=INTERACTION_MODULE_FILES
    )
    assert not unexpected, (
        f"interactions/ 只允许白名单内的职责文件，出现聚合文件：{unexpected}"
    )
