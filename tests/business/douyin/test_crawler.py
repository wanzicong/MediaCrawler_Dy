"""抖音采集服务（DouyinCrawlerService）的测试：覆盖请求随机延迟、CDP 槽位释放后再做媒体等待、全局作品上限、搜索/评论断点续采、一次性 cookie 头与作者反查的身份脱敏。"""

import asyncio
import uuid
from typing import Any, cast

import pytest
from crawler.bootstrap.settings import settings
from crawler.business.douyin.tasks.crawler import DouyinCrawlerService
from crawler.business.douyin.tasks.models import (
    CrawlTaskCreate,
    CrawlTaskPhase,
    DouyinRequestDelayLevel,
)
from crawler.business.douyin.tasks.persistence import DouyinStorage
from crawler.douyin_client.errors import DataFetchError


class FakeStorage:
    """内存态任务存储替身：记录已保存的作品 id 与检查点，支撑断点续采断言。"""

    def __init__(self) -> None:
        """初始化空的作品列表与 crawl 阶段的初始检查点。"""
        self.awemes: list[str] = []
        self.checkpoint: dict[str, Any] = {
            "phase": "crawl",
            "crawl_type": "search",
            "position": {},
        }

    async def save_aweme(self, item: dict[str, Any], *, source_keyword: str) -> bool:
        """记录作品 id，返回保存成功。"""
        self.awemes.append(str(item["aweme_id"]))
        return True

    async def load_checkpoint(self) -> dict[str, Any]:
        """返回当前内存中的检查点。"""
        return self.checkpoint

    async def save_checkpoint(
        self,
        *,
        phase: CrawlTaskPhase,
        crawl_type: str,
        position: dict[str, Any] | None = None,
    ) -> None:
        """覆盖写入检查点（阶段/采集类型/位置）。"""
        self.checkpoint = {
            "phase": phase.value,
            "crawl_type": crawl_type,
            "position": position or {},
        }

    async def aweme_ids(self) -> set[str]:
        """返回已保存作品 id 集合。"""
        return set(self.awemes)

    async def comment_counts(self, aweme_ids: list[str]) -> dict[str, int]:
        """返回各作品已持久化评论数（默认全部为 0）。"""
        return dict.fromkeys(aweme_ids, 0)

    async def save_comments(self, _aweme_id: str, _items: list[dict[str, Any]]) -> None:
        """评论保存空实现。"""
        return None


class FakeSearchClient:
    """模拟搜索客户端：每次调用固定返回 20 条作品并带下一页 logid。"""

    def __init__(self) -> None:
        """初始化调用计数器。"""
        self.calls = 0

    async def search(self, *_: Any, **__: Any) -> dict[str, Any]:
        """返回一页模拟搜索结果。"""
        self.calls += 1
        return {
            "data": [
                {"aweme_info": {"aweme_id": str(index), "desc": "测试"}}
                for index in range(20)
            ],
            "extra": {"logid": "next"},
        }


async def _no_qrcode(_: Any) -> None:
    """二维码回调空实现（测试不触发扫码流程）。"""
    return None


