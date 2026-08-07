import asyncio
import uuid
from typing import Any, cast

from app.core.config import settings
from app.douyin.crawler import DouyinCrawlerService
from app.douyin.exceptions import DataFetchError
from app.douyin.storage import DouyinStorage
from app.models import CrawlTaskCreate, CrawlTaskPhase


class FakeStorage:
    def __init__(self) -> None:
        self.awemes: list[str] = []
        self.checkpoint: dict[str, Any] = {
            "phase": "crawl",
            "crawl_type": "search",
            "position": {},
        }

    async def save_aweme(
        self, item: dict[str, Any], *, source_keyword: str
    ) -> bool:
        self.awemes.append(str(item["aweme_id"]))
        return True

    async def load_checkpoint(self) -> dict[str, Any]:
        return self.checkpoint

    async def save_checkpoint(
        self,
        *,
        phase: CrawlTaskPhase,
        crawl_type: str,
        position: dict[str, Any] | None = None,
    ) -> None:
        self.checkpoint = {
            "phase": phase.value,
            "crawl_type": crawl_type,
            "position": position or {},
        }

    async def aweme_ids(self) -> set[str]:
        return set(self.awemes)

    async def comment_counts(self, aweme_ids: list[str]) -> dict[str, int]:
        return dict.fromkeys(aweme_ids, 0)

    async def save_comments(
        self, _aweme_id: str, _items: list[dict[str, Any]]
    ) -> None:
        return None


class FakeSearchClient:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, *_: Any, **__: Any) -> dict[str, Any]:
        self.calls += 1
        return {
            "data": [
                {"aweme_info": {"aweme_id": str(index), "desc": "测试"}}
                for index in range(20)
            ],
            "extra": {"logid": "next"},
        }


async def _no_qrcode(_: Any) -> None:
    return None


def test_search_honours_global_aweme_limit() -> None:
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


class CheckpointSearchClient:
    def __init__(self, *, fail_offset: int | None = None) -> None:
        self.fail_offset = fail_offset
        self.offsets: list[int] = []

    async def search(
        self, _keyword: str, *, offset: int, **_kwargs: Any
    ) -> dict[str, Any]:
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
    storage = FakeStorage()
    request = CrawlTaskCreate(
        keywords=["断点测试"], max_awemes=4, fetch_comments=False
    )
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
    def __init__(self, *, fail_comments: bool) -> None:
        self.fail_comments = fail_comments
        self.offsets: list[int] = []
        self.comment_aweme_ids: list[str] = []

    async def search(
        self, _keyword: str, *, offset: int, **_kwargs: Any
    ) -> dict[str, Any]:
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
        self.comment_aweme_ids.append(aweme_id)
        if self.fail_comments:
            raise DataFetchError("simulated comment interruption")


def test_search_resume_retries_interrupted_page_comments() -> None:
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
    async def comment_counts(self, aweme_ids: list[str]) -> dict[str, int]:
        existing = {"complete": 10, "partial": 7}
        return {aweme_id: existing.get(aweme_id, 0) for aweme_id in aweme_ids}


class CommentLimitClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def get_all_comments(
        self, aweme_id: str, *, max_count: int, **_kwargs: Any
    ) -> int:
        self.calls.append((aweme_id, max_count))
        return max_count


def test_comment_resume_uses_remaining_persisted_limit() -> None:
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
        service._batch_comments(
            ["complete", "partial", "partial", "empty"], ""
        )
    )

    assert sorted(client.calls) == [("empty", 10), ("partial", 3)]


class CreatorDiscoveryClient:
    async def get_video(self, aweme_id: str) -> dict[str, Any]:
        assert aweme_id == "123456"
        return {
            "aweme_id": aweme_id,
            "author": {"sec_uid": "raw-sec-user-id"},
        }


def test_creator_from_aweme_uses_raw_creator_id_in_memory_only() -> None:
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
        captured.extend(service.request.creator_ids)

    service._creators = cast(Any, capture_creator_request)

    asyncio.run(service._creator_from_awemes())

    assert captured == ["raw-sec-user-id"]
    assert service.request is request
    assert service.request.creator_ids == []
    assert "raw-sec-user-id" not in str(service.request.public_request())
