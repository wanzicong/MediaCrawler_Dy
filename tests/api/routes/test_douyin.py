"""抖音业务路由的集成测试。

覆盖任务创建/恢复/媒体后处理、cookie 等敏感字段脱敏、媒体迁移到 MinIO，
以及媒体文件下载与预览的流式传输（含 Range 分段）等外部可观察行为。
"""

import json
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

from crawler.bootstrap.security import create_access_token
from crawler.bootstrap.settings import settings
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.media.migration import (
    MigrationEnqueueResult,
    media_migration_manager,
)
from crawler.business.douyin.media.models import (
    DouyinMediaAsset,
    DouyinMediaProcessRequest,
    DouyinSubtitle,
    MediaDownloadStatus,
    MediaStorageBackend,
    SubtitleStatus,
)
from crawler.business.douyin.media.storage import (
    MediaStorageUnavailableError,
    media_storage,
)
from crawler.business.douyin.tasks.models import CrawlTask, CrawlTaskStatus
from crawler.business.douyin.tasks.service import task_manager
from crawler.business.identity.models import User
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlmodel import Session, select

from tests.utils.douyin import default_track_id


def _source_task_with_aweme(db: Session) -> tuple[User, CrawlTask, DouyinAweme]:
    """构造一个含一条作品的已完成来源任务，返回 (属主, 任务, 作品)。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="search",
        status=CrawlTaskStatus.succeeded.value,
        request_json=json.dumps({"crawl_type": "search", "keywords": ["来源"]}),
        checkpoint_json=json.dumps(
            {"version": 1, "phase": "completed", "crawl_type": "search"}
        ),
        aweme_count=1,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    aweme = DouyinAweme(
        task_id=task.id,
        aweme_id="7390000000000000001",
        title="来源作品",
    )
    db.add(aweme)
    db.commit()
    db.refresh(aweme)
    return owner, task, aweme


def test_create_douyin_task_is_accepted_and_never_echoes_cookie(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    """验证创建采集任务返回 202，且 cookie 秘密不回显在响应及公开请求视图中。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="search",
        status=CrawlTaskStatus.queued.value,
        request_json=json.dumps(
            {
                "crawl_type": "search",
                "login_type": "cookie",
                "keywords": ["FastAPI"],
                "max_awemes": 1,
            }
        ),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    create = AsyncMock(return_value=task)
    monkeypatch.setattr(task_manager, "create", create)

    response = client.post(
        "/api/v1/douyin/tasks",
        headers=superuser_token_headers,
        json={
            "crawl_type": "search",
            "keywords": ["FastAPI"],
            "cookies": "sessionid=top-secret",
            "browser_mode": "remote",
            "media_storage": "minio",
            "max_awemes": 1,
            "fetch_comments": False,
            "request_delay_level": "ultra_steady",
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert "cookies" not in payload["request"]
    assert "top-secret" not in response.text
    submitted = create.await_args.kwargs["request"]
    assert "cookies" not in submitted.public_request()
    assert submitted.browser_mode == "remote"
    assert submitted.media_storage == "minio"
    assert submitted.request_delay_level == "ultra_steady"
    assert submitted.request_interval_range_seconds() == (6.0, 12.0)


def test_douyin_tasks_require_authentication(client: TestClient) -> None:
    """验证未认证访问任务列表返回 401。"""
    response = client.get("/api/v1/douyin/tasks")

    assert response.status_code == 401


def test_recrawl_single_aweme_comments_creates_isolated_detail_task(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    """验证重采单条作品评论会创建隔离的 detail 子任务，且 cookie 不回显。"""
    owner, source_task, aweme = _source_task_with_aweme(db)
    child = CrawlTask(
        owner_id=owner.id,
        track_id=source_task.track_id,
        crawl_type="detail",
        status=CrawlTaskStatus.queued.value,
        request_json=json.dumps(
            {"crawl_type": "detail", "video_ids": [aweme.aweme_id]}
        ),
    )
    create = AsyncMock(return_value=child)
    monkeypatch.setattr(task_manager, "create", create)

    response = client.post(
        f"/api/v1/douyin/tasks/{source_task.id}/awemes/{aweme.aweme_id}/comments/recrawl",
        headers=superuser_token_headers,
        json={
            "browser_mode": "remote",
            "cookies": "sessionid=comment-secret",
            "fetch_sub_comments": True,
            "max_comments_per_aweme": 35,
            "concurrency": 3,
        },
    )

    assert response.status_code == 202
    assert response.json()["crawl_type"] == "detail"
    assert "comment-secret" not in response.text
    submitted = create.await_args.kwargs["request"]
    assert submitted.video_ids == [aweme.aweme_id]
    assert submitted.max_awemes == 1
    assert submitted.fetch_comments is True
    assert submitted.fetch_sub_comments is True
    assert submitted.max_comments_per_aweme == 35
    assert submitted.browser_mode == "remote"
    assert submitted.cookies.get_secret_value() == "sessionid=comment-secret"
    assert "cookies" not in submitted.public_request()


def test_crawl_aweme_creator_creates_privacy_safe_discovery_task(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    """验证按作品采集作者会创建 creator_from_aweme 发现任务，且参数正确透传。"""
    owner, source_task, aweme = _source_task_with_aweme(db)
    child = CrawlTask(
        owner_id=owner.id,
        track_id=source_task.track_id,
        crawl_type="creator_from_aweme",
        status=CrawlTaskStatus.queued.value,
        request_json=json.dumps(
            {
                "crawl_type": "creator_from_aweme",
                "video_ids": [aweme.aweme_id],
            }
        ),
    )
    create = AsyncMock(return_value=child)
    monkeypatch.setattr(task_manager, "create", create)

    response = client.post(
        f"/api/v1/douyin/tasks/{source_task.id}/awemes/{aweme.aweme_id}/creator/crawl",
        headers=superuser_token_headers,
        json={
            "max_awemes": 25,
            "fetch_comments": True,
            "max_comments_per_aweme": 8,
            "request_interval_seconds": 1.5,
        },
    )

    assert response.status_code == 202
    assert response.json()["crawl_type"] == "creator_from_aweme"
    submitted = create.await_args.kwargs["request"]
    assert submitted.crawl_type == "creator_from_aweme"
    assert submitted.video_ids == [aweme.aweme_id]
    assert submitted.creator_ids == []
    assert submitted.max_awemes == 25
    assert submitted.fetch_comments is True
    assert submitted.max_comments_per_aweme == 8


def test_resume_douyin_task_accepts_scopes_without_echoing_cookie(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    """验证恢复中断任务支持指定恢复范围（采集/媒体），且一次性 cookie 不回显。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="search",
        status=CrawlTaskStatus.interrupted.value,
        request_json=json.dumps(
            {
                "crawl_type": "search",
                "login_type": "cookie",
                "keywords": ["恢复测试"],
                "download_media": True,
                "media_processing_mode": "immediate",
            }
        ),
        checkpoint_json=json.dumps(
            {"version": 1, "phase": "crawl", "crawl_type": "search", "position": {}}
        ),
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    async def fake_resume(**_kwargs: object) -> CrawlTask:
        """模拟 task_manager.resume：将任务标记为重新排队并累加恢复次数。"""
        persisted = db.get(CrawlTask, task.id)
        assert persisted is not None
        persisted.status = CrawlTaskStatus.queued.value
        persisted.resume_count = 1
        db.add(persisted)
        db.commit()
        db.refresh(persisted)
        return persisted

    resume = AsyncMock(side_effect=fake_resume)
    monkeypatch.setattr(task_manager, "resume", resume)

    response = client.post(
        f"/api/v1/douyin/tasks/{task.id}/resume",
        headers=superuser_token_headers,
        json={
            "resume_crawl": True,
            "resume_media": True,
            "cookies": "sessionid=one-time-secret",
        },
    )

    assert response.status_code == 202
    assert response.json()["resume_count"] == 1
    assert "one-time-secret" not in response.text
    options = resume.await_args.kwargs["options"]
    assert options.resume_crawl is True
    assert options.resume_media is True
    assert options.cookies.get_secret_value() == "sessionid=one-time-secret"


def test_resume_rejects_active_task(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证运行中的活动任务不允许重复恢复，返回 409。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="search",
        status=CrawlTaskStatus.running.value,
        request_json=json.dumps({"crawl_type": "search", "keywords": ["运行中"]}),
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    response = client.post(
        f"/api/v1/douyin/tasks/{task.id}/resume",
        headers=superuser_token_headers,
        json={},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "活动任务不能重复恢复"


def test_process_completed_task_media_accepts_new_configuration(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    """验证已完成任务的媒体后处理接口接受新配置，且 cookie 不回显。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="search",
        status=CrawlTaskStatus.succeeded.value,
        request_json=json.dumps({"crawl_type": "search", "keywords": ["后处理"]}),
        checkpoint_json=json.dumps(
            {
                "version": 1,
                "phase": "completed",
                "crawl_type": "search",
                "position": {},
            }
        ),
        aweme_count=2,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    processed = task.model_copy(
        update={
            "status": CrawlTaskStatus.queued.value,
            "request_json": json.dumps(
                {
                    "crawl_type": "search",
                    "keywords": ["后处理"],
                    "download_media": True,
                    "translate_subtitles": True,
                    "media_storage": "minio",
                }
            ),
            "checkpoint_json": json.dumps(
                {
                    "version": 1,
                    "phase": "media",
                    "crawl_type": "search",
                    "position": {},
                }
            ),
            "resume_count": 1,
        }
    )
    process_media = AsyncMock(return_value=processed)
    monkeypatch.setattr(task_manager, "process_media", process_media)

    response = client.post(
        f"/api/v1/douyin/tasks/{task.id}/media/process",
        headers=superuser_token_headers,
        json={
            "media_storage": "minio",
            "translate_subtitles": True,
            "force_retranslate": True,
            "transcription_language": "zh",
            "cookies": "sessionid=post-process-secret",
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert "post-process-secret" not in response.text
    options = process_media.await_args.kwargs["options"]
    assert isinstance(options, DouyinMediaProcessRequest)
    assert options.force_retranslate is True
    assert options.translate_subtitles is True
    assert options.cookies is not None
    assert options.cookies.get_secret_value() == "sessionid=post-process-secret"


def test_douyin_tasks_reject_token_for_deleted_user(client: TestClient) -> None:
    """验证已删除用户签发的 token 访问任务列表返回 403。"""
    access_token = create_access_token(
        subject=str(uuid.uuid4()), expires_delta=timedelta(minutes=5)
    )

    response = client.get(
        "/api/v1/douyin/tasks",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Could not validate credentials"}


def test_get_unknown_douyin_task_returns_404(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """验证查询不存在的任务返回 404。"""
    response = client.get(
        f"/api/v1/douyin/tasks/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 404


def test_list_media_returns_progress_and_subtitle_without_local_path(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证媒体列表返回进度与字幕，且不泄露本地路径与签名 URL。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="detail",
        status=CrawlTaskStatus.succeeded.value,
        request_json=json.dumps({"crawl_type": "detail", "video_ids": ["123"]}),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    asset = DouyinMediaAsset(
        task_id=task.id,
        aweme_id="123",
        source_url="https://video.example/signed-secret",
        local_path="D:/private/media/source.mp4",
        status=MediaDownloadStatus.downloaded.value,
        progress=100,
        file_size=1234,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    subtitle = DouyinSubtitle(
        asset_id=asset.id,
        task_id=task.id,
        aweme_id=asset.aweme_id,
        status=SubtitleStatus.completed.value,
        progress=100,
        full_text="翻译后的字幕",
        segments_json=json.dumps(
            [{"start": 0, "end": 1, "text": "翻译后的字幕"}], ensure_ascii=False
        ),
    )
    db.add(subtitle)
    db.commit()

    response = client.get(
        f"/api/v1/douyin/tasks/{task.id}/media",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["data"][0]["subtitle"]["full_text"] == "翻译后的字幕"
    assert payload["data"][0]["storage_backend"] == "local"
    assert "local_path" not in response.text
    assert "signed-secret" not in response.text


def test_migrate_media_to_minio_queues_selected_local_asset(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    """验证选中的本地媒体资产可排队迁移到 MinIO，并返回排队/跳过计数。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="detail",
        status=CrawlTaskStatus.succeeded.value,
        request_json=json.dumps({"crawl_type": "detail", "video_ids": ["migrate"]}),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    asset = DouyinMediaAsset(
        task_id=task.id,
        aweme_id="migrate",
        storage_backend=MediaStorageBackend.local.value,
        status=MediaDownloadStatus.downloaded.value,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    ready = AsyncMock(return_value=None)
    queue = AsyncMock(return_value=MigrationEnqueueResult(queued=1, skipped=0))
    monkeypatch.setattr(media_storage, "ensure_minio_ready", ready)
    monkeypatch.setattr(media_migration_manager, "enqueue_task", queue)

    response = client.post(
        f"/api/v1/douyin/tasks/{task.id}/media/migrate-to-minio",
        headers=superuser_token_headers,
        json={"asset_ids": [str(asset.id)]},
    )

    assert response.status_code == 202
    assert response.json() == {
        "queued": 1,
        "skipped": 0,
        "message": "Queued 1 media migrations",
    }
    ready.assert_awaited_once_with()
    queue.assert_awaited_once_with(task.id, [asset.id])


def test_migrate_media_to_minio_hides_storage_failure(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    """验证 MinIO 不可用时返回 503 统一提示，且不泄露内部端点信息。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="detail",
        status=CrawlTaskStatus.succeeded.value,
        request_json="{}",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    monkeypatch.setattr(
        media_storage,
        "ensure_minio_ready",
        AsyncMock(
            side_effect=MediaStorageUnavailableError(
                "secret endpoint http://minio.internal?token=hidden"
            )
        ),
    )

    response = client.post(
        f"/api/v1/douyin/tasks/{task.id}/media/migrate-to-minio",
        headers=superuser_token_headers,
        json={"asset_ids": []},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Media storage is unavailable"}
    assert "minio.internal" not in response.text


def test_minio_media_file_is_streamed_through_authenticated_api(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    """验证 MinIO 媒体文件经认证 API 流式下载，且响应结束后正确关闭并释放连接。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="detail",
        status=CrawlTaskStatus.succeeded.value,
        request_json=json.dumps({"crawl_type": "detail", "video_ids": ["456"]}),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    asset = DouyinMediaAsset(
        task_id=task.id,
        aweme_id="456",
        storage_backend=MediaStorageBackend.minio.value,
        storage_bucket="private-media",
        object_key=f"douyin/{task.id}/456/source.mp4",
        status=MediaDownloadStatus.downloaded.value,
        progress=100,
        mime_type="video/mp4",
        file_size=12,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    class FakeObjectResponse:
        """模拟 MinIO 对象响应的测试替身，记录关闭/释放状态。"""

        closed = False
        released = False

        def stream(self, amt: int = 2**16):  # type: ignore[no-untyped-def]
            """按块产出固定的远程视频字节流。"""
            assert amt > 0
            yield b"remote-video"

        def close(self) -> None:
            """记录连接已关闭。"""
            self.closed = True

        def release_conn(self) -> None:
            """记录连接已释放回连接池。"""
            self.released = True

    remote = FakeObjectResponse()
    monkeypatch.setattr(media_storage, "open_object", lambda _asset: remote)

    response = client.get(
        f"/api/v1/douyin/tasks/{task.id}/media/{asset.id}/file",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.content == b"remote-video"
    assert response.headers["content-type"] == "video/mp4"
    assert "attachment" in response.headers["content-disposition"]
    assert remote.closed is True
    assert remote.released is True


def test_local_media_preview_session_streams_byte_ranges(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """验证本地媒体预览：未认证 401、会话 cookie 属性、完整/Range 分段流式传输及 416 边界。"""
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="detail",
        status=CrawlTaskStatus.succeeded.value,
        request_json=json.dumps({"crawl_type": "detail", "video_ids": ["789"]}),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    media_path = tmp_path / "douyin" / str(task.id) / "789" / "source.mp4"
    media_path.parent.mkdir(parents=True)
    media_path.write_bytes(b"0123456789")
    asset = DouyinMediaAsset(
        task_id=task.id,
        aweme_id="789",
        storage_backend=MediaStorageBackend.local.value,
        local_path=str(media_path),
        status=MediaDownloadStatus.downloaded.value,
        progress=100,
        mime_type="video/mp4",
        file_size=10,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    preview_url = f"/api/v1/douyin/tasks/{task.id}/media/{asset.id}/preview"

    unauthorized = client.get(preview_url)
    assert unauthorized.status_code == 401

    session_response = client.post(
        f"{preview_url}-session",
        headers=superuser_token_headers,
    )
    assert session_response.status_code == 201
    assert "HttpOnly" in session_response.headers["set-cookie"]
    assert "SameSite=lax" in session_response.headers["set-cookie"]

    full = client.get(preview_url)
    assert full.status_code == 200
    assert full.content == b"0123456789"
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["content-length"] == "10"
    assert "inline" in full.headers["content-disposition"]

    partial = client.get(preview_url, headers={"Range": "bytes=3-6"})
    assert partial.status_code == 206
    assert partial.content == b"3456"
    assert partial.headers["content-range"] == "bytes 3-6/10"
    assert partial.headers["content-length"] == "4"

    invalid = client.get(preview_url, headers={"Range": "bytes=99-"})
    assert invalid.status_code == 416
    assert invalid.headers["content-range"] == "bytes */10"


def test_minio_media_preview_passes_range_to_object_storage(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    """验证 MinIO 媒体预览将 HTTP Range 正确换算为对象存储的 offset/length。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="detail",
        status=CrawlTaskStatus.succeeded.value,
        request_json=json.dumps({"crawl_type": "detail", "video_ids": ["987"]}),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    asset = DouyinMediaAsset(
        task_id=task.id,
        aweme_id="987",
        storage_backend=MediaStorageBackend.minio.value,
        storage_bucket="private-media",
        object_key=f"douyin/{task.id}/987/source.mp4",
        status=MediaDownloadStatus.downloaded.value,
        progress=100,
        mime_type="video/mp4",
        file_size=10,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    content = b"abcdefghij"
    opened_ranges: list[tuple[int, int | None]] = []

    class FakeObjectResponse:
        """模拟 MinIO 对象响应的测试替身，产出指定字节内容。"""

        def __init__(self, body: bytes) -> None:
            self.body = body

        def stream(self, amt: int = 2**16):  # type: ignore[no-untyped-def]
            """一次性产出全部字节内容。"""
            del amt
            yield self.body

        def close(self) -> None:
            """关闭连接（测试替身无实际操作）。"""
            pass

        def release_conn(self) -> None:
            """释放连接（测试替身无实际操作）。"""
            pass

    def open_object(
        _asset: DouyinMediaAsset, *, offset: int = 0, length: int | None = None
    ) -> FakeObjectResponse:
        """按 offset/length 切片返回模拟对象，并记录请求的范围。"""
        opened_ranges.append((offset, length))
        end = None if length is None else offset + length
        return FakeObjectResponse(content[offset:end])

    monkeypatch.setattr(media_storage, "object_size", lambda _asset: len(content))
    monkeypatch.setattr(media_storage, "open_object", open_object)
    preview_url = f"/api/v1/douyin/tasks/{task.id}/media/{asset.id}/preview"

    session_response = client.post(
        f"{preview_url}-session",
        headers=superuser_token_headers,
    )
    assert session_response.status_code == 201
    partial = client.get(preview_url, headers={"Range": "bytes=2-5"})

    assert partial.status_code == 206
    assert partial.content == b"cdef"
    assert partial.headers["content-range"] == "bytes 2-5/10"
    assert opened_ranges == [(2, 4)]
