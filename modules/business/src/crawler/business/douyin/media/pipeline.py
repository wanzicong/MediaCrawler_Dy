# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音媒体下载与远程字幕转写管道。

以异步协程池方式执行媒体下载（重试、进度落库、大小/类型校验）与远程字幕
API 转写，处理状态全程持久化，支持服务重启后的中断标记与手动重试。
"""

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
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from crawler.bootstrap.database import engine
from crawler.bootstrap.settings import settings
from crawler.business.common.models import get_datetime_utc
from crawler.business.concurrency import FairLimiter
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.media.models import (
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
)
from crawler.business.douyin.tasks.models import CrawlTask
from crawler.business.resources.media.ffmpeg import (
    FFmpegEmptyOutputError,
    FFmpegNotFoundError,
    FFmpegOutputUnavailableError,
    FFmpegTimeoutError,
    extract_transcription_audio,
)
from sqlalchemy import case
from sqlmodel import Session, col, func, select

from .storage import StoredMedia, media_storage


@dataclass
class MediaHandle:
    """单个资产媒体处理协程的句柄。"""

    task_id: uuid.UUID  # 所属采集任务 ID
    task: asyncio.Task[None]  # 运行下载/转写流程的 asyncio 任务


@asynccontextmanager
async def _existing_media_path(path: Path) -> AsyncIterator[Path]:
    """把临时媒体路径适配为与存储驱动一致的异步上下文。"""
    yield path


class _TaskFairLimiter(FairLimiter[uuid.UUID]):
    """兼容包装层：保留媒体场景专属的错误信息约定。"""

    def __init__(self, limit: int) -> None:
        super().__init__(
            limit,
            state_error_message="媒体并发限制器状态损坏",
        )


def _safe_error(exc: Exception) -> str:
    """把异常转为脱敏并截断的错误文本（替换 URL 与凭据），用于安全落库与展示。"""
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
    message = re.sub(
        r"(?i)(authorization|api[-_ ]?key|token)=?\S+", r"\1=<redacted>", message
    )
    return message[:1000]


def _subtitle_public(subtitle: DouyinSubtitle) -> DouyinSubtitlePublic:
    """把字幕记录转换为对外视图，segments_json 解析为对象列表（解析失败按空列表处理）。"""
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


def media_public(
    asset: DouyinMediaAsset, subtitle: DouyinSubtitle | None
) -> DouyinMediaAssetPublic:
    """组装媒体资产的对外只读视图。

    参数：
        asset: 媒体资产记录。
        subtitle: 关联的字幕记录，可为 None。

    返回：
        资产对外视图；download_available 按后端实际可用性计算
        （local 看本地文件是否存在，minio 看下载状态与 object_key）。
    """
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
    """持久化的异步媒体下载与远程字幕转写管道管理器。"""

    def __init__(
        self,
        *,
        download_client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
        subtitle_client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
    ) -> None:
        """初始化管道管理器；HTTP 客户端工厂可注入以便测试。"""
        self._handles: dict[uuid.UUID, MediaHandle] = {}
        self._lock = asyncio.Lock()
        self._download_limiter = _TaskFairLimiter(settings.MEDIA_DOWNLOAD_CONCURRENCY)
        self._subtitle_limiter = _TaskFairLimiter(settings.WHISPER_API_CONCURRENCY)
        self._download_client_factory = download_client_factory
        self._subtitle_client_factory = subtitle_client_factory

    async def startup(self) -> None:
        """服务启动时恢复上次进程遗留的下载与字幕任务。"""
        jobs = await asyncio.to_thread(self._prepare_interrupted_sync)
        for (
            task_id,
            aweme_id,
            storage_backend,
            translate,
            language,
            temporary_only,
        ) in jobs:
            await self.enqueue_aweme(
                task_id=task_id,
                aweme_id=aweme_id,
                storage_backend=storage_backend,
                translate_subtitles=translate,
                language=language,
                temporary_only=temporary_only,
            )

    def _prepare_interrupted_sync(
        self,
    ) -> list[tuple[uuid.UUID, str, str, bool, str, bool]]:
        """把活动记录回退到可重入状态，并返回需要重新调度的媒体作业。"""
        now = get_datetime_utc()
        jobs: dict[uuid.UUID, tuple[uuid.UUID, str, str, bool, str, bool]] = {}
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
            task_requests: dict[uuid.UUID, dict[str, Any]] = {}

            def is_temporary_only(task_id: uuid.UUID) -> bool:
                if task_id not in task_requests:
                    task = session.get(CrawlTask, task_id)
                    try:
                        value = json.loads(task.request_json) if task else {}
                    except json.JSONDecodeError:
                        value = {}
                    task_requests[task_id] = value if isinstance(value, dict) else {}
                return bool(task_requests[task_id].get("subtitle_only"))

            for asset in assets:
                asset.status = MediaDownloadStatus.queued.value
                asset.progress = 0
                asset.error = None
                asset.updated_at = now
                session.add(asset)
                jobs[asset.id] = (
                    asset.task_id,
                    asset.aweme_id,
                    asset.storage_backend,
                    False,
                    "auto",
                    is_temporary_only(asset.task_id),
                )
            subtitles = session.exec(
                select(DouyinSubtitle).where(
                    col(DouyinSubtitle.status).in_(
                        [SubtitleStatus.pending.value, SubtitleStatus.running.value]
                    )
                )
            ).all()
            for subtitle in subtitles:
                subtitle.status = SubtitleStatus.pending.value
                subtitle.progress = 0
                subtitle.error = None
                subtitle.started_at = None
                subtitle.finished_at = None
                session.add(subtitle)
                subtitle_asset = session.get(DouyinMediaAsset, subtitle.asset_id)
                if subtitle_asset is not None:
                    jobs[subtitle_asset.id] = (
                        subtitle_asset.task_id,
                        subtitle_asset.aweme_id,
                        subtitle_asset.storage_backend,
                        True,
                        subtitle.language or "auto",
                        is_temporary_only(subtitle_asset.task_id),
                    )
            session.commit()
        return list(jobs.values())

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
        temporary_only: bool = False,
    ) -> DouyinMediaAsset | None:
        """把单个作品加入媒体处理队列并启动处理协程。

        若该资产已有协程在运行则直接复用，不重复启动。

        参数：
            task_id: 采集任务 ID。
            aweme_id: 抖音作品 ID。
            storage_backend: 目标存储后端，None 表示沿用已有配置或系统默认。
            translate_subtitles: 下载完成后是否转写字幕。
            language: 转写语言，auto 表示自动识别。
            headers: 下载媒体时附加的请求头（如 cookie）。
            allow_download: 是否允许实际下载（仅转写场景传 False）。
            force_download: 即使已有可用副本也强制重新下载。
            force_retranslate: 即使字幕已完成也强制重新转写。
            temporary_only: 仅为字幕转写准备临时文件，处理后不保留视频。

        返回：
            媒体资产记录；作品不存在时返回 None。
        """
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
                    temporary_only=temporary_only,
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
        """读取作品并创建/更新对应的媒体资产记录。

        新建时按目标后端初始化存储位置；已存在时按需更新存储目标、
        重置失败状态为排队并刷新源地址。若其他任务已经保存了同一作品的
        可用媒体副本，则复用其存储位置，后续由统一的 existing 检查完成资产更新，
        避免再次请求抖音视频地址。作品不存在时返回 None。
        """
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
            if asset.status != MediaDownloadStatus.downloaded.value:
                reusable = session.exec(
                    select(DouyinMediaAsset)
                    .where(
                        DouyinMediaAsset.aweme_id == aweme_id,
                        DouyinMediaAsset.status == MediaDownloadStatus.downloaded.value,
                        DouyinMediaAsset.id != asset.id,
                    )
                    .order_by(
                        col(DouyinMediaAsset.completed_at).desc().nulls_last(),
                        col(DouyinMediaAsset.updated_at).desc(),
                        col(DouyinMediaAsset.id).asc(),
                    )
                ).first()
                if reusable is not None:
                    # 资产记录仍归当前任务所有，但媒体文件/对象可以跨任务复用。
                    # _download 会再次校验实际存储是否存在；副本失效时才回退到网络下载。
                    asset.storage_backend = reusable.storage_backend
                    asset.storage_bucket = reusable.storage_bucket
                    asset.object_key = reusable.object_key
                    asset.local_path = reusable.local_path
                    asset.file_size = reusable.file_size
                    asset.sha256 = reusable.sha256
                    asset.mime_type = reusable.mime_type
                    asset.migration_status = reusable.migration_status
                    asset.migration_progress = reusable.migration_progress
                    asset.migration_attempt_count = reusable.migration_attempt_count
                    asset.migration_error = reusable.migration_error
                    asset.migration_started_at = reusable.migration_started_at
                    asset.migration_finished_at = reusable.migration_finished_at
                    asset.status = MediaDownloadStatus.queued.value
                    asset.progress = 0
                    asset.error = None
                    asset.completed_at = None
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
        temporary_only: bool = False,
    ) -> int:
        """把任务下全部作品加入媒体处理队列。

        参数：
            task_id: 采集任务 ID。
            storage_backend: 目标存储后端。
            translate_subtitles: 下载完成后是否转写字幕。
            language: 转写语言。
            headers: 下载媒体时附加的请求头。
            force_retranslate: 是否强制重新转写。
            temporary_only: 仅为字幕转写准备临时文件，处理后不保留视频。

        返回：
            入队的作品数量。
        """
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
                temporary_only=temporary_only,
            )
        return len(aweme_ids)

    @staticmethod
    def _task_aweme_ids_sync(task_id: uuid.UUID) -> list[str]:
        """查询任务下全部作品 ID。"""
        with Session(engine) as session:
            return list(
                session.exec(
                    select(DouyinAweme.aweme_id).where(DouyinAweme.task_id == task_id)
                ).all()
            )

    async def wait_for_task(self, task_id: uuid.UUID) -> None:
        """等待指定任务的所有媒体处理协程结束。"""
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
        """取消指定任务的所有媒体处理协程并等待退出。"""
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
        temporary_only: bool = False,
    ) -> int:
        """按筛选结果重试失败的下载与字幕转写。

        参数：
            task_id: 采集任务 ID。
            asset_ids: 限定重试的资产 ID 列表，为空表示任务内全部候选。
            retry_downloads: 是否重试未完成/失败的下载。
            retry_subtitles: 是否重试失败的字幕转写。
            force_retranslate: 是否强制重新转写（含已完成字幕）。
            translate_if_missing: 字幕记录缺失时是否补转写。
            language: 转写语言。
            temporary_only: 仅为字幕转写准备临时文件，处理后不保留视频。

        返回：
            实际重新入队的资产数量。
        """
        candidates = await asyncio.to_thread(
            self._retry_candidates_sync, task_id, asset_ids
        )
        queued = 0
        for asset, subtitle in candidates:
            download_needed = asset.status in {
                MediaDownloadStatus.queued.value,
                MediaDownloadStatus.downloading.value,
                MediaDownloadStatus.failed.value,
                MediaDownloadStatus.temporary.value,
            }
            subtitle_needed = bool(
                retry_subtitles
                and (
                    (subtitle and subtitle.status == SubtitleStatus.failed.value)
                    or (subtitle is None and translate_if_missing)
                )
            )
            should_translate = subtitle_needed or force_retranslate
            can_retry_temporary = temporary_only and asset.status == (
                MediaDownloadStatus.temporary.value
            )
            if download_needed and not retry_downloads and not can_retry_temporary:
                continue
            if not download_needed and not should_translate:
                continue
            if await self.enqueue_aweme(
                task_id=task_id,
                aweme_id=asset.aweme_id,
                storage_backend=asset.storage_backend,
                translate_subtitles=should_translate,
                language=language,
                force_download=download_needed and retry_downloads,
                force_retranslate=force_retranslate or subtitle_needed,
                temporary_only=temporary_only,
                allow_download=retry_downloads or can_retry_temporary,
            ):
                queued += 1
        return queued

    @staticmethod
    def _retry_candidates_sync(
        task_id: uuid.UUID, asset_ids: list[uuid.UUID]
    ) -> list[tuple[DouyinMediaAsset, DouyinSubtitle | None]]:
        """查询任务内（可选指定）的资产及其字幕记录，脱离会话后返回。"""
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
        temporary_only: bool,
    ) -> None:
        """执行单个资产的媒体处理流程：按需下载，再按需转写字幕。

        取消时先把进行中的状态落库为失败再向上抛出；结束时清理句柄登记。
        """
        temporary_dir: Path | None = None
        try:
            asset = await asyncio.to_thread(self._get_asset_sync, asset_id)
            if asset is None:
                return
            if temporary_only:
                subtitle = await asyncio.to_thread(
                    self._get_subtitle_for_asset_sync, asset_id
                )
                if (
                    translate_subtitles
                    and subtitle
                    and subtitle.status == SubtitleStatus.completed.value
                    and not force_retranslate
                ):
                    return

                existing = await media_storage.existing(asset)
                if existing is not None:
                    if translate_subtitles:
                        await self._transcribe(asset, language=language)
                    return
                if not allow_download:
                    return
                temporary_path, temporary_dir, result = await self._download_temporary(
                    asset, headers=headers
                )
                asset = await asyncio.to_thread(self._get_asset_sync, asset_id)
                if asset is None or asset.status != MediaDownloadStatus.temporary.value:
                    return
                if translate_subtitles:
                    await self._transcribe(
                        asset,
                        language=language,
                        media_path=temporary_path,
                        mime_type=str(result["mime_type"]),
                    )
                return
            if force_download or asset.status != MediaDownloadStatus.downloaded.value:
                if not allow_download:
                    return
                await self._download(asset, headers=headers, force=force_download)
                asset = await asyncio.to_thread(self._get_asset_sync, asset_id)
                if (
                    asset is None
                    or asset.status != MediaDownloadStatus.downloaded.value
                ):
                    return
            if translate_subtitles:
                subtitle = await asyncio.to_thread(
                    self._get_subtitle_for_asset_sync, asset_id
                )
                if (
                    force_retranslate
                    or not subtitle
                    or subtitle.status != SubtitleStatus.completed.value
                ):
                    await self._transcribe(asset, language=language)
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.to_thread(self._cancel_asset_sync, asset_id))
            raise
        finally:
            if temporary_dir is not None:
                await asyncio.to_thread(shutil.rmtree, temporary_dir, True)
            async with self._lock:
                self._handles.pop(asset_id, None)

    async def _download_temporary(
        self,
        asset: DouyinMediaAsset,
        *,
        headers: dict[str, str],
    ) -> tuple[Path, Path, dict[str, Any]]:
        """为仅字幕任务下载临时媒体，成功后只保留到当前协程结束。"""
        async with self._download_limiter.slot(asset.task_id):
            if not asset.source_url:
                await asyncio.to_thread(
                    self._fail_download_sync, asset.id, "作品没有可下载的视频地址"
                )
                raise RuntimeError("作品没有可下载的视频地址")

            temporary_dir = (
                settings.MEDIA_OUTPUT_DIR.resolve() / ".tmp" / f"subtitle-{asset.id}"
            )
            temporary_dir.mkdir(parents=True, exist_ok=True)
            staged_path = temporary_dir / "source.mp4"
            partial_path = temporary_dir / "source.mp4.part"
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
                        await asyncio.to_thread(
                            self._complete_temporary_download_sync,
                            asset.id,
                            result["mime_type"],
                        )
                        return staged_path, temporary_dir, result
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
                raise last_error
            except BaseException:
                partial_path.unlink(missing_ok=True)
                if staged_path.exists():
                    staged_path.unlink(missing_ok=True)
                await asyncio.to_thread(shutil.rmtree, temporary_dir, True)
                raise

    async def _download(
        self,
        asset: DouyinMediaAsset,
        *,
        headers: dict[str, str],
        force: bool,
    ) -> None:
        """下载媒体文件并写入目标存储后端，带并发限制与指数退避重试。

        已存在可用副本且未强制下载时直接复用（本地副本缺 sha256 时补算）。
        下载先写入暂存目录，成功后再原子入库；最终失败会清理暂存并落库错误。

        参数：
            asset: 媒体资产记录。
            headers: 下载请求附加的请求头。
            force: 为 True 时忽略已有副本强制重新下载。
        """
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
        """带整体超时控制执行单次下载尝试，超时后抛出中文 TimeoutError。"""
        try:
            return await asyncio.wait_for(
                self._download_once_within_deadline(
                    asset_id,
                    source_url,
                    partial_path,
                    final_path,
                    headers,
                ),
                timeout=settings.MEDIA_DOWNLOAD_TIMEOUT,
            )
        except asyncio.TimeoutError as exc:
            timeout_seconds = f"{settings.MEDIA_DOWNLOAD_TIMEOUT:g}"
            raise TimeoutError(
                f"媒体下载单次尝试超过 {timeout_seconds} 秒，已主动终止"
            ) from exc

    async def _download_once_within_deadline(
        self,
        asset_id: uuid.UUID,
        source_url: str,
        partial_path: Path,
        final_path: Path,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """流式下载到临时 .part 文件，边下边算 SHA-256 并周期性落库进度。

        校验 Content-Length 与实际大小不超过配置上限、Content-Type 必须是媒体
        类型；下载完成后把 .part 原子重命名为最终暂存文件。

        返回：
            包含 file_size、sha256、mime_type 的字典。

        异常：
            ValueError: 超过大小限制、内容不是媒体或下载结果为空。
        """
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
                content_length = (
                    int(content_length_value) if content_length_value.isdigit() else 0
                )
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

    async def _transcribe(
        self,
        asset: DouyinMediaAsset,
        *,
        language: str,
        media_path: Path | None = None,
        mime_type: str | None = None,
    ) -> None:
        """转写单个资产的字幕：物化媒体、抽取音频、调用远程字幕 API。

        参数：
            asset: 已下载完成的媒体资产。
            language: 转写语言，auto 表示自动识别。

        进度与结果全程落库；任何异常都会把字幕标记为失败并写入脱敏错误。
        """
        async with self._subtitle_limiter.slot(asset.task_id):
            subtitle_id = await asyncio.to_thread(
                self._begin_subtitle_sync, asset, language
            )
            try:
                if media_path is not None:
                    media_context = _existing_media_path(media_path)
                else:
                    media_context = media_storage.materialize(asset)
                async with media_context as resolved_media_path:
                    await asyncio.to_thread(
                        self._set_subtitle_progress_sync, subtitle_id, 20
                    )
                    async with self._transcription_upload_file(
                        resolved_media_path,
                        mime_type=mime_type or asset.mime_type,
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
        """准备用于上传的紧凑音频文件；语音识别始终只在远程 API 完成。

        输入本身已是音频时直接复用原文件；否则用 FFmpeg 抽取低码率 mp3 到
        临时目录，上下文退出时自动清理。

        异常：
            RuntimeError: FFmpeg 未安装、无法抽取音频或抽取结果为空。
            TimeoutError: 音频抽取超时。
        """
        audio_suffixes = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"}
        if (
            mime_type.startswith("audio/")
            or media_path.suffix.lower() in audio_suffixes
        ):
            yield media_path, mime_type or "application/octet-stream"
            return

        with tempfile.TemporaryDirectory(prefix="douyin-transcription-") as temp_dir:
            audio_path = Path(temp_dir) / "audio.mp3"
            try:
                await extract_transcription_audio(
                    binary=settings.FFMPEG_BINARY,
                    input_path=media_path,
                    output_path=audio_path,
                    bitrate_kbps=settings.WHISPER_AUDIO_BITRATE_KBPS,
                    timeout=settings.WHISPER_AUDIO_PREPROCESS_TIMEOUT,
                )
            except FFmpegNotFoundError as exc:
                raise RuntimeError(
                    "服务未安装 FFmpeg，无法为远程字幕 API 准备音频"
                ) from exc.__cause__
            except FFmpegTimeoutError as exc:
                raise TimeoutError("为远程字幕 API 提取音频超时") from exc.__cause__
            except FFmpegOutputUnavailableError:
                raise RuntimeError("无法从视频提取可转写音频") from None
            except FFmpegEmptyOutputError:
                raise RuntimeError("从视频提取的音频为空") from None
            yield audio_path, "audio/mpeg"

    async def _transcribe_api(
        self, media_path: Path, *, mime_type: str, language: str
    ) -> dict[str, Any]:
        """调用 OpenAI 兼容的远程字幕 API 转写音频/视频文件。

        参数：
            media_path: 待上传的本地媒体文件路径。
            mime_type: 上传时声明的 Content-Type。
            language: 转写语言；空或 auto 时交由服务端自动识别。

        返回：
            解析后的转写结果字典。

        异常：
            FileNotFoundError: 本地媒体文件不存在。
            RuntimeError: API 返回非 2xx 状态。
            ValueError: API 返回内容格式无效。
        """
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
            files = {"file": (media_path.name, media_file, mime_type or "video/mp4")}
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
        """校验 WHISPER_API_BASE_URL 并拼接转写接口地址。

        强制 HTTPS（仅允许本机回环地址使用 HTTP），并拒绝 URL 中的凭据、
        查询参数与片段，防止 API 密钥经由不安全通道泄露。
        """
        normalized = base_url.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("WHISPER_API_BASE_URL 必须是有效的 HTTP(S) 地址")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("WHISPER_API_BASE_URL 不能包含凭据、查询参数或片段")
        hostname = parsed.hostname.rstrip(".").lower()
        try:
            private_transport = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            private_transport = hostname in {
                "localhost",
                "host.docker.internal",
                "gateway.docker.internal",
            }
        if parsed.scheme == "http" and not private_transport:
            raise ValueError("远程字幕 API 必须使用 HTTPS")
        return (
            f"{normalized}/audio/transcriptions"
            if normalized.endswith("/v1")
            else f"{normalized}/v1/audio/transcriptions"
        )

    @staticmethod
    def _parse_transcription(payload: Any) -> dict[str, Any]:
        """解析并校验 verbose_json 格式的转写响应，时间戳与时长做容错归一化。"""
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
        """计算文件的 SHA-256 摘要（分块读取）。"""
        digest = hashlib.sha256()
        with path.open("rb") as file:
            while chunk := file.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _get_asset_sync(asset_id: uuid.UUID) -> DouyinMediaAsset | None:
        """按 ID 读取资产并脱离会话返回。"""
        with Session(engine) as session:
            asset = session.get(DouyinMediaAsset, asset_id)
            if asset:
                session.expunge(asset)
            return asset

    @staticmethod
    def _get_subtitle_for_asset_sync(asset_id: uuid.UUID) -> DouyinSubtitle | None:
        """读取资产对应的字幕记录并脱离会话返回。"""
        with Session(engine) as session:
            subtitle = session.exec(
                select(DouyinSubtitle).where(DouyinSubtitle.asset_id == asset_id)
            ).first()
            if subtitle:
                session.expunge(subtitle)
            return subtitle

    @staticmethod
    def _begin_download_sync(asset_id: uuid.UUID) -> None:
        """下载开始：状态置为 downloading、清零进度并累加尝试次数。"""
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
        """更新下载进度（仅下载中的资产生效）。"""
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
        """下载完成：写入存储位置、大小、摘要等信息并置为 downloaded。"""
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
    def _complete_temporary_download_sync(
        asset_id: uuid.UUID,
        mime_type: str,
    ) -> None:
        """记录临时下载完成，但不写入正式存储位置或文件元数据。"""
        with Session(engine) as session:
            asset = session.get(DouyinMediaAsset, asset_id)
            if not asset:
                return
            now = get_datetime_utc()
            asset.status = MediaDownloadStatus.temporary.value
            asset.progress = 100
            asset.local_path = ""
            asset.storage_bucket = ""
            asset.object_key = ""
            asset.file_size = 0
            asset.sha256 = ""
            asset.mime_type = mime_type
            asset.error = None
            asset.updated_at = now
            asset.completed_at = now
            asset.migration_status = MediaMigrationStatus.idle.value
            asset.migration_progress = 0
            asset.migration_error = None
            asset.migration_started_at = None
            asset.migration_finished_at = None
            session.add(asset)
            session.commit()

    @staticmethod
    def _fail_download_sync(asset_id: uuid.UUID, error: str) -> None:
        """下载失败：置为 failed 并写入错误信息。"""
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
        """协程被取消时，把进行中的下载/字幕状态落库为失败。"""
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
        """字幕转写开始：创建（或复用）字幕记录并置为 running，返回字幕 ID。"""
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
        """更新转写进度（仅转写中的记录生效，进度封顶 99）。"""
        with Session(engine) as session:
            subtitle = session.get(DouyinSubtitle, subtitle_id)
            if subtitle and subtitle.status == SubtitleStatus.running.value:
                subtitle.progress = max(0, min(progress, 99))
                session.add(subtitle)
                session.commit()

    @staticmethod
    def _complete_subtitle_sync(subtitle_id: uuid.UUID, values: dict[str, Any]) -> None:
        """转写完成：写入文本、分段、语言、时长等结果并置为 completed。"""
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
        """转写失败：置为 failed 并写入错误信息。"""
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
        """取消并等待全部媒体处理协程退出（服务关闭时调用）。"""
        async with self._lock:
            tasks = [handle.task for handle in self._handles.values()]
            for task in tasks:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def list_media_sync(
    task_id: uuid.UUID, skip: int, limit: int
) -> DouyinMediaAssetsPublic:
    """分页查询任务下的媒体资产（左连接字幕），按处理活跃度优先排序。

    参数：
        task_id: 采集任务 ID。
        skip: 分页偏移量。
        limit: 每页条数。

    返回：
        资产对外视图列表与总数。
    """
    with Session(engine) as session:
        count = session.exec(
            select(func.count())
            .select_from(DouyinMediaAsset)
            .where(DouyinMediaAsset.task_id == task_id)
        ).one()
        # 活跃度优先：下载中 > 转写中 > 排队下载 > 等待转写 > 下载失败 > 转写失败 > 其他
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
    """统计任务下媒体下载、字幕转写与迁移各状态的数量。

    参数：
        task_id: 采集任务 ID。

    返回：
        各状态计数汇总。
    """
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
        temporary=statuses.count(MediaDownloadStatus.temporary.value),
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


# 全局共享的媒体管道管理器实例
media_manager = MediaPipelineManager()
