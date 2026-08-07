import asyncio
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlmodel import Session, select

from app.core.config import settings
from app.douyin.storage import DouyinStorage
from app.models import (
    CrawlTaskCreate,
    DouyinAweme,
    DouyinMediaAsset,
    MediaDownloadStatus,
    MediaStorageBackend,
    User,
)
from app.services.media_pipeline import MediaPipelineManager


def test_enqueue_task_forwards_force_retranslation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = MediaPipelineManager()
    monkeypatch.setattr(
        manager, "_task_aweme_ids_sync", lambda _task_id: ["aweme-1"]
    )
    enqueue = AsyncMock(return_value=None)
    monkeypatch.setattr(manager, "enqueue_aweme", enqueue)
    task_id = uuid.uuid4()

    queued = asyncio.run(
        manager.enqueue_task(
            task_id=task_id,
            storage_backend="minio",
            translate_subtitles=True,
            language="zh",
            headers={"Cookie": "sessionid=one-time"},
            force_retranslate=True,
        )
    )

    assert queued == 1
    enqueue.assert_awaited_once_with(
        task_id=task_id,
        aweme_id="aweme-1",
        storage_backend="minio",
        translate_subtitles=True,
        language="zh",
        headers={"Cookie": "sessionid=one-time"},
        force_retranslate=True,
    )


def test_pending_asset_uses_new_storage_choice_but_downloaded_asset_stays_put(
    db: Session,
) -> None:
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(keywords=["切换媒体存储"]),
        )
    )
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id="storage-switch-aweme",
            video_download_url="https://example.invalid/video.mp4",
        )
    )
    db.add(
        DouyinMediaAsset(
            task_id=task.id,
            aweme_id="storage-switch-aweme",
            status=MediaDownloadStatus.failed.value,
            storage_backend=MediaStorageBackend.local.value,
            local_path="stale-local-path",
        )
    )
    db.commit()
    manager = MediaPipelineManager()

    pending = manager._prepare_asset_sync(
        task.id,
        "storage-switch-aweme",
        MediaStorageBackend.minio,
    )
    assert pending is not None
    assert pending.storage_backend == MediaStorageBackend.minio.value
    assert pending.storage_bucket == settings.MINIO_BUCKET
    assert pending.object_key
    assert pending.local_path == ""

    pending.status = MediaDownloadStatus.downloaded.value
    db.merge(pending)
    db.commit()
    downloaded = manager._prepare_asset_sync(
        task.id,
        "storage-switch-aweme",
        MediaStorageBackend.local,
    )
    assert downloaded is not None
    assert downloaded.storage_backend == MediaStorageBackend.minio.value


def test_transcription_url_accepts_loopback_and_openai_v1_shape() -> None:
    assert (
        MediaPipelineManager._transcription_url("http://127.0.0.1:9000")
        == "http://127.0.0.1:9000/v1/audio/transcriptions"
    )
    assert (
        MediaPipelineManager._transcription_url("https://speech.example.com/v1")
        == "https://speech.example.com/v1/audio/transcriptions"
    )


def test_transcription_url_rejects_insecure_remote_host() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        MediaPipelineManager._transcription_url("http://speech.example.com")


def test_parse_transcription_keeps_text_and_timestamps() -> None:
    result = MediaPipelineManager._parse_transcription(
        {
            "language": "zh",
            "duration": 3.5,
            "text": "你好世界",
            "segments": [
                {"start": 0, "end": 1.2, "text": "你好"},
                {"start": 1.2, "end": 3.5, "text": "世界"},
            ],
        }
    )

    assert result["language"] == "zh"
    assert result["full_text"] == "你好世界"
    assert "你好" in str(result["segments_json"])
    assert result["actual_backend"] == "api"


def test_api_failure_marks_subtitle_job_failed_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    media_path = tmp_path / "source.mp4"
    media_path.write_bytes(b"fake-video")
    failed: dict[str, Any] = {}
    manager = MediaPipelineManager()
    subtitle_id = uuid.uuid4()
    monkeypatch.setattr(
        manager,
        "_begin_subtitle_sync",
        lambda _asset, _language: subtitle_id,
    )

    async def fail_api(
        _path: Path, *, mime_type: str, language: str
    ) -> dict[str, Any]:
        assert mime_type == "video/mp4"
        assert language == "zh"
        raise httpx.ConnectError("remote unavailable")

    monkeypatch.setattr(manager, "_transcribe_api", fail_api)
    monkeypatch.setattr(
        manager,
        "_complete_subtitle_sync",
        lambda _actual_id, _values: pytest.fail("远程失败后不应完成字幕任务"),
    )
    monkeypatch.setattr(
        manager,
        "_fail_subtitle_sync",
        lambda actual_id, error: failed.update(id=actual_id, error=error),
    )
    asset = DouyinMediaAsset(
        task_id=uuid.uuid4(),
        aweme_id="123",
        local_path=str(media_path),
        mime_type="video/mp4",
    )

    asyncio.run(manager._transcribe(asset, language="zh"))

    assert failed["id"] == subtitle_id
    assert "ConnectError" in str(failed["error"])
    assert "remote unavailable" in str(failed["error"])


def test_streaming_download_is_atomically_committed(tmp_path: Path) -> None:
    content = b"video-content"
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=content,
            headers={"content-type": "video/mp4", "content-length": str(len(content))},
        )
    )

    def client_factory(**kwargs: object) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport, **kwargs)

    manager = MediaPipelineManager(download_client_factory=client_factory)
    partial_path = tmp_path / "source.mp4.part"
    final_path = tmp_path / "source.mp4"
    result = asyncio.run(
        manager._download_once(
            uuid.uuid4(),
            "https://video.example/source.mp4",
            partial_path,
            final_path,
            {},
        )
    )

    assert final_path.read_bytes() == content
    assert not partial_path.exists()
    assert result["file_size"] == len(content)
