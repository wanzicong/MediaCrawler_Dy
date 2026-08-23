"""抖音赛道（track）功能的测试：覆盖赛道任务请求模型约束、赛道 CRUD 与关键词维护、按赛道发起采集的任务归属、详情/提示词字段与跨用户权限隔离、关键词解绑。"""

import uuid
from unittest.mock import AsyncMock

import pytest
from crawler.bootstrap.database import engine
from crawler.bootstrap.settings import settings
from crawler.business.douyin.interactions.service import interaction_manager
from crawler.business.douyin.media.migration import media_migration_manager
from crawler.business.douyin.media.pipeline import media_manager
from crawler.business.douyin.tasks import service as douyin_tasks
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskStatus,
)
from crawler.business.douyin.tracks import service as track_service
from crawler.business.douyin.tracks.models import DouyinTrack, DouyinTrackTaskRequest
from fastapi.testclient import TestClient
from sqlmodel import Session


def test_track_task_keyword_selection_schema() -> None:
    """验证赛道发起任务请求模型：keyword_ids 默认空数组、上限 1000 且文档说明省略即全选。"""
    schema = DouyinTrackTaskRequest.model_json_schema()
    keyword_ids_schema = schema["properties"]["keyword_ids"]

    assert DouyinTrackTaskRequest().keyword_ids == []
    assert keyword_ids_schema["maxItems"] == 1000
    assert "省略或传空数组" in keyword_ids_schema["description"]


def test_track_task_supports_explicit_task_interval() -> None:
    """验证赛道批量任务请求支持独立的任务完成后间隔。"""
    request = DouyinTrackTaskRequest(task_interval_seconds=12.0)

    assert request.task_interval_seconds == 12.0
    assert request.model_json_schema()["properties"]["task_interval_seconds"]


def test_track_task_creator_selection_schema() -> None:
    """验证赛道发起任务请求模型：creator_ids 默认空数组、上限 200。"""
    schema = DouyinTrackTaskRequest.model_json_schema()
    creator_ids_schema = schema["properties"]["creator_ids"]

    assert DouyinTrackTaskRequest().creator_ids == []
    assert creator_ids_schema["maxItems"] == 200


def test_reset_track_endpoint_keeps_track_and_clears_keywords(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    """重置接口返回清理统计、删除关键词并保留赛道本身。"""
    suffix = uuid.uuid4().hex[:8]
    created = client.post(
        f"{settings.API_V1_STR}/douyin/tracks",
        headers=superuser_token_headers,
        json={"name": f"重置接口-{suffix}", "keywords": [f"重置词-{suffix}"]},
    )
    assert created.status_code == 201
    track_id = created.json()["id"]

    reset = client.post(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}/reset",
        headers=superuser_token_headers,
    )

    assert reset.status_code == 200
    assert "赛道已重置，配置已保留" in reset.json()["message"]
    detail = client.get(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}",
        headers=superuser_token_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["keyword_count"] == 0
    assert detail.json()["enabled"] is True


def test_delete_track_stops_every_executor_before_purge(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """删除赛道必须取消并等待采集、媒体、迁移与互动四类执行器。"""
    created = client.post(
        f"{settings.API_V1_STR}/douyin/tracks",
        headers=superuser_token_headers,
        json={"name": f"执行器清理-{uuid.uuid4().hex[:8]}"},
    )
    assert created.status_code == 201
    track_id = uuid.UUID(created.json()["id"])
    track = db.get(DouyinTrack, track_id)
    assert track is not None
    task = CrawlTask(
        owner_id=track.owner_id,
        track_id=track.id,
        crawl_type="detail",
        status=CrawlTaskStatus.cancelled.value,
        request_json='{"crawl_type":"detail","video_ids":["1"]}',
    )
    db.add(task)
    db.commit()
    task_id = task.id

    crawl_cancel = AsyncMock(return_value=True)
    media_cancel = AsyncMock(return_value=None)
    migration_cancel = AsyncMock(return_value=None)
    interaction_cancel = AsyncMock(return_value=0)
    monkeypatch.setattr(douyin_tasks.task_manager, "cancel", crawl_cancel)
    monkeypatch.setattr(media_manager, "cancel_task", media_cancel)
    monkeypatch.setattr(media_migration_manager, "cancel_task", migration_cancel)
    monkeypatch.setattr(interaction_manager, "cancel_tasks", interaction_cancel)

    deleted = client.delete(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}",
        headers=superuser_token_headers,
    )

    assert deleted.status_code == 200
    crawl_cancel.assert_awaited_once_with(task_id)
    media_cancel.assert_awaited_once_with(task_id)
    migration_cancel.assert_awaited_once_with(task_id)
    interaction_cancel.assert_awaited_once_with({task_id})
    db.expire_all()
    assert db.get(DouyinTrack, track_id) is None
    assert db.get(CrawlTask, task_id) is None


