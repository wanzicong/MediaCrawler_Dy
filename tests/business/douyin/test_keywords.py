"""抖音关键词库的测试：覆盖关键词状态推导、批量创建去重、改名约束（历史归因保护）、任务同步与历史同步、批量建任务以及任务落库自动绑定关键词。"""

import json
import uuid

from crawler.bootstrap.settings import settings
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.keywords.models import DouyinKeyword, DouyinKeywordTaskLink
from crawler.business.douyin.keywords.service import _status_for
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskStatus,
)
from crawler.business.douyin.tasks.service import task_manager
from crawler.business.identity.models import User
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlmodel import Session, select

from tests.utils.douyin import default_track_id


def test_keyword_status_prioritizes_active_recrawl() -> None:
    """验证关键词状态推导：存在进行中的重采任务时优先标记为 active 而非 succeeded。"""
    owner_id = uuid.uuid4()
    track_id = uuid.uuid4()
    tasks = [
        CrawlTask(
            owner_id=owner_id,
            track_id=track_id,
            crawl_type="search",
            status=CrawlTaskStatus.succeeded.value,
            request_json="{}",
            checkpoint_json="{}",
        ),
        CrawlTask(
            owner_id=owner_id,
            track_id=track_id,
            crawl_type="search",
            status=CrawlTaskStatus.running.value,
            request_json="{}",
            checkpoint_json="{}",
        ),
    ]

    assert _status_for(tasks).value == "active"


def test_keyword_crud_sync_status_and_history(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证关键词批量创建（去空白/大小写去重）、历史任务同步绑定、状态筛选与统计、改名受历史归因保护、停用与历史全量同步。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    suffix = uuid.uuid4().hex[:8]
    fastapi_keyword = f"FastAPI-{suffix}"
    python_keyword = f"Python-{suffix}"
    created = client.post(
        f"{settings.API_V1_STR}/douyin/keywords/bulk",
        headers=superuser_token_headers,
        json={
            "keywords": [
                f" {fastapi_keyword} ",
                fastapi_keyword.casefold(),
                python_keyword,
            ],
            "notes": "技术词",
        },
    )
    assert created.status_code == 201
    assert created.json()["created_count"] == 2
    assert created.json()["existing_count"] == 0
    keyword_ids = {item["keyword"]: item["id"] for item in created.json()["data"]}

    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="search",
        status=CrawlTaskStatus.succeeded.value,
        request_json=json.dumps(
            {"crawl_type": "search", "keywords": [fastapi_keyword]}
        ),
        checkpoint_json='{"version":1,"phase":"completed","position":{}}',
        aweme_count=1,
    )
    db.add(task)
    db.flush()
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id="keyword-work",
            title="关键词作品",
            source_keyword=fastapi_keyword,
        )
    )
    db.commit()

    legacy_work_rename = client.patch(
        f"{settings.API_V1_STR}/douyin/keywords/by-id/{keyword_ids[fastapi_keyword]}",
        headers=superuser_token_headers,
        json={"keyword": "FastAPI 遗留新词"},
    )
    assert legacy_work_rename.status_code == 409
    assert "历史任务或作品" in legacy_work_rename.json()["detail"]

    synced = client.post(
        f"{settings.API_V1_STR}/douyin/keywords/sync/tasks/{task.id}",
        headers=superuser_token_headers,
    )
    assert synced.status_code == 200
    assert synced.json() == {
        "task_count": 1,
        "keyword_count": 1,
        "created_count": 0,
        "binding_count": 1,
    }

    listing = client.get(
        f"{settings.API_V1_STR}/douyin/keywords/",
        headers=superuser_token_headers,
        params={"search": suffix, "status": "crawled"},
    )
    assert listing.status_code == 200
    assert listing.json()["count"] == 1
    row = listing.json()["data"][0]
    assert row["task_count"] == 1
    assert row["success_task_count"] == 1
    assert row["aweme_count"] == 1
    assert row["last_task_id"] == str(task.id)

    blocked_rename = client.patch(
        f"{settings.API_V1_STR}/douyin/keywords/by-id/{keyword_ids[fastapi_keyword]}",
        headers=superuser_token_headers,
        json={"keyword": "FastAPI 新词"},
    )
    assert blocked_rename.status_code == 409
    assert "已有历史任务" in blocked_rename.json()["detail"]
    notes_only = client.patch(
        f"{settings.API_V1_STR}/douyin/keywords/by-id/{keyword_ids[fastapi_keyword]}",
        headers=superuser_token_headers,
        json={"notes": "保留历史归因"},
    )
    assert notes_only.status_code == 200
    assert notes_only.json()["keyword"] == fastapi_keyword
    assert notes_only.json()["notes"] == "保留历史归因"

    tasks = client.get(
        f"{settings.API_V1_STR}/douyin/keywords/by-id/{keyword_ids[fastapi_keyword]}/tasks",
        headers=superuser_token_headers,
    )
    assert tasks.status_code == 200
    assert [item["id"] for item in tasks.json()] == [str(task.id)]

    edited = client.patch(
        f"{settings.API_V1_STR}/douyin/keywords/by-id/{keyword_ids[python_keyword]}",
        headers=superuser_token_headers,
        json={"enabled": False, "notes": "暂停运营"},
    )
    assert edited.status_code == 200
    assert edited.json()["enabled"] is False

    history = client.post(
        f"{settings.API_V1_STR}/douyin/keywords/sync/history",
        headers=superuser_token_headers,
    )
    assert history.status_code == 200
    assert history.json()["task_count"] >= 1

    db.delete(task)
    for item in db.exec(
        select(DouyinKeyword).where(DouyinKeyword.owner_id == owner.id)
    ):
        if item.id in {uuid.UUID(value) for value in keyword_ids.values()}:
            db.delete(item)
    db.commit()


