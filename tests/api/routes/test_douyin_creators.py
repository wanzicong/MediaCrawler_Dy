"""抖音达人路由的集成测试：批量创建去重、列表过滤、任务同步绑定、编辑启停、
批量建任务（独立模式一人一任务）、赛道达人追加/移除回默认，以及作品库
达人深链（uid 哈希与 sec_uid 哈希均可命中）。"""

import json
import uuid

from crawler.bootstrap.settings import settings
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.creators.models import DouyinCreator
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskStatus,
)
from crawler.business.douyin.tasks.service import task_manager
from crawler.business.douyin.tracks.models import DouyinTrack
from crawler.business.identity.models import User
from crawler.douyin_client.privacy import anonymize_user_id
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlmodel import Session, col, delete, select

from tests.utils.douyin import default_track_id


def test_creator_api_crud_sync_and_status(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证达人批量创建（主页链接归一）、列表过滤与状态统计、任务同步绑定、编辑启停。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    suffix = uuid.uuid4().hex[:8]
    sec_uid = f"MS{suffix}"
    link = f"https://www.douyin.com/user/{sec_uid}"

    created = client.post(
        f"{settings.API_V1_STR}/douyin/creators/bulk",
        headers=superuser_token_headers,
        json={
            "creators": [link, sec_uid, f"MS{uuid.uuid4().hex}"],
            "notes": "达人名单测试",
        },
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["created_count"] == 2
    assert payload["existing_count"] == 0
    by_sec_uid = {item["sec_uid"]: item for item in payload["data"]}
    assert by_sec_uid[sec_uid]["creator_hash"] == anonymize_user_id(sec_uid)
    assert by_sec_uid[sec_uid]["track_is_default"] is True

    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="creator",
        status=CrawlTaskStatus.succeeded.value,
        request_json=json.dumps({"crawl_type": "creator", "creator_ids": [sec_uid]}),
        checkpoint_json='{"version":1,"phase":"completed","position":{}}',
        aweme_count=1,
    )
    db.add(task)
    db.flush()
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id="creator-api-work",
            title="达人API作品",
            sec_uid=anonymize_user_id(sec_uid),
        )
    )
    db.commit()

    synced = client.post(
        f"{settings.API_V1_STR}/douyin/creators/sync/tasks/{task.id}",
        headers=superuser_token_headers,
    )
    assert synced.status_code == 200
    assert synced.json() == {
        "task_count": 1,
        "creator_count": 1,
        "created_count": 0,
        "binding_count": 1,
    }

    listing = client.get(
        f"{settings.API_V1_STR}/douyin/creators/",
        headers=superuser_token_headers,
        params={"search": suffix, "status": "crawled"},
    )
    assert listing.status_code == 200
    assert listing.json()["count"] == 1
    row = listing.json()["data"][0]
    assert row["sec_uid"] == sec_uid
    assert row["task_count"] == 1
    assert row["success_task_count"] == 1
    assert row["aweme_count"] == 1
    assert row["last_task_id"] == str(task.id)

    tasks = client.get(
        f"{settings.API_V1_STR}/douyin/creators/by-id/{by_sec_uid[sec_uid]['id']}/tasks",
        headers=superuser_token_headers,
    )
    assert tasks.status_code == 200
    assert [item["id"] for item in tasks.json()] == [str(task.id)]
    assert tasks.json()[0]["creator_names"] == ["未命名达人"]

    edited = client.patch(
        f"{settings.API_V1_STR}/douyin/creators/by-id/{by_sec_uid[sec_uid]['id']}",
        headers=superuser_token_headers,
        json={"nickname": "测试达人", "enabled": False, "notes": "暂停投放"},
    )
    assert edited.status_code == 200
    assert edited.json()["nickname"] == "测试达人"
    assert edited.json()["enabled"] is False
    assert edited.json()["notes"] == "暂停投放"

    disabled_list = client.get(
        f"{settings.API_V1_STR}/douyin/creators/",
        headers=superuser_token_headers,
        params={"enabled": False},
    )
    assert disabled_list.status_code == 200
    assert any(
        item["id"] == by_sec_uid[sec_uid]["id"] for item in disabled_list.json()["data"]
    )

    history = client.post(
        f"{settings.API_V1_STR}/douyin/creators/sync/history",
        headers=superuser_token_headers,
    )
    assert history.status_code == 200
    assert history.json()["task_count"] >= 1

    deleted = client.delete(
        f"{settings.API_V1_STR}/douyin/creators/by-id/{by_sec_uid[sec_uid]['id']}",
        headers=superuser_token_headers,
    )
    assert deleted.status_code == 200
    assert "保留" in deleted.json()["message"]

    db.exec(delete(DouyinCreator).where(DouyinCreator.owner_id == owner.id))
    db.exec(delete(CrawlTask).where(CrawlTask.id == task.id))
    db.commit()


