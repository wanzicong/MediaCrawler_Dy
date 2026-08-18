"""抖音媒体处理管线的测试：覆盖任务公平限流、错误文案、入队与重试、存储后端切换、转写地址校验、FFmpeg 音频提取与超时治理、媒体列表排序、流式下载原子提交与端到端超时。"""

import asyncio
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from crawler.bootstrap.settings import settings
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.media.models import (
    DouyinMediaAsset,
    DouyinSubtitle,
    MediaDownloadStatus,
    MediaStorageBackend,
    SubtitleStatus,
)
from crawler.business.douyin.media.pipeline import (
    MediaPipelineManager,
    _safe_error,
    _TaskFairLimiter,
    list_media_sync,
)
from crawler.business.douyin.tasks.models import CrawlTaskCreate
from crawler.business.douyin.tasks.persistence import DouyinStorage
from crawler.business.identity.models import User
from sqlmodel import Session, select


def test_task_fair_limiter_does_not_starve_later_task() -> None:
    """验证按任务公平轮转的并发限制器：同任务连续排队不会饿死后到任务（交替获得槽位）。"""

    async def scenario() -> list[str]:
        """编排三同一异的四个协程竞争单槽位，返回实际执行顺序。"""
        limiter = _TaskFairLimiter(1)
        first_task = uuid.uuid4()
        later_task = uuid.uuid4()
        release_first = asyncio.Event()
        order: list[str] = []

        async def run(label: str, task_id: uuid.UUID, hold: bool = False) -> None:
            """占用一个槽位记录标签；hold 时先等待放行信号。"""
            async with limiter.slot(task_id):
                order.append(label)
                if hold:
                    await release_first.wait()

        first = asyncio.create_task(run("first-1", first_task, hold=True))
        await asyncio.sleep(0)
        queued = [
            asyncio.create_task(run("first-2", first_task)),
            asyncio.create_task(run("first-3", first_task)),
            asyncio.create_task(run("later-1", later_task)),
        ]
        await asyncio.sleep(0)
        release_first.set()
        await asyncio.gather(first, *queued)
        return order

    assert asyncio.run(scenario()) == [
        "first-1",
        "first-2",
        "later-1",
        "first-3",
    ]


def test_empty_remote_timeout_error_has_actionable_detail() -> None:
    """验证空消息的写超时异常被转换为带可操作指引的中文错误文案。"""
    error = _safe_error(httpx.WriteTimeout(""))

    assert error == "WriteTimeout: 远程服务未及时接收上传内容"


def test_empty_connect_error_has_actionable_detail() -> None:
    """验证空消息的连接异常被转换为带可操作指引的中文错误文案。"""
    error = _safe_error(httpx.ConnectError(""))

    assert error == "ConnectError: 无法连接媒体源或远程服务"


def test_enqueue_task_forwards_force_retranslation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证任务级媒体入队将强制重译、存储后端、语言与请求头等参数原样透传到作品级入队。"""
    manager = MediaPipelineManager()
    monkeypatch.setattr(manager, "_task_aweme_ids_sync", lambda _task_id: ["aweme-1"])
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


def test_retry_task_recovers_durable_queued_asset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证重试会捞起滞留 queued 状态的资产并以强制下载方式重新入队。"""
    manager = MediaPipelineManager()
    task_id = uuid.uuid4()
    asset = DouyinMediaAsset(
        task_id=task_id,
        aweme_id="stale-queued",
        status=MediaDownloadStatus.queued.value,
        storage_backend=MediaStorageBackend.minio.value,
    )
    monkeypatch.setattr(
        manager, "_retry_candidates_sync", lambda *_args: [(asset, None)]
    )
    enqueue = AsyncMock(return_value=asset)
    monkeypatch.setattr(manager, "enqueue_aweme", enqueue)

    recovered = asyncio.run(
        manager.retry_task(
            task_id=task_id,
            asset_ids=[],
            retry_downloads=True,
            retry_subtitles=False,
            force_retranslate=False,
        )
    )

    assert recovered == 1
    assert enqueue.await_args.kwargs["force_download"] is True


