"""uv workspace 模块的物理布局规则。

这些测试锁定仓库的物理结构：crawler 是 PEP 420 命名空间包，每个 workspace
成员恰好拥有一个子包，业务子域保持 models/service 成对约定，资源文件随模块
一起搬移，且测试套件中每个 monkeypatch 字符串都能解析到真实的模块树。
"""

from __future__ import annotations

import ast
import importlib
import re
from importlib.util import resolve_name
from pathlib import Path
from typing import Any

import pytest
import tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULES_ROOT = REPO_ROOT / "modules"
TESTS_ROOT = REPO_ROOT / "tests"

MEMBER_PACKAGES = {
    "bootstrap": "bootstrap",
    "browser": "browser",
    "douyin-client": "douyin_client",
    "business": "business",
    "api": "api",
    "mcp": "mcp",
}

DOUYIN_SUBDOMAINS = (
    "accounts",
    "adapters",
    "categories",
    "comments",
    "content",
    "interactions",
    "keywords",
    "library",
    "media",
    "mine",
    "tags",
    "tasks",
    "tracks",
)

# 刻意不提供 service.py 的子域：content 是只读投影，
# comments 对外暴露的是 exports/query_service。
NO_SERVICE_SUBDOMAINS = {"comments", "content"}

REQUIRED_RESOURCE_FILES = (
    "modules/douyin-client/src/crawler/douyin_client/resources/douyin.js",
    "modules/browser/src/crawler/browser/resources/stealth.js",
    "modules/business/src/crawler/business/identity/email-templates/build/new_account.html",
    "modules/business/src/crawler/business/identity/email-templates/build/reset_password.html",
    "modules/business/src/crawler/business/identity/email-templates/build/test_email.html",
)

PATCH_TARGET_RE = re.compile(
    r"""(?:monkeypatch\.setattr|patch)\(\s*['"](crawler\.[^'"]+)['"]"""
)


def test_crawler_namespace_directories_have_no_init() -> None:
    """验证 crawler 命名空间目录下不得存在 __init__.py（PEP 420）。"""
    offenders = [str(path) for path in MODULES_ROOT.glob("*/src/crawler/__init__.py")]
    assert not offenders, f"crawler 命名空间目录不得包含 __init__.py：{offenders}"


def test_each_member_owns_exactly_one_subpackage() -> None:
    """验证每个 workspace 成员在 src/crawler 下恰好拥有一个子包且含 __init__.py。"""
    for member, package in MEMBER_PACKAGES.items():
        crawler_dir = MODULES_ROOT / member / "src" / "crawler"
        children = sorted(child.name for child in crawler_dir.iterdir())
        assert children == [package], (
            f"{member} 的 src/crawler 下只能包含 {package}：{children}"
        )
        assert (crawler_dir / package / "__init__.py").exists(), (
            f"{member} 缺少 {package}/__init__.py"
        )


def test_business_douyin_subdomains_keep_models_service_pair() -> None:
    """验证抖音业务子域保持 models.py/service.py 成对约定（豁免子域除外）。"""
    douyin_root = MODULES_ROOT / "business" / "src" / "crawler" / "business" / "douyin"
    subdomains = sorted(
        child.name
        for child in douyin_root.iterdir()
        if child.is_dir() and (child / "__init__.py").exists()
    )
    assert subdomains == sorted(DOUYIN_SUBDOMAINS)
    for name in subdomains:
        package = douyin_root / name
        assert (package / "__init__.py").exists(), f"{name} 缺少 __init__.py"
        assert (package / "models.py").exists(), f"{name} 缺少 models.py"
        if name not in NO_SERVICE_SUBDOMAINS:
            assert (package / "service.py").exists(), f"{name} 缺少 service.py"


def test_business_top_level_subdomains_keep_models_service_pair() -> None:
    """验证 business 顶层子域（identity/items/common/system）的模型与服务文件约定。"""
    business_root = MODULES_ROOT / "business" / "src" / "crawler" / "business"
    for name in ("identity", "items"):
        package = business_root / name
        assert (package / "models.py").exists(), f"{name} 缺少 models.py"
        assert (package / "service.py").exists(), f"{name} 缺少 service.py"
    for name in ("common", "system"):
        assert (business_root / name / "models.py").exists(), f"{name} 缺少 models.py"


