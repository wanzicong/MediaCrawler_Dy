from app.models import CrawlTaskCreate, DouyinBrowserMode, MediaStorageBackend
from app.services.douyin_tasks import resolve_browser_mode, resolve_media_storage


def test_configured_browser_mode_is_used_when_request_omits_it() -> None:
    request = CrawlTaskCreate(keywords=["测试"])

    resolved = resolve_browser_mode(request, "remote")

    assert resolved.browser_mode == DouyinBrowserMode.remote
    assert request.browser_mode is None


def test_task_browser_mode_overrides_configured_default() -> None:
    request = CrawlTaskCreate(keywords=["测试"], browser_mode="local")

    resolved = resolve_browser_mode(request, "remote")

    assert resolved is request
    assert resolved.browser_mode == DouyinBrowserMode.local


def test_configured_media_storage_is_used_when_request_omits_it() -> None:
    request = CrawlTaskCreate(keywords=["测试"])

    resolved = resolve_media_storage(request, "minio")

    assert resolved.media_storage == MediaStorageBackend.minio
    assert request.media_storage is None


def test_task_media_storage_overrides_configured_default() -> None:
    request = CrawlTaskCreate(keywords=["测试"], media_storage="local")

    resolved = resolve_media_storage(request, "minio")

    assert resolved is request
    assert resolved.media_storage == MediaStorageBackend.local
