import asyncio
import uuid
from typing import Any, cast

from app.core.config import settings
from app.douyin.crawler import DouyinCrawlerService
from app.douyin.storage import DouyinStorage
from app.models import CrawlTaskCreate


class FakeStorage:
    def __init__(self) -> None:
        self.awemes: list[str] = []

    async def save_aweme(
        self, item: dict[str, Any], *, source_keyword: str
    ) -> bool:
        self.awemes.append(str(item["aweme_id"]))
        return True


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