def test_resource_files_travel_with_their_module() -> None:
    """验证资源文件（JS、邮件模板等）随所属模块一起存在。"""
    missing = [
        relative
        for relative in REQUIRED_RESOURCE_FILES
        if not (REPO_ROOT / relative).exists()
    ]
    assert not missing, f"资源文件必须随模块一起搬移：{missing}"


def _iter_patch_targets() -> list[str]:
    """收集测试套件中所有 monkeypatch.setattr/patch 的 crawler.* 目标字符串。"""
    targets: set[str] = set()
    for path in TESTS_ROOT.rglob("*.py"):
        targets.update(PATCH_TARGET_RE.findall(path.read_text(encoding="utf-8")))
    return sorted(targets)


def _resolve_patch_target(target: str) -> str | None:
    """逐段导入并解析 patch 目标，返回问题描述；可解析时返回 None。"""
    parts = target.split(".")
    for index in range(len(parts), 0, -1):
        module_name = ".".join(parts[:index])
        try:
            resolved: object = importlib.import_module(module_name)
        except ImportError:
            continue
        try:
            for attribute in parts[index:]:
                resolved = getattr(resolved, attribute)
        except AttributeError:
            return f"{target}：模块 {module_name} 中不存在该属性"
        return None
    return f"{target}：无法导入任何模块前缀"


@pytest.mark.parametrize("target", _iter_patch_targets())
def test_monkeypatch_target_exists(target: str) -> None:
    """验证每个 monkeypatch 目标字符串都能解析到真实模块与属性。"""
    problem = _resolve_patch_target(target)
    assert problem is None, problem


# ===========================================================================
# 重构后的物理布局边界（规格 §5 的 G7–G13、G18；规格 §7 的对应测试名）
#
# 与 test_dependency_boundaries 同构：所有判定都写成「对显式输入求违规列表」的
# 纯函数，便于用合成反例证明规则不是空断言。
# ===========================================================================

# 模块根目录（物理路径）与 import 包名前缀。
MODULE_PACKAGE_DIRS = {
    "bootstrap": MODULES_ROOT / "bootstrap" / "src" / "crawler" / "bootstrap",
    "browser": MODULES_ROOT / "browser" / "src" / "crawler" / "browser",
    "douyin-client": MODULES_ROOT
    / "douyin-client"
    / "src"
    / "crawler"
    / "douyin_client",
    "business": MODULES_ROOT / "business" / "src" / "crawler" / "business",
    "api": MODULES_ROOT / "api" / "src" / "crawler" / "api",
    "mcp": MODULES_ROOT / "mcp" / "src" / "crawler" / "mcp",
}

MODULE_PACKAGE_PREFIXES = {
    "bootstrap": "crawler.bootstrap",
    "browser": "crawler.browser",
    "douyin-client": "crawler.douyin_client",
    "business": "crawler.business",
    "api": "crawler.api",
    "mcp": "crawler.mcp",
}

# G7：「模块根无裸 .py」只覆盖 browser 与 douyin-client 两个成员。
#
# 为什么只有这两个成员：bootstrap/api/mcp/business 的模块根**今天**就存在裸 .py
# （bootstrap/settings.py、api/main.py、mcp/server.py、business/errors.py 等），
# 它们不在本次 browser/douyin-client 重构的范围内。若把 G7 扩到那 4 个成员，
# 门禁必然永久变红，规则就失去了「钉住本次新边界」的作用。
BARE_PY_GUARDED_MEMBERS = ("browser", "douyin-client")

# 模块根允许出现的非包条目。
ALLOWED_ROOT_ENTRIES = frozenset({"__init__.py", "resources"})

# G10：browser 与 douyin_client 的直接子包集合（resources/ 是资源目录，不是子包）。
FROZEN_SUBPACKAGES = {
    "browser": frozenset(
        {
            "connection",
            "errors",
            "facade",
            "interactions",
            "login",
            "page",
            "session",
        }
    ),
    "douyin-client": frozenset(
        {"errors", "http", "parsing", "privacy", "session", "signing"}
    ),
}

# G11：旧路径。
LEGACY_BROWSER_DIRS = ("base", "runtime", "remote")
LEGACY_BROWSER_MODULE_PATHS = tuple(
    f"crawler.browser.{name}" for name in LEGACY_BROWSER_DIRS
)