def test_keyword_batch_task_creation(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    """验证按关键词批量发起采集任务：合并为一个任务、关键词完整透传且归属赛道已解析。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    created = client.post(
        f"{settings.API_V1_STR}/douyin/keywords/bulk",
        headers=superuser_token_headers,
        json={"keywords": ["批量甲", "批量乙"]},
    ).json()
    keyword_ids = [item["id"] for item in created["data"]]
    requests: list[CrawlTaskCreate] = []

    async def fake_create(
        *, owner_id: uuid.UUID, request: CrawlTaskCreate
    ) -> CrawlTask:
        """模拟任务创建：捕获请求并返回一条排队中的任务记录（不入库）。"""
        assert owner_id == owner.id
        assert request.track_id is not None
        requests.append(request)
        return CrawlTask(
            owner_id=owner_id,
            track_id=request.track_id,
            crawl_type="search",
            status="queued",
            request_json=json.dumps(request.public_request(), ensure_ascii=False),
            checkpoint_json='{"version":1,"phase":"crawl","position":{}}',
        )

    monkeypatch.setattr(task_manager, "create", fake_create)
    response = client.post(
        f"{settings.API_V1_STR}/douyin/keywords/batch-tasks",
        headers=superuser_token_headers,
        json={
            "keyword_ids": keyword_ids,
            "mode": "combined",
            "max_awemes": 30,
            "fetch_comments": False,
        },
    )
    assert response.status_code == 202
    assert response.json()["count"] == 1
    assert requests[0].keywords == ["批量甲", "批量乙"]
    assert requests[0].max_awemes == 30
    assert requests[0].fetch_comments is False

    for item in db.exec(
        select(DouyinKeyword).where(DouyinKeyword.owner_id == owner.id)
    ):
        if str(item.id) in keyword_ids:
            db.delete(item)
    db.commit()


def test_task_storage_auto_binds_keywords(db: Session) -> None:
    """验证任务落库时自动创建缺失关键词并建立 automatic 来源的任务-关键词关联。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    from crawler.business.douyin.tasks.persistence import DouyinStorage

    task = DouyinStorage._create_task_sync(
        owner.id, CrawlTaskCreate(keywords=["自动同步关键词"], fetch_comments=False)
    )
    db.expire_all()
    keyword = db.exec(
        select(DouyinKeyword).where(
            DouyinKeyword.owner_id == owner.id,
            DouyinKeyword.normalized_keyword == "自动同步关键词",
        )
    ).one()
    link = db.exec(
        select(DouyinKeywordTaskLink).where(
            DouyinKeywordTaskLink.keyword_id == keyword.id,
            DouyinKeywordTaskLink.task_id == task.id,
        )
    ).one()
    assert link.source == "automatic"
    db.delete(db.get(CrawlTask, task.id))
    db.delete(keyword)
    db.commit()