def test_delete_track_stays_frozen_when_cancellation_fails(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """任一执行器停止失败时不清理数据，并保持赛道冻结以便安全重试。"""
    created = client.post(
        f"{settings.API_V1_STR}/douyin/tracks",
        headers=superuser_token_headers,
        json={"name": f"停止失败恢复-{uuid.uuid4().hex[:8]}"},
    )
    assert created.status_code == 201
    track_id = uuid.UUID(created.json()["id"])
    track = db.get(DouyinTrack, track_id)
    assert track is not None
    task = CrawlTask(
        owner_id=track.owner_id,
        track_id=track.id,
        crawl_type="detail",
        status=CrawlTaskStatus.cancelled.value,
        request_json='{"crawl_type":"detail","video_ids":["1"]}',
    )
    db.add(task)
    db.commit()
    monkeypatch.setattr(
        douyin_tasks.task_manager,
        "cancel",
        AsyncMock(side_effect=RuntimeError("cancel failed")),
    )

    deleted = client.delete(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}",
        headers=superuser_token_headers,
    )

    assert deleted.status_code == 409
    db.expire_all()
    retained_track = db.get(DouyinTrack, track_id)
    assert retained_track is not None
    assert retained_track.enabled is False
    assert db.get(CrawlTask, task.id) is not None


def test_delete_track_stays_frozen_when_purge_fails(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """任务停止后若数据库清理失败，赛道保持冻结而不尝试重放任务。"""
    created = client.post(
        f"{settings.API_V1_STR}/douyin/tracks",
        headers=superuser_token_headers,
        json={"name": f"清理失败恢复-{uuid.uuid4().hex[:8]}"},
    )
    assert created.status_code == 201
    track_id = uuid.UUID(created.json()["id"])

    def fail_purge(*_args: object, **_kwargs: object) -> None:
        """模拟事务清理阶段在提交前失败。"""
        raise track_service.TrackConflictError("purge failed")

    monkeypatch.setattr(track_service, "delete_track_record", fail_purge)
    deleted = client.delete(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}",
        headers=superuser_token_headers,
    )

    assert deleted.status_code == 409
    db.expire_all()
    retained_track = db.get(DouyinTrack, track_id)
    assert retained_track is not None
    assert retained_track.enabled is False


