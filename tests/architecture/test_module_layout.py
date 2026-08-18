"""Packaging rules for the uv workspace modules.

These tests lock the physical layout: crawler is a PEP 420 namespace package,
each workspace member owns exactly one subpackage, business subdomains keep the
models/service pair convention, resource files travel with their module, and
every monkeypatch string in the test suite resolves against the real tree.
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

# Subdomains that intentionally have no service.py: content is a read-only
# projection, comments exposes exports/query_service instead.
NO_SERVICE_SUBDOMAINS = {"comments", "content"}

REQUIRED_RESOURCE_FILES = (
    "modules/douyin-client/src/crawler/douyin_client/resources/douyin.js",
    "modules/douyin-client/src/crawler/douyin_client/NON_COMMERCIAL_LICENSE",
    "modules/browser/src/crawler/browser/resources/stealth.js",
    "modules/business/src/crawler/business/identity/email-templates/build/new_account.html",
    "modules/business/src/crawler/business/identity/email-templates/build/reset_password.html",
    "modules/business/src/crawler/business/identity/email-templates/build/test_email.html",
)

PATCH_TARGET_RE = re.compile(
    r"""(?:monkeypatch\.setattr|patch)\(\s*['"](crawler\.[^'"]+)['"]"""
)


def test_crawler_namespace_directories_have_no_init() -> None:
    offenders = [
        str(path)
        for path in MODULES_ROOT.glob("*/src/crawler/__init__.py")
    ]
    assert not offenders, f"crawler 命名空间目录不得包含 __init__.py：{offenders}"


def test_each_member_owns_exactly_one_subpackage() -> None:
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
    business_root = MODULES_ROOT / "business" / "src" / "crawler" / "business"
    for name in ("identity", "items"):
        package = business_root / name
        assert (package / "models.py").exists(), f"{name} 缺少 models.py"
        assert (package / "service.py").exists(), f"{name} 缺少 service.py"
    for name in ("common", "system"):
        assert (business_root / name / "models.py").exists(), f"{name} 缺少 models.py"


def test_resource_files_travel_with_their_module() -> None:
    missing = [
        relative for relative in REQUIRED_RESOURCE_FILES
        if not (REPO_ROOT / relative).exists()
    ]
    assert not missing, f"资源文件必须随模块一起搬移：{missing}"


def _iter_patch_targets() -> list[str]:
    targets: set[str] = set()
    for path in TESTS_ROOT.rglob("*.py"):
        targets.update(PATCH_TARGET_RE.findall(path.read_text(encoding="utf-8")))
    return sorted(targets)


def _resolve_patch_target(target: str) -> str | None:
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
    problem = _resolve_patch_target(target)
    assert problem is None, problem
