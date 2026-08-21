"""抖音爬取任务管理器：任务创建、恢复、取消、多账号分片调度与进程内运行态跟踪。"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from crawler.bootstrap.settings import settings
from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.accounts.models import DouyinAccount, DouyinBrowserMode
from crawler.business.douyin.accounts.service import (
    AccountConfigurationError,
    account_login_manager,
    release_account,
    reserve_accounts,
    reset_stale_account_leases,
    select_task_accounts,
)
from crawler.business.douyin.media.migration import media_migration_manager
from crawler.business.douyin.media.models import (
    DouyinMediaProcessRequest,
    MediaProcessingMode,
    MediaStorageBackend,
)
from crawler.business.douyin.media.pipeline import media_manager
from crawler.business.douyin.tasks.crawler import DouyinCrawlerService
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskPhase,
    CrawlTaskResumeRequest,
    CrawlTaskShard,
    CrawlTaskShardStatus,
    CrawlTaskStatus,
    DouyinCrawlType,
    DouyinLoginType,
)
from crawler.business.douyin.tasks.persistence import DouyinStorage

logger = logging.getLogger(__name__)


class TaskResumeError(RuntimeError):
    """任务恢复或独立媒体处理请求不合法（状态不允许、配置损坏等）时抛出的异常。"""


def resolve_browser_mode(
    request: CrawlTaskCreate, default_mode: str
) -> CrawlTaskCreate:
    """为请求补充浏览器模式默认值；已显式指定或选择了托管账号时保持原样。

    参数：request 任务请求；default_mode 服务端默认浏览器模式。
    返回：补齐后的请求副本。
    """
    if request.browser_mode is not None or (
        request.account_id or request.account_ids or request.account_pool_id
    ):
        return request
    return request.model_copy(update={"browser_mode": DouyinBrowserMode(default_mode)})


def resolve_media_storage(
    request: CrawlTaskCreate, default_backend: str
) -> CrawlTaskCreate:
    """为请求补充媒体存储后端默认值；已显式指定时保持原样。

    参数：request 任务请求；default_backend 服务端默认存储后端。
    返回：补齐后的请求副本。
    """
    if request.media_storage is not None:
        return request
    return request.model_copy(
        update={"media_storage": MediaStorageBackend(default_backend)}
    )


def normalize_new_task_targets(request: CrawlTaskCreate) -> CrawlTaskCreate:
    """规范新建采集任务：一词一任务，且不在采集执行器内串联媒体处理。

    该规则只用于新任务提交；历史任务恢复仍按原请求快照重建，确保早期已经
    创建的多关键词或组合媒体任务可以继续断点续跑。新任务的下载与字幕必须
    从独立媒体管理模块发起，并通过来源任务 ID 保留依赖关系。
    """
    updates: dict[str, object] = {
        "download_media": False,
        "translate_subtitles": False,
        "media_processing_mode": MediaProcessingMode.none,
    }
    if request.crawl_type == DouyinCrawlType.search:
        keywords = [value.strip() for value in request.keywords if value.strip()]
        if len(keywords) != 1:
            raise ValueError("关键词采集任务只能包含一个关键词")
        updates["keywords"] = keywords
    return request.model_copy(update=updates)


@dataclass
class TaskHandle:
    """进程内运行中的任务句柄（后台协程 + 请求快照）。"""

    task: asyncio.Task[None]  # 后台执行的 asyncio 任务
    request: CrawlTaskCreate  # 该次运行的请求快照


class DouyinTaskManager:
    """抖音任务管理器：驱动任务级爬虫运行，仅对绑定 CDP 浏览器的无账号任务做并发串行化。"""

    def __init__(self) -> None:
        """初始化运行态句柄表、互斥锁与全局并发信号量。"""
        self._handles: dict[uuid.UUID, TaskHandle] = {}
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(settings.DOUYIN_MAX_ACTIVE_TASKS)

    async def startup(self) -> None:
        """服务启动钩子：协调残留任务、重置租约、启动资源管理器并自动断点续跑。"""
        resumable_ids = await DouyinStorage.mark_active_tasks_interrupted()
        await asyncio.to_thread(reset_stale_account_leases)
        await media_manager.startup()
        await media_migration_manager.startup()
        for task_id in resumable_ids:
            try:
                await self.resume(task_id=task_id, options=CrawlTaskResumeRequest())
            except Exception:
                logger.exception("Douyin task %s automatic resume failed", task_id)

    async def create(
        self, *, owner_id: uuid.UUID, request: CrawlTaskCreate
    ) -> CrawlTask:
        """创建任务记录并启动后台执行。

        参数：owner_id 任务归属用户 ID；request 任务创建请求。
        返回：新创建的任务实体。
        异常：ValueError —— 请求超出服务端限制或账号解析失败。
        """
        request = normalize_new_task_targets(request)
        self._validate_request_limits(request)
        request = resolve_browser_mode(request, settings.DOUYIN_BROWSER_MODE)
        request = resolve_media_storage(request, settings.MEDIA_STORAGE_BACKEND)
        accounts = await self._resolve_submission_accounts(owner_id, request)
        db_task = await DouyinStorage.create_task(owner_id, request)
        async with self._lock:
            runner = asyncio.create_task(
                self._run(db_task.id, request, accounts=accounts),
                name=f"douyin-{db_task.id}",
            )
            self._handles[db_task.id] = TaskHandle(task=runner, request=request)
        return db_task

    @staticmethod
    def _validate_request_limits(request: CrawlTaskCreate) -> None:
        """校验请求不超出服务端配置的数量上限。"""
        if request.max_awemes > settings.DOUYIN_MAX_AWEMES_PER_TASK:
            raise ValueError("max_awemes 超出服务端限制")
        if request.max_comments_per_aweme > settings.DOUYIN_MAX_COMMENTS_PER_AWEME:
            raise ValueError("max_comments_per_aweme 超出服务端限制")

    async def resume(
        self, *, task_id: uuid.UUID, options: CrawlTaskResumeRequest
    ) -> CrawlTask:
        """恢复已终止的任务，按断点与请求决定恢复爬取阶段和/或媒体处理阶段。

        参数：task_id 任务 ID；options 恢复选项（可注入新 Cookie）。
        返回：被重置为排队状态的任务实体。
        异常：TaskResumeError —— 任务仍在运行、不存在、配置损坏或没有可恢复阶段。
        """
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
                crawl_default if options.resume_crawl is None else options.resume_crawl
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
            try:
                accounts = (
                    await self._resolve_submission_accounts(task.owner_id, request)
                    if crawl_enabled
                    else []
                )
            except ValueError as exc:
                raise TaskResumeError(str(exc)) from exc
            prior_status = task.status
            prior_error = task.error
            resumed_task = await DouyinStorage(task_id).mark_resumed(
                CrawlTaskStatus.queued,
                phase=(
                    CrawlTaskPhase.media
                    if media_enabled and not crawl_enabled
                    else None
                ),
                crawl_type=request.crawl_type.value,
                request=request,
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
                    accounts=accounts,
                ),
                name=f"douyin-resume-{task_id}",
            )
            self._handles[task_id] = TaskHandle(task=runner, request=request)
            return resumed_task

    async def restart(self, *, task_id: uuid.UUID) -> CrawlTask:
        """重新运行已失败/中断/已取消的任务：清空断点、从头开始采集。

        参数：task_id 任务 ID。
        返回：被重置为排队状态的任务实体。
        异常：TaskResumeError —— 任务仍在运行、不存在或不是可重启的终态。
        """
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
                raise TaskResumeError("活动任务不能重复重启")
            if task.status not in {
                CrawlTaskStatus.failed.value,
                CrawlTaskStatus.interrupted.value,
                CrawlTaskStatus.cancelled.value,
            }:
                raise TaskResumeError("只有失败、中断或已取消的任务才能重启")
            request = self._rebuild_request(task, CrawlTaskResumeRequest())
            self._validate_request_limits(request)
            restarted_task = await DouyinStorage(task_id).mark_resumed(
                CrawlTaskStatus.queued,
                phase=CrawlTaskPhase.crawl,
                crawl_type=request.crawl_type.value,
            )
            accounts = await self._resolve_submission_accounts(task.owner_id, request)
            runner = asyncio.create_task(
                self._run(task_id, request, accounts=accounts),
                name=f"douyin-restart-{task_id}",
            )
            self._handles[task_id] = TaskHandle(task=runner, request=request)
            return restarted_task

    async def process_media(
        self, *, task_id: uuid.UUID, options: DouyinMediaProcessRequest
    ) -> CrawlTask:
        """对爬取已完成的任务单独发起一轮媒体批处理。

        参数：task_id 任务 ID；options 媒体处理选项（字幕、存储后端、强制重转写等）。
        返回：被重置为排队状态的任务实体。
        异常：TaskResumeError —— 任务活动、爬取未完成或没有可处理的作品。
        """
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
        """由任务请求快照重建 CrawlTaskCreate。

        cookie 有意不落库：恢复时可注入新 Cookie，否则 cookie 登录回退为扫码登录。

        异常：TaskResumeError —— 快照损坏或已不满足当前校验规则。
        """
        try:
            payload = json.loads(task.request_json)
        except json.JSONDecodeError as exc:
            raise TaskResumeError("任务配置损坏，无法恢复") from exc
        if not isinstance(payload, dict):
            raise TaskResumeError("任务配置损坏，无法恢复")
        payload["track_id"] = str(task.track_id)
        payload.pop("cookies", None)
        if options.account_id is not None:
            # 恢复时允许替换已经失效的原账号。覆盖为单账号后必须清空旧的
            # 多账号/账号池选择，避免 CrawlTaskCreate 的三选一校验冲突。
            payload["account_id"] = str(options.account_id)
            payload["account_ids"] = []
            payload["account_pool_id"] = None
        if options.cookies and options.cookies.get_secret_value().strip():
            payload["login_type"] = DouyinLoginType.cookie.value
            payload["cookies"] = options.cookies.get_secret_value().strip()
        elif payload.get("login_type") == DouyinLoginType.cookie.value:
            # Cookie 有意不落库：CDP 浏览器配置仍登录时直接复用，
            # 否则爬虫会展示二维码走扫码登录。
            payload["login_type"] = DouyinLoginType.qrcode.value
        try:
            return CrawlTaskCreate.model_validate(payload)
        except ValueError as exc:
            raise TaskResumeError("任务配置不再有效，无法恢复") from exc

    @staticmethod
    def _build_media_request(
        task: CrawlTask, options: DouyinMediaProcessRequest
    ) -> CrawlTaskCreate:
        """由任务请求快照构造媒体批处理请求（强制开启下载、批处理模式）。

        异常：TaskResumeError —— 快照损坏或已不满足当前校验规则。
        """
        try:
            payload = json.loads(task.request_json)
        except json.JSONDecodeError as exc:
            raise TaskResumeError("任务配置损坏，无法处理媒体") from exc
        if not isinstance(payload, dict):
            raise TaskResumeError("任务配置损坏，无法处理媒体")
        payload["track_id"] = str(task.track_id)
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
        accounts: list[DouyinAccount] | None = None,
    ) -> None:
        """后台执行入口：解析账号、按需拆分多账号分片并驱动爬虫，统一落盘取消/失败状态。

        参数：task_id 任务 ID；request 请求快照；resumed 是否为恢复运行；
              crawl_enabled/media_enabled 各阶段是否启用；checkpoint_phase 断点阶段；
              prior_status/prior_error 恢复前的状态与错误（仅媒体恢复时回写）；
              force_retranslate 是否强制重转写字幕；accounts 预解析的账号列表。
        """
        storage = DouyinStorage(task_id)
        reserved_account: DouyinAccount | None = None
        account_success = False
        try:
            if accounts is None:
                if crawl_enabled:
                    task = await DouyinStorage.get_task(task_id)
                    if task is None:
                        raise TaskResumeError("任务不存在")
                    accounts = await self._wait_for_account_candidates(
                        task.owner_id, request
                    )
                else:
                    accounts = []
            assignments = self._split_assignments(request, accounts)
            if assignments and crawl_enabled:
                accounts = await self._reserve_runtime_accounts(
                    task_id=task_id,
                    request=request,
                    candidates=[account for account, _ in assignments],
                )
                assignments = self._split_assignments(request, accounts)
            if len(assignments) > 1 and crawl_enabled:
                await self._execute_multi_account(
                    task_id,
                    request,
                    storage=storage,
                    assignments=assignments,
                    media_enabled=media_enabled,
                    force_retranslate=force_retranslate,
                    accounts_pre_reserved=True,
                )
                return
            account = accounts[0] if accounts else None
            if account is not None and crawl_enabled:
                reserved_account = account
                request = request.model_copy(
                    update={
                        "request_interval_seconds": max(
                            request.request_interval_seconds,
                            reserved_account.min_request_interval_seconds,
                        )
                    }
                )
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
                account=reserved_account,
            )
            account_success = True
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
            if reserved_account is not None:
                await asyncio.to_thread(
                    release_account,
                    reserved_account.id,
                    success=account_success,
                    error=None if account_success else "任务执行失败",
                )
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
        account: DouyinAccount | None = None,
    ) -> None:
        """执行单账号（或无账号）爬虫并在结束后落盘最终任务状态。

        参数：task_id 任务 ID；request 请求快照；storage 持久化适配器；resumed 是否为恢复运行；
              crawl_enabled/media_enabled 各阶段是否启用；checkpoint_phase 断点阶段；
              prior_status/prior_error 恢复前的状态与错误；force_retranslate 是否强制重转写；
              account 已租用的托管账号（None 表示无账号任务，走全局并发信号量）。
        """
        if not crawl_enabled:
            values: dict[str, object] = {
                "status": CrawlTaskStatus.processing_media,
                "error": None,
            }
            if not resumed:
                values["started_at"] = get_datetime_utc()
            await storage.update_task(**values)

        async def on_browser_acquired() -> None:
            """获取浏览器并发许可后将任务标记为运行中。"""
            values: dict[str, object] = {
                "status": CrawlTaskStatus.running,
                "error": None,
            }
            if not resumed:
                values["started_at"] = get_datetime_utc()
            await storage.update_task(**values)

        async def on_qrcode(path: Path | None) -> None:
            """二维码生成时进入等待登录状态，登录成功后恢复运行状态。"""
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
            browser_semaphore=None if account is not None else self._semaphore,
            on_browser_acquired=on_browser_acquired,
            account=account,
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

    async def _resolve_accounts(
        self, owner_id: uuid.UUID, request: CrawlTaskCreate
    ) -> list[DouyinAccount]:
        """解析并校验任务指定的账号/账号列表/账号池（三选一）。

        返回：可用账号列表；未指定账号时返回空列表。
        异常：ValueError —— 账号配置不合法、池内无可用账号，或点赞/收藏任务选择了多个账号。
        """
        if not (request.account_id or request.account_ids or request.account_pool_id):
            return []
        try:
            accounts = await asyncio.to_thread(
                select_task_accounts,
                owner_id=owner_id,
                account_id=request.account_id,
                account_ids=request.account_ids,
                pool_id=request.account_pool_id,
                strategy=request.account_strategy,
            )
        except AccountConfigurationError as exc:
            raise ValueError(str(exc)) from exc
        if not accounts:
            raise ValueError("账号池当前没有可用账号")
        if (
            request.crawl_type
            in {
                DouyinCrawlType.liked,
                DouyinCrawlType.collected,
            }
            and len(accounts) > 1
        ):
            raise ValueError("点赞/收藏属于账号私有数据，每个任务只能选择一个账号")
        return accounts

    @staticmethod
    def _account_temporarily_unavailable(exc: BaseException) -> bool:
        """判断账号错误是否仅由当前租约/调度容量造成，可安全排队等待。"""
        message = str(exc)
        return any(
            marker in message
            for marker in (
                "当前不可调度",
                "当前没有可用账号",
                "已达到并发",
                "已达到并发/每日上限",
            )
        )

    async def _resolve_submission_accounts(
        self, owner_id: uuid.UUID, request: CrawlTaskCreate
    ) -> list[DouyinAccount] | None:
        """提交时校验账号配置；暂时繁忙返回 None，让后台任务进入等待队列。"""
        try:
            return await self._resolve_accounts(owner_id, request)
        except ValueError as exc:
            if self._account_temporarily_unavailable(exc):
                return None
            raise

    async def _wait_for_account_candidates(
        self, owner_id: uuid.UUID, request: CrawlTaskCreate
    ) -> list[DouyinAccount]:
        """等待指定账号或账号池出现调度容量；配置永久失效时立即失败。"""
        while True:
            try:
                return await self._resolve_accounts(owner_id, request)
            except ValueError as exc:
                if not self._account_temporarily_unavailable(exc):
                    raise
                await asyncio.sleep(2)

    async def _reserve_runtime_accounts(
        self,
        *,
        task_id: uuid.UUID,
        request: CrawlTaskCreate,
        candidates: list[DouyinAccount],
    ) -> list[DouyinAccount]:
        """原子租用运行时账号；若池候选被其他任务抢占，则刷新候选后重试一次。"""
        current_candidates = candidates
        while True:
            try:
                return await asyncio.to_thread(
                    reserve_accounts,
                    [account.id for account in current_candidates],
                )
            except AccountConfigurationError as first_error:
                if not self._account_temporarily_unavailable(first_error):
                    raise ValueError(str(first_error)) from first_error
                task = await DouyinStorage.get_task(task_id)
                if task is None:
                    raise TaskResumeError("任务不存在") from first_error
                await asyncio.sleep(2)
                current_candidates = await self._wait_for_account_candidates(
                    task.owner_id, request
                )

    @staticmethod
    def _split_assignments(
        request: CrawlTaskCreate, accounts: list[DouyinAccount]
    ) -> list[tuple[DouyinAccount, CrawlTaskCreate]]:
        """将爬取目标按账号轮询分片：目标数、账号数与 max_awemes 共同决定分片数。

        返回：(账号, 分片请求) 列表；分片请求关闭媒体处理（媒体阶段由任务级统一执行）。
        """
        if not accounts:
            return []
        target_field = {
            DouyinCrawlType.search: "keywords",
            DouyinCrawlType.detail: "video_ids",
            DouyinCrawlType.creator: "creator_ids",
            DouyinCrawlType.creator_from_aweme: "video_ids",
        }.get(request.crawl_type)
        if target_field is None:
            account = accounts[0]
            return [(account, request)]
        targets = [
            str(value).strip()
            for value in getattr(request, target_field)
            if str(value).strip()
        ]
        shard_count = min(len(accounts), len(targets), request.max_awemes)
        if shard_count <= 1:
            return [(accounts[0], request)]
        groups: list[list[str]] = [[] for _ in range(shard_count)]
        for index, target in enumerate(targets):
            groups[index % shard_count].append(target)
        base_limit, remainder = divmod(request.max_awemes, shard_count)
        assignments: list[tuple[DouyinAccount, CrawlTaskCreate]] = []
        for index, (account, group) in enumerate(
            zip(accounts[:shard_count], groups, strict=True)
        ):
            shard_limit = max(1, base_limit + int(index < remainder))
            shard_request = request.model_copy(
                update={
                    target_field: group,
                    "max_awemes": shard_limit,
                    "account_id": account.id,
                    "account_ids": [],
                    "account_pool_id": None,
                    "request_interval_seconds": max(
                        request.request_interval_seconds,
                        account.min_request_interval_seconds,
                    ),
                    "download_media": False,
                    "translate_subtitles": False,
                    "media_processing_mode": MediaProcessingMode.none,
                }
            )
            assignments.append((account, shard_request))
        return assignments

    async def _execute_multi_account(
        self,
        task_id: uuid.UUID,
        request: CrawlTaskCreate,
        *,
        storage: DouyinStorage,
        assignments: list[tuple[DouyinAccount, CrawlTaskCreate]],
        media_enabled: bool,
        force_retranslate: bool,
        accounts_pre_reserved: bool = False,
    ) -> None:
        """多账号分片并行执行：创建分片记录、并发运行，全部成功后统一进入媒体阶段。

        异常：RuntimeError —— 任一分片失败时抛出（汇总失败分片数量，可修复后恢复任务）。
        """
        try:
            shards = await DouyinStorage.create_shards(
                task_id,
                [(account.id, shard_request) for account, shard_request in assignments],
            )
            # 分片协程启动后由各自 finally 释放租约；在此之前的任何异常（包括
            # 服务关闭导致的 CancelledError）都必须在当前协程统一归还全部预占账号。
            await storage.update_task(
                status=CrawlTaskStatus.running,
                error=None,
                started_at=get_datetime_utc(),
                finished_at=None,
                qrcode_path=None,
            )
        except BaseException:
            if accounts_pre_reserved:
                for account, _ in assignments:
                    await asyncio.to_thread(
                        release_account,
                        account.id,
                        success=False,
                        error="分片初始化失败",
                    )
            raise
        results = await asyncio.gather(
            *(
                self._run_shard(
                    task_id,
                    shard,
                    account,
                    shard_request,
                    account_pre_reserved=accounts_pre_reserved,
                )
                for shard, (account, shard_request) in zip(
                    shards, assignments, strict=True
                )
            ),
            return_exceptions=True,
        )
        errors = [item for item in results if isinstance(item, BaseException)]
        if errors:
            summaries = ", ".join(type(error).__name__ for error in errors[:3])
            raise RuntimeError(
                f"{len(errors)}/{len(results)} 个账号分片执行失败（{summaries}），可修复账号后继续任务"
            )

        await storage.save_checkpoint(
            phase=(
                CrawlTaskPhase.media
                if request.download_media
                else CrawlTaskPhase.completed
            ),
            crawl_type=request.crawl_type.value,
        )
        if request.download_media and media_enabled:
            await storage.update_task(status=CrawlTaskStatus.processing_media)
            media_crawler = DouyinCrawlerService(
                task_id=task_id,
                request=request,
                settings=settings,
                storage=storage,
                on_qrcode=self._ignore_qrcode,
            )
            await media_crawler.run(
                crawl_enabled=False,
                media_enabled=True,
                force_retranslate=force_retranslate,
            )
        if request.download_media and not media_enabled:
            await storage.update_task(
                status=CrawlTaskStatus.interrupted,
                error="爬取已完成，媒体处理尚未恢复",
                qrcode_path=None,
                finished_at=get_datetime_utc(),
            )
        else:
            await storage.complete_task(request.crawl_type.value)

    async def _run_shard(
        self,
        task_id: uuid.UUID,
        shard: CrawlTaskShard,
        account: DouyinAccount,
        request: CrawlTaskCreate,
        *,
        account_pre_reserved: bool = False,
    ) -> None:
        """执行单个账号分片：租用账号、运行爬虫并维护分片状态与账号租约。"""
        reserved: DouyinAccount | None = None
        success = False
        try:
            reserved = (
                account
                if account_pre_reserved
                else (await asyncio.to_thread(reserve_accounts, [account.id]))[0]
            )
            await DouyinStorage.update_shard(
                shard.id,
                status=CrawlTaskShardStatus.running,
                started_at=get_datetime_utc(),
                error=None,
            )
            crawler = DouyinCrawlerService(
                task_id=task_id,
                request=request,
                settings=settings,
                storage=DouyinStorage(task_id, shard.id),
                on_qrcode=self._ignore_qrcode,
                account=reserved,
            )
            await crawler.run(crawl_enabled=True, media_enabled=False)
            success = True
            await DouyinStorage.update_shard(
                shard.id,
                status=CrawlTaskShardStatus.succeeded,
                finished_at=get_datetime_utc(),
            )
        except asyncio.CancelledError:
            await DouyinStorage.update_shard(
                shard.id,
                status=CrawlTaskShardStatus.cancelled,
                finished_at=get_datetime_utc(),
            )
            raise
        except Exception as exc:
            await DouyinStorage.update_shard(
                shard.id,
                status=CrawlTaskShardStatus.failed,
                error=f"{type(exc).__name__}: {exc}",
                finished_at=get_datetime_utc(),
            )
            raise
        finally:
            if reserved is not None:
                await asyncio.to_thread(
                    release_account,
                    reserved.id,
                    success=success,
                    error=None if success else "账号分片执行失败",
                )

    @staticmethod
    async def _ignore_qrcode(_path: Path | None) -> None:
        """分片与媒体阶段不使用二维码登录，忽略二维码回调。"""
        return None

    async def cancel(self, task_id: uuid.UUID) -> bool:
        """取消当前进程内正在运行的任务。

        返回：是否成功取消（任务不在本进程运行或已结束时返回 False）。
        """
        async with self._lock:
            handle = self._handles.get(task_id)
            if not handle or handle.task.done():
                return False
            await DouyinStorage(task_id).update_task(status=CrawlTaskStatus.cancelling)
            handle.task.cancel()
            task = handle.task
        try:
            await task
        except asyncio.CancelledError:
            pass
        return True

    async def shutdown(self) -> None:
        """进程退出钩子：取消全部在途任务并关闭媒体与登录管理器。"""
        async with self._lock:
            tasks = [handle.task for handle in self._handles.values()]
            for task in tasks:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await media_manager.shutdown()
        await media_migration_manager.shutdown()
        await account_login_manager.shutdown()


task_manager = DouyinTaskManager()  # 进程级任务管理器单例