def test_request_delay_uses_random_value_inside_selected_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证请求延迟取自所选档位区间内的随机值（steady 档为 3~6 秒）。"""
    request = CrawlTaskCreate(
        keywords=["随机延迟"],
        request_delay_level=DouyinRequestDelayLevel.steady,
    )
    service = DouyinCrawlerService(
        task_id=uuid.uuid4(),
        request=request,
        settings=settings,
        storage=cast(DouyinStorage, FakeStorage()),
        on_qrcode=_no_qrcode,
    )
    captured: list[tuple[float, float]] = []

    def fake_uniform(minimum: float, maximum: float) -> float:
        """记录随机区间入参并返回固定值，便于断言区间与结果。"""
        captured.append((minimum, maximum))
        return 4.25

    monkeypatch.setattr(
        "crawler.business.douyin.tasks.crawler.random.uniform", fake_uniform
    )

    assert service._request_delay_seconds() == 4.25
    assert captured == [(3.0, 6.0)]


def test_media_wait_runs_after_releasing_cdp_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证采集完成后先释放 CDP 浏览器槽位再进入媒体处理等待，媒体阶段不再占用槽位且复用采集期请求头。"""
    browser_slot = asyncio.Semaphore(1)
    storage = FakeStorage()
    observations: list[str] = []

    async def acquired() -> None:
        """浏览器槽位获取回调：断言此时槽位被占用。"""
        assert browser_slot.locked()
        observations.append("acquired")

    service = DouyinCrawlerService(
        task_id=uuid.uuid4(),
        request=CrawlTaskCreate(
            keywords=["释放浏览器"],
            fetch_comments=False,
            download_media=True,
            media_processing_mode="batch",
        ),
        settings=settings,
        storage=cast(DouyinStorage, storage),
        on_qrcode=_no_qrcode,
        browser_semaphore=browser_slot,
        on_browser_acquired=acquired,
    )

    async def crawl() -> dict[str, str]:
        """模拟采集阶段：断言持有槽位并返回请求头。"""
        assert browser_slot.locked()
        observations.append("crawl")
        return {"Referer": "https://www.douyin.com/"}

    async def media(
        headers: dict[str, str] | None = None,
        *,
        force_retranslate: bool = False,
    ) -> None:
        """模拟媒体阶段：断言槽位已释放且请求头被透传。"""
        assert not browser_slot.locked()
        assert headers == {"Referer": "https://www.douyin.com/"}
        assert force_retranslate is False
        observations.append("media")

    monkeypatch.setattr(service, "_crawl", crawl)
    monkeypatch.setattr(service, "_run_media", media)

    asyncio.run(service.run())

    assert observations == ["acquired", "crawl", "media"]


def test_search_honours_global_aweme_limit() -> None:
    """验证多关键词搜索共享全局作品上限：达到 max_awemes 后停止翻页与后续关键词。"""
    storage = FakeStorage()
    client = FakeSearchClient()
    service = DouyinCrawlerService(
        task_id=uuid.uuid4(),
        request=CrawlTaskCreate(
            keywords=["关键词一", "关键词二"], max_awemes=3, fetch_comments=False
        ),
        settings=settings,
        storage=cast(DouyinStorage, storage),
        on_qrcode=_no_qrcode,
    )
    service.client = cast(Any, client)

    asyncio.run(service._search())

    assert storage.awemes == ["0", "1", "2"]
    assert client.calls == 1


def test_search_verify_check_is_not_marked_as_successful_empty_result() -> None:
    """验证 HTTP 200 但命中 verify_check 时显式失败，避免关键词任务显示成功且作品为零。"""
    storage = FakeStorage()

    class VerifyCheckClient:
        async def search(self, *_: Any, **__: Any) -> dict[str, Any]:
            return {
                "status_code": 0,
                "data": [],
                "search_nil_info": {
                    "search_nil_type": "verify_check",
                    "search_nil_item": "verify_check",
                },
            }

    service = DouyinCrawlerService(
        task_id=uuid.uuid4(),
        request=CrawlTaskCreate(
            keywords=["有真实结果的关键词"], max_awemes=3, fetch_comments=False
        ),
        settings=settings,
        storage=cast(DouyinStorage, storage),
        on_qrcode=_no_qrcode,
    )
    service.client = cast(Any, VerifyCheckClient())

    with pytest.raises(DataFetchError, match="安全校验"):
        asyncio.run(service._search())


