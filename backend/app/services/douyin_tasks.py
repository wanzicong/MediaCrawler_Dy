import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.douyin.crawler import DouyinCrawlerService
from app.douyin.storage import DouyinStorage
from app.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskPhase,
    CrawlTaskResumeRequest,
    CrawlTaskStatus,
    DouyinBrowserMode,
    DouyinLoginType,
    DouyinMediaProcessRequest,
    MediaProcessingMode,
    MediaStorageBackend,
    get_datetime_utc,
)
from app.services.media_migration import media_migration_manager
from app.services.media_pipeline import media_manager

logger = logging.getLogger(__name__)


class TaskResumeError(RuntimeError):
    pass


def resolve_browser_mode(
    request: CrawlTaskCreate, default_mode: str
) -> CrawlTaskCreate:
    if request.browser_mode is not None:
        return request
    return request.model_copy(
        update={"browser_mode": DouyinBrowserMode(default_mode)}
    )


def resolve_media_storage(
    request: CrawlTaskCreate, default_backend: str
) -> CrawlTaskCreate:
    if request.media_storage is not None:
        return request
    return request.model_copy(
        update={"media_storage": MediaStorageBackend(default_backend)}
    )


@dataclass
class TaskHandle:
    task: asyncio.Task[None]
    request: CrawlTaskCreate