# G12：只允许从 crawler.browser 门面取得的站点层符号。
SITE_LAYER_SYMBOLS = (
    "DouyinInteractionExecutor",
    "DouyinLogin",
    "InteractionExecutionError",
    "InteractionExecutionRequest",
    "InteractionExecutionResult",
    "LoginError",
)
SITE_LAYER_PACKAGES = ("interactions", "login")

# G13：测试侧边界只约束这两个目录（tests/browser/** 是内部单测的合法落点）。
GUARDED_TEST_PACKAGE_DIRS = {
    "tests.business": TESTS_ROOT / "business",
    "tests.api": TESTS_ROOT / "api",
}
BROWSER_FACADE_MODULES = frozenset({"crawler.browser", "crawler.browser.facade"})

# G18：douyin-client 的打包级依赖黑名单。
DOUYIN_CLIENT_PYPROJECT = MODULES_ROOT / "douyin-client" / "pyproject.toml"
FORBIDDEN_CLIENT_REQUIREMENTS = frozenset({"crawler-browser", "playwright"})
FORBIDDEN_CLIENT_UV_SOURCES = frozenset({"crawler-browser", "crawler-bootstrap"})

# G11/G13 的全仓文本扫描范围：仓库的 Python 源码树。
SCAN_ROOTS = (MODULES_ROOT, TESTS_ROOT, REPO_ROOT / "scripts")
_IGNORED_DIR_PARTS = frozenset({"__pycache__", ".venv", "node_modules"})


def _python_sources(root: Path) -> list[Path]:
    """返回 root 下全部 .py 源文件（忽略构建产物与虚拟环境）。"""
    return sorted(
        path
        for path in root.rglob("*.py")
        if not _IGNORED_DIR_PARTS.intersection(path.parts)
    )


def _repo_python_files() -> list[Path]:
    """返回仓库全部 Python 源文件（modules/、tests/、scripts/ 与仓库根目录）。"""
    files = {path for root in SCAN_ROOTS for path in _python_sources(root)}
    files.update(
        path
        for path in REPO_ROOT.glob("*.py")
        if not _IGNORED_DIR_PARTS.intersection(path.parts)
    )
    return sorted(files)


def _root_entry_problems(root: Path) -> list[str]:
    """返回模块根不被允许的条目名（G7）。"""
    problems: list[str] = []
    for item in sorted(root.iterdir()):
        if item.name in _IGNORED_DIR_PARTS:
            continue
        if item.name in ALLOWED_ROOT_ENTRIES:
            continue
        if item.is_dir() and (item / "__init__.py").exists():
            continue
        problems.append(item.name)
    return problems


def _subpackage_name_repeat_problems(root: Path) -> list[str]:
    """返回「子包名与包内同名文件/同名嵌套目录重名」的位置（G8）。

    两种形态都会命中，因为都会让 ``import`` 解析产生歧义：

    - 包内同名文件：``p/facade.py``（规格 §5 G8 的字面写法）；
    - 同级同名文件：``p.parent/facade.py`` 与 ``p.parent/facade/`` 并存，
      这是 Python 里经典的「包遮蔽模块」陷阱，正是该规则要防的形态。
    """
    problems: list[str] = []
    for directory in sorted(path for path in root.rglob("*") if path.is_dir()):
        if _IGNORED_DIR_PARTS.intersection(directory.parts):
            continue
        if (directory / f"{directory.name}.py").exists():
            problems.append(f"{directory} 内含同名文件 {directory.name}.py")
        if (directory / directory.name).is_dir():
            problems.append(f"{directory} 内含同名嵌套目录 {directory.name}/")
        if (directory.parent / f"{directory.name}.py").exists():
            problems.append(f"{directory} 与同级 {directory.name}.py 重名")
    return problems


def _missing_init_problems(root: Path) -> list[str]:
    """返回缺少 __init__.py 的目录（G9；resources/ 是纯资源目录，豁免）。"""
    problems: list[str] = []
    for directory in sorted(path for path in root.rglob("*") if path.is_dir()):
        if _IGNORED_DIR_PARTS.intersection(directory.parts):
            continue
        if directory.name == "resources":
            continue
        if not (directory / "__init__.py").exists():
            problems.append(directory.relative_to(root).as_posix())
    return problems


def _direct_subpackage_problems(root: Path, expected: frozenset[str]) -> list[str]:
    """返回 direct 子包集合与冻结值不一致的明细（G10）。"""
    actual = frozenset(
        path.name
        for path in root.iterdir()
        if path.is_dir()
        and not _IGNORED_DIR_PARTS.intersection(path.parts)
        and (path / "__init__.py").exists()
    )
    problems: list[str] = []
    for missing in sorted(expected - actual):
        problems.append(f"缺少冻结子包 {missing}/")
    for extra in sorted(actual - expected):
        problems.append(f"新增未冻结子包 {extra}/")
    return problems


