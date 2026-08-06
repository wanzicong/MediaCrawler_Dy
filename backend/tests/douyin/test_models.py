import pytest
from pydantic import ValidationError

from app.models import (
    CrawlTaskCreate,
    DouyinBrowserMode,
    DouyinCrawlType,
    DouyinLoginType,
    MediaProcessingMode,
)


def test_search_requires_keywords() -> None:
    with pytest.raises(ValidationError, match="keywords"):
        CrawlTaskCreate(crawl_type=DouyinCrawlType.search)


def test_detail_requires_video_ids() -> None:
    with pytest.raises(ValidationError, match="video_ids"):
        CrawlTaskCreate(crawl_type=DouyinCrawlType.detail)


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
