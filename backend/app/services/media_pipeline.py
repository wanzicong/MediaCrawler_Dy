# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import re
import shutil
import tempfile
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import case
from sqlmodel import Session, col, func, select

from app.core.config import settings
from app.core.db import engine
from app.models import (
    DouyinAweme,
    DouyinMediaAsset,
    DouyinMediaAssetPublic,
    DouyinMediaAssetsPublic,
    DouyinMediaSummaryPublic,
    DouyinSubtitle,
    DouyinSubtitlePublic,
    MediaDownloadStatus,
    MediaMigrationStatus,
    MediaStorageBackend,
    SubtitleStatus,
    get_datetime_utc,
)
from app.services.media_storage import StoredMedia, media_storage


@dataclass
class MediaHandle:
    task_id: uuid.UUID
    task: asyncio.Task[None]


class _TaskFairLimiter:
    """Bound concurrency without letting one large task starve later tasks."""

    def __init__(self, limit: int) -> None:
        self._limit = max(limit, 1)
        self._active = 0
        self._waiters: dict[
            uuid.UUID, deque[asyncio.Future[None]]
        ] = {}
        self._turns: deque[uuid.UUID] = deque()
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def slot(self, task_id: uuid.UUID) -> AsyncIterator[None]:
        await self._acquire(task_id)
        try:
            yield
        finally:
            await self._release()

    async def _acquire(self, task_id: uuid.UUID) -> None:
        future = asyncio.get_running_loop().create_future()
        async with self._lock:
            queue = self._waiters.get(task_id)
            if queue is None:
                queue = deque()
                self._waiters[task_id] = queue
                self._turns.append(task_id)
            queue.append(future)
            self._grant_locked()
        try:
            await future
        except BaseException:
            async with self._lock:
                queue = self._waiters.get(task_id)
                if future.done() and not future.cancelled():
                    # The slot was granted immediately before cancellation.
                    self._active -= 1
                elif queue is not None:
                    try:
                        queue.remove(future)
                    except ValueError:
                        pass
                self._remove_empty_queue_locked(task_id)
                self._grant_locked()
            raise

    async def _release(self) -> None:
        async with self._lock:
            if self._active <= 0:
                raise RuntimeError("媒体并发限制器状态损坏")
            self._active -= 1
            self._grant_locked()

    def _grant_locked(self) -> None:
        while self._active < self._limit and self._turns:
            task_id = self._turns.popleft()
            queue = self._waiters.get(task_id)
            if queue is None:
                continue
            while queue and queue[0].cancelled():
                queue.popleft()
            if not queue:
                self._waiters.pop(task_id, None)
                continue
            future = queue.popleft()
            if queue:
                self._turns.append(task_id)
            else:
                self._waiters.pop(task_id, None)
            self._active += 1
            future.set_result(None)

    def _remove_empty_queue_locked(self, task_id: uuid.UUID) -> None:
        queue = self._waiters.get(task_id)
        if queue:
            return
        self._waiters.pop(task_id, None)
        try:
            self._turns.remove(task_id)
        except ValueError:
            pass


def _safe_error(exc: Exception) -> str:
    detail = str(exc).strip()
    if not detail:
        if isinstance(exc, httpx.WriteTimeout):
            detail = "远程服务未及时接收上传内容"
        elif isinstance(exc, httpx.ReadTimeout):
            detail = "远程服务处理超时"
        elif isinstance(exc, httpx.ConnectTimeout):
            detail = "连接远程服务超时"
        elif isinstance(exc, httpx.ConnectError):
            detail = "无法连接媒体源或远程服务"
        elif isinstance(exc, httpx.PoolTimeout):
            detail = "等待远程服务连接超时"
        else:
            detail = "未提供错误详情"
    message = f"{type(exc).__name__}: {detail}"
    message = re.sub(r"https?://\S+", "<url>", message)
    message = re.sub(r"(?i)(authorization|api[-_ ]?key|token)=?\S+", r"\1=<redacted>", message)
    return message[:1000]


def _subtitle_public(subtitle: DouyinSubtitle) -> DouyinSubtitlePublic:
    try:
        raw_segments = json.loads(subtitle.segments_json or "[]")
    except json.JSONDecodeError:
        raw_segments = []
    segments = raw_segments if isinstance(raw_segments, list) else []
    return DouyinSubtitlePublic(
        id=subtitle.id,
        asset_id=subtitle.asset_id,
        task_id=subtitle.task_id,
        aweme_id=subtitle.aweme_id,
        status=SubtitleStatus(subtitle.status),
        progress=subtitle.progress,
        attempt_count=subtitle.attempt_count,
        requested_backend=subtitle.requested_backend,
        actual_backend=subtitle.actual_backend,
        model=subtitle.model,
        language=subtitle.language,
        duration_seconds=subtitle.duration_seconds,
        full_text=subtitle.full_text,
        segments=[value for value in segments if isinstance(value, dict)],
        error=subtitle.error,
        created_at=subtitle.created_at,
        started_at=subtitle.started_at,
        finished_at=subtitle.finished_at,
    )