def test_bulk_delete_failure_keeps_completed_freeze_and_leaves_later_track_unchanged(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """批量处理中途失败时，已停止赛道保持冻结，尚未处理赛道维持原状。"""
    track_ids: list[uuid.UUID] = []
    for index in range(2):
        created = client.post(
            f"{settings.API_V1_STR}/douyin/tracks",
            headers=superuser_token_headers,
            json={"name": f"批量失败-{index}-{uuid.uuid4().hex[:8]}"},
        )
        assert created.status_code == 201
        track_ids.append(uuid.UUID(created.json()["id"]))
    first_id, second_id = sorted(track_ids)
    original_stop = track_service.stop_track_tasks

    async def fail_on_second(
        session: Session,
        *,
        track_id: uuid.UUID,
        actor_id: uuid.UUID,
        is_superuser: bool,
        allow_default: bool = True,
    ) -> track_service.TrackStopResult:
        if track_id == second_id:
            raise track_service.TrackConflictError("second stop failed")
        return await original_stop(
            session,
            track_id=track_id,
            actor_id=actor_id,
            is_superuser=is_superuser,
            allow_default=allow_default,
        )

    monkeypatch.setattr(track_service, "stop_track_tasks", fail_on_second)
    deleted = client.post(
        f"{settings.API_V1_STR}/douyin/tracks/bulk-delete",
        headers=superuser_token_headers,
        json={"ids": [str(second_id), str(first_id)]},
    )

    assert deleted.status_code == 409
    db.expire_all()
    first = db.get(DouyinTrack, first_id)
    second = db.get(DouyinTrack, second_id)
    assert first is not None and first.enabled is False
    assert second is not None and second.enabled is True


def test_default_track_delete_rejects_before_cancelling_tasks(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认赛道删除必须在产生任何停止副作用前拒绝。"""
    listing = client.get(
        f"{settings.API_V1_STR}/douyin/tracks",
        headers=superuser_token_headers,
    )
    default_track = next(item for item in listing.json()["data"] if item["is_default"])
    cancel = AsyncMock(return_value=False)
    monkeypatch.setattr(douyin_tasks.task_manager, "cancel", cancel)

    deleted = client.delete(
        f"{settings.API_V1_STR}/douyin/tracks/{default_track['id']}",
        headers=superuser_token_headers,
    )

    assert deleted.status_code == 409
    cancel.assert_not_awaited()


def test_track_crud_keywords_and_task_attribution(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证赛道创建（名称去空白）、关键词追加去重、按赛道发起任务（全选/子集/空选语义、超上限 422）及列表任务统计归属。"""
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
    assert track["default_task_config"]["max_awemes"] == 10
    assert track["default_task_config"]["mode"] == "separate"
    assert track["default_task_config"]["browser_mode"] == "remote"
    assert track["default_task_config"]["media_processing_mode"] == "none"
    assert track["default_task_config"]["media_storage"] == "minio"
    assert "cookies" not in track["default_task_config"]
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

    captured_requests: list[CrawlTaskCreate] = []

    async def fake_create(*, owner_id: uuid.UUID, request: object) -> CrawlTask:
        """模拟任务创建：捕获请求对象并入库一条排队中的任务记录。"""
        assert isinstance(request, CrawlTaskCreate)
        captured_requests.append(request)
        track_id = request.track_id
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
    assert task_response.json()["count"] == 3
    assert {request.keywords[0] for request in captured_requests[-3:]} == {
        camping_gear,
        tent_tip,
        stove,
    }
    assert all(len(request.keywords) == 1 for request in captured_requests[-3:])

    listing = client.get(
        f"{settings.API_V1_STR}/douyin/tracks",
        headers=superuser_token_headers,
    )
    row = next(item for item in listing.json()["data"] if item["id"] == track_id)
    assert row["task_count"] == 3
    assert row["active_task_count"] == 3
    assert row["last_task_id"] == task_response.json()["data"][-1]["id"]

    keyword_ids = {item["keyword"]: item["id"] for item in appended.json()["data"]}
    defaults_updated = client.patch(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}",
        headers=superuser_token_headers,
        json={
            "default_task_config": {
                "max_awemes": 77,
                "concurrency": 3,
                "fetch_comments": True,
                "request_delay_level": "ultra_steady",
                "download_media": True,
                "translate_subtitles": True,
                "transcription_language": "zh",
            }
        },
    )
    assert defaults_updated.status_code == 200
    assert defaults_updated.json()["default_task_config"]["max_awemes"] == 77
    subset_response = client.post(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}/tasks",
        headers=superuser_token_headers,
        json={
            "keyword_ids": [keyword_ids[tent_tip]],
            "mode": "combined",
            "fetch_comments": False,
        },
    )
    assert subset_response.status_code == 202
    assert subset_response.json()["count"] == 1
    assert captured_requests[-1].keywords == [tent_tip]
    assert captured_requests[-1].max_awemes == 77
    assert captured_requests[-1].concurrency == 3
    assert captured_requests[-1].fetch_comments is False
    assert captured_requests[-1].media_processing_mode.value == "immediate"
    assert captured_requests[-1].translate_subtitles is True

    empty_selection_response = client.post(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}/tasks",
        headers=superuser_token_headers,
        json={
            "keyword_ids": [],
            "mode": "combined",
            "fetch_comments": False,
        },
    )
    assert empty_selection_response.status_code == 202
    assert empty_selection_response.json()["count"] == 3
    assert {request.keywords[0] for request in captured_requests[-3:]} == {
        camping_gear,
        tent_tip,
        stove,
    }
    assert all(len(request.keywords) == 1 for request in captured_requests[-3:])

    too_many_keywords_response = client.post(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}/tasks",
        headers=superuser_token_headers,
        json={"keyword_ids": [str(uuid.uuid4()) for _ in range(1001)]},
    )
    assert too_many_keywords_response.status_code == 422
    assert too_many_keywords_response.json()["detail"][0]["loc"] == [
        "body",
        "keyword_ids",
    ]

    deleted = client.delete(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}",
        headers=superuser_token_headers,
    )
    assert deleted.status_code == 200
    task_ids = [
        item["id"]
        for response in (task_response, subset_response, empty_selection_response)
        for item in response.json()["data"]
    ]
    for task_id in task_ids:
        task = db.get(CrawlTask, uuid.UUID(task_id))
        if task is not None:
            db.delete(task)
    db.commit()


