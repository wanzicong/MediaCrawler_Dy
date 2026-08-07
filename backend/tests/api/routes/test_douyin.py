import json
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import create_access_token
from app.models import (
    CrawlTask,
    CrawlTaskStatus,
    DouyinMediaAsset,
    DouyinMediaProcessRequest,
    DouyinSubtitle,
    MediaDownloadStatus,
    MediaStorageBackend,
    SubtitleStatus,
    User,
)
from app.services.douyin_tasks import task_manager
from app.services.media_storage import media_storage


def test_create_douyin_task_is_accepted_and_never_echoes_cookie(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    task = CrawlTask(
        owner_id=uuid.uuid4(),
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


def test_douyin_tasks_require_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/douyin/tasks")

    assert response.status_code == 401


def test_resume_douyin_task_accepts_scopes_without_echoing_cookie(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
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
    resumed = CrawlTask(
        id=task.id,
        owner_id=owner.id,
        crawl_type=task.crawl_type,
        status=CrawlTaskStatus.queued.value,
        request_json=task.request_json,
        checkpoint_json=task.checkpoint_json,
        resume_count=1,
    )
    resume = AsyncMock(return_value=resumed)
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
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
        crawl_type="search",
        status=CrawlTaskStatus.running.value,
        request_json=json.dumps(
            {"crawl_type": "search", "keywords": ["运行中"]}
        ),
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
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
        crawl_type="search",
        status=CrawlTaskStatus.succeeded.value,
        request_json=json.dumps(
            {"crawl_type": "search", "keywords": ["后处理"]}
        ),
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
            "status": CrawlTaskStatus.processing_media.value,
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
    assert response.json()["status"] == "processing_media"
    assert "post-process-secret" not in response.text
    options = process_media.await_args.kwargs["options"]
    assert isinstance(options, DouyinMediaProcessRequest)
    assert options.force_retranslate is True
    assert options.translate_subtitles is True
    assert options.cookies is not None
    assert options.cookies.get_secret_value() == "sessionid=post-process-secret"


def test_douyin_tasks_reject_token_for_deleted_user(client: TestClient) -> None:
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
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
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


def test_minio_media_file_is_streamed_through_authenticated_api(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
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
        closed = False
        released = False

        def stream(self, amt: int = 2**16):  # type: ignore[no-untyped-def]
            assert amt > 0
            yield b"remote-video"

        def close(self) -> None:
            self.closed = True

        def release_conn(self) -> None:
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