def _legacy_path_problems(files: list[Path]) -> list[str]:
    """返回全仓 .py 文本中残留的旧路径引用（G11）。"""
    problems: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for legacy in LEGACY_BROWSER_MODULE_PATHS:
            if legacy in text:
                problems.append(f"{_display_path(path)} 仍引用 {legacy}")
    return problems


def _display_path(path: Path) -> str:
    """返回相对仓库根的展示路径；仓库外的路径原样返回。"""
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve_import_from(node: ast.ImportFrom, package: str) -> str:
    """将 ImportFrom 节点解析为绝对模块名（处理包内相对 import）。"""
    module = node.module or ""
    if not node.level:
        return module
    return resolve_name(f"{'.' * node.level}{module}", package)


def _facade_import_problems(
    root: Path,
    *,
    package_prefix: str,
    allowed_modules: frozenset[str],
    symbol_pool: frozenset[str],
    guarded_prefix: str = "crawler.browser",
) -> list[tuple[str, str, str]]:
    """返回绕过 browser 门面的 (相对文件, 模块名, 符号名) 明细（G13）。"""
    violations: list[tuple[str, str, str]] = []
    for path in _python_sources(root):
        relative = path.relative_to(root).as_posix()
        parts = path.relative_to(root).parts[:-1]
        package = ".".join((package_prefix, *parts))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(f"{guarded_prefix}."):
                        violations.append((relative, alias.name, "*"))
            elif isinstance(node, ast.ImportFrom):
                module = _resolve_import_from(node, package)
                if module != guarded_prefix and not module.startswith(
                    f"{guarded_prefix}."
                ):
                    continue
                for alias in node.names:
                    if module not in allowed_modules or alias.name not in symbol_pool:
                        violations.append((relative, module, alias.name))
    return sorted(set(violations))


def _normalize_requirement(requirement: str) -> str:
    """把 PEP 508 依赖串归一化为发行包名（小写、下划线转连字符）。"""
    name = re.split(r"[<>=!~;\[\s@]", requirement.strip(), maxsplit=1)[0]
    return name.strip().lower().replace("_", "-")


def _pyproject_dependency_problems(data: dict[str, Any]) -> list[str]:
    """返回 douyin-client 打包级越界依赖明细（G18）。"""
    problems: list[str] = []
    dependencies = data.get("project", {}).get("dependencies", [])
    for requirement in dependencies:
        name = _normalize_requirement(str(requirement))
        if name in FORBIDDEN_CLIENT_REQUIREMENTS:
            problems.append(f"project.dependencies 不得包含 {name}：{requirement}")
    sources = data.get("tool", {}).get("uv", {}).get("sources", {})
    for name in sources:
        if str(name).lower().replace("_", "-") in FORBIDDEN_CLIENT_UV_SOURCES:
            problems.append(f"[tool.uv.sources] 不得包含 {name}")
    return problems


def test_module_roots_have_no_bare_python_modules() -> None:
    """G7：模块根无裸 .py —— 只覆盖 browser 与 douyin-client 两个成员。

    范围声明（防止门禁永久变红）：`bootstrap` / `api` / `mcp` / `business` 的模块根
    **当前就存在裸 .py**（`settings.py` / `main.py` / `server.py` / `errors.py` 等），
    它们不在本次重构范围内，因此 `BARE_PY_GUARDED_MEMBERS` 刻意只含两个成员。
    """
    assert BARE_PY_GUARDED_MEMBERS == ("browser", "douyin-client")
    for member in BARE_PY_GUARDED_MEMBERS:
        root = MODULE_PACKAGE_DIRS[member]
        bare_modules = sorted(path.name for path in root.glob("*.py"))
        assert bare_modules == ["__init__.py"], (
            f"{member} 模块根只能是 __init__.py，出现裸模块：{bare_modules}"
        )
        offenders = _root_entry_problems(root)
        assert not offenders, (
            f"{member} 模块根只允许 __init__.py、含 __init__.py 的子包与 resources/："
            f"{offenders}"
        )


