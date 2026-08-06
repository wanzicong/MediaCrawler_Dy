import asyncio
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
    CrawlTaskStatus,
    DouyinBrowserMode,
    get_datetime_utc,
)
from app.services.media_pipeline import media_manager

logger = logging.getLogger(__name__)


def resolve_browser_mode(
    request: CrawlTaskCreate, default_mode: str
) -> CrawlTaskCreate:
    if request.browser_mode is not None:
        return request
    return request.model_copy(
        update={"browser_mode": DouyinBrowserMode(default_mode)}
    )


@dataclass
class TaskHandle:
    task: asyncio.Task[None]
    request: CrawlTaskCreate


class DouyinTaskManager:
    """Run task-scoped crawlers while serializing access to one CDP profile."""

    def __init__(self) -> None:
        self._handles: dict[uuid.UUID, TaskHandle] = {}
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(settings.DOUYIN_MAX_ACTIVE_TASKS)

    async def startup(self) -> None:
        await DouyinStorage.mark_active_tasks_interrupted()
        await media_manager.startup()

    async def create(
        self, *, owner_id: uuid.UUID, request: CrawlTaskCreate
    ) -> CrawlTask:
        if request.max_awemes > settings.DOUYIN_MAX_AWEMES_PER_TASK:
            raise ValueError("max_awemes 超出服务端限制")
        if request.max_comments_per_aweme > settings.DOUYIN_MAX_COMMENTS_PER_AWEME:
            raise ValueError("max_comments_per_aweme 超出服务端限制")
        request = resolve_browser_mode(request, settings.DOUYIN_BROWSER_MODE)
        db_task = await DouyinStorage.create_task(owner_id, request)
        async with self._lock:
            runner = asyncio.create_task(
                self._run(db_task.id, request), name=f"douyin-{db_task.id}"
            )
            self._handles[db_task.id] = TaskHandle(task=runner, request=request)
        return db_task

    async def _run(self, task_id: uuid.UUID, request: CrawlTaskCreate) -> None:
        storage = DouyinStorage(task_id)
        try:
            async with self._semaphore:
                await storage.update_task(
                    status=CrawlTaskStatus.running,
                    started_at=get_datetime_utc(),
                    error=None,
                )

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
                )
                await crawler.run()
                await storage.update_task(
                    status=CrawlTaskStatus.succeeded,
                    qrcode_path=None,
                    finished_at=get_datetime_utc(),
                )
        except asyncio.CancelledError:
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


task_manager = DouyinTaskManager()