class CheckpointSearchClient:
    """可在指定页码抛错的模拟搜索客户端：按 offset 生成作品 id，用于断点续采测试。"""

    def __init__(self, *, fail_offset: int | None = None) -> None:
        """初始化失败页码与 offset 记录列表。

        参数：
            fail_offset: 该 offset 的搜索请求将抛出异常以模拟中断，None 表示不失败。
        """
        self.fail_offset = fail_offset
        self.offsets: list[int] = []

    async def search(
        self, _keyword: str, *, offset: int, **_kwargs: Any
    ) -> dict[str, Any]:
        """记录 offset；命中失败页则抛错，否则返回两条模拟作品。"""
        self.offsets.append(offset)
        if offset == self.fail_offset:
            raise RuntimeError("simulated interruption")
        start = offset + 1
        return {
            "data": [
                {"aweme_info": {"aweme_id": str(start + index), "desc": "测试"}}
                for index in range(2)
            ],
            "extra": {"logid": f"page-{offset}"},
        }


def test_search_resume_starts_from_persisted_page_checkpoint() -> None:
    """验证搜索在第二页中断后，续采从检查点记录的页码继续且不重复拉取已保存作品。"""
    storage = FakeStorage()
    request = CrawlTaskCreate(keywords=["断点测试"], max_awemes=4, fetch_comments=False)
    interrupted_client = CheckpointSearchClient(fail_offset=10)
    first = DouyinCrawlerService(
        task_id=uuid.uuid4(),
        request=request,
        settings=settings,
        storage=cast(DouyinStorage, storage),
        on_qrcode=_no_qrcode,
    )
    first.client = cast(Any, interrupted_client)

    try:
        asyncio.run(first._search())
    except RuntimeError as exc:
        assert "interruption" in str(exc)
    else:
        raise AssertionError("第一次爬取应在第二页中断")

    assert storage.awemes == ["1", "2"]
    assert storage.checkpoint["position"]["page"] == 2
    resumed_client = CheckpointSearchClient()
    resumed = DouyinCrawlerService(
        task_id=first.task_id,
        request=request,
        settings=settings,
        storage=cast(DouyinStorage, storage),
        on_qrcode=_no_qrcode,
    )
    resumed.client = cast(Any, resumed_client)
    resumed.seen_aweme_ids = asyncio.run(storage.aweme_ids())

    asyncio.run(resumed._search())

    assert resumed_client.offsets == [10]
    assert storage.awemes == ["1", "2", "11", "12"]


class CommentCheckpointClient:
    """模拟搜索+评论客户端：评论拉取可按开关抛错，用于评论阶段断点续采测试。"""

    def __init__(self, *, fail_comments: bool) -> None:
        """初始化评论失败开关与调用记录列表。"""
        self.fail_comments = fail_comments
        self.offsets: list[int] = []
        self.comment_aweme_ids: list[str] = []

    async def search(
        self, _keyword: str, *, offset: int, **_kwargs: Any
    ) -> dict[str, Any]:
        """首页返回两条作品，后续页返回空列表。"""
        self.offsets.append(offset)
        if offset:
            return {"data": []}
        return {
            "data": [
                {"aweme_info": {"aweme_id": "comment-1"}},
                {"aweme_info": {"aweme_id": "comment-2"}},
            ]
        }

    async def get_all_comments(self, aweme_id: str, **_kwargs: Any) -> None:
        """记录评论拉取的作品 id；开启失败开关时抛出 DataFetchError 模拟中断。"""
        self.comment_aweme_ids.append(aweme_id)
        if self.fail_comments:
            raise DataFetchError("simulated comment interruption")