def test_subpackages_do_not_repeat_their_own_name() -> None:
    """G8：browser/douyin_client 下不存在与子包同名的 .py 或嵌套同名目录。"""
    for member in BARE_PY_GUARDED_MEMBERS:
        problems = _subpackage_name_repeat_problems(MODULE_PACKAGE_DIRS[member])
        assert not problems, f"{member} 子包名与包内文件重名：{problems}"


def test_every_subpackage_has_init() -> None:
    """G9：browser/douyin_client 递归下的每个目录（除 resources/）都含 __init__.py。"""
    for member in BARE_PY_GUARDED_MEMBERS:
        problems = _missing_init_problems(MODULE_PACKAGE_DIRS[member])
        assert not problems, f"{member} 存在缺少 __init__.py 的目录：{problems}"


def test_browser_and_douyin_client_subpackage_sets_are_frozen() -> None:
    """G10：browser/douyin_client 的直接子包集合被冻结，新增/删除子包都会变红。"""
    for member in BARE_PY_GUARDED_MEMBERS:
        problems = _direct_subpackage_problems(
            MODULE_PACKAGE_DIRS[member], FROZEN_SUBPACKAGES[member]
        )
        assert not problems, f"{member} 直接子包集合与冻结值不一致：{problems}"


def test_legacy_browser_paths_are_gone() -> None:
    """G11：base/runtime/remote 目录消失，且全仓 .py 文本无旧路径引用。"""
    browser_root = MODULE_PACKAGE_DIRS["browser"]
    for legacy in LEGACY_BROWSER_DIRS:
        assert not (browser_root / legacy).exists(), (
            f"旧路径 crawler.browser.{legacy} 必须已删除"
        )

    files = _repo_python_files()
    assert len(files) > 100, f"全仓扫描范围异常，只找到 {len(files)} 个 .py 文件"
    problems = _legacy_path_problems(files)
    assert not problems, f"全仓仍有旧路径引用（含 tests/）：{problems}"


def test_interaction_and_login_live_in_browser_only() -> None:
    """G12：interactions/login 只属于 browser，douyin_client 不再暴露相关符号。"""
    client_root = MODULE_PACKAGE_DIRS["douyin-client"]
    for layer in SITE_LAYER_PACKAGES:
        assert not (client_root / layer).exists(), (
            f"douyin_client/{layer}/ 必须已迁往 crawler.browser"
        )
        with pytest.raises(ImportError):
            importlib.import_module(f"crawler.douyin_client.{layer}")

    import crawler.browser as browser_root
    import crawler.douyin_client as douyin_client

    problems: list[str] = []
    for name in SITE_LAYER_SYMBOLS:
        browser_symbol = getattr(browser_root, name, None)
        if browser_symbol is None:
            problems.append(f"crawler.browser 缺少站点层符号 {name}")
        if getattr(douyin_client, name, None) is not None:
            problems.append(f"crawler.douyin_client 仍可取得 {name}（应只属 browser）")
    assert not problems, problems


def test_business_and_api_tests_stay_out_of_browser_internals() -> None:
    """G13：tests/business/**、tests/api/** 只允许 browser 两个门面入口。

    刻意不约束 `tests/browser/**`：那是浏览器内部单测的合法落点。
    """
    import crawler.browser.facade as browser_facade

    symbols = frozenset(browser_facade.__all__)
    violations: list[tuple[str, str, str]] = []
    for package_prefix, root in GUARDED_TEST_PACKAGE_DIRS.items():
        violations.extend(
            _facade_import_problems(
                root,
                package_prefix=package_prefix,
                allowed_modules=BROWSER_FACADE_MODULES,
                symbol_pool=symbols,
            )
        )
    assert not violations, (
        "tests/business 与 tests/api 只能经 crawler.browser / crawler.browser.facade "
        f"取浏览器能力，以下 (文件, 模块, 符号) 越界：{violations}"
    )


def test_douyin_client_pyproject_has_no_browser_dependency() -> None:
    """G18：douyin-client 的打包级依赖与 uv.sources 不含任何浏览器依赖。"""
    data = tomllib.loads(DOUYIN_CLIENT_PYPROJECT.read_text(encoding="utf-8"))
    assert "dependencies" in data.get("project", {}), (
        "pyproject 必须显式声明 project.dependencies（否则规则空转）"
    )
    problems = _pyproject_dependency_problems(data)
    assert not problems, f"douyin-client 必须保持打包级零浏览器依赖：{problems}"