def media_public(asset: DouyinMediaAsset, subtitle: DouyinSubtitle | None) -> DouyinMediaAssetPublic:
    local_path = Path(asset.local_path) if asset.local_path else None
    backend = MediaStorageBackend(asset.storage_backend)
    return DouyinMediaAssetPublic(
        id=asset.id,
        task_id=asset.task_id,
        aweme_id=asset.aweme_id,
        storage_backend=backend,
        status=MediaDownloadStatus(asset.status),
        progress=asset.progress,
        attempt_count=asset.attempt_count,
        mime_type=asset.mime_type,
        file_size=asset.file_size,
        sha256=asset.sha256,
        error=asset.error,
        download_available=(
            bool(local_path and local_path.is_file())
            if backend == MediaStorageBackend.local
            else bool(
                asset.status == MediaDownloadStatus.downloaded.value
                and asset.object_key
            )
        ),
        created_at=asset.created_at,
        updated_at=asset.updated_at,
        completed_at=asset.completed_at,
        migration_status=MediaMigrationStatus(asset.migration_status),
        migration_progress=asset.migration_progress,
        migration_attempt_count=asset.migration_attempt_count,
        migration_error=asset.migration_error,
        migration_started_at=asset.migration_started_at,
        migration_finished_at=asset.migration_finished_at,
        subtitle=_subtitle_public(subtitle) if subtitle else None,
    )