def test_search_resume_retries_interrupted_page_comments() -> None:
    """验证评论阶段中断会记录待处理作品清单，续采时跳过搜索直接补拉这些作品的评论。"""
    storage = FakeStorage()
    request = CrawlTaskCreate(
        keywords=["评论断点"],
        max_awemes=2,
        fetch_comments=True,
        concurrency=2,
    )
    interrupted_client = CommentCheckpointClient(fail_comments=True)
    first = DouyinCrawlerService(
        task_id=uuid.uuid4(),
        request=request,
        settings=settings,
        storage=cast(DouyinStorage, storage),
        on_qrcode=_no_qrcode,
    )
    first.client = cast(Any, interrupted_client)

    try:
        asyncio.run(first._search())
    except DataFetchError as exc:
        assert "评论未完成" in str(exc)
    else:
        raise AssertionError("评论处理中断应让任务进入可恢复失败状态")

    assert storage.checkpoint["position"]["stage"] == "comments"
    assert storage.checkpoint["position"]["pending_aweme_ids"] == [
        "comment-1",
        "comment-2",
    ]
    resumed_client = CommentCheckpointClient(fail_comments=False)
    resumed = DouyinCrawlerService(
        task_id=first.task_id,
        request=request,
        settings=settings,
        storage=cast(DouyinStorage, storage),
        on_qrcode=_no_qrcode,
    )
    resumed.client = cast(Any, resumed_client)
    resumed.seen_aweme_ids = asyncio.run(storage.aweme_ids())

    asyncio.run(resumed._search())

    assert resumed_client.comment_aweme_ids == ["comment-1", "comment-2"]
    assert resumed_client.offsets == [10]


def test_media_only_resume_builds_non_persistent_cookie_headers() -> None:
    """验证媒体补跑用的一次性请求头携带 Cookie 与 Referer，且 cookie 不写入公开请求快照。"""
    request = CrawlTaskCreate(
        keywords=["媒体断点"],
        cookies="sessionid=one-time-secret",
        download_media=True,
    )
    service = DouyinCrawlerService(
        task_id=uuid.uuid4(),
        request=request,
        settings=settings,
        storage=cast(DouyinStorage, FakeStorage()),
        on_qrcode=_no_qrcode,
    )

    headers = service._one_time_media_headers()

    assert headers == {
        "Cookie": "sessionid=one-time-secret",
        "Referer": "https://www.douyin.com/",
    }
    assert "cookies" not in request.public_request()


class ExistingCommentStorage(FakeStorage):
    """带既有评论数的存储替身：complete 已拉满、partial 只拉到一部分。"""

    async def comment_counts(self, aweme_ids: list[str]) -> dict[str, int]:
        """返回各作品已持久化的评论数（未知名作品视为 0）。"""
        existing = {"complete": 10, "partial": 7}
        return {aweme_id: existing.get(aweme_id, 0) for aweme_id in aweme_ids}


class CommentLimitClient:
    """记录评论拉取调用的模拟客户端：按传入上限返回拉取数量。"""

    def __init__(self) -> None:
        """初始化调用记录列表（元素为 (aweme_id, max_count)）。"""
        self.calls: list[tuple[str, int]] = []

    async def get_all_comments(
        self, aweme_id: str, *, max_count: int, **_kwargs: Any
    ) -> int:
        """记录调用并返回 max_count 作为本次拉取数。"""
        self.calls.append((aweme_id, max_count))
        return max_count


def test_comment_resume_uses_remaining_persisted_limit() -> None:
    """验证评论续采按「上限-已持久化数」计算剩余额度：已拉满的跳过、部分完成的只补差额、去重处理。"""
    storage = ExistingCommentStorage()
    client = CommentLimitClient()
    service = DouyinCrawlerService(
        task_id=uuid.uuid4(),
        request=CrawlTaskCreate(
            keywords=["累计评论上限"],
            max_comments_per_aweme=10,
            concurrency=3,
        ),
        settings=settings,
        storage=cast(DouyinStorage, storage),
        on_qrcode=_no_qrcode,
    )
    service.client = cast(Any, client)

    asyncio.run(
        service._batch_comments(["complete", "partial", "partial", "empty"], "")
    )

    assert sorted(client.calls) == [("empty", 10), ("partial", 3)]


class CommentRecrawlSourceStorage(FakeStorage):
    """评论补采的来源存储替身：持有既有作品并记录评论回写。"""

    def __init__(self) -> None:
        """初始化一个既有作品和空的评论回写记录。"""
        super().__init__()
        self.awemes = ["7654321098765432100"]
        self.saved_comment_awemes: list[str] = []

    async def save_comments(self, aweme_id: str, _items: list[dict[str, Any]]) -> None:
        """记录评论写入的作品，证明回写到了来源任务。"""
        self.saved_comment_awemes.append(aweme_id)