def test_track_task_runs_keywords_and_creators_together(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证运行赛道同时选达人和关键词：关键词任务与每达人独立任务一起创建。"""
    suffix = uuid.uuid4().hex[:8]
    track_name = f"混合运行-{suffix}"
    camping_gear = f"露营装备-{suffix}"
    creator_link = f"https://www.douyin.com/user/MX{suffix}"
    created = client.post(
        f"{settings.API_V1_STR}/douyin/tracks",
        headers=superuser_token_headers,
        json={
            "name": track_name,
            "keywords": [camping_gear],
        },
    )
    assert created.status_code == 201
    track_id = created.json()["id"]

    appended_creators = client.post(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}/creators",
        headers=superuser_token_headers,
        json={"creators": [creator_link]},
    )
    assert appended_creators.status_code == 200
    assert appended_creators.json()["count"] == 1
    creator_id = appended_creators.json()["data"][0]["id"]
    keyword_rows = client.get(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}/keywords",
        headers=superuser_token_headers,
    ).json()["data"]
    camping_keyword_id = next(
        item["id"] for item in keyword_rows if item["keyword"] == camping_gear
    )

    captured_requests: list[CrawlTaskCreate] = []

    async def fake_create(*, owner_id: uuid.UUID, request: object) -> CrawlTask:
        """模拟任务创建：捕获请求对象并入库一条排队中的任务记录。"""
        assert isinstance(request, CrawlTaskCreate)
        captured_requests.append(request)
        track_id = request.track_id
        assert isinstance(track_id, uuid.UUID)
        task = CrawlTask(
            owner_id=owner_id,
            track_id=track_id,
            crawl_type=request.crawl_type.value,
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
            "keyword_ids": [camping_keyword_id],
            "creator_ids": [creator_id],
            "mode": "combined",
            "max_awemes": 30,
            "fetch_comments": True,
            "login_type": "cookie",
            "browser_mode": "local",
            "cookies": "sessionid=track-runtime-only",
            "request_interval_seconds": 2.5,
            "download_media": True,
            "media_processing_mode": "batch",
        },
    )
    assert task_response.status_code == 202
    assert task_response.json()["count"] == 2
    types = {request.crawl_type.value for request in captured_requests}
    assert types == {"search", "creator"}
    search_request = next(
        request for request in captured_requests if request.crawl_type.value == "search"
    )
    assert set(search_request.keywords) == {camping_gear}
    assert search_request.login_type.value == "cookie"
    assert search_request.browser_mode.value == "local"
    assert search_request.cookies is not None
    assert search_request.cookies.get_secret_value() == "sessionid=track-runtime-only"
    assert search_request.request_interval_seconds == 2.5
    assert search_request.media_processing_mode.value == "batch"
    creator_request = next(
        request
        for request in captured_requests
        if request.crawl_type.value == "creator"
    )
    assert creator_request.creator_ids == [f"MX{suffix}"]
    assert creator_request.login_type.value == "cookie"
    assert creator_request.browser_mode.value == "local"
    assert creator_request.cookies is not None
    assert creator_request.cookies.get_secret_value() == "sessionid=track-runtime-only"
    assert creator_request.request_interval_seconds == 2.5
    assert creator_request.media_processing_mode.value == "batch"

    # 跨赛道达人被拒绝：另一个赛道的达人不能随本赛道运行
    other_track = client.post(
        f"{settings.API_V1_STR}/douyin/tracks",
        headers=superuser_token_headers,
        json={"name": f"混合运行-其他-{suffix}", "keywords": [f"别的词-{suffix}"]},
    ).json()
    other_creator = client.post(
        f"{settings.API_V1_STR}/douyin/tracks/{other_track['id']}/creators",
        headers=superuser_token_headers,
        json={"creators": [f"https://www.douyin.com/user/MY{suffix}"]},
    ).json()["data"][0]
    rejected = client.post(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}/tasks",
        headers=superuser_token_headers,
        json={"creator_ids": [other_creator["id"]], "fetch_comments": False},
    )
    assert rejected.status_code == 422
    assert "达人" in rejected.json()["detail"]

    for task_id in [item["id"] for item in task_response.json()["data"]]:
        task = db.get(CrawlTask, uuid.UUID(task_id))
        if task is not None:
            db.delete(task)
    # 先提交释放行锁，否则赛道删除服务把任务迁移回默认赛道的 UPDATE 会互锁
    db.commit()
    deleted = client.delete(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}",
        headers=superuser_token_headers,
    )
    assert deleted.status_code == 200
    client.delete(
        f"{settings.API_V1_STR}/douyin/tracks/{other_track['id']}",
        headers=superuser_token_headers,
    )
    db.commit()


def test_track_task_runs_creators_only_without_keywords(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证只选达人不选关键词也能创建任务：空关键词数组不再回退全选，只创建达人任务。"""
    suffix = uuid.uuid4().hex[:8]
    track_name = f"仅达人-{suffix}"
    creator_link = f"https://www.douyin.com/user/MN{suffix}"
    created = client.post(
        f"{settings.API_V1_STR}/douyin/tracks",
        headers=superuser_token_headers,
        json={
            "name": track_name,
            "keywords": [f"不会用的词-{suffix}"],
        },
    )
    assert created.status_code == 201
    track_id = created.json()["id"]

    appended_creators = client.post(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}/creators",
        headers=superuser_token_headers,
        json={"creators": [creator_link]},
    )
    assert appended_creators.status_code == 200
    creator_id = appended_creators.json()["data"][0]["id"]

    captured_requests: list[CrawlTaskCreate] = []

    async def fake_create(*, owner_id: uuid.UUID, request: object) -> CrawlTask:
        """模拟任务创建：捕获请求对象并入库一条排队中的任务记录。"""
        assert isinstance(request, CrawlTaskCreate)
        captured_requests.append(request)
        track_id = request.track_id
        assert isinstance(track_id, uuid.UUID)
        task = CrawlTask(
            owner_id=owner_id,
            track_id=track_id,
            crawl_type=request.crawl_type.value,
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
            "keyword_ids": [],
            "creator_ids": [creator_id],
            "mode": "combined",
            "max_awemes": 30,
            "fetch_comments": False,
        },
    )
    assert task_response.status_code == 202
    assert task_response.json()["count"] == 1
    assert {request.crawl_type.value for request in captured_requests} == {"creator"}
    creator_request = captured_requests[0]
    assert creator_request.creator_ids == [f"MN{suffix}"]

    # 关键词与达人皆为空：向后兼容回退为运行全部已启用关键词
    empty_response = client.post(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}/tasks",
        headers=superuser_token_headers,
        json={"keyword_ids": [], "creator_ids": [], "mode": "combined"},
    )
    assert empty_response.status_code == 202
    assert empty_response.json()["count"] == 1
    fallback_request = captured_requests[-1]
    assert fallback_request.crawl_type.value == "search"
    assert fallback_request.keywords == [f"不会用的词-{suffix}"]

    for response in (task_response, empty_response):
        for task_id in [item["id"] for item in response.json()["data"]]:
            task = db.get(CrawlTask, uuid.UUID(task_id))
            if task is not None:
                db.delete(task)
    # 先提交释放行锁，否则赛道删除服务把任务迁移回默认赛道的 UPDATE 会互锁
    db.commit()
    deleted = client.delete(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}",
        headers=superuser_token_headers,
    )
    assert deleted.status_code == 200
    db.commit()