class MediaPipelineManager:
    """Persistent async media download and remote subtitle pipeline."""

    def __init__(
        self,
        *,
        download_client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
        subtitle_client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
    ) -> None:
        self._handles: dict[uuid.UUID, MediaHandle] = {}
        self._lock = asyncio.Lock()
        self._download_limiter = _TaskFairLimiter(settings.MEDIA_DOWNLOAD_CONCURRENCY)
        self._subtitle_limiter = _TaskFairLimiter(settings.WHISPER_API_CONCURRENCY)
        self._download_client_factory = download_client_factory
        self._subtitle_client_factory = subtitle_client_factory

    async def startup(self) -> None:
        await asyncio.to_thread(self._mark_interrupted_sync)

    def _mark_interrupted_sync(self) -> None:
        now = get_datetime_utc()
        with Session(engine) as session:
            assets = session.exec(
                select(DouyinMediaAsset).where(
                    col(DouyinMediaAsset.status).in_(
                        [
                            MediaDownloadStatus.queued.value,
                            MediaDownloadStatus.downloading.value,
                        ]
                    )
                )
            ).all()
            for asset in assets:
                asset.status = MediaDownloadStatus.failed.value
                asset.error = "API 服务重启，下载任务已中断"
                asset.updated_at = now
                session.add(asset)
            subtitles = session.exec(
                select(DouyinSubtitle).where(
                    col(DouyinSubtitle.status).in_(
                        [SubtitleStatus.pending.value, SubtitleStatus.running.value]
                    )
                )
            ).all()
            for subtitle in subtitles:
                subtitle.status = SubtitleStatus.failed.value
                subtitle.error = "API 服务重启，字幕任务已中断"
                subtitle.finished_at = now
                session.add(subtitle)
            session.commit()

    async def enqueue_aweme(
        self,
        *,
        task_id: uuid.UUID,
        aweme_id: str,
        storage_backend: MediaStorageBackend | str | None,
        translate_subtitles: bool,
        language: str,
        headers: dict[str, str] | None = None,
        allow_download: bool = True,
        force_download: bool = False,
        force_retranslate: bool = False,
    ) -> DouyinMediaAsset | None:
        asset = await asyncio.to_thread(
            self._prepare_asset_sync,
            task_id,
            aweme_id,
            storage_backend,
        )
        if asset is None:
            return None
        async with self._lock:
            handle = self._handles.get(asset.id)
            if handle and not handle.task.done():
                return asset
            runner = asyncio.create_task(
                self._run_asset(
                    asset.id,
                    translate_subtitles=translate_subtitles,
                    language=language,
                    headers=dict(headers or {}),
                    allow_download=allow_download,
                    force_download=force_download,
                    force_retranslate=force_retranslate,
                ),
                name=f"media-{asset.id}",
            )
            self._handles[asset.id] = MediaHandle(task_id=task_id, task=runner)
        return asset

    def _prepare_asset_sync(
        self,
        task_id: uuid.UUID,
        aweme_id: str,
        storage_backend: MediaStorageBackend | str | None,
    ) -> DouyinMediaAsset | None:
        with Session(engine) as session:
            aweme = session.exec(
                select(DouyinAweme).where(
                    DouyinAweme.task_id == task_id,
                    DouyinAweme.aweme_id == aweme_id,
                )
            ).first()
            if aweme is None:
                return None
            asset = session.exec(
                select(DouyinMediaAsset).where(
                    DouyinMediaAsset.task_id == task_id,
                    DouyinMediaAsset.aweme_id == aweme_id,
                )
            ).first()
            if asset is None:
                backend, bucket, object_key = media_storage.location_values(
                    task_id=task_id,
                    aweme_id=aweme_id,
                    backend=storage_backend,
                )
                asset = DouyinMediaAsset(
                    task_id=task_id,
                    aweme_id=aweme_id,
                    source_url=aweme.video_download_url,
                    storage_backend=backend.value,
                    storage_bucket=bucket,
                    object_key=object_key,
                )
            else:
                if (
                    asset.status != MediaDownloadStatus.downloaded.value
                    and storage_backend is not None
                ):
                    backend, bucket, object_key = media_storage.location_values(
                        task_id=task_id,
                        aweme_id=aweme_id,
                        backend=storage_backend,
                    )
                    asset.storage_backend = backend.value
                    asset.storage_bucket = bucket
                    asset.object_key = object_key
                    asset.local_path = ""
                if asset.status == MediaDownloadStatus.failed.value:
                    asset.status = MediaDownloadStatus.queued.value
                    asset.progress = 0
                    asset.error = None
                if aweme.video_download_url:
                    asset.source_url = aweme.video_download_url
                asset.updated_at = get_datetime_utc()
            session.add(asset)
            session.commit()
            session.refresh(asset)
            return asset

    async def enqueue_task(
        self,
        *,
        task_id: uuid.UUID,
        storage_backend: MediaStorageBackend | str | None,
        translate_subtitles: bool,
        language: str,
        headers: dict[str, str] | None = None,
        force_retranslate: bool = False,
    ) -> int:
        aweme_ids = await asyncio.to_thread(self._task_aweme_ids_sync, task_id)
        for aweme_id in aweme_ids:
            await self.enqueue_aweme(
                task_id=task_id,
                aweme_id=aweme_id,
                storage_backend=storage_backend,
                translate_subtitles=translate_subtitles,
                language=language,
                headers=headers,
                force_retranslate=force_retranslate,
            )
        return len(aweme_ids)

    @staticmethod
    def _task_aweme_ids_sync(task_id: uuid.UUID) -> list[str]:
        with Session(engine) as session:
            return list(
                session.exec(
                    select(DouyinAweme.aweme_id).where(DouyinAweme.task_id == task_id)
                ).all()
            )

    async def wait_for_task(self, task_id: uuid.UUID) -> None:
        while True:
            async with self._lock:
                tasks = [
                    handle.task
                    for handle in self._handles.values()
                    if handle.task_id == task_id and not handle.task.done()
                ]
            if not tasks:
                return
            await asyncio.gather(*tasks, return_exceptions=True)

    async def cancel_task(self, task_id: uuid.UUID) -> None:
        async with self._lock:
            tasks = [
                handle.task
                for handle in self._handles.values()
                if handle.task_id == task_id and not handle.task.done()
            ]
            for task in tasks:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def retry_task(
        self,
        *,
        task_id: uuid.UUID,
        asset_ids: list[uuid.UUID],
        retry_downloads: bool,
        retry_subtitles: bool,
        force_retranslate: bool,
        translate_if_missing: bool = False,
        language: str = "auto",
    ) -> int:
        candidates = await asyncio.to_thread(
            self._retry_candidates_sync, task_id, asset_ids
        )
        queued = 0
        for asset, subtitle in candidates:
            download_needed = asset.status == MediaDownloadStatus.failed.value
            subtitle_needed = bool(
                retry_subtitles
                and (
                    (subtitle and subtitle.status == SubtitleStatus.failed.value)
                    or (subtitle is None and translate_if_missing)
                )
            )
            should_translate = subtitle_needed or force_retranslate
            if download_needed and not retry_downloads:
                continue
            if not download_needed and not should_translate:
                continue
            if await self.enqueue_aweme(
                task_id=task_id,
                aweme_id=asset.aweme_id,
                storage_backend=asset.storage_backend,
                translate_subtitles=should_translate,
                language=language,
                allow_download=retry_downloads,
                force_download=download_needed and retry_downloads,
                force_retranslate=force_retranslate or subtitle_needed,
            ):
                queued += 1
        return queued

    @staticmethod
    def _retry_candidates_sync(
        task_id: uuid.UUID, asset_ids: list[uuid.UUID]
    ) -> list[tuple[DouyinMediaAsset, DouyinSubtitle | None]]:
        with Session(engine) as session:
            statement = select(DouyinMediaAsset).where(
                DouyinMediaAsset.task_id == task_id
            )
            if asset_ids:
                statement = statement.where(col(DouyinMediaAsset.id).in_(asset_ids))
            assets = session.exec(statement).all()
            result: list[tuple[DouyinMediaAsset, DouyinSubtitle | None]] = []
            for asset in assets:
                subtitle = session.exec(
                    select(DouyinSubtitle).where(DouyinSubtitle.asset_id == asset.id)
                ).first()
                session.expunge(asset)
                if subtitle:
                    session.expunge(subtitle)
                result.append((asset, subtitle))
            return result

    async def _run_asset(
        self,
        asset_id: uuid.UUID,
        *,
        translate_subtitles: bool,
        language: str,
        headers: dict[str, str],
        allow_download: bool,
        force_download: bool,
        force_retranslate: bool,
    ) -> None:
        try:
            asset = await asyncio.to_thread(self._get_asset_sync, asset_id)
            if asset is None:
                return
            if force_download or asset.status != MediaDownloadStatus.downloaded.value:
                if not allow_download:
                    return
                await self._download(asset, headers=headers, force=force_download)
                asset = await asyncio.to_thread(self._get_asset_sync, asset_id)
                if asset is None or asset.status != MediaDownloadStatus.downloaded.value:
                    return
            if translate_subtitles:
                subtitle = await asyncio.to_thread(
                    self._get_subtitle_for_asset_sync, asset_id
                )
                if force_retranslate or not subtitle or subtitle.status != SubtitleStatus.completed.value:
                    await self._transcribe(asset, language=language)
        except asyncio.CancelledError:
            await asyncio.shield(
                asyncio.to_thread(self._cancel_asset_sync, asset_id)
            )
            raise
        finally:
            async with self._lock:
                self._handles.pop(asset_id, None)

    async def _download(
        self,
        asset: DouyinMediaAsset,
        *,
        headers: dict[str, str],
        force: bool,
    ) -> None:
        async with self._download_limiter.slot(asset.task_id):
            if not force:
                existing = await media_storage.existing(asset)
                if existing is not None:
                    if (
                        not existing.sha256
                        and existing.backend == MediaStorageBackend.local
                    ):
                        existing = StoredMedia(
                            backend=existing.backend,
                            local_path=existing.local_path,
                            bucket=existing.bucket,
                            object_key=existing.object_key,
                            file_size=existing.file_size,
                            sha256=await asyncio.to_thread(
                                self._sha256_file, Path(existing.local_path)
                            ),
                        )
                    await asyncio.to_thread(
                        self._complete_download_sync,
                        asset.id,
                        existing,
                        asset.mime_type or "video/mp4",
                    )
                    return
            if not asset.source_url:
                await asyncio.to_thread(
                    self._fail_download_sync, asset.id, "作品没有可下载的视频地址"
                )
                return

            staging_dir = (
                settings.MEDIA_OUTPUT_DIR.resolve() / ".staging" / str(asset.id)
            )
            staging_dir.mkdir(parents=True, exist_ok=True)
            staged_path = staging_dir / "source.mp4"
            partial_path = staging_dir / "source.mp4.part"
            last_error: Exception | None = None
            try:
                for attempt in range(max(settings.MEDIA_DOWNLOAD_RETRIES, 1)):
                    await asyncio.to_thread(self._begin_download_sync, asset.id)
                    try:
                        result = await self._download_once(
                            asset.id,
                            asset.source_url,
                            partial_path,
                            staged_path,
                            headers,
                        )
                        stored = await media_storage.store(
                            asset,
                            staged_path,
                            file_size=result["file_size"],
                            sha256=result["sha256"],
                            mime_type=result["mime_type"],
                        )
                        await asyncio.to_thread(
                            self._complete_download_sync,
                            asset.id,
                            stored,
                            result["mime_type"],
                        )
                        return
                    except Exception as exc:
                        last_error = exc
                        partial_path.unlink(missing_ok=True)
                        staged_path.unlink(missing_ok=True)
                        if attempt + 1 < max(settings.MEDIA_DOWNLOAD_RETRIES, 1):
                            await asyncio.sleep(min(2 ** (attempt + 1), 5))
                assert last_error is not None
                await asyncio.to_thread(
                    self._fail_download_sync, asset.id, _safe_error(last_error)
                )
            finally:
                partial_path.unlink(missing_ok=True)
                staged_path.unlink(missing_ok=True)
                await asyncio.to_thread(shutil.rmtree, staging_dir, True)

    async def _download_once(
        self,
        asset_id: uuid.UUID,
        source_url: str,
        partial_path: Path,
        final_path: Path,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        max_bytes = settings.MEDIA_MAX_SIZE_MB * 1024 * 1024
        digest = hashlib.sha256()
        total = 0
        last_progress = 0
        timeout = httpx.Timeout(settings.MEDIA_DOWNLOAD_TIMEOUT)
        async with self._download_client_factory(
            headers=headers,
            follow_redirects=True,
            timeout=timeout,
            trust_env=False,
        ) as client:
            async with client.stream("GET", source_url) as response:
                response.raise_for_status()
                content_length_value = response.headers.get("content-length", "")
                content_length = int(content_length_value) if content_length_value.isdigit() else 0
                if content_length > max_bytes:
                    raise ValueError("媒体文件超过服务端大小限制")
                mime_type = response.headers.get("content-type", "").split(";", 1)[0]
                if mime_type and not (
                    mime_type.startswith("video/")
                    or mime_type.startswith("audio/")
                    or mime_type == "application/octet-stream"
                ):
                    raise ValueError(f"响应不是媒体内容: {mime_type}")
                with partial_path.open("wb") as output:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > max_bytes:
                            raise ValueError("媒体文件超过服务端大小限制")
                        digest.update(chunk)
                        output.write(chunk)
                        if content_length:
                            progress = min(int(total * 100 / content_length), 99)
                            if progress >= last_progress + 5:
                                last_progress = progress
                                await asyncio.to_thread(
                                    self._set_download_progress_sync, asset_id, progress
                                )
        if total <= 0:
            raise ValueError("下载结果为空")
        os.replace(partial_path, final_path)
        return {
            "file_size": total,
            "sha256": digest.hexdigest(),
            "mime_type": mime_type or "application/octet-stream",
        }

    async def _transcribe(self, asset: DouyinMediaAsset, *, language: str) -> None:
        async with self._subtitle_limiter.slot(asset.task_id):
            subtitle_id = await asyncio.to_thread(
                self._begin_subtitle_sync, asset, language
            )
            try:
                async with media_storage.materialize(asset) as media_path:
                    await asyncio.to_thread(
                        self._set_subtitle_progress_sync, subtitle_id, 20
                    )
                    async with self._transcription_upload_file(
                        media_path, mime_type=asset.mime_type
                    ) as (upload_path, upload_mime_type):
                        await asyncio.to_thread(
                            self._set_subtitle_progress_sync, subtitle_id, 40
                        )
                        parsed = await self._transcribe_api(
                            upload_path,
                            mime_type=upload_mime_type,
                            language=language,
                        )
                        await asyncio.to_thread(
                            self._set_subtitle_progress_sync, subtitle_id, 90
                        )
                await asyncio.to_thread(
                    self._complete_subtitle_sync, subtitle_id, parsed
                )
            except Exception as exc:
                await asyncio.to_thread(
                    self._fail_subtitle_sync, subtitle_id, _safe_error(exc)
                )

    @asynccontextmanager
    async def _transcription_upload_file(
        self, media_path: Path, *, mime_type: str
    ) -> AsyncIterator[tuple[Path, str]]:
        """Prepare a compact audio upload; speech recognition remains remote-only."""
        audio_suffixes = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"}
        if mime_type.startswith("audio/") or media_path.suffix.lower() in audio_suffixes:
            yield media_path, mime_type or "application/octet-stream"
            return

        with tempfile.TemporaryDirectory(prefix="douyin-transcription-") as temp_dir:
            audio_path = Path(temp_dir) / "audio.mp3"
            try:
                process = await asyncio.create_subprocess_exec(
                    settings.FFMPEG_BINARY,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-y",
                    "-i",
                    str(media_path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-b:a",
                    f"{settings.WHISPER_AUDIO_BITRATE_KBPS}k",
                    str(audio_path),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    "服务未安装 FFmpeg，无法为远程字幕 API 准备音频"
                ) from exc
            try:
                await asyncio.wait_for(
                    process.communicate(),
                    timeout=settings.WHISPER_AUDIO_PREPROCESS_TIMEOUT,
                )
            except asyncio.TimeoutError as exc:
                process.kill()
                await process.communicate()
                raise TimeoutError("为远程字幕 API 提取音频超时") from exc
            if process.returncode != 0 or not audio_path.is_file():
                raise RuntimeError("无法从视频提取可转写音频")
            if audio_path.stat().st_size <= 0:
                raise RuntimeError("从视频提取的音频为空")
            yield audio_path, "audio/mpeg"

    async def _transcribe_api(
        self, media_path: Path, *, mime_type: str, language: str
    ) -> dict[str, Any]:
        if not media_path.is_file():
            raise FileNotFoundError("已下载的视频文件不存在")
        endpoint = self._transcription_url(settings.WHISPER_API_BASE_URL)
        data: dict[str, str] = {
            "model": settings.WHISPER_API_MODEL,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "segment",
        }
        if language not in {"", "auto"}:
            data["language"] = language
        request_headers: dict[str, str] = {}
        api_key = settings.WHISPER_API_KEY.get_secret_value()
        if api_key:
            request_headers["Authorization"] = f"Bearer {api_key}"
        timeout = httpx.Timeout(
            connect=min(settings.WHISPER_API_TIMEOUT, 5.0),
            read=settings.WHISPER_API_TIMEOUT,
            write=min(settings.WHISPER_API_TIMEOUT, 300.0),
            pool=5.0,
        )
        with media_path.open("rb") as media_file:
            files = {
                "file": (media_path.name, media_file, mime_type or "video/mp4")
            }
            async with self._subtitle_client_factory(
                timeout=timeout,
                follow_redirects=False,
                trust_env=settings.WHISPER_API_TRUST_ENV,
            ) as client:
                response = await client.post(
                    endpoint,
                    data=data,
                    files=files,
                    headers=request_headers,
                )
        if response.status_code >= 300:
            detail = response.text.strip().replace("\r", " ").replace("\n", " ")
            raise RuntimeError(
                f"字幕 API 返回 HTTP {response.status_code}: {detail[:500] or '无详情'}"
            )
        return self._parse_transcription(response.json())

    @staticmethod
    def _transcription_url(base_url: str) -> str:
        normalized = base_url.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("WHISPER_API_BASE_URL 必须是有效的 HTTP(S) 地址")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("WHISPER_API_BASE_URL 不能包含凭据、查询参数或片段")
        hostname = parsed.hostname.rstrip(".").lower()
        try:
            loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            loopback = hostname == "localhost"
        if parsed.scheme == "http" and not loopback:
            raise ValueError("远程字幕 API 必须使用 HTTPS")
        return (
            f"{normalized}/audio/transcriptions"
            if normalized.endswith("/v1")
            else f"{normalized}/v1/audio/transcriptions"
        )

    @staticmethod
    def _parse_transcription(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
            raise ValueError("字幕 API 返回格式无效")
        raw_segments = payload.get("segments") or []
        if not isinstance(raw_segments, list):
            raise ValueError("字幕 API 的 segments 格式无效")
        segments: list[dict[str, object]] = []
        for value in raw_segments:
            if not isinstance(value, dict) or not isinstance(value.get("text"), str):
                continue
            try:
                start = max(float(value.get("start", 0)), 0.0)
                end = max(float(value.get("end", start)), start)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("字幕时间戳格式无效") from exc
            segments.append(
                {"start": start, "end": end, "text": str(value["text"]).strip()}
            )
        try:
            duration = max(float(payload.get("duration", 0)), 0.0)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("字幕时长格式无效") from exc
        return {
            "language": str(payload.get("language") or ""),
            "duration_seconds": duration,
            "full_text": str(payload["text"]).strip(),
            "segments_json": json.dumps(segments, ensure_ascii=False),
            "actual_backend": "api",
            "resolved_model": (
                settings.WHISPER_API_MODEL_VERSION or settings.WHISPER_API_MODEL
            ),
        }

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            while chunk := file.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _get_asset_sync(asset_id: uuid.UUID) -> DouyinMediaAsset | None:
        with Session(engine) as session:
            asset = session.get(DouyinMediaAsset, asset_id)
            if asset:
                session.expunge(asset)
            return asset

    @staticmethod
    def _get_subtitle_for_asset_sync(asset_id: uuid.UUID) -> DouyinSubtitle | None:
        with Session(engine) as session:
            subtitle = session.exec(
                select(DouyinSubtitle).where(DouyinSubtitle.asset_id == asset_id)
            ).first()
            if subtitle:
                session.expunge(subtitle)
            return subtitle

    @staticmethod
    def _begin_download_sync(asset_id: uuid.UUID) -> None:
        with Session(engine) as session:
            asset = session.get(DouyinMediaAsset, asset_id)
            if not asset:
                return
            asset.status = MediaDownloadStatus.downloading.value
            asset.progress = 0
            asset.attempt_count += 1
            asset.error = None
            asset.updated_at = get_datetime_utc()
            session.add(asset)
            session.commit()

    @staticmethod
    def _set_download_progress_sync(asset_id: uuid.UUID, progress: int) -> None:
        with Session(engine) as session:
            asset = session.get(DouyinMediaAsset, asset_id)
            if asset and asset.status == MediaDownloadStatus.downloading.value:
                asset.progress = progress
                asset.updated_at = get_datetime_utc()
                session.add(asset)
                session.commit()

    @staticmethod
    def _complete_download_sync(
        asset_id: uuid.UUID,
        stored: StoredMedia,
        mime_type: str,
    ) -> None:
        with Session(engine) as session:
            asset = session.get(DouyinMediaAsset, asset_id)
            if not asset:
                return
            now = get_datetime_utc()
            asset.status = MediaDownloadStatus.downloaded.value
            asset.progress = 100
            asset.storage_backend = stored.backend.value
            asset.local_path = stored.local_path
            asset.storage_bucket = stored.bucket
            asset.object_key = stored.object_key
            asset.file_size = stored.file_size
            asset.sha256 = stored.sha256
            asset.mime_type = mime_type
            asset.error = None
            asset.updated_at = now
            asset.completed_at = now
            session.add(asset)
            session.commit()

    @staticmethod
    def _fail_download_sync(asset_id: uuid.UUID, error: str) -> None:
        with Session(engine) as session:
            asset = session.get(DouyinMediaAsset, asset_id)
            if not asset:
                return
            asset.status = MediaDownloadStatus.failed.value
            asset.progress = 0
            asset.error = error
            asset.updated_at = get_datetime_utc()
            session.add(asset)
            session.commit()

    @staticmethod
    def _cancel_asset_sync(asset_id: uuid.UUID) -> None:
        with Session(engine) as session:
            asset = session.get(DouyinMediaAsset, asset_id)
            if asset and asset.status in {
                MediaDownloadStatus.queued.value,
                MediaDownloadStatus.downloading.value,
            }:
                asset.status = MediaDownloadStatus.failed.value
                asset.progress = 0
                asset.error = "媒体任务已取消"
                asset.updated_at = get_datetime_utc()
                session.add(asset)
            subtitle = session.exec(
                select(DouyinSubtitle).where(DouyinSubtitle.asset_id == asset_id)
            ).first()
            if subtitle and subtitle.status in {
                SubtitleStatus.pending.value,
                SubtitleStatus.running.value,
            }:
                subtitle.status = SubtitleStatus.failed.value
                subtitle.progress = 0
                subtitle.error = "字幕任务已取消"
                subtitle.finished_at = get_datetime_utc()
                session.add(subtitle)
            session.commit()

    @staticmethod
    def _begin_subtitle_sync(asset: DouyinMediaAsset, language: str) -> uuid.UUID:
        with Session(engine) as session:
            subtitle = session.exec(
                select(DouyinSubtitle).where(DouyinSubtitle.asset_id == asset.id)
            ).first()
            if subtitle is None:
                subtitle = DouyinSubtitle(
                    asset_id=asset.id,
                    task_id=asset.task_id,
                    aweme_id=asset.aweme_id,
                )
            subtitle.status = SubtitleStatus.running.value
            subtitle.progress = 10
            subtitle.attempt_count += 1
            subtitle.requested_backend = "api"
            subtitle.actual_backend = ""
            subtitle.model = (
                settings.WHISPER_API_MODEL_VERSION or settings.WHISPER_API_MODEL
            )
            subtitle.language = language
            subtitle.error = None
            subtitle.started_at = get_datetime_utc()
            subtitle.finished_at = None
            session.add(subtitle)
            session.commit()
            session.refresh(subtitle)
            return subtitle.id

    @staticmethod
    def _set_subtitle_progress_sync(subtitle_id: uuid.UUID, progress: int) -> None:
        with Session(engine) as session:
            subtitle = session.get(DouyinSubtitle, subtitle_id)
            if subtitle and subtitle.status == SubtitleStatus.running.value:
                subtitle.progress = max(0, min(progress, 99))
                session.add(subtitle)
                session.commit()

    @staticmethod
    def _complete_subtitle_sync(subtitle_id: uuid.UUID, values: dict[str, Any]) -> None:
        with Session(engine) as session:
            subtitle = session.get(DouyinSubtitle, subtitle_id)
            if not subtitle:
                return
            subtitle.status = SubtitleStatus.completed.value
            subtitle.progress = 100
            subtitle.actual_backend = str(values["actual_backend"])
            subtitle.model = str(values["resolved_model"])
            subtitle.language = str(values["language"])
            subtitle.duration_seconds = float(values["duration_seconds"])
            subtitle.full_text = str(values["full_text"])
            subtitle.segments_json = str(values["segments_json"])
            subtitle.error = None
            subtitle.finished_at = get_datetime_utc()
            session.add(subtitle)
            session.commit()

    @staticmethod
    def _fail_subtitle_sync(subtitle_id: uuid.UUID, error: str) -> None:
        with Session(engine) as session:
            subtitle = session.get(DouyinSubtitle, subtitle_id)
            if not subtitle:
                return
            subtitle.status = SubtitleStatus.failed.value
            subtitle.progress = 0
            subtitle.error = error
            subtitle.finished_at = get_datetime_utc()
            session.add(subtitle)
            session.commit()

    async def shutdown(self) -> None:
        async with self._lock:
            tasks = [handle.task for handle in self._handles.values()]
            for task in tasks:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def list_media_sync(task_id: uuid.UUID, skip: int, limit: int) -> DouyinMediaAssetsPublic:
    with Session(engine) as session:
        count = session.exec(
            select(func.count())
            .select_from(DouyinMediaAsset)
            .where(DouyinMediaAsset.task_id == task_id)
        ).one()
        activity_priority = case(
            (col(DouyinMediaAsset.status) == MediaDownloadStatus.downloading.value, 0),
            (col(DouyinSubtitle.status) == SubtitleStatus.running.value, 1),
            (col(DouyinMediaAsset.status) == MediaDownloadStatus.queued.value, 2),
            (col(DouyinSubtitle.status) == SubtitleStatus.pending.value, 3),
            (col(DouyinMediaAsset.status) == MediaDownloadStatus.failed.value, 4),
            (col(DouyinSubtitle.status) == SubtitleStatus.failed.value, 5),
            else_=6,
        )
        rows = session.exec(
            select(DouyinMediaAsset, DouyinSubtitle)
            .outerjoin(
                DouyinSubtitle,
                col(DouyinSubtitle.asset_id) == col(DouyinMediaAsset.id),
            )
            .where(DouyinMediaAsset.task_id == task_id)
            .order_by(activity_priority, col(DouyinMediaAsset.updated_at).desc())
            .offset(skip)
            .limit(limit)
        ).all()
        data = [media_public(asset, subtitle) for asset, subtitle in rows]
        return DouyinMediaAssetsPublic(data=data, count=count)


def media_summary_sync(task_id: uuid.UUID) -> DouyinMediaSummaryPublic:
    with Session(engine) as session:
        asset_rows = session.exec(
            select(
                DouyinMediaAsset.status,
                DouyinMediaAsset.storage_backend,
                DouyinMediaAsset.migration_status,
            ).where(DouyinMediaAsset.task_id == task_id)
        ).all()
        subtitles = session.exec(
            select(DouyinSubtitle.status).where(DouyinSubtitle.task_id == task_id)
        ).all()
    statuses = [row[0] for row in asset_rows]
    backends = [row[1] for row in asset_rows]
    migrations = [row[2] for row in asset_rows]
    return DouyinMediaSummaryPublic(
        total=len(statuses),
        queued=statuses.count(MediaDownloadStatus.queued.value),
        downloading=statuses.count(MediaDownloadStatus.downloading.value),
        downloaded=statuses.count(MediaDownloadStatus.downloaded.value),
        download_failed=statuses.count(MediaDownloadStatus.failed.value),
        subtitle_pending=subtitles.count(SubtitleStatus.pending.value),
        subtitle_running=subtitles.count(SubtitleStatus.running.value),
        subtitle_completed=subtitles.count(SubtitleStatus.completed.value),
        subtitle_failed=subtitles.count(SubtitleStatus.failed.value),
        local_downloaded=sum(
            status == MediaDownloadStatus.downloaded.value
            and backend == MediaStorageBackend.local.value
            for status, backend in zip(statuses, backends, strict=True)
        ),
        minio_downloaded=sum(
            status == MediaDownloadStatus.downloaded.value
            and backend == MediaStorageBackend.minio.value
            for status, backend in zip(statuses, backends, strict=True)
        ),
        migration_queued=migrations.count(MediaMigrationStatus.queued.value),
        migration_running=sum(
            value
            in {
                MediaMigrationStatus.uploading.value,
                MediaMigrationStatus.verifying.value,
                MediaMigrationStatus.switching.value,
            }
            for value in migrations
        ),
        migration_cleanup_pending=migrations.count(
            MediaMigrationStatus.cleanup_pending.value
        ),
        migration_completed=migrations.count(MediaMigrationStatus.completed.value),
        migration_failed=migrations.count(MediaMigrationStatus.failed.value),
    )


media_manager = MediaPipelineManager()
