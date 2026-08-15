"""Compatibility contracts for services moved into the application layer."""

from __future__ import annotations

import importlib
from typing import Any

import pytest


@pytest.mark.parametrize(
    ("legacy_name", "canonical_name"),
    [
        (
            "app.core.config",
            "app.bootstrap.settings",
        ),
        (
            "app.services.douyin_keywords",
            "app.application.douyin.keywords.service",
        ),
        (
            "app.services.douyin_tracks",
            "app.application.douyin.tracks.service",
        ),
        (
            "app.services.douyin_tags",
            "app.application.douyin.tags.service",
        ),
        (
            "app.services.douyin_exports",
            "app.application.douyin.comments.exports",
        ),
        (
            "app.services.douyin_accounts",
            "app.application.douyin.accounts.service",
        ),
        (
            "app.services.douyin_interactions",
            "app.application.douyin.interactions.service",
        ),
        (
            "app.services.interaction_screenshots",
            "app.application.douyin.interactions.screenshots",
        ),
        (
            "app.services.douyin_tasks",
            "app.application.douyin.tasks.service",
        ),
        (
            "app.services.media_pipeline",
            "app.application.douyin.media.pipeline",
        ),
        (
            "app.services.media_migration",
            "app.application.douyin.media.migration",
        ),
        (
            "app.services.media_preview",
            "app.application.douyin.media.preview",
        ),
        (
            "app.services.media_storage",
            "app.application.douyin.media.storage",
        ),
        (
            "app.douyin.client",
            "app.integrations.douyin.client",
        ),
        (
            "app.douyin.exceptions",
            "app.integrations.douyin.exceptions",
        ),
        (
            "app.douyin.signer",
            "app.integrations.douyin.signer",
        ),
        (
            "app.douyin.types",
            "app.integrations.douyin.types",
        ),
        (
            "app.douyin.browser",
            "app.integrations.douyin.browser",
        ),
        (
            "app.douyin.remote_browser",
            "app.integrations.douyin.remote_browser",
        ),
        (
            "app.douyin.login",
            "app.integrations.douyin.login",
        ),
        (
            "app.douyin.privacy",
            "app.integrations.douyin.privacy",
        ),
        (
            "app.douyin.crawler",
            "app.application.douyin.tasks.crawler",
        ),
        (
            "app.douyin.storage",
            "app.application.douyin.tasks.persistence",
        ),
        (
            "app.douyin.interactions",
            "app.integrations.douyin.interactions",
        ),
    ],
)
def test_legacy_module_path_is_the_canonical_module_object(
    legacy_name: str,
    canonical_name: str,
) -> None:
    canonical = importlib.import_module(canonical_name)
    legacy = importlib.import_module(legacy_name)

    assert legacy is canonical


def test_framework_compatibility_modules_keep_identity_and_assignment_propagation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_database = importlib.import_module("app.core.db")
    canonical_database = importlib.import_module("app.framework.database")
    legacy_logging = importlib.import_module("app.core.logging")
    canonical_logging = importlib.import_module("app.framework.logging")
    legacy_security = importlib.import_module("app.core.security")
    canonical_security = importlib.import_module("app.framework.security")

    assert legacy_database.engine is canonical_database.engine
    assert legacy_logging is canonical_logging
    assert legacy_security is canonical_security
    assert legacy_security.password_hash is canonical_security.password_hash

    replacement_logging: Any = object()
    replacement_security: Any = object()
    monkeypatch.setattr(
        legacy_logging,
        "configure_sensitive_transport_logging",
        replacement_logging,
    )
    monkeypatch.setattr(
        legacy_security,
        "create_access_token",
        replacement_security,
    )

    assert canonical_logging.configure_sensitive_transport_logging is replacement_logging
    assert canonical_security.create_access_token is replacement_security


@pytest.mark.parametrize(
    ("name", "consumers"),
    [
        (
            "task_manager",
            (
                "app.application.douyin.tasks.api_service",
                "app.application.douyin.media.service",
                "app.application.douyin.library.service",
            ),
        ),
        ("media_manager", ("app.application.douyin.media.service",)),
        ("media_migration_manager", ("app.application.douyin.media.service",)),
        (
            "media_storage",
            (
                "app.application.douyin.media.service",
                "app.application.douyin.media.delivery",
            ),
        ),
    ],
)
def test_legacy_douyin_router_assignment_reaches_split_endpoint_modules(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    consumers: tuple[str, ...],
) -> None:
    legacy_router = importlib.import_module("app.api.routes.douyin")
    replacement: Any = object()

    monkeypatch.setattr(legacy_router, name, replacement)

    for consumer_name in consumers:
        consumer = importlib.import_module(consumer_name)
        assert getattr(consumer, name) is replacement


@pytest.mark.parametrize(
    ("endpoint_name", "canonical_module"),
    [
        ("create_task", "app.api.routes.douyin_tasks"),
        ("list_tasks", "app.api.routes.douyin_tasks"),
        ("list_comment_library", "app.api.routes.douyin_catalog"),
        ("export_comment_selection", "app.api.routes.douyin_catalog"),
        ("list_library_creators", "app.api.routes.douyin_catalog"),
        ("list_library_works", "app.api.routes.douyin_catalog"),
        ("migrate_library_media_to_minio", "app.api.routes.douyin_media"),
        ("get_task", "app.api.routes.douyin_tasks"),
        ("list_task_shards", "app.api.routes.douyin_tasks"),
        ("cancel_task", "app.api.routes.douyin_tasks"),
        ("resume_task", "app.api.routes.douyin_tasks"),
        ("list_media", "app.api.routes.douyin_media"),
        ("get_media_summary", "app.api.routes.douyin_media"),
        ("migrate_media_to_minio", "app.api.routes.douyin_media"),
        ("process_media", "app.api.routes.douyin_media"),
        ("retry_media", "app.api.routes.douyin_media"),
        ("retranslate_media", "app.api.routes.douyin_media"),
        ("download_media_file", "app.api.routes.douyin_media"),
        ("create_media_preview_session", "app.api.routes.douyin_media"),
        ("preview_media_file", "app.api.routes.douyin_media"),
        ("get_qrcode", "app.api.routes.douyin_tasks"),
        ("list_works", "app.api.routes.douyin_catalog"),
        ("get_work", "app.api.routes.douyin_catalog"),
        ("list_awemes", "app.api.routes.douyin_catalog"),
        ("recrawl_aweme_comments", "app.api.routes.douyin_catalog"),
        ("crawl_aweme_creator", "app.api.routes.douyin_catalog"),
        ("list_comments", "app.api.routes.douyin_catalog"),
        ("export_comments", "app.api.routes.douyin_catalog"),
        ("export_subtitles", "app.api.routes.douyin_catalog"),
        ("list_actions", "app.api.routes.douyin_catalog"),
    ],
)
def test_legacy_douyin_endpoint_import_surface_is_preserved(
    endpoint_name: str,
    canonical_module: str,
) -> None:
    legacy_router = importlib.import_module("app.api.routes.douyin")
    canonical = importlib.import_module(canonical_module)

    assert getattr(legacy_router, endpoint_name) is getattr(canonical, endpoint_name)
    assert endpoint_name in legacy_router.__all__
