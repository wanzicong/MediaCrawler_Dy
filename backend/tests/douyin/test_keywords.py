import json
import uuid

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskStatus,
    DouyinAweme,
    DouyinKeyword,
    DouyinKeywordTaskLink,
    User,
)
from app.services.douyin_keywords import _status_for
from app.services.douyin_tasks import task_manager


def test_keyword_status_prioritizes_active_recrawl() -> None:
    owner_id = uuid.uuid4()
    tasks = [
        CrawlTask(
            owner_id=owner_id,
            crawl_type="search",
            status=CrawlTaskStatus.succeeded.value,
            request_json="{}",
            checkpoint_json="{}",
        ),
        CrawlTask(
            owner_id=owner_id,
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
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    created = client.post(
        f"{settings.API_V1_STR}/douyin/keywords/bulk",
        headers=superuser_token_headers,
        json={"keywords": [" FastAPI ", "fastapi", "Python"], "notes": "技术词"},
    )
    assert created.status_code == 201
    assert created.json()["created_count"] == 2
    assert created.json()["existing_count"] == 0
    keyword_ids = {item["keyword"]: item["id"] for item in created.json()["data"]}

    task = CrawlTask(
        owner_id=owner.id,
        crawl_type="search",
        status=CrawlTaskStatus.succeeded.value,
        request_json=json.dumps({"crawl_type": "search", "keywords": ["FastAPI"]}),
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
            source_keyword="FastAPI",
        )
    )
    db.commit()

    legacy_work_rename = client.patch(
        f"{settings.API_V1_STR}/douyin/keywords/by-id/{keyword_ids['FastAPI']}",
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
        params={"search": "fast", "status": "crawled"},
    )
    assert listing.status_code == 200
    assert listing.json()["count"] == 1
    row = listing.json()["data"][0]
    assert row["task_count"] == 1
    assert row["success_task_count"] == 1
    assert row["aweme_count"] == 1
    assert row["last_task_id"] == str(task.id)

    blocked_rename = client.patch(
        f"{settings.API_V1_STR}/douyin/keywords/by-id/{keyword_ids['FastAPI']}",
        headers=superuser_token_headers,
        json={"keyword": "FastAPI 新词"},
    )
    assert blocked_rename.status_code == 409
    assert "已有历史任务" in blocked_rename.json()["detail"]
    notes_only = client.patch(
        f"{settings.API_V1_STR}/douyin/keywords/by-id/{keyword_ids['FastAPI']}",
        headers=superuser_token_headers,
        json={"notes": "保留历史归因"},
    )
    assert notes_only.status_code == 200
    assert notes_only.json()["keyword"] == "FastAPI"
    assert notes_only.json()["notes"] == "保留历史归因"

    tasks = client.get(
        f"{settings.API_V1_STR}/douyin/keywords/by-id/{keyword_ids['FastAPI']}/tasks",
        headers=superuser_token_headers,
    )
    assert tasks.status_code == 200
    assert [item["id"] for item in tasks.json()] == [str(task.id)]

    edited = client.patch(
        f"{settings.API_V1_STR}/douyin/keywords/by-id/{keyword_ids['Python']}",
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
    for item in db.exec(select(DouyinKeyword).where(DouyinKeyword.owner_id == owner.id)):
        if item.id in {uuid.UUID(value) for value in keyword_ids.values()}:
            db.delete(item)
    db.commit()


def test_keyword_batch_task_creation(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    created = client.post(
        f"{settings.API_V1_STR}/douyin/keywords/bulk",
        headers=superuser_token_headers,
        json={"keywords": ["批量甲", "批量乙"]},
    ).json()
    keyword_ids = [item["id"] for item in created["data"]]
    requests: list[CrawlTaskCreate] = []

    async def fake_create(*, owner_id: uuid.UUID, request: CrawlTaskCreate) -> CrawlTask:
        assert owner_id == owner.id
        requests.append(request)
        return CrawlTask(
            owner_id=owner_id,
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

    for item in db.exec(select(DouyinKeyword).where(DouyinKeyword.owner_id == owner.id)):
        if str(item.id) in keyword_ids:
            db.delete(item)
    db.commit()


def test_task_storage_auto_binds_keywords(db: Session) -> None:
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    from app.douyin.storage import DouyinStorage

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