def test_pending_asset_uses_new_storage_choice_but_downloaded_asset_stays_put(
    db: Session,
) -> None:
    """验证未完成资产重备时按新选择的存储后端重置；已下载资产保持原后端不被迁移。"""
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
            progress=63,
            error="API 服务重启，下载任务已中断",
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
    assert pending.status == MediaDownloadStatus.queued.value
    assert pending.progress == 0
    assert pending.error is None

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
    """验证转写地址校验放行回环地址与 OpenAI 兼容的 /v1 形式，并补全转写端点路径。"""
    assert (
        MediaPipelineManager._transcription_url("http://127.0.0.1:9000")
        == "http://127.0.0.1:9000/v1/audio/transcriptions"
    )
    assert (
        MediaPipelineManager._transcription_url("https://speech.example.com/v1")
        == "https://speech.example.com/v1/audio/transcriptions"
    )


def test_transcription_url_accepts_docker_host_gateway() -> None:
    """验证转写地址校验放行 Docker 宿主机网关地址（容器内访问宿主机服务的常见形式）。"""
    assert (
        MediaPipelineManager._transcription_url("http://host.docker.internal:9000")
        == "http://host.docker.internal:9000/v1/audio/transcriptions"
    )


def test_transcription_url_rejects_insecure_remote_host() -> None:
    """验证远程非回环地址必须使用 HTTPS，否则拒绝并提示。"""
    with pytest.raises(ValueError, match="HTTPS"):
        MediaPipelineManager._transcription_url("http://speech.example.com")


def test_parse_transcription_keeps_text_and_timestamps() -> None:
    """验证转写结果解析保留全文与分段时间戳，实际后端标记为 api。"""
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
    """验证远程转写 API 失败时字幕任务被标记为失败且记录错误，不做本地回退、不误标完成。"""
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    media_path = tmp_path / "source.mp3"
    media_path.write_bytes(b"fake-audio")
    failed: dict[str, Any] = {}
    manager = MediaPipelineManager()
    subtitle_id = uuid.uuid4()
    monkeypatch.setattr(
        manager,
        "_begin_subtitle_sync",
        lambda _asset, _language: subtitle_id,
    )

    async def fail_api(_path: Path, *, mime_type: str, language: str) -> dict[str, Any]:
        """模拟远程转写 API 连接失败，断言传入的 MIME 与语言正确。"""
        assert mime_type == "audio/mpeg"
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
        mime_type="audio/mpeg",
    )

    asyncio.run(manager._transcribe(asset, language="zh"))

    assert failed["id"] == subtitle_id
    assert "ConnectError" in str(failed["error"])
    assert "remote unavailable" in str(failed["error"])