def test_creator_api_batch_task_creation(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    """验证按达人批量发起采集任务：每人一个独立任务、sec_uid 完整透传且归属赛道已解析。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    created = client.post(
        f"{settings.API_V1_STR}/douyin/creators/bulk",
        headers=superuser_token_headers,
        json={"creators": ["MB批量甲", "MB批量乙"]},
    ).json()
    creator_ids = [item["id"] for item in created["data"]]
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
            crawl_type="creator",
            status="queued",
            request_json=json.dumps(request.public_request(), ensure_ascii=False),
            checkpoint_json='{"version":1,"phase":"crawl","position":{}}',
        )

    monkeypatch.setattr(task_manager, "create", fake_create)
    response = client.post(
        f"{settings.API_V1_STR}/douyin/creators/batch-tasks",
        headers=superuser_token_headers,
        json={
            "creator_ids": creator_ids,
            "max_awemes": 30,
            "fetch_comments": False,
        },
    )
    assert response.status_code == 202
    assert response.json()["count"] == 2
    assert {item.creator_ids[0] for item in requests} == {"MB批量甲", "MB批量乙"}
    assert all(item.max_awemes == 30 for item in requests)
    assert all(item.fetch_comments is False for item in requests)

    db.exec(delete(DouyinCreator).where(DouyinCreator.owner_id == owner.id))
    db.commit()


def test_track_creators_api_append_and_remove(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证赛道达人：追加挂载、列表查询、移除回默认赛道（达人本身保留）。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    track = client.post(
        f"{settings.API_V1_STR}/douyin/tracks",
        headers=superuser_token_headers,
        json={"name": f"达人赛道{uuid.uuid4().hex[:8]}"},
    )
    assert track.status_code == 201
    track_id = track.json()["id"]
    sec_uid = f"MT{uuid.uuid4().hex}"

    appended = client.post(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}/creators",
        headers=superuser_token_headers,
        json={"creators": [sec_uid]},
    )
    assert appended.status_code == 200
    assert appended.json()["count"] == 1
    assert appended.json()["data"][0]["track_id"] == track_id
    creator_id = appended.json()["data"][0]["id"]

    listing = client.get(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}/creators",
        headers=superuser_token_headers,
    )
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()["data"]] == [creator_id]
    assert listing.json()["data"][0]["track_name"].startswith("达人赛道")

    removed = client.delete(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}/creators/{creator_id}",
        headers=superuser_token_headers,
    )
    assert removed.status_code == 200

    after = client.get(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}/creators",
        headers=superuser_token_headers,
    )
    assert after.json()["count"] == 0
    # 达人本身保留，回到默认赛道
    creator = db.get(DouyinCreator, uuid.UUID(creator_id))
    assert creator is not None
    assert creator.track_id == default_track_id(db, owner_id=owner.id)

    db.delete(creator)
    db.exec(delete(DouyinTrack).where(DouyinTrack.id == uuid.UUID(track_id)))
    db.commit()


def test_library_works_creator_deep_link(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证作品库达人深链：uid 哈希（旧聚合视图）与 sec_uid 哈希（达人名单）均可过滤命中。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    track_id = default_track_id(db, owner_id=owner.id)
    sec_uid = f"ML{uuid.uuid4().hex}"
    uid_hash = f"uidhash{uuid.uuid4().hex}"
    sec_hash = anonymize_user_id(sec_uid)
    task = CrawlTask(
        owner_id=owner.id,
        track_id=track_id,
        crawl_type="creator",
        status=CrawlTaskStatus.succeeded.value,
        request_json=json.dumps({"crawl_type": "creator", "creator_ids": [sec_uid]}),
        checkpoint_json='{"version":1,"phase":"completed","position":{}}',
    )
    db.add(task)
    db.flush()
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id="deep-link-work",
            title="深链作品",
            creator_hash=uid_hash,
            sec_uid=sec_hash,
        )
    )
    db.commit()

    by_uid = client.get(
        f"{settings.API_V1_STR}/douyin/library/works",
        headers=superuser_token_headers,
        params={"creator_hash": uid_hash, "download_status": "all"},
    )
    assert by_uid.status_code == 200
    assert by_uid.json()["count"] == 1

    by_sec = client.get(
        f"{settings.API_V1_STR}/douyin/library/works",
        headers=superuser_token_headers,
        params={"creator_hash": sec_hash, "download_status": "all"},
    )
    assert by_sec.status_code == 200
    assert by_sec.json()["count"] == 1
    assert by_sec.json()["data"][0]["aweme"]["aweme_id"] == "deep-link-work"

    db.exec(delete(DouyinAweme).where(DouyinAweme.task_id == task.id))
    db.exec(delete(CrawlTask).where(CrawlTask.id == task.id))
    db.commit()


def test_creator_api_placeholder_sync_complete_and_block(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证占位达人全链路：作品导入→列表透出→补全（哈希校验/冲突）→批量任务拦截。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    # 防御性清理：清除此前失败运行残留的占位数据（不依赖业务代码）
    db.exec(delete(DouyinCreator).where(DouyinCreator.is_placeholder.is_(True)))
    stale_tasks = db.exec(
        select(CrawlTask.id)
        .join(DouyinAweme, col(DouyinAweme.task_id) == col(CrawlTask.id))
        .where(col(DouyinAweme.aweme_id).like("ph-api-%"))
    ).all()
    db.exec(delete(DouyinAweme).where(col(DouyinAweme.aweme_id).like("ph-api-%")))
    db.exec(delete(CrawlTask).where(col(CrawlTask.id).in_(stale_tasks)))
    db.commit()
    # 建立基线：把历史作品哈希全部导入为占位达人，使后续计数只反映本次新增
    baseline = client.post(
        f"{settings.API_V1_STR}/douyin/creators/sync/awemes",
        headers=superuser_token_headers,
    )
    assert baseline.status_code == 200
    track_id = default_track_id(db, owner_id=owner.id)
    raw_a = f"MP{uuid.uuid4().hex}"
    raw_b = f"MQ{uuid.uuid4().hex}"
    hash_a = anonymize_user_id(raw_a)
    hash_b = anonymize_user_id(raw_b)
    task = CrawlTask(
        owner_id=owner.id,
        track_id=track_id,
        crawl_type="creator",
        status=CrawlTaskStatus.succeeded.value,
        request_json="{}",
        checkpoint_json='{"version":1,"phase":"completed","position":{}}',
    )
    db.add(task)
    db.flush()
    db.add_all(
        [
            DouyinAweme(
                task_id=task.id,
                aweme_id="ph-api-a",
                title="",
                sec_uid=hash_a,
                nickname="尘***客",
            ),
            DouyinAweme(
                task_id=task.id,
                aweme_id="ph-api-b",
                title="",
                sec_uid=hash_b,
                nickname="鲁***魔",
            ),
        ]
    )
    db.commit()

    imported = client.post(
        f"{settings.API_V1_STR}/douyin/creators/sync/awemes",
        headers=superuser_token_headers,
    )
    assert imported.status_code == 200
    payload = imported.json()
    assert payload["created_count"] == 2  # 库中可能还有其他历史作品，只看本次新建
    assert payload["existing_count"] == payload["total_count"] - 2

    def _find_placeholder(creator_hash: str) -> dict:
        """按哈希精确检索占位达人（search 匹配 sec_uid，占位时 sec_uid 即哈希）。"""
        resp = client.get(
            f"{settings.API_V1_STR}/douyin/creators/",
            headers=superuser_token_headers,
            params={"search": creator_hash, "limit": 500},
        )
        assert resp.status_code == 200
        items = [
            item for item in resp.json()["data"] if item["creator_hash"] == creator_hash
        ]
        assert len(items) == 1
        return items[0]

    ph_a = _find_placeholder(hash_a)
    ph_b = _find_placeholder(hash_b)
    assert ph_a["is_placeholder"] is True
    assert ph_a["sec_uid"] == hash_a
    assert ph_a["nickname"] == "尘***客"

    # 再次导入应全部跳过（无新建）
    again = client.post(
        f"{settings.API_V1_STR}/douyin/creators/sync/awemes",
        headers=superuser_token_headers,
    )
    assert again.status_code == 200
    assert again.json()["created_count"] == 0

    # 哈希不匹配的补全 → 422
    wrong = client.patch(
        f"{settings.API_V1_STR}/douyin/creators/by-id/{ph_a['id']}",
        headers=superuser_token_headers,
        json={"sec_uid": f"MR{uuid.uuid4().hex}"},
    )
    assert wrong.status_code == 422
    assert "不匹配" in wrong.json()["detail"]

    # 正确的补全 → 转正
    real_uid = raw_a
    completed = client.patch(
        f"{settings.API_V1_STR}/douyin/creators/by-id/{ph_a['id']}",
        headers=superuser_token_headers,
        json={"sec_uid": real_uid},
    )
    assert completed.status_code == 200
    assert completed.json()["is_placeholder"] is False
    assert completed.json()["sec_uid"] == real_uid

    # 批量任务拦截未补全的占位达人 → 409
    blocked = client.post(
        f"{settings.API_V1_STR}/douyin/creators/batch-tasks",
        headers=superuser_token_headers,
        json={
            "creator_ids": [ph_b["id"]],
            "max_awemes": 10,
            "fetch_comments": False,
        },
    )
    assert blocked.status_code == 409
    assert "待补全" in blocked.json()["detail"]

    db.exec(delete(DouyinCreator).where(DouyinCreator.owner_id == owner.id))
    db.exec(delete(DouyinAweme).where(DouyinAweme.task_id == task.id))
    db.exec(delete(CrawlTask).where(CrawlTask.id == task.id))
    db.commit()