class DouyinTaskManager:
    """Run task-scoped crawlers while serializing only CDP-bound work."""

    def __init__(self) -> None:
        self._handles: dict[uuid.UUID, TaskHandle] = {}
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(settings.DOUYIN_MAX_ACTIVE_TASKS)

    async def startup(self) -> None:
        await DouyinStorage.mark_active_tasks_interrupted()
        await media_manager.startup()
        await media_migration_manager.startup()

    async def create(
        self, *, owner_id: uuid.UUID, request: CrawlTaskCreate
    ) -> CrawlTask:
        self._validate_request_limits(request)
        request = resolve_browser_mode(request, settings.DOUYIN_BROWSER_MODE)
        request = resolve_media_storage(request, settings.MEDIA_STORAGE_BACKEND)
        db_task = await DouyinStorage.create_task(owner_id, request)
        async with self._lock:
            runner = asyncio.create_task(
                self._run(db_task.id, request), name=f"douyin-{db_task.id}"
            )
            self._handles[db_task.id] = TaskHandle(task=runner, request=request)
        return db_task

    @staticmethod
    def _validate_request_limits(request: CrawlTaskCreate) -> None:
        if request.max_awemes > settings.DOUYIN_MAX_AWEMES_PER_TASK:
            raise ValueError("max_awemes 超出服务端限制")
        if request.max_comments_per_aweme > settings.DOUYIN_MAX_COMMENTS_PER_AWEME:
            raise ValueError("max_comments_per_aweme 超出服务端限制")

    async def resume(
        self, *, task_id: uuid.UUID, options: CrawlTaskResumeRequest
    ) -> CrawlTask:
        async with self._lock:
            active = self._handles.get(task_id)
            if active and not active.task.done():
                raise TaskResumeError("任务已在当前进程运行")
            task = await DouyinStorage.get_task(task_id)
            if task is None:
                raise TaskResumeError("任务不存在")
            if task.status in {
                CrawlTaskStatus.queued.value,
                CrawlTaskStatus.waiting_login.value,
                CrawlTaskStatus.running.value,
                CrawlTaskStatus.processing_media.value,
                CrawlTaskStatus.cancelling.value,
            }:
                raise TaskResumeError("活动任务不能重复恢复")
            request = self._rebuild_request(task, options)
            self._validate_request_limits(request)
            checkpoint = await DouyinStorage(task_id).load_checkpoint()
            phase = CrawlTaskPhase(str(checkpoint["phase"]))
            crawl_default = bool(
                task.status
                in {
                    CrawlTaskStatus.failed.value,
                    CrawlTaskStatus.cancelled.value,
                    CrawlTaskStatus.interrupted.value,
                }
                and phase == CrawlTaskPhase.crawl
            )
            crawl_enabled = (
                crawl_default
                if options.resume_crawl is None
                else options.resume_crawl
            )
            media_enabled = (
                request.download_media
                if options.resume_media is None
                else options.resume_media
            )
            if crawl_enabled and not crawl_default:
                raise TaskResumeError("该任务的爬取阶段已经完成，不能重复爬取")
            if media_enabled and not request.download_media:
                raise TaskResumeError("该任务没有启用视频下载或字幕处理")
            if not crawl_enabled and not media_enabled:
                raise TaskResumeError("没有可恢复的任务阶段")
            prior_status = task.status
            prior_error = task.error
            resumed_task = await DouyinStorage(task_id).mark_resumed(
                CrawlTaskStatus.queued
            )
            runner = asyncio.create_task(
                self._run(
                    task_id,
                    request,
                    resumed=True,
                    crawl_enabled=crawl_enabled,
                    media_enabled=media_enabled,
                    checkpoint_phase=phase,
                    prior_status=prior_status,
                    prior_error=prior_error,
                ),
                name=f"douyin-resume-{task_id}",
            )
            self._handles[task_id] = TaskHandle(task=runner, request=request)
            return resumed_task

    async def process_media(
        self, *, task_id: uuid.UUID, options: DouyinMediaProcessRequest
    ) -> CrawlTask:
        async with self._lock:
            active = self._handles.get(task_id)
            if active and not active.task.done():
                raise TaskResumeError("任务已在当前进程运行")
            task = await DouyinStorage.get_task(task_id)
            if task is None:
                raise TaskResumeError("任务不存在")
            if task.status in {
                CrawlTaskStatus.queued.value,
                CrawlTaskStatus.waiting_login.value,
                CrawlTaskStatus.running.value,
                CrawlTaskStatus.processing_media.value,
                CrawlTaskStatus.cancelling.value,
            }:
                raise TaskResumeError("活动任务不能启动新的媒体处理")
            checkpoint = await DouyinStorage(task_id).load_checkpoint()
            if checkpoint["phase"] == CrawlTaskPhase.crawl.value:
                raise TaskResumeError("爬取阶段尚未完成，请先继续爬取任务")
            if task.aweme_count <= 0:
                raise TaskResumeError("任务没有可处理的作品")
            request = self._build_media_request(task, options)
            prepared = await DouyinStorage(task_id).prepare_media_processing(request)
            runner = asyncio.create_task(
                self._run(
                    task_id,
                    request,
                    resumed=True,
                    crawl_enabled=False,
                    media_enabled=True,
                    checkpoint_phase=CrawlTaskPhase.media,
                    force_retranslate=options.force_retranslate,
                ),
                name=f"douyin-media-process-{task_id}",
            )
            self._handles[task_id] = TaskHandle(task=runner, request=request)
            return prepared

    @staticmethod
    def _rebuild_request(
        task: CrawlTask, options: CrawlTaskResumeRequest
    ) -> CrawlTaskCreate:
        try:
            payload = json.loads(task.request_json)
        except json.JSONDecodeError as exc:
            raise TaskResumeError("任务配置损坏，无法恢复") from exc
        if not isinstance(payload, dict):
            raise TaskResumeError("任务配置损坏，无法恢复")
        payload.pop("cookies", None)
        if options.cookies and options.cookies.get_secret_value().strip():
            payload["login_type"] = DouyinLoginType.cookie.value
            payload["cookies"] = options.cookies.get_secret_value().strip()
        elif payload.get("login_type") == DouyinLoginType.cookie.value:
            # Cookie is intentionally not persisted. Reuse the CDP profile when
            # it is still logged in; otherwise the crawler will display a QR code.
            payload["login_type"] = DouyinLoginType.qrcode.value
        try:
            return CrawlTaskCreate.model_validate(payload)
        except ValueError as exc:
            raise TaskResumeError("任务配置不再有效，无法恢复") from exc

    @staticmethod
    def _build_media_request(
        task: CrawlTask, options: DouyinMediaProcessRequest
    ) -> CrawlTaskCreate:
        try:
            payload = json.loads(task.request_json)
        except json.JSONDecodeError as exc:
            raise TaskResumeError("任务配置损坏，无法处理媒体") from exc
        if not isinstance(payload, dict):
            raise TaskResumeError("任务配置损坏，无法处理媒体")
        payload.pop("cookies", None)
        payload.update(
            {
                "download_media": True,
                "translate_subtitles": options.translate_subtitles,
                "media_processing_mode": MediaProcessingMode.batch.value,
                "transcription_language": options.transcription_language,
            }
        )
        if options.media_storage is not None:
            payload["media_storage"] = options.media_storage.value
        elif not payload.get("media_storage"):
            payload["media_storage"] = settings.MEDIA_STORAGE_BACKEND
        if options.cookies and options.cookies.get_secret_value().strip():
            payload["login_type"] = DouyinLoginType.cookie.value
            payload["cookies"] = options.cookies.get_secret_value().strip()
        elif payload.get("login_type") == DouyinLoginType.cookie.value:
            payload["login_type"] = DouyinLoginType.qrcode.value
        try:
            return CrawlTaskCreate.model_validate(payload)
        except ValueError as exc:
            raise TaskResumeError("任务配置不再有效，无法处理媒体") from exc

    async def _run(
        self,
        task_id: uuid.UUID,
        request: CrawlTaskCreate,
        *,
        resumed: bool = False,
        crawl_enabled: bool = True,
        media_enabled: bool = True,
        checkpoint_phase: CrawlTaskPhase = CrawlTaskPhase.crawl,
        prior_status: str | None = None,
        prior_error: str | None = None,
        force_retranslate: bool = False,
    ) -> None:
        storage = DouyinStorage(task_id)
        try:
            await self._execute(
                task_id,
                request,
                storage=storage,
                resumed=resumed,
                crawl_enabled=crawl_enabled,
                media_enabled=media_enabled,
                checkpoint_phase=checkpoint_phase,
                prior_status=prior_status,
                prior_error=prior_error,
                force_retranslate=force_retranslate,
            )
        except asyncio.CancelledError:
            current = await asyncio.shield(DouyinStorage.get_task(task_id))
            if current and current.status == CrawlTaskStatus.succeeded.value:
                raise
            await media_manager.cancel_task(task_id)
            await storage.update_task(
                status=CrawlTaskStatus.cancelled,
                qrcode_path=None,
                finished_at=get_datetime_utc(),
            )
            raise
        except Exception as exc:
            logger.exception("Douyin task %s failed", task_id)
            await storage.update_task(
                status=CrawlTaskStatus.failed,
                error=f"{type(exc).__name__}: {exc}",
                qrcode_path=None,
                finished_at=get_datetime_utc(),
            )
        finally:
            async with self._lock:
                self._handles.pop(task_id, None)

    async def _execute(
        self,
        task_id: uuid.UUID,
        request: CrawlTaskCreate,
        *,
        storage: DouyinStorage,
        resumed: bool,
        crawl_enabled: bool,
        media_enabled: bool,
        checkpoint_phase: CrawlTaskPhase,
        prior_status: str | None,
        prior_error: str | None,
        force_retranslate: bool,
    ) -> None:
        if not crawl_enabled:
            values: dict[str, object] = {
                "status": CrawlTaskStatus.processing_media,
                "error": None,
            }
            if not resumed:
                values["started_at"] = get_datetime_utc()
            await storage.update_task(**values)

        async def on_browser_acquired() -> None:
            values: dict[str, object] = {
                "status": CrawlTaskStatus.running,
                "error": None,
            }
            if not resumed:
                values["started_at"] = get_datetime_utc()
            await storage.update_task(**values)

        async def on_qrcode(path: Path | None) -> None:
            if path:
                await storage.update_task(
                    status=CrawlTaskStatus.waiting_login,
                    qrcode_path=str(path.resolve()),
                )
            else:
                await storage.update_task(
                    status=CrawlTaskStatus.running, qrcode_path=None
                )

        crawler = DouyinCrawlerService(
            task_id=task_id,
            request=request,
            settings=settings,
            storage=storage,
            on_qrcode=on_qrcode,
            browser_semaphore=self._semaphore,
            on_browser_acquired=on_browser_acquired,
        )
        await crawler.run(
            crawl_enabled=crawl_enabled,
            media_enabled=media_enabled,
            force_retranslate=force_retranslate,
        )
        if crawl_enabled and request.download_media and not media_enabled:
            await storage.update_task(
                status=CrawlTaskStatus.interrupted,
                error="爬取已完成，媒体处理尚未恢复",
                qrcode_path=None,
                finished_at=get_datetime_utc(),
            )
        elif not crawl_enabled and checkpoint_phase == CrawlTaskPhase.crawl:
            await storage.update_task(
                status=prior_status or CrawlTaskStatus.interrupted,
                error=prior_error,
                qrcode_path=None,
                finished_at=get_datetime_utc(),
            )
        else:
            await storage.complete_task(request.crawl_type.value)

    async def cancel(self, task_id: uuid.UUID) -> bool:
        async with self._lock:
            handle = self._handles.get(task_id)
            if not handle or handle.task.done():
                return False
            await DouyinStorage(task_id).update_task(
                status=CrawlTaskStatus.cancelling
            )
            handle.task.cancel()
            task = handle.task
        try:
            await task
        except asyncio.CancelledError:
            pass
        return True

    async def shutdown(self) -> None:
        async with self._lock:
            tasks = [handle.task for handle in self._handles.values()]
            for task in tasks:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await media_manager.shutdown()
        await media_migration_manager.shutdown()


task_manager = DouyinTaskManager()