def test_video_is_compacted_to_audio_before_remote_transcription(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证视频文件先用 FFmpeg 压制为单声道 16kHz 小体积音频再上传转写，临时文件随上下文退出清理。"""
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    created: dict[str, object] = {}

    class FakeProcess:
        """模拟 FFmpeg 子进程：立即成功返回。"""

        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            """返回空的 stdout/stderr。"""
            return b"", b""

        def kill(self) -> None:
            """记录被强制结束（本用例不应触发）。"""
            created["killed"] = True

    async def create_process(*args: object, **kwargs: object) -> FakeProcess:
        """模拟创建子进程：记录命令行参数并写出压缩后的音频产物。"""
        output = Path(str(args[-1]))
        output.write_bytes(b"compact-audio")
        created["args"] = args
        created["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    manager = MediaPipelineManager()

    async def prepare() -> tuple[str, bytes, bool]:
        """在上下文内读取上传文件类型、内容与存在性。"""
        async with manager._transcription_upload_file(
            source, mime_type="video/mp4"
        ) as (upload_path, upload_type):
            return upload_type, upload_path.read_bytes(), upload_path.is_file()

    upload_type, content, existed_during_context = asyncio.run(prepare())

    assert upload_type == "audio/mpeg"
    assert content == b"compact-audio"
    assert existed_during_context is True
    process_args = created["args"]
    assert isinstance(process_args, tuple)
    assert process_args[:-1] == (
        settings.FFMPEG_BINARY,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        f"{settings.WHISPER_AUDIO_BITRATE_KBPS}k",
    )
    assert Path(str(process_args[-1])).name == "audio.mp3"
    assert created["kwargs"] == {
        "stdout": asyncio.subprocess.DEVNULL,
        "stderr": asyncio.subprocess.DEVNULL,
    }
    assert "killed" not in created


def test_missing_ffmpeg_keeps_application_error_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证系统缺少 FFmpeg 时抛出约定文案的运行时错误，不产生上传文件。"""
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    async def missing_binary(*_args: object, **_kwargs: object) -> object:
        """模拟 FFmpeg 可执行文件不存在。"""
        raise FileNotFoundError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", missing_binary)
    manager = MediaPipelineManager()

    async def prepare() -> None:
        """进入上传文件准备上下文（预期不会成功进入）。"""
        async with manager._transcription_upload_file(source, mime_type="video/mp4"):
            pytest.fail("FFmpeg 缺失时不应产生上传文件")

    with pytest.raises(
        RuntimeError,
        match="^服务未安装 FFmpeg，无法为远程字幕 API 准备音频$",
    ):
        asyncio.run(prepare())


def test_ffmpeg_timeout_kills_process_and_keeps_error_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证 FFmpeg 提取音频超时会 kill 子进程并抛出约定文案的超时错误。"""
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    state = {"calls": 0, "killed": False}

    class SlowProcess:
        """模拟迟迟不结束的 FFmpeg 子进程：被 kill 后才返回。"""

        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            """未被 kill 时长时间挂起，被 kill 后立即返回。"""
            state["calls"] += 1
            if not state["killed"]:
                await asyncio.sleep(60)
            return b"", b""

        def kill(self) -> None:
            """记录被强制结束。"""
            state["killed"] = True

    async def create_process(*_args: object, **_kwargs: object) -> SlowProcess:
        """返回慢速模拟子进程。"""
        return SlowProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr(settings, "WHISPER_AUDIO_PREPROCESS_TIMEOUT", 0.001)
    manager = MediaPipelineManager()

    async def prepare() -> None:
        """进入上传文件准备上下文（预期因超时而失败）。"""
        async with manager._transcription_upload_file(source, mime_type="video/mp4"):
            pytest.fail("FFmpeg 超时时不应产生上传文件")

    with pytest.raises(TimeoutError, match="^为远程字幕 API 提取音频超时$"):
        asyncio.run(prepare())
    assert state == {"calls": 2, "killed": True}


@pytest.mark.parametrize(
    ("returncode", "output", "message"),
    [
        (1, b"partial", "无法从视频提取可转写音频"),
        (0, None, "无法从视频提取可转写音频"),
        (0, b"", "从视频提取的音频为空"),
    ],
)
def test_ffmpeg_output_validation_keeps_application_error_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    output: bytes | None,
    message: str,
) -> None:
    """验证 FFmpeg 产物校验（非零退出码/无产物/空产物）抛出约定文案错误，且不误杀进程。

    参数：
        returncode: 模拟子进程退出码。
        output: 模拟写出的音频内容，None 表示未产出文件。
        message: 期望的中文错误文案。
    """
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    class FakeProcess:
        """模拟 FFmpeg 子进程：按参数化退出码立即结束。"""

        def __init__(self) -> None:
            """按参数化用例设置退出码。"""
            self.returncode = returncode

        async def communicate(self) -> tuple[bytes, bytes]:
            """返回空的 stdout/stderr。"""
            return b"", b""

        def kill(self) -> None:
            """非超时场景不应 kill 进程。"""
            pytest.fail("非超时失败不应 kill FFmpeg")

    async def create_process(*args: object, **_kwargs: object) -> FakeProcess:
        """模拟创建子进程：按用例写出（或不写）音频产物。"""
        if output is not None:
            Path(str(args[-1])).write_bytes(output)
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    manager = MediaPipelineManager()

    async def prepare() -> None:
        """进入上传文件准备上下文（预期因产物校验失败而不会成功进入）。"""
        async with manager._transcription_upload_file(source, mime_type="video/mp4"):
            pytest.fail("无效 FFmpeg 产物不应进入上传阶段")

    with pytest.raises(RuntimeError, match=f"^{message}$"):
        asyncio.run(prepare())


def test_media_list_prioritizes_active_work(
    db: Session,
) -> None:
    """验证媒体资产列表按活跃程度排序：下载中 > 转写中 > 失败 > 已完成。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = asyncio.run(
        DouyinStorage.create_task(
            owner.id,
            CrawlTaskCreate(keywords=["活跃媒体优先"]),
        )
    )
    completed = DouyinMediaAsset(
        task_id=task.id,
        aweme_id="completed",
        status=MediaDownloadStatus.downloaded.value,
    )
    failed = DouyinMediaAsset(
        task_id=task.id,
        aweme_id="failed",
        status=MediaDownloadStatus.failed.value,
    )
    translating = DouyinMediaAsset(
        task_id=task.id,
        aweme_id="translating",
        status=MediaDownloadStatus.downloaded.value,
    )
    downloading = DouyinMediaAsset(
        task_id=task.id,
        aweme_id="downloading",
        status=MediaDownloadStatus.downloading.value,
    )
    db.add_all([completed, failed, translating, downloading])
    db.commit()
    db.refresh(translating)
    db.add(
        DouyinSubtitle(
            asset_id=translating.id,
            task_id=task.id,
            aweme_id=translating.aweme_id,
            status=SubtitleStatus.running.value,
        )
    )
    db.commit()

    result = list_media_sync(task.id, 0, 100)

    assert [asset.aweme_id for asset in result.data] == [
        "downloading",
        "translating",
        "failed",
        "completed",
    ]


def test_streaming_download_is_atomically_committed(tmp_path: Path) -> None:
    """验证流式下载先写入 .part 临时文件再原子改名为最终文件，成功后无临时文件残留。"""
    content = b"video-content"
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=content,
            headers={"content-type": "video/mp4", "content-length": str(len(content))},
        )
    )

    def client_factory(**kwargs: object) -> httpx.AsyncClient:
        """构造使用 MockTransport 的异步 HTTP 客户端。"""
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


