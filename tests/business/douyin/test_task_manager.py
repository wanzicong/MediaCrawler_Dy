"""抖音采集任务管理器的测试：覆盖浏览器模式/媒体存储默认值解析、任务断点续跑请求重建、纯媒体任务跳过 CDP 信号量等调度行为。"""

import asyncio
import json
import uuid
from typing import Any

import pytest
from crawler.business.douyin.accounts.models import DouyinBrowserMode
from crawler.business.douyin.media.models import MediaStorageBackend
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskPhase,
    CrawlTaskResumeRequest,
    DouyinLoginType,
)
from crawler.business.douyin.tasks.service import (
    DouyinTaskManager,
    resolve_browser_mode,
    resolve_media_storage,
)


def test_configured_browser_mode_is_used_when_request_omits_it() -> None:
    """验证请求未指定浏览器模式时使用配置默认值，且不修改原请求对象。"""
    request = CrawlTaskCreate(keywords=["测试"])

    resolved = resolve_browser_mode(request, "remote")

    assert resolved.browser_mode == DouyinBrowserMode.remote
    assert request.browser_mode is None


def test_task_browser_mode_overrides_configured_default() -> None:
    """验证请求显式指定浏览器模式时优先于配置默认值，且返回原请求对象。"""
    request = CrawlTaskCreate(keywords=["测试"], browser_mode="local")

    resolved = resolve_browser_mode(request, "remote")

    assert resolved is request
    assert resolved.browser_mode == DouyinBrowserMode.local


def test_configured_media_storage_is_used_when_request_omits_it() -> None:
    """验证请求未指定媒体存储后端时使用配置默认值，且不修改原请求对象。"""
    request = CrawlTaskCreate(keywords=["测试"])

    resolved = resolve_media_storage(request, "minio")

    assert resolved.media_storage == MediaStorageBackend.minio
    assert request.media_storage is None


def test_task_media_storage_overrides_configured_default() -> None:
    """验证请求显式指定媒体存储后端时优先于配置默认值，且返回原请求对象。"""
    request = CrawlTaskCreate(keywords=["测试"], media_storage="local")

    resolved = resolve_media_storage(request, "minio")

    assert resolved is request
    assert resolved.media_storage == MediaStorageBackend.local


def test_resume_rebuilds_cookie_task_without_persisting_cookie() -> None:
    """验证断点续跑重建请求时：默认回退为扫码登录、显式传入 cookies 才走 cookie 登录，且 cookies 不出现在 repr 中（防泄密）。"""
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

    qrcode_request = DouyinTaskManager._rebuild_request(task, CrawlTaskResumeRequest())
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
    """验证纯媒体处理任务（不采集）不会阻塞等待 CDP 浏览器信号量，直接执行媒体补跑并完成。"""
    updates: list[dict[str, object]] = []
    crawler_runs: list[dict[str, Any]] = []

    class FakeStorage:
        """模拟任务存储层：仅记录状态更新与任务完成事件。"""

        def __init__(self, _task_id: uuid.UUID) -> None:
            pass

        async def update_task(self, **values: object) -> None:
            """记录一次任务字段更新到 updates 列表。"""
            updates.append(values)

        async def complete_task(self, crawl_type: str) -> None:
            """记录任务完成事件。"""
            updates.append({"completed": crawl_type})

    class FakeCrawler:
        """模拟采集服务：仅记录 run 调用参数，不执行真实采集。"""

        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def run(self, **kwargs: Any) -> None:
            """记录一次采集运行参数到 crawler_runs 列表。"""
            crawler_runs.append(kwargs)

    monkeypatch.setattr(
        "crawler.business.douyin.tasks.service.DouyinStorage", FakeStorage
    )
    monkeypatch.setattr(
        "crawler.business.douyin.tasks.service.DouyinCrawlerService", FakeCrawler
    )
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
