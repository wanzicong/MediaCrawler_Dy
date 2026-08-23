"""抖音采集任务管理器的测试：覆盖浏览器模式/媒体存储默认值解析、任务断点续跑请求重建、纯媒体任务跳过 CDP 信号量等调度行为。"""

import asyncio
import json
import uuid
from typing import Any

import pytest
from crawler.business.douyin.accounts.models import DouyinBrowserMode
from crawler.business.douyin.media.models import (
    MediaProcessingMode,
    MediaStorageBackend,
)
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskPhase,
    CrawlTaskResumeRequest,
    DouyinLoginType,
)
from crawler.business.douyin.tasks.service import (
    DouyinTaskManager,
    TaskIntervalGate,
    normalize_new_task_targets,
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


def test_task_interval_gate_waits_after_completed_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证任务完成后才启动随机冷却，首个任务与未真正启动的任务不产生冷却。"""
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def exercise() -> None:
        gate = TaskIntervalGate()
        await gate.acquire()
        gate.release(None)
        await gate.acquire()
        gate.release((5.0, 5.0))
        await gate.acquire()
        gate.release(None)

    monkeypatch.setattr(
        "crawler.business.douyin.tasks.service.asyncio.sleep", fake_sleep
    )
    monkeypatch.setattr(
        "crawler.business.douyin.tasks.service.time.monotonic", lambda: 0.0
    )

    asyncio.run(exercise())

    assert sleeps == [5.0]


def test_explicit_task_interval_is_independent_from_request_interval() -> None:
    """验证任务级间隔显式设置后不再复用单请求间隔区间。"""
    request = CrawlTaskCreate(
        keywords=["任务间隔"],
        request_delay_level="fast",
        request_interval_seconds=1.0,
        task_interval_seconds=17.0,
    )

    assert request.request_interval_range_seconds() == (1.0, 2.0)
    assert request.task_interval_range_seconds() == (17.0, 17.0)


def test_task_manager_serializes_crawl_runs_with_task_interval_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证管理器会在前一任务完成后才放行下一任务，并复用任务请求风控区间。"""
    starts: list[uuid.UUID] = []
    sleeps: list[float] = []

    class FakeStorage:
        """记录任务完成事件的最小存储替身。"""

        def __init__(self, _task_id: uuid.UUID) -> None:
            pass

        @staticmethod
        async def get_task(task_id: uuid.UUID) -> CrawlTask:
            """返回供 worker 准入复检使用的最小任务快照。"""
            return CrawlTask(
                id=task_id,
                owner_id=uuid.uuid4(),
                track_id=uuid.uuid4(),
                crawl_type="search",
                request_json="{}",
            )

        @staticmethod
        async def validate_task_track_enabled(_task: CrawlTask) -> None:
            """模拟任务所属赛道仍处于启用状态。"""

        async def complete_task(self, _crawl_type: str) -> None:
            """记录任务已完成。"""

    class FakeCrawler:
        """记录爬虫开始顺序的最小爬虫替身。"""

        def __init__(self, *, task_id: uuid.UUID, **_kwargs: Any) -> None:
            self.task_id = task_id

        async def run(self, **_kwargs: Any) -> None:
            """记录一次爬虫运行。"""
            starts.append(self.task_id)

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    task_ids = (uuid.uuid4(), uuid.uuid4())

    async def exercise() -> None:
        manager = DouyinTaskManager()
        await asyncio.gather(
            manager._run(
                task_ids[0],
                CrawlTaskCreate(keywords=["任务一"]),
                accounts=[],
                media_enabled=False,
            ),
            manager._run(
                task_ids[1],
                CrawlTaskCreate(keywords=["任务二"]),
                accounts=[],
                media_enabled=False,
            ),
        )

    monkeypatch.setattr(
        "crawler.business.douyin.tasks.service.DouyinStorage", FakeStorage
    )
    monkeypatch.setattr(
        "crawler.business.douyin.tasks.service.DouyinCrawlerService", FakeCrawler
    )
    monkeypatch.setattr(
        "crawler.business.douyin.tasks.service.asyncio.sleep", fake_sleep
    )
    monkeypatch.setattr(
        "crawler.business.douyin.tasks.service.random.uniform", lambda _min, _max: 1.5
    )
    monkeypatch.setattr(
        "crawler.business.douyin.tasks.service.time.monotonic", lambda: 0.0
    )

    asyncio.run(exercise())

    assert starts == list(task_ids)
    assert sleeps == [1.5]


def test_new_search_task_requires_exactly_one_keyword() -> None:
    """验证新建关键词任务拒绝多关键词，并在落库前清理唯一关键词空白。"""
    with pytest.raises(ValueError, match="只能包含一个关键词"):
        normalize_new_task_targets(CrawlTaskCreate(keywords=["关键词一", "关键词二"]))

    normalized = normalize_new_task_targets(
        CrawlTaskCreate(
            keywords=["  唯一词  "],
            download_media=True,
            translate_subtitles=True,
            media_processing_mode="batch",
        )
    )

    assert normalized.keywords == ["唯一词"]
    assert normalized.download_media is False
    assert normalized.translate_subtitles is False
    assert normalized.media_processing_mode == MediaProcessingMode.none


def test_legacy_multi_keyword_task_can_still_be_rebuilt() -> None:
    """验证新规则不阻断历史多关键词任务的断点续跑。"""
    task = CrawlTask(
        owner_id=uuid.uuid4(),
        track_id=uuid.uuid4(),
        crawl_type="search",
        request_json=json.dumps(
            {"crawl_type": "search", "keywords": ["历史词一", "历史词二"]}
        ),
    )

    rebuilt = DouyinTaskManager._rebuild_request(task, CrawlTaskResumeRequest())

    assert rebuilt.keywords == ["历史词一", "历史词二"]


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


def test_resume_can_override_task_interval_without_touching_request_interval() -> None:
    """验证恢复时可覆盖任务间隔，单请求间隔保持原任务快照。"""
    task = CrawlTask(
        owner_id=uuid.uuid4(),
        track_id=uuid.uuid4(),
        crawl_type="search",
        request_json=json.dumps(
            {
                "crawl_type": "search",
                "keywords": ["恢复间隔"],
                "request_interval_seconds": 1.0,
                "task_interval_seconds": 4.0,
            }
        ),
    )

    rebuilt = DouyinTaskManager._rebuild_request(
        task,
        CrawlTaskResumeRequest(task_interval_seconds=23.0),
    )

    assert rebuilt.request_interval_seconds == 1.0
    assert rebuilt.task_interval_seconds == 23.0


def test_resume_can_replace_an_unavailable_original_account() -> None:
    """验证恢复时可用新的单账号覆盖旧账号池/多账号配置，避免历史账号失效后无法续跑。"""
    replacement_account_id = uuid.uuid4()
    task = CrawlTask(
        owner_id=uuid.uuid4(),
        track_id=uuid.uuid4(),
        crawl_type="creator",
        request_json=json.dumps(
            {
                "crawl_type": "creator",
                "creator_ids": ["creator-target"],
                "account_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
                "account_pool_id": None,
            }
        ),
    )

    rebuilt = DouyinTaskManager._rebuild_request(
        task,
        CrawlTaskResumeRequest(account_id=replacement_account_id),
    )

    assert rebuilt.account_id == replacement_account_id
    assert rebuilt.account_ids == []
    assert rebuilt.account_pool_id is None


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

        @staticmethod
        async def get_task(task_id: uuid.UUID) -> CrawlTask:
            """返回供 worker 准入复检使用的最小任务快照。"""
            return CrawlTask(
                id=task_id,
                owner_id=uuid.uuid4(),
                track_id=uuid.uuid4(),
                crawl_type="search",
                request_json="{}",
            )

        @staticmethod
        async def validate_task_track_enabled(_task: CrawlTask) -> None:
            """模拟任务所属赛道仍处于启用状态。"""

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


def test_busy_account_is_queued_at_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证账号仅因租约占满而暂不可用时，提交阶段进入后台等待而不是直接失败。"""
    manager = DouyinTaskManager()

    async def temporarily_busy(
        _owner_id: uuid.UUID, _request: CrawlTaskCreate
    ) -> list[object]:
        raise ValueError("所选账号当前不可调度，请等待可用容量")

    monkeypatch.setattr(manager, "_resolve_accounts", temporarily_busy)
    result = asyncio.run(
        manager._resolve_submission_accounts(
            uuid.uuid4(), CrawlTaskCreate(keywords=["排队测试"])
        )
    )

    assert result is None


def test_invalid_account_configuration_still_fails_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证账号不存在、未登录或停用等永久配置错误不会被误判成可等待状态。"""
    manager = DouyinTaskManager()

    async def permanently_invalid(
        _owner_id: uuid.UUID, _request: CrawlTaskCreate
    ) -> list[object]:
        raise ValueError("所选账号不存在、未登录或已停用")

    monkeypatch.setattr(manager, "_resolve_accounts", permanently_invalid)

    with pytest.raises(ValueError, match="不存在、未登录或已停用"):
        asyncio.run(
            manager._resolve_submission_accounts(
                uuid.uuid4(), CrawlTaskCreate(keywords=["配置错误"])
            )
        )
