import asyncio
import json
import uuid
from typing import Any

import pytest

from app.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskPhase,
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
    track_id = uuid.uuid4()
    task = CrawlTask(
        owner_id=uuid.uuid4(),
        track_id=track_id,
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
    assert cookie_request.track_id == track_id
    assert "fresh-secret" not in repr(cookie_request)


def test_media_only_run_does_not_wait_for_cdp_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updates: list[dict[str, object]] = []
    crawler_runs: list[dict[str, Any]] = []

    class FakeStorage:
        def __init__(self, _task_id: uuid.UUID) -> None:
            pass

        async def update_task(self, **values: object) -> None:
            updates.append(values)

        async def complete_task(self, crawl_type: str) -> None:
            updates.append({"completed": crawl_type})

    class FakeCrawler:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def run(self, **kwargs: Any) -> None:
            crawler_runs.append(kwargs)

    monkeypatch.setattr("app.services.douyin_tasks.DouyinStorage", FakeStorage)
    monkeypatch.setattr("app.services.douyin_tasks.DouyinCrawlerService", FakeCrawler)
    manager = DouyinTaskManager()
    manager._semaphore = asyncio.Semaphore(0)
    request = CrawlTaskCreate(
        keywords=["纯媒体任务"],
        download_media=True,
        media_processing_mode="batch",
    )

    asyncio.run(
        asyncio.wait_for(
            manager._run(
                uuid.uuid4(),
                request,
                resumed=True,
                crawl_enabled=False,
                media_enabled=True,
                checkpoint_phase=CrawlTaskPhase.media,
            ),
            timeout=0.5,
        )
    )

    assert crawler_runs == [
        {
            "crawl_enabled": False,
            "media_enabled": True,
            "force_retranslate": False,
        }
    ]
    assert updates[0]["status"] == "processing_media"
    assert updates[-1] == {"completed": "search"}