class CommentOnlyClient:
    """评论补采客户端：禁止请求作品详情，只允许请求评论。"""

    def __init__(self) -> None:
        """初始化接口调用记录。"""
        self.detail_calls = 0
        self.comment_calls: list[str] = []

    async def get_video(self, _aweme_id: str) -> dict[str, Any]:
        """评论补采不应调用详情接口。"""
        self.detail_calls += 1
        raise AssertionError("comment recrawl must not request aweme detail")

    async def get_all_comments(
        self,
        aweme_id: str,
        *,
        callback: Any,
        **_kwargs: Any,
    ) -> int:
        """模拟抓取一页评论并调用持久化回调。"""
        self.comment_calls.append(aweme_id)
        await callback(aweme_id, [{"cid": "comment-1"}])
        return 1


def test_comment_recrawl_reuses_existing_aweme_without_fetching_or_inserting_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证已有作品的评论补采只更新来源评论，不请求详情或向子任务重复写作品。"""
    child_storage = FakeStorage()
    source_storage = CommentRecrawlSourceStorage()
    source_task_id = uuid.uuid4()
    client = CommentOnlyClient()
    service = DouyinCrawlerService(
        task_id=uuid.uuid4(),
        request=CrawlTaskCreate(
            crawl_type="detail",
            video_ids=["7654321098765432100"],
            comment_source_task_id=source_task_id,
            max_comments_per_aweme=10,
        ),
        settings=settings,
        storage=cast(DouyinStorage, child_storage),
        on_qrcode=_no_qrcode,
    )
    service.client = cast(Any, client)

    def source_storage_factory(task_id: uuid.UUID) -> CommentRecrawlSourceStorage:
        """仅允许执行器打开声明的来源任务存储。"""
        assert task_id == source_task_id
        return source_storage

    monkeypatch.setattr(
        "crawler.business.douyin.tasks.crawler.DouyinStorage",
        source_storage_factory,
    )

    asyncio.run(service._details())

    assert client.detail_calls == 0
    assert client.comment_calls == ["7654321098765432100"]
    assert child_storage.awemes == []
    assert source_storage.saved_comment_awemes == ["7654321098765432100"]
    assert child_storage.checkpoint["position"]["completed_indexes"] == [0]


class CreatorPostsClient:
    """达人作品列表客户端：列表直接返回完整作品，并禁止额外调用作品详情。"""

    def __init__(
        self,
        *,
        fail_comment_for: str | None = None,
    ) -> None:
        """初始化评论失败目标与接口调用记录。"""
        self.fail_comment_for = fail_comment_for
        self.post_calls = 0
        self.detail_calls = 0
        self.comment_calls: list[str] = []

    async def get_user_info(self, _sec_user_id: str) -> dict[str, Any]:
        """模拟达人资料校验成功。"""
        return {"status_code": 0}

    async def get_user_posts(self, _sec_user_id: str, _cursor: str) -> dict[str, Any]:
        """返回一页完整作品以及两条应被忽略的无效数据。"""
        self.post_calls += 1
        return {
            "aweme_list": [
                {
                    "aweme_id": "creator-post-1",
                    "desc": "达人作品一",
                    "author": {"nickname": "达人"},
                    "statistics": {"digg_count": 12},
                },
                None,
                {},
                {
                    "aweme_id": "creator-post-2",
                    "desc": "达人作品二",
                    "author": {"nickname": "达人"},
                    "statistics": {"digg_count": 8},
                },
            ],
            "has_more": 0,
            "max_cursor": "",
        }

    async def get_video(self, _aweme_id: str) -> dict[str, Any]:
        """达人列表链路不应再逐条调用详情接口。"""
        self.detail_calls += 1
        raise AssertionError("creator crawl must not call the detail endpoint")

    async def get_all_comments(self, aweme_id: str, **_kwargs: Any) -> int:
        """记录评论请求，并可模拟单作品评论失败。"""
        self.comment_calls.append(aweme_id)
        if aweme_id == self.fail_comment_for:
            raise DataFetchError("simulated single-work comment failure")
        return 1


def test_creator_crawl_persists_post_list_without_per_work_detail_requests() -> None:
    """验证达人采集直接保存作品列表对象，不再发出逐作品详情请求。"""
    storage = FakeStorage()
    client = CreatorPostsClient()
    service = DouyinCrawlerService(
        task_id=uuid.uuid4(),
        request=CrawlTaskCreate(
            crawl_type="creator",
            creator_ids=["creator-sec-user"],
            max_awemes=10,
            fetch_comments=False,
        ),
        settings=settings,
        storage=cast(DouyinStorage, storage),
        on_qrcode=_no_qrcode,
    )
    service.client = cast(Any, client)

    asyncio.run(service._creators())

    assert storage.awemes == ["creator-post-1", "creator-post-2"]
    assert client.post_calls == 1
    assert client.detail_calls == 0
    assert storage.checkpoint["position"] == {
        "target_index": 1,
        "cursor": "",
        "stage": "fetch",
    }


def test_creator_crawl_tolerates_single_work_comment_failure() -> None:
    """验证达人批量采集的一条评论失败只降级该作品，不再让整个任务失败。"""
    storage = FakeStorage()
    client = CreatorPostsClient(fail_comment_for="creator-post-2")
    service = DouyinCrawlerService(
        task_id=uuid.uuid4(),
        request=CrawlTaskCreate(
            crawl_type="creator",
            creator_ids=["creator-sec-user"],
            max_awemes=10,
            fetch_comments=True,
            concurrency=2,
        ),
        settings=settings,
        storage=cast(DouyinStorage, storage),
        on_qrcode=_no_qrcode,
    )
    service.client = cast(Any, client)

    asyncio.run(service._creators())

    assert storage.awemes == ["creator-post-1", "creator-post-2"]
    assert sorted(client.comment_calls) == ["creator-post-1", "creator-post-2"]
    assert storage.checkpoint["position"]["target_index"] == 1


class CreatorDiscoveryClient:
    """模拟详情客户端：返回带原始 sec_uid 的作者信息，用于作者反采链路测试。"""

    async def get_video(self, aweme_id: str) -> dict[str, Any]:
        """返回指定作品的模拟详情（含未脱敏的作者 sec_uid）。"""
        assert aweme_id == "123456"
        return {
            "aweme_id": aweme_id,
            "author": {"sec_uid": "raw-sec-user-id"},
        }


def test_creator_from_aweme_uses_raw_creator_id_in_memory_only() -> None:
    """验证由作品反查作者时原始 sec_uid 仅存在于内存请求中，不写入任务请求与公开快照。"""
    request = CrawlTaskCreate(
        crawl_type="creator_from_aweme",
        video_ids=["123456"],
        fetch_comments=False,
    )
    service = DouyinCrawlerService(
        task_id=uuid.uuid4(),
        request=request,
        settings=settings,
        storage=cast(DouyinStorage, FakeStorage()),
        on_qrcode=_no_qrcode,
    )
    service.client = cast(Any, CreatorDiscoveryClient())
    captured: list[str] = []

    async def capture_creator_request() -> None:
        """捕获进入作者采集流程时的 creator_ids（应为内存中的原始 sec_uid）。"""
        captured.extend(service.request.creator_ids)

    service._creators = cast(Any, capture_creator_request)

    asyncio.run(service._creator_from_awemes())

    assert captured == ["raw-sec-user-id"]
    assert service.request is request
    assert service.request.creator_ids == []
    assert "raw-sec-user-id" not in str(service.request.public_request())
