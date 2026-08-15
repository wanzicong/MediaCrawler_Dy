import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.models import CrawlTask, CrawlTaskStatus
from app.services import douyin_tasks


def test_track_crud_keywords_and_task_attribution(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    track_name = f"户外露营-{suffix}"
    camping_gear = f"露营装备-{suffix}"
    tent_tip = f"帐篷推荐-{suffix}"
    stove = f"户外炉具-{suffix}"
    created = client.post(
        f"{settings.API_V1_STR}/douyin/tracks",
        headers=superuser_token_headers,
        json={
            "name": f" {track_name} ",
            "description": "寻找户外装备兴趣用户",
            "keywords": [camping_gear, tent_tip],
        },
    )
    assert created.status_code == 201
    track = created.json()
    assert track["name"] == track_name
    assert track["keyword_count"] == 2
    track_id = track["id"]

    appended = client.post(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}/keywords",
        headers=superuser_token_headers,
        json={"keywords": [camping_gear, stove]},
    )
    assert appended.status_code == 200
    assert appended.json()["count"] == 3
    assert {item["keyword"] for item in appended.json()["data"]} == {
        camping_gear,
        tent_tip,
        stove,
    }

    async def fake_create(*, owner_id: uuid.UUID, request: object) -> CrawlTask:
        assert request is not None
        track_id = getattr(request, "track_id", None)
        assert isinstance(track_id, uuid.UUID)
        task = CrawlTask(
            owner_id=owner_id,
            track_id=track_id,
            crawl_type="search",
            status=CrawlTaskStatus.queued.value,
            request_json="{}",
        )
        with Session(engine) as session:
            session.add(task)
            session.commit()
            session.refresh(task)
            session.expunge(task)
        return task

    monkeypatch.setattr(
        douyin_tasks.task_manager,
        "create",
        AsyncMock(side_effect=fake_create),
    )
    task_response = client.post(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}/tasks",
        headers=superuser_token_headers,
        json={
            "mode": "combined",
            "max_awemes": 30,
            "fetch_comments": True,
            "max_comments_per_aweme": 10,
            "request_delay_level": "steady",
        },
    )
    assert task_response.status_code == 202
    assert task_response.json()["count"] == 1

    listing = client.get(
        f"{settings.API_V1_STR}/douyin/tracks",
        headers=superuser_token_headers,
    )
    row = next(item for item in listing.json()["data"] if item["id"] == track_id)
    assert row["task_count"] == 1
    assert row["active_task_count"] == 1
    assert row["last_task_id"] == task_response.json()["data"][0]["id"]

    deleted = client.delete(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}",
        headers=superuser_token_headers,
    )
    assert deleted.status_code == 200
    task = db.get(CrawlTask, uuid.UUID(task_response.json()["data"][0]["id"]))
    if task is not None:
        db.delete(task)
        db.commit()


def test_track_detail_prompt_and_keyword_unlink(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    suffix = uuid.uuid4().hex[:8]
    track_name = f"本地生活获客-{suffix}"
    city_keyword = f"同城探店-{suffix}"
    local_keyword = f"本地生活-{suffix}"
    created = client.post(
        f"{settings.API_V1_STR}/douyin/tracks",
        headers=superuser_token_headers,
        json={
            "name": track_name,
            "description": "验证赛道详情工作台",
            "prompt": " 分析评论中的高频需求与购买阻力。 ",
            "keywords": [city_keyword, local_keyword],
        },
    )
    assert created.status_code == 201
    track_id = created.json()["id"]

    detail = client.get(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}",
        headers=superuser_token_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["name"] == track_name
    assert detail.json()["prompt"] == "分析评论中的高频需求与购买阻力。"
    listing = client.get(
        f"{settings.API_V1_STR}/douyin/tracks",
        headers=superuser_token_headers,
        params={"search": track_name},
    )
    assert listing.status_code == 200
    assert listing.json()["count"] == 1
    assert "prompt" not in listing.json()["data"][0]
    forbidden_detail = client.get(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}",
        headers=normal_user_token_headers,
    )
    assert forbidden_detail.status_code == 404

    normal_track = client.post(
        f"{settings.API_V1_STR}/douyin/tracks",
        headers=normal_user_token_headers,
        json={
            "name": f"普通用户赛道-{suffix}",
            "keywords": [f"权限隔离-{suffix}"],
        },
    )
    assert normal_track.status_code == 201
    normal_track_id = normal_track.json()["id"]
    cross_owner_run = client.post(
        f"{settings.API_V1_STR}/douyin/tracks/{normal_track_id}/tasks",
        headers=superuser_token_headers,
        json={"keyword_ids": [], "fetch_comments": False},
    )
    assert cross_owner_run.status_code == 403
    assert "其他用户" in cross_owner_run.json()["detail"]
    normal_deleted = client.delete(
        f"{settings.API_V1_STR}/douyin/tracks/{normal_track_id}",
        headers=normal_user_token_headers,
    )
    assert normal_deleted.status_code == 200
    too_long = client.patch(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}",
        headers=superuser_token_headers,
        json={"prompt": "字" * 10001},
    )
    assert too_long.status_code == 422

    updated = client.patch(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}",
        headers=superuser_token_headers,
        json={"prompt": " 提炼需求、异议和行动信号。 "},
    )
    assert updated.status_code == 200
    assert updated.json()["prompt"] == "提炼需求、异议和行动信号。"

    keywords = client.get(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}/keywords",
        headers=superuser_token_headers,
    )
    keyword = next(
        item for item in keywords.json()["data"] if item["keyword"] == city_keyword
    )
    unlinked = client.delete(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}/keywords/{keyword['id']}",
        headers=superuser_token_headers,
    )
    assert unlinked.status_code == 200
    remaining = client.get(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}/keywords",
        headers=superuser_token_headers,
    )
    assert {item["keyword"] for item in remaining.json()["data"]} == {
        local_keyword
    }
    after_unlink = client.get(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}",
        headers=superuser_token_headers,
    )
    assert after_unlink.json()["keyword_count"] == 1
    global_keyword = client.get(
        f"{settings.API_V1_STR}/douyin/keywords/",
        headers=superuser_token_headers,
        params={"search": city_keyword},
    )
    assert global_keyword.status_code == 200
    assert any(
        item["keyword"] == city_keyword for item in global_keyword.json()["data"]
    )

    cleared = client.patch(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}",
        headers=superuser_token_headers,
        json={"prompt": ""},
    )
    assert cleared.status_code == 200
    assert cleared.json()["prompt"] == ""

    deleted = client.delete(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}",
        headers=superuser_token_headers,
    )
    assert deleted.status_code == 200