def test_track_detail_prompt_and_keyword_unlink(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    """验证赛道详情提示词的读写/去空白/长度校验/清空、列表不返回提示词、跨用户 404/403 隔离及关键词解绑后全局词库仍保留。"""
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
            "reply_templates": ["  欢迎交流具体需求  ", "欢迎交流具体需求"],
            "keyword_categories": ["品类词", "意向词"],
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
    assert detail.json()["reply_templates"] == ["欢迎交流具体需求"]
    assert detail.json()["keyword_categories"] == ["品类词", "意向词"]
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
        json={
            "prompt": " 提炼需求、异议和行动信号。 ",
            "reply_templates": ["可以私信我了解详情", "欢迎交流具体需求"],
            "keyword_categories": ["品类词", "场景词"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["prompt"] == "提炼需求、异议和行动信号。"
    assert updated.json()["reply_templates"] == [
        "可以私信我了解详情",
        "欢迎交流具体需求",
    ]
    assert updated.json()["keyword_categories"] == ["品类词", "场景词"]

    categorized_keyword = f"露营桌椅-{suffix}"
    categorized = client.post(
        f"{settings.API_V1_STR}/douyin/keywords/bulk",
        headers=superuser_token_headers,
        json={
            "keywords": [categorized_keyword],
            "track_id": track_id,
            "category": "品类词",
        },
    )
    assert categorized.status_code == 201
    assert categorized.json()["data"][0]["category"] == "品类词"
    invalid_category = client.post(
        f"{settings.API_V1_STR}/douyin/keywords/bulk",
        headers=superuser_token_headers,
        json={
            "keywords": [f"非法分类-{suffix}"],
            "track_id": track_id,
            "category": "未定义分类",
        },
    )
    assert invalid_category.status_code == 422

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
        local_keyword,
        categorized_keyword,
    }
    after_unlink = client.get(
        f"{settings.API_V1_STR}/douyin/tracks/{track_id}",
        headers=superuser_token_headers,
    )
    assert after_unlink.json()["keyword_count"] == 2
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
