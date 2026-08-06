import asyncio
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.models import DouyinMediaAsset
from app.services.media_pipeline import MediaPipelineManager


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
