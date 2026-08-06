import pytest
from pydantic import ValidationError

from app.models import CrawlTaskCreate, DouyinCrawlType, DouyinLoginType


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
