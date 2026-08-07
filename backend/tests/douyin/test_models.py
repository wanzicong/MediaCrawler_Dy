import uuid

import pytest
from pydantic import ValidationError

from app.models import (
    CrawlTaskCreate,
    CrawlTaskResumeRequest,
    DouyinBrowserMode,
    DouyinCrawlType,
    DouyinLoginType,
    DouyinMediaAsset,
    DouyinMediaAssetPublic,
    DouyinMediaMigrationRequest,
    DouyinMediaProcessRequest,
    MediaMigrationStatus,
    MediaProcessingMode,
    MediaStorageBackend,
)


def test_media_migration_models_are_persistent_and_private() -> None:
    asset = DouyinMediaAsset(task_id=uuid.uuid4(), aweme_id="migration-aweme")
    request = DouyinMediaMigrationRequest(asset_ids=[asset.id])

    assert asset.migration_status == MediaMigrationStatus.idle.value
    assert asset.migration_progress == 0
    assert asset.migration_attempt_count == 0
    assert asset.migration_error is None
    assert request.asset_ids == [asset.id]
    assert "local_path" not in DouyinMediaAssetPublic.model_fields
    assert "storage_bucket" not in DouyinMediaAssetPublic.model_fields
    assert "object_key" not in DouyinMediaAssetPublic.model_fields


def test_media_migration_request_limits_asset_ids() -> None:
    with pytest.raises(ValidationError):
        DouyinMediaMigrationRequest(asset_ids=[uuid.uuid4() for _ in range(1001)])


def test_search_requires_keywords() -> None:
    with pytest.raises(ValidationError, match="keywords"):
        CrawlTaskCreate(crawl_type=DouyinCrawlType.search)


def test_detail_requires_video_ids() -> None:
    with pytest.raises(ValidationError, match="video_ids"):
        CrawlTaskCreate(crawl_type=DouyinCrawlType.detail)


def test_creator_from_aweme_requires_video_ids() -> None:
    with pytest.raises(ValidationError, match="video_ids"):
        CrawlTaskCreate(crawl_type=DouyinCrawlType.creator_from_aweme)

    request = CrawlTaskCreate(
        crawl_type=DouyinCrawlType.creator_from_aweme,
        video_ids=["123456"],
        fetch_comments=False,
    )
    assert request.video_ids == ["123456"]


def test_cookie_is_secret_and_never_in_public_request() -> None:
    request = CrawlTaskCreate(
        crawl_type=DouyinCrawlType.search,
        keywords=["中文关键词"],
        cookies="sessionid=secret-value",
    )

    assert request.login_type == DouyinLoginType.cookie
    assert "cookies" not in request.public_request()
    assert "secret-value" not in repr(request)


def test_disabling_comments_also_disables_sub_comments() -> None:
    request = CrawlTaskCreate(
        keywords=["测试"], fetch_comments=False, fetch_sub_comments=True
    )

    assert request.fetch_sub_comments is False


def test_subtitle_translation_enables_download_and_defaults_to_immediate() -> None:
    request = CrawlTaskCreate(
        keywords=["测试"],
        translate_subtitles=True,
    )

    assert request.download_media is True
    assert request.media_processing_mode == MediaProcessingMode.immediate


def test_batch_media_processing_is_preserved() -> None:
    request = CrawlTaskCreate(
        keywords=["测试"],
        download_media=True,
        media_processing_mode=MediaProcessingMode.batch,
    )

    assert request.media_processing_mode == MediaProcessingMode.batch


def test_browser_mode_is_task_scoped_and_public() -> None:
    request = CrawlTaskCreate(keywords=["测试"], browser_mode="remote")

    assert request.browser_mode == DouyinBrowserMode.remote
    assert request.public_request()["browser_mode"] == "remote"


def test_media_storage_is_task_scoped_and_public() -> None:
    request = CrawlTaskCreate(keywords=["测试"], media_storage="minio")

    assert request.media_storage == MediaStorageBackend.minio
    assert request.public_request()["media_storage"] == "minio"


def test_resume_request_rejects_empty_scope_and_hides_cookie() -> None:
    with pytest.raises(ValidationError, match="至少需要"):
        CrawlTaskResumeRequest(resume_crawl=False, resume_media=False)

    request = CrawlTaskResumeRequest(cookies="sessionid=resume-secret")

    assert "resume-secret" not in repr(request)


def test_media_process_force_translation_is_normalized_and_cookie_is_secret() -> None:
    request = DouyinMediaProcessRequest(
        force_retranslate=True,
        cookies="sessionid=media-secret",
    )

    assert request.translate_subtitles is True
    assert request.cookies is not None
    assert request.cookies.get_secret_value() == "sessionid=media-secret"
    assert "media-secret" not in repr(request)
