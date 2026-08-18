"""uv workspace 模块的物理布局规则。

这些测试锁定仓库的物理结构：crawler 是 PEP 420 命名空间包，每个 workspace
成员恰好拥有一个子包，业务子域保持 models/service 成对约定，资源文件随模块
一起搬移，且测试套件中每个 monkeypatch 字符串都能解析到真实的模块树。
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

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
    "comments",
    "content",
    "interactions",
    "keywords",
    "library",
    "media",
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
