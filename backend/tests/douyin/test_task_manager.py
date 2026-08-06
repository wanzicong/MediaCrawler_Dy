import json
import uuid

from app.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskResumeRequest,
    DouyinBrowserMode,
    DouyinLoginType,
    MediaStorageBackend,
)
from app.services.douyin_tasks import (
    DouyinTaskManager,
    resolve_browser_mode,
    resolve_media_storage,
)


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


def test_resume_rebuilds_cookie_task_without_persisting_cookie() -> None:
    task = CrawlTask(
        owner_id=uuid.uuid4(),
        crawl_type="search",
        request_json=json.dumps(
            {
                "crawl_type": "search",
                "login_type": "cookie",
                "keywords": ["测试"],
            }
        ),
    )

    qrcode_request = DouyinTaskManager._rebuild_request(
        task, CrawlTaskResumeRequest()
    )
    cookie_request = DouyinTaskManager._rebuild_request(
        task, CrawlTaskResumeRequest(cookies="sessionid=fresh-secret")
    )

    assert qrcode_request.login_type == DouyinLoginType.qrcode
    assert qrcode_request.cookies is None
    assert cookie_request.login_type == DouyinLoginType.cookie
    assert cookie_request.cookies is not None
    assert cookie_request.cookies.get_secret_value() == "sessionid=fresh-secret"
    assert "fresh-secret" not in repr(cookie_request)