def test_streaming_download_has_an_end_to_end_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证流式下载有端到端总时限：慢速响应体整体超时报 TimeoutError。"""

    class SlowStream(httpx.AsyncByteStream):
        """模拟缓慢的字节响应流：首块数据前长时间挂起。"""

        async def __aiter__(self):  # type: ignore[no-untyped-def]
            await asyncio.sleep(1)
            yield b"never reached"

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            stream=SlowStream(),
            headers={"content-type": "video/mp4"},
        )
    )

    def client_factory(**kwargs: object) -> httpx.AsyncClient:
        """构造返回慢速流响应的异步 HTTP 客户端。"""
        return httpx.AsyncClient(transport=transport, **kwargs)

    monkeypatch.setattr(settings, "MEDIA_DOWNLOAD_TIMEOUT", 0.01)
    manager = MediaPipelineManager(download_client_factory=client_factory)

    with pytest.raises(TimeoutError, match="单次尝试超过 0.01 秒"):
        asyncio.run(
            manager._download_once(
                uuid.uuid4(),
                "https://video.example/slow.mp4",
                tmp_path / "slow.part",
                tmp_path / "slow.mp4",
                {},
            )
        )


def test_streaming_download_deadline_does_not_require_asyncio_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证下载总时限的实现不依赖 asyncio.timeout（兼容 Python 3.10），删除该属性后仍可正常下载。"""
    content = b"python-310-compatible-video"
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=content,
            headers={"content-type": "video/mp4"},
        )
    )

    def client_factory(**kwargs: object) -> httpx.AsyncClient:
        """构造使用 MockTransport 的异步 HTTP 客户端。"""
        return httpx.AsyncClient(transport=transport, **kwargs)

    monkeypatch.delattr(asyncio, "timeout", raising=False)
    manager = MediaPipelineManager(download_client_factory=client_factory)
    final_path = tmp_path / "compatible.mp4"

    result = asyncio.run(
        manager._download_once(
            uuid.uuid4(),
            "https://video.example/compatible.mp4",
            tmp_path / "compatible.part",
            final_path,
            {},
        )
    )

    assert result["file_size"] == len(content)
    assert final_path.read_bytes() == content
