# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音爬取任务的任务级爬虫编排。

负责 CDP 浏览器登录、按爬取类型（搜索/详情/创作者/点赞/收藏）分发抓取、
断点续爬位置维护，以及媒体处理流水线的触发；由 DouyinTaskManager 按任务驱动。
"""

import asyncio
import logging
import random
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from crawler.bootstrap.settings import Settings
from crawler.browser.facade import (
    BrowserAutomationTimeoutError,
    BrowserSessionSpec,
    CDPBrowserSession,
    DouyinLogin,
    LoginError,
)
from crawler.business.douyin.accounts.models import (
    DouyinAccount,
    DouyinBrowserMode,
)
from crawler.business.douyin.adapters.service import (
    DouyinLoginApi,
    open_douyin_client,
)
from crawler.business.douyin.media.models import MediaProcessingMode
from crawler.business.douyin.media.pipeline import media_manager
from crawler.business.douyin.request_logs.service import (
    build_request_logger,
    load_task_owner,
)
from crawler.business.douyin.tasks.models import (
    CrawlTaskCreate,
    CrawlTaskPhase,
    CrawlTaskStatus,
    DouyinCrawlType,
    DouyinLoginType,
)
from crawler.business.douyin.tasks.persistence import DouyinStorage
from crawler.douyin_client import (
    DataFetchError,
    DouyinClient,
    PublishTimeType,
    anonymize_account_id,
    anonymize_user_id,
    mask_nickname,
    parse_creator_info,
    parse_video_info,
)

logger = logging.getLogger(__name__)
QRCodeCallback = Callable[
    [Path | None], Awaitable[None]
]  # 二维码生成/失效回调（None 表示已登录）
BrowserAcquiredCallback = Callable[[], Awaitable[None]]  # 获取到浏览器并发许可后的回调


def session_browser_mode(request_mode: str | None, default_mode: str) -> str:
    """把任务请求里的浏览器模式归一化为会话参数需要的字符串取值。

    历史坑：``DouyinBrowserMode`` 是 ``(str, Enum)``，但 Python 3.11 起
    ``str(member)`` 返回的是 ``"DouyinBrowserMode.local"``（成员名）而不是取值
    ``"local"``，直接 ``str()`` 会让「临时浏览器登录」的任务在构造 CDP 会话时
    抛 ``'DouyinBrowserMode.local' is not a valid BrowserMode``。

    参数：
        request_mode: 任务请求里的浏览器模式；可能来自 ORM 枚举、字符串或 None。
        default_mode: 请求未指定时使用的模式字符串（来自服务端配置）。
    返回：
        可直接放进 ``BrowserSessionSpec.browser_mode`` 的 ``"local"`` / ``"remote"``。
    """
    requested = request_mode or DouyinBrowserMode(default_mode)
    return str(getattr(requested, "value", requested))


class DouyinCrawlerService:
    """单个任务（或分片）的爬取编排器：登录浏览器、分发抓取流程并触发媒体处理。"""

    index_url = "https://www.douyin.com"  # 抖音首页 URL，用于建立会话与请求 Referer

    def __init__(
        self,
        *,
        task_id: uuid.UUID,
        request: CrawlTaskCreate,
        settings: Settings,
        storage: DouyinStorage,
        on_qrcode: QRCodeCallback,
        browser_semaphore: asyncio.Semaphore | None = None,
        on_browser_acquired: BrowserAcquiredCallback | None = None,
        account: DouyinAccount | None = None,
    ):
        """初始化任务级爬虫编排器。

        参数：task_id 任务 ID；request 任务请求；settings 全局配置；storage 持久化适配器；
              on_qrcode 二维码回调；browser_semaphore 浏览器并发信号量（托管账号任务不使用）；
              on_browser_acquired 获取浏览器许可后的回调；account 托管账号（可选）。
        """
        self.task_id = task_id
        self.request = request
        self.settings = settings
        self.storage = storage
        self.on_qrcode = on_qrcode
        self.browser_semaphore = browser_semaphore
        self.on_browser_acquired = on_browser_acquired
        self.account = account
        self.client: DouyinClient | None = None
        self.seen_aweme_ids: set[str] = set()
        self.media_headers: dict[str, str] = {}

    async def run(
        self,
        *,
        crawl_enabled: bool = True,
        media_enabled: bool = True,
        force_retranslate: bool = False,
    ) -> None:
        """任务执行入口：按需串行执行「爬取」与「媒体处理」两个阶段。

        参数：crawl_enabled 是否执行爬取阶段（False 时只做媒体处理）；
              media_enabled 是否执行媒体处理阶段；
              force_retranslate 是否强制重新转写字幕。
        """
        if not crawl_enabled:
            if media_enabled:
                await self._run_media(
                    headers=self._one_time_media_headers(),
                    force_retranslate=force_retranslate,
                )
            return
        if self.browser_semaphore is None:
            if self.on_browser_acquired is not None:
                await self.on_browser_acquired()
            media_headers = await self._crawl()
        else:
            async with self.browser_semaphore:
                if self.on_browser_acquired is not None:
                    await self.on_browser_acquired()
                media_headers = await self._crawl()
        if media_enabled:
            await self._run_media(
                headers=media_headers,
                force_retranslate=force_retranslate,
            )

    async def _crawl(self) -> dict[str, str]:
        """打开 CDP 浏览器、完成登录并按类型分发抓取，返回后续媒体下载所需的请求头。"""
        if self.account is not None:
            from crawler.business.douyin.accounts.service import resolve_account_browser

            # 账号解析结果是连接参数的唯一真源，直接作为 spec 交给会话。
            spec = resolve_account_browser(self.account)
        else:
            spec = BrowserSessionSpec(
                browser_mode=session_browser_mode(
                    self.request.browser_mode, self.settings.DOUYIN_BROWSER_MODE
                )
            )
        browser = CDPBrowserSession.from_spec(self.settings, spec)
        async with browser:
            try:
                await browser.open(self.index_url)
            except BrowserAutomationTimeoutError:
                logger.warning("Douyin home page timed out; continuing with loaded DOM")

            client = await open_douyin_client(
                page=browser.browser_page,
                settings=self.settings,
            )
            api = DouyinLoginApi(client=client)
            self.client = client
            owner_id = await load_task_owner(self.task_id)
            if owner_id is not None:
                client.request_logger = build_request_logger(owner_id, self.task_id)
            try:
                login = DouyinLogin.from_session(
                    browser,
                    qrcode_path=Path("../data/qrcode") / f"{self.task_id}.png",
                    timeout=self.settings.DOUYIN_LOGIN_TIMEOUT,
                    on_qrcode=self.on_qrcode,
                )
                require_profile = self.request.crawl_type in {
                    DouyinCrawlType.liked,
                    DouyinCrawlType.collected,
                    DouyinCrawlType.following,
                }
                if self.request.login_type == DouyinLoginType.cookie:
                    assert self.request.cookies is not None
                    await login.login_with_cookie(
                        self.request.cookies.get_secret_value(), api
                    )
                else:
                    logged_in = await api.verify_login(
                        require_self_profile=require_profile
                    )
                    if not logged_in and self.account is not None:
                        raise LoginError(
                            f"托管账号“{self.account.name}”登录已失效，请先在账号管理中重新登录"
                        )
                    if not logged_in:
                        await login.login_with_qrcode(
                            api, require_self_profile=require_profile
                        )
                await api.refresh_cookies()
                self.media_headers = {
                    key: value
                    for key, value in client.headers.items()
                    if key.lower() in {"user-agent", "referer", "cookie"}
                }
                self.seen_aweme_ids = await self.storage.aweme_ids()
                await self._dispatch()
                await self.storage.save_checkpoint(
                    phase=(
                        CrawlTaskPhase.media
                        if self.request.download_media
                        else CrawlTaskPhase.completed
                    ),
                    crawl_type=self.request.crawl_type.value,
                )
                return dict(self.media_headers)
            finally:
                self.media_headers = {}
                await api.aclose()
                self.client = None

    def _one_time_media_headers(self) -> dict[str, str] | None:
        """由一次性 Cookie 构造媒体请求头（无 Cookie 时返回 None）。"""
        if not self.request.cookies:
            return None
        cookie = self.request.cookies.get_secret_value().strip()
        if not cookie:
            return None
        return {"Cookie": cookie, "Referer": f"{self.index_url}/"}

    async def _run_media(
        self,
        headers: dict[str, str] | None = None,
        *,
        force_retranslate: bool = False,
    ) -> None:
        """把任务已落库的作品全部入队媒体处理并等待完成（media_manager 幂等）。

        参数：headers 媒体下载请求头；force_retranslate 是否强制重新转写字幕。
        """
        if not self.request.download_media:
            return
        await self.storage.update_task(status=CrawlTaskStatus.processing_media)
        # 即使是 immediate 模式也统一入队全部已落库作品：media_manager 幂等，
        # 同时可覆盖「作品已保存但媒体资产尚未创建」之间的崩溃窗口。
        await media_manager.enqueue_task(
            task_id=self.task_id,
            storage_backend=self.request.media_storage,
            translate_subtitles=self.request.translate_subtitles,
            language=self.request.transcription_language,
            headers=headers,
            force_retranslate=force_retranslate,
            temporary_only=self.request.subtitle_only,
        )
        await media_manager.wait_for_task(self.task_id)

    async def _resume_position(self) -> dict[str, Any]:
        """读取断点中的爬取位置；阶段或爬取类型不匹配时返回空（视为从头开始）。"""
        checkpoint = await self.storage.load_checkpoint()
        if (
            checkpoint.get("phase") != CrawlTaskPhase.crawl.value
            or checkpoint.get("crawl_type") != self.request.crawl_type.value
        ):
            return {}
        position = checkpoint.get("position")
        return position if isinstance(position, dict) else {}

    async def _save_position(self, **position: Any) -> None:
        """把当前爬取位置写入断点检查点（phase 固定为 crawl）。"""
        await self.storage.save_checkpoint(
            phase=CrawlTaskPhase.crawl,
            crawl_type=self.request.crawl_type.value,
            position=position,
        )

    @property
    def api(self) -> DouyinClient:
        """已初始化的 DouyinClient；未初始化时抛出 RuntimeError。"""
        if self.client is None:
            raise RuntimeError("Douyin client is not initialized")
        return self.client

    def _request_delay_seconds(self) -> float:
        """在配置的随机区间内取一次请求间隔（秒）。"""
        minimum, maximum = self.request.request_interval_range_seconds()
        return random.uniform(minimum, maximum)

    async def _wait_for_next_request(self) -> None:
        """按随机间隔休眠，控制请求频率。"""
        await asyncio.sleep(self._request_delay_seconds())

    async def _dispatch(self) -> None:
        """按爬取类型分发到对应的抓取流程。"""
        if self.request.crawl_type == DouyinCrawlType.search:
            await self._search()
        elif self.request.crawl_type == DouyinCrawlType.detail:
            await self._details()
        elif self.request.crawl_type == DouyinCrawlType.creator:
            await self._creators()
        elif self.request.crawl_type == DouyinCrawlType.creator_from_aweme:
            await self._creator_from_awemes()
        elif self.request.crawl_type == DouyinCrawlType.liked:
            await self._personal_feed("liked")
        elif self.request.crawl_type == DouyinCrawlType.collected:
            await self._personal_feed("collected")
        elif self.request.crawl_type == DouyinCrawlType.following:
            await self._following()

    async def _search(self) -> None:
        """关键词搜索抓取：按关键词分页拉取作品并抓评论，全程维护断点位置。

        通过页内 aweme_id 签名识别重复翻页（接口返回不变时终止），max_awemes 控制总量。
        """
        publish_time = PublishTimeType(self.request.publish_time)
        position = await self._resume_position()
        start_target = max(int(position.get("target_index") or 0), 0)
        for target_index, raw_keyword in enumerate(self.request.keywords):
            if target_index < start_target:
                continue
            keyword = raw_keyword.strip()
            same_target = target_index == start_target
            if not keyword:
                continue
            if len(self.seen_aweme_ids) >= self.request.max_awemes and not same_target:
                break
            page = (
                max(int(position.get("page") or self.request.start_page), 1)
                if same_target
                else self.request.start_page
            )
            if same_target and position.get("stage") == "comments":
                pending = [
                    str(value)
                    for value in position.get("pending_aweme_ids", [])
                    if str(value)
                ]
                await self._batch_comments(pending, keyword)
                page += 1
                await self._save_position(
                    target_index=target_index, page=page, stage="fetch"
                )
            search_id = ""
            first_page = True
            seen_page_signatures: set[tuple[str, ...]] = set()
            while first_page or len(self.seen_aweme_ids) < self.request.max_awemes:
                first_page = False
                await self._save_position(
                    target_index=target_index, page=page, stage="fetch"
                )
                response = await self.api.search_api.search(
                    keyword,
                    offset=(page - 1) * 10,
                    search_id=search_id,
                    publish_time=publish_time,
                )
                data = response.get("data")
                if not isinstance(data, list) or not data:
                    nil_info = response.get("search_nil_info")
                    nil_reason = (
                        str(nil_info.get("search_nil_type") or "")
                        if isinstance(nil_info, dict)
                        else ""
                    )
                    nil_item = (
                        str(nil_info.get("search_nil_item") or "")
                        if isinstance(nil_info, dict)
                        else ""
                    )
                    if "verify_check" in {nil_reason, nil_item}:
                        raise DataFetchError(
                            f"关键词“{keyword}”搜索触发抖音安全校验，未返回作品；请验证账号后断点续爬"
                        )
                    await self._save_position(
                        target_index=target_index + 1,
                        page=self.request.start_page,
                        stage="fetch",
                    )
                    break
                search_id = str((response.get("extra") or {}).get("logid") or "")
                page_aweme_ids: list[str] = []
                for post in data:
                    mix_items = (post.get("aweme_mix_info") or {}).get(
                        "mix_items"
                    ) or []
                    item = post.get("aweme_info") or (
                        mix_items[0] if mix_items else None
                    )
                    if not isinstance(item, dict):
                        continue
                    aweme_id = str(item.get("aweme_id") or "")
                    if not aweme_id:
                        continue
                    if aweme_id not in self.seen_aweme_ids:
                        if len(self.seen_aweme_ids) >= self.request.max_awemes:
                            break
                        self.seen_aweme_ids.add(aweme_id)
                        await self._save_aweme(item, source_keyword=keyword)
                    if (
                        aweme_id in self.seen_aweme_ids
                        and aweme_id not in page_aweme_ids
                    ):
                        page_aweme_ids.append(aweme_id)
                signature = tuple(page_aweme_ids)
                if signature and signature in seen_page_signatures:
                    break
                seen_page_signatures.add(signature)
                await self._save_position(
                    target_index=target_index,
                    page=page,
                    stage="comments",
                    pending_aweme_ids=page_aweme_ids,
                )
                await self._batch_comments(page_aweme_ids, keyword)
                if not page_aweme_ids:
                    break
                page += 1
                await self._save_position(
                    target_index=target_index, page=page, stage="fetch"
                )
                await self._wait_for_next_request()

    async def _details(self) -> None:
        """指定作品详情抓取：解析短链、并发批处理详情与评论，按已完成序号断点续爬。

        异常：DataFetchError —— 批次内仍有作品未完成时抛出（可继续任务重试）。
        """
        position = await self._resume_position()
        raw_targets = position.get("resolved_aweme_ids")
        aweme_ids = (
            [str(value) for value in raw_targets if str(value)]
            if isinstance(raw_targets, list)
            else []
        )
        if not aweme_ids:
            for value in self.request.video_ids:
                parsed = parse_video_info(value)
                if parsed.url_type == "short":
                    parsed = parse_video_info(
                        await self.api.resolver_api.resolve_short_url(value)
                    )
                if parsed.aweme_id and parsed.aweme_id not in aweme_ids:
                    aweme_ids.append(parsed.aweme_id)
            aweme_ids = aweme_ids[: self.request.max_awemes]
        completed = {
            int(value)
            for value in position.get("completed_indexes", [])
            if isinstance(value, int) or str(value).isdigit()
        }
        await self._save_position(
            resolved_aweme_ids=aweme_ids,
            completed_indexes=sorted(completed),
        )
        remaining = [
            (index, aweme_id)
            for index, aweme_id in enumerate(aweme_ids)
            if index not in completed
        ]
        for offset in range(0, len(remaining), self.request.concurrency):
            batch = remaining[offset : offset + self.request.concurrency]
            results = await asyncio.gather(
                *(
                    self._process_detail_target(index, aweme_id)
                    for index, aweme_id in batch
                ),
                return_exceptions=True,
            )
            errors: list[BaseException] = []
            for (index, _), result in zip(batch, results, strict=True):
                if isinstance(result, BaseException):
                    errors.append(result)
                else:
                    completed.add(index)
            await self._save_position(
                resolved_aweme_ids=aweme_ids,
                completed_indexes=sorted(completed),
            )
            if errors:
                raise DataFetchError(
                    f"指定作品仍有 {len(errors)} 项未完成，可继续任务重试"
                ) from errors[0]

    async def _process_detail_target(self, index: int, aweme_id: str) -> int:
        """处理一个详情目标；评论补采复用来源作品，否则抓详情后再抓评论。"""
        if self.request.comment_source_task_id is not None:
            source_storage = DouyinStorage(self.request.comment_source_task_id)
            if aweme_id not in await source_storage.aweme_ids():
                raise DataFetchError(f"来源任务中不存在作品 {aweme_id}")
            await self._batch_comments(
                [aweme_id],
                "detail",
                storage=source_storage,
                ignore_stored_counts=True,
            )
            return index
        item = await self.api.aweme_api.get_video(aweme_id)
        if not item:
            raise DataFetchError(f"作品 {aweme_id} 没有返回详情")
        self.seen_aweme_ids.add(aweme_id)
        await self._save_aweme(item, source_keyword="detail")
        await self._batch_comments([aweme_id], "detail")
        await self._wait_for_next_request()
        return index

    async def _creator_from_awemes(self) -> None:
        """由作品详情反查创作者（sec_uid）后转入创作者抓取流程，原始账号 ID 仅驻留内存不落库。"""
        sec_user_ids: list[str] = []
        for value in self.request.video_ids:
            parsed = parse_video_info(value)
            if parsed.url_type == "short":
                parsed = parse_video_info(
                    await self.api.resolver_api.resolve_short_url(value)
                )
            if not parsed.aweme_id:
                continue
            item = await self.api.aweme_api.get_video(parsed.aweme_id)
            if not item:
                raise DataFetchError(f"作品 {parsed.aweme_id} 没有返回详情")
            author = item.get("author") or {}
            sec_user_id = str(author.get("sec_uid") or "").strip()
            if not sec_user_id:
                raise DataFetchError(f"作品 {parsed.aweme_id} 没有返回作者标识")
            if sec_user_id not in sec_user_ids:
                sec_user_ids.append(sec_user_id)
        if not sec_user_ids:
            raise DataFetchError("指定作品没有可抓取的作者")

        original_request = self.request
        self.request = self.request.model_copy(update={"creator_ids": sec_user_ids})
        try:
            await self._creators()
        finally:
            # 原始创作者 ID 仅在本调用期间驻留内存。
            self.request = original_request

    async def _creators(self) -> None:
        """创作者主页作品抓取：按游标分页保存列表作品并抓评论，支持断点续爬。"""
        position = await self._resume_position()
        start_target = max(int(position.get("target_index") or 0), 0)
        for target_index, value in enumerate(self.request.creator_ids):
            if target_index < start_target:
                continue
            same_target = target_index == start_target
            if len(self.seen_aweme_ids) >= self.request.max_awemes and not same_target:
                break
            sec_user_id = parse_creator_info(value).sec_user_id
            source_keyword = "creator:" + anonymize_account_id(
                f"dy:sec_uid:{sec_user_id}", self.settings.SECRET_KEY
            )
            # 保持上游项目的隐私行为：请求创作者资料仅用于会话校验，资料本身不落库。
            await self.api.user_api.get_user_info(sec_user_id)
            cursor = str(position.get("cursor") or "") if same_target else ""
            seen_cursors: set[str] = set()
            if same_target and position.get("stage") == "comments":
                pending = [
                    str(item)
                    for item in position.get("pending_aweme_ids", [])
                    if str(item)
                ]
                await self._batch_comments(
                    pending,
                    source_keyword,
                    tolerate_partial_failures=True,
                )
                if not position.get("has_more"):
                    await self._save_position(
                        target_index=target_index + 1,
                        cursor="",
                        stage="fetch",
                    )
                    continue
                cursor = str(position.get("next_cursor") or "")
                if not cursor:
                    await self._save_position(
                        target_index=target_index + 1,
                        cursor="",
                        stage="fetch",
                    )
                    continue
                await self._save_position(
                    target_index=target_index,
                    cursor=cursor,
                    stage="fetch",
                )
            first_page = True
            while first_page or len(self.seen_aweme_ids) < self.request.max_awemes:
                first_page = False
                await self._save_position(
                    target_index=target_index,
                    cursor=cursor,
                    stage="fetch",
                )
                response = await self.api.aweme_api.get_user_posts(sec_user_id, cursor)
                items = response.get("aweme_list") or []
                if not isinstance(items, list) or not items:
                    await self._save_position(
                        target_index=target_index + 1,
                        cursor="",
                        stage="fetch",
                    )
                    break
                ids: list[str] = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    aweme_id = str(item.get("aweme_id") or "")
                    if not aweme_id:
                        continue
                    if aweme_id not in self.seen_aweme_ids:
                        if len(self.seen_aweme_ids) >= self.request.max_awemes:
                            break
                        self.seen_aweme_ids.add(aweme_id)
                    # 达人作品列表已经返回完整作品对象。直接落库可避免对每条作品
                    # 再调用一次高风控的详情接口，也不会因单条详情 403 让整页失败。
                    await self._save_aweme(item, source_keyword=source_keyword)
                    if aweme_id in self.seen_aweme_ids and aweme_id not in ids:
                        ids.append(aweme_id)
                next_cursor = str(response.get("max_cursor") or "")
                has_more = response.get("has_more") in (True, 1, "1")
                await self._save_position(
                    target_index=target_index,
                    cursor=cursor,
                    stage="comments",
                    pending_aweme_ids=ids,
                    has_more=has_more,
                    next_cursor=next_cursor,
                )
                await self._batch_comments(
                    ids,
                    source_keyword,
                    tolerate_partial_failures=True,
                )
                if not has_more:
                    await self._save_position(
                        target_index=target_index + 1,
                        cursor="",
                        stage="fetch",
                    )
                    break
                if (
                    not next_cursor
                    or next_cursor == cursor
                    or next_cursor in seen_cursors
                ):
                    break
                seen_cursors.add(cursor)
                cursor = next_cursor
                await self._save_position(
                    target_index=target_index,
                    cursor=cursor,
                    stage="fetch",
                )
                await self._wait_for_next_request()

    async def _batch_comments(
        self,
        aweme_ids: list[str],
        source_keyword: str,
        *,
        tolerate_partial_failures: bool = False,
        storage: DouyinStorage | None = None,
        ignore_stored_counts: bool = False,
    ) -> None:
        """并发抓取一批作品的评论（未开启评论抓取或已达单作品上限的自动跳过）。

        参数：aweme_ids 作品 ID 列表；source_keyword 来源关键词/类型标记（写入评论记录）；
              tolerate_partial_failures 为 True 时记录单作品失败并继续，用于达人批量采集；
              storage 指定评论写入位置，评论补采时指向已有作品的来源任务；
              ignore_stored_counts 为 True 时重新拉取配置上限并通过 upsert 更新评论。
        异常：DataFetchError —— 仍有作品评论未完成时抛出（可继续任务重试）。
        """
        if not self.request.fetch_comments or not aweme_ids:
            return
        target_storage = storage or self.storage
        unique_aweme_ids = list(dict.fromkeys(aweme_ids))
        semaphore = asyncio.Semaphore(self.request.concurrency)
        stored_counts = (
            {}
            if ignore_stored_counts
            else await target_storage.comment_counts(unique_aweme_ids)
        )

        async def fetch(aweme_id: str) -> None:
            """抓取单个作品的剩余评论额度（受并发信号量限制）。"""
            remaining = max(
                self.request.max_comments_per_aweme - stored_counts.get(aweme_id, 0),
                0,
            )
            if remaining == 0:
                return
            async with semaphore:
                await self.api.comments_api.get_all_comments(
                    aweme_id,
                    interval=self._request_delay_seconds,
                    include_sub_comments=self.request.fetch_sub_comments,
                    callback=target_storage.save_comments,
                    max_count=remaining,
                    keyword=source_keyword,
                )

        results = await asyncio.gather(
            *(fetch(aweme_id) for aweme_id in unique_aweme_ids),
            return_exceptions=True,
        )
        errors = [result for result in results if isinstance(result, BaseException)]
        if errors:
            if tolerate_partial_failures:
                logger.warning(
                    "Douyin task %s skipped comments for %d works after partial failures",
                    self.task_id,
                    len(errors),
                )
                return
            raise DataFetchError(
                f"当前页面仍有 {len(errors)} 个作品评论未完成，可继续任务重试"
            ) from errors[0]

    @staticmethod
    def _extract_self_ids(payload: dict[str, Any]) -> tuple[str, str]:
        """从个人资料响应中提取 (uid, sec_uid)，兼容多种返回结构。"""
        data = payload.get("data")
        candidates = [
            payload.get("user"),
            payload.get("user_info"),
            data.get("user") if isinstance(data, dict) else None,
            data.get("user_info") if isinstance(data, dict) else None,
            data,
            payload,
        ]
        user_id = ""
        sec_uid = ""
        for candidate in candidates:
            if isinstance(candidate, dict):
                user_id = user_id or str(candidate.get("uid") or "")
                sec_uid = sec_uid or str(
                    candidate.get("sec_uid") or candidate.get("sec_user_id") or ""
                )
        return user_id, sec_uid

    def _mine_aweme_rows(self, items: list[Any]) -> list[dict[str, Any]]:
        """（关注列表的映射见 _mine_following_rows，两者共用同一套隐私映射）"""
        return [row for row in (self._aweme_row(item) for item in items) if row]

    def _mine_following_rows(self, items: list[Any]) -> list[dict[str, Any]]:
        """把关注列表接口返回的用户项映射成「我的关注」表要存的扁平字典。"""
        rows: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            sec_uid = str(item.get("sec_uid") or "")
            uid_hash = anonymize_user_id(sec_uid or item.get("uid"))
            if not uid_hash:
                continue
            avatar = item.get("avatar_thumb") or item.get("avatar_larger") or {}
            urls = avatar.get("url_list") if isinstance(avatar, dict) else None
            stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
            if not stats:
                stats = item if isinstance(item, dict) else {}
            rows.append(
                {
                    "sec_uid": sec_uid,
                    "uid_hash": uid_hash,
                    "nickname": mask_nickname(item.get("nickname")),
                    "avatar_url": (
                        str(urls[-1])[:1000] if isinstance(urls, list) and urls else ""
                    ),
                    "signature": str(item.get("signature") or ""),
                    "follower_count": int(item.get("follower_count") or 0),
                    "aweme_count": int(item.get("aweme_count") or 0),
                    "is_mutual": bool(
                        item.get("is_mutual") or stats.get("is_mutual") or False
                    ),
                }
            )
        return rows

    def _aweme_row(self, item: Any) -> dict[str, Any] | None:
        """把单条点赞/收藏作品映射成「我的」表要存的扁平字典（无效项返回 None）。"""
        if not isinstance(item, dict):
            return None
        aweme_id = str(item.get("aweme_id") or "")
        if not aweme_id:
            return None
        author_raw = item.get("author")
        author: dict[str, Any] = author_raw if isinstance(author_raw, dict) else {}
        video_raw = item.get("video")
        video: dict[str, Any] = video_raw if isinstance(video_raw, dict) else {}
        cover = video.get("cover") or video.get("origin_cover") or {}
        urls = cover.get("url_list") if isinstance(cover, dict) else None
        stats_raw = item.get("statistics")
        stats: dict[str, Any] = stats_raw if isinstance(stats_raw, dict) else {}
        return {
            "aweme_id": aweme_id,
            "title": str(item.get("desc") or ""),
            "nickname": mask_nickname(author.get("nickname")),
            "creator_hash": anonymize_user_id(author.get("sec_uid")),
            "cover_url": (
                str(urls[-1])[:1000] if isinstance(urls, list) and urls else ""
            ),
            "aweme_url": f"https://www.douyin.com/video/{aweme_id}",
            "liked_count": int(stats.get("digg_count") or 0),
            "comment_count": int(stats.get("comment_count") or 0),
            "collected_count": int(stats.get("collect_count") or 0),
            "share_count": int(stats.get("share_count") or 0),
        }

    def _persist_mine_awemes(self, feed_type: str, items: list[Any]) -> None:
        """把本页点赞/收藏作品写进「我的」表（按账号幂等；异常只记日志）。"""
        from crawler.bootstrap.database import engine  # noqa: PLC0415
        from crawler.business.douyin.mine.service import (  # noqa: PLC0415
            save_account_awemes,
        )
        from sqlmodel import Session  # noqa: PLC0415

        if self.account is None:
            return
        rows = self._mine_aweme_rows(items)
        if not rows:
            return
        try:
            with Session(engine) as session:
                save_account_awemes(
                    session,
                    owner_id=self.account.owner_id,
                    account_id=self.account.id,
                    kind="liked" if feed_type == "liked" else "collected",
                    items=rows,
                    task_id=self.task_id,
                )
        except Exception:  # noqa: BLE001 - 「我的」资产写入失败不影响采集主流程
            logger.exception("写入「我的」%s 资产失败（已忽略）", feed_type)

    async def _following(self) -> None:
        """关注博主列表抓取：本人 sec_uid → 按 max_time 游标翻页 → 落「我的关注」。

        接口（真机确认）：``/aweme/v1/web/user/following/list/``，返回
        ``followings`` 列表与 ``has_more`` / ``max_time``；``offset`` 为已拉条数。
        关注数上限沿用任务的最大作品数（``max_awemes``），避免无界拉取。
        """
        profile = await self.api.user_api.get_self_profile()
        if profile.get("status_code") not in (0, "0"):
            raise DataFetchError("抖音关注模式无法验证登录账号")
        _, sec_uid = self._extract_self_ids(profile)
        if not sec_uid:
            raise DataFetchError("抖音账号资料缺少稳定 sec_uid")
        target = max(int(self.request.max_awemes or 0), 1)
        collected = 0
        offset = 0
        cursor: int | str = 0
        seen_cursors: set[str] = set()
        # 抖音的 has_more 会抖动（同一游标复请求又能拿到数据），因此不能一见到
        # false 就收尾：只有连续两轮都没拿到「新页游标推进」才判定到底。
        stale_rounds = 0
        while collected < target:
            count = min(20, target - collected)
            response = await self.api.user_api.get_followings(
                sec_uid, cursor, max(count, 1), offset
            )
            if response.get("status_code") not in (0, "0"):
                raise DataFetchError("抖音关注列表业务状态失败")
            items = response.get("followings")
            if not isinstance(items, list):
                raise DataFetchError("抖音关注列表响应缺少 followings")
            if items:
                await asyncio.to_thread(self._persist_followings, items)
                collected += len(items)
            next_cursor = str(response.get("max_time") or "")
            advanced = (
                bool(next_cursor)
                and next_cursor != str(cursor)
                and next_cursor not in seen_cursors
            )
            if advanced:
                stale_rounds = 0
                seen_cursors.add(next_cursor)
                cursor = next_cursor
                offset += len(items)
                await asyncio.sleep(random.uniform(1.2, 2.4))
                continue
            stale_rounds += 1
            if stale_rounds >= 2:
                break
            # 抖动确认：退避后用同一游标再要一页，拿到新数据就继续
            await asyncio.sleep(random.uniform(1.5, 3.0))

    def _persist_followings(self, items: list[Any]) -> None:
        """把本页关注博主写进「我的关注」（按账号幂等；异常只记日志）。"""
        from crawler.bootstrap.database import engine  # noqa: PLC0415
        from crawler.business.douyin.mine.service import (  # noqa: PLC0415
            save_followings,
        )
        from sqlmodel import Session  # noqa: PLC0415

        if self.account is None:
            return
        rows = self._mine_following_rows(items)
        if not rows:
            return
        try:
            with Session(engine) as session:
                save_followings(
                    session,
                    owner_id=self.account.owner_id,
                    account_id=self.account.id,
                    items=rows,
                    task_id=self.task_id,
                )
        except Exception:  # noqa: BLE001 - 「我的」资产写入失败不影响采集主流程
            logger.exception("写入「我的关注」资产失败（已忽略）")

    async def _personal_feed(self, feed_type: str) -> None:
        """点赞/收藏列表抓取：校验登录态后按游标分页拉取作品并记录用户行为。

        参数：feed_type 列表类型，"liked" 点赞 / "collected" 收藏。
        异常：DataFetchError —— 登录校验失败或响应结构异常。
        """
        # 本方法保留原有「作品入库」行为不变；额外把每页结果写进「我的」表
        # （账号维度的点赞/收藏资产），历史作品库数据不受影响。
        position = await self._resume_position()
        profile = await self.api.user_api.get_self_profile()
        if profile.get("status_code") not in (0, "0"):
            raise DataFetchError(f"抖音 {feed_type} 模式无法验证登录账号")
        _, sec_uid = self._extract_self_ids(profile)
        if not sec_uid:
            raise DataFetchError("抖音账号资料缺少稳定 sec_uid")
        account_hash = anonymize_account_id(
            f"dy:sec_uid:{sec_uid}", self.settings.SECRET_KEY
        )
        cursor: int | str = position.get("cursor", 0)
        seen_cursors: set[str] = set()
        page = max(int(position.get("page") or 1), 1)
        if position.get("stage") == "comments":
            pending = [
                str(value)
                for value in position.get("pending_aweme_ids", [])
                if str(value)
            ]
            await self._batch_comments(pending, feed_type)
            if not position.get("has_more"):
                return
            cursor = position.get("next_cursor", cursor)
            page += 1
            await self._save_position(
                cursor=cursor,
                page=page,
                stage="fetch",
            )
        first_page = True
        while first_page or len(self.seen_aweme_ids) < self.request.max_awemes:
            first_page = False
            await self._save_position(cursor=cursor, page=page, stage="fetch")
            count = min(20, self.request.max_awemes - len(self.seen_aweme_ids))
            count = max(count, 1)
            response = (
                await self.api.user_api.get_liked(sec_uid, cursor, count)
                if feed_type == "liked"
                else await self.api.user_api.get_collected(cursor, count)
            )
            if response.get("status_code") not in (0, "0"):
                raise DataFetchError(f"抖音 {feed_type} 第 {page} 页业务状态失败")
            items = response.get("aweme_list")
            if not isinstance(items, list):
                raise DataFetchError(f"抖音 {feed_type} 响应缺少 aweme_list")
            # 账号维度的「我的」资产：与作品入库互不影响，失败不影响采集
            if self.account is not None and items:
                await asyncio.to_thread(self._persist_mine_awemes, feed_type, items)
            page_ids: list[str] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                aweme_id = str(item.get("aweme_id") or "")
                if not aweme_id:
                    continue
                if aweme_id not in self.seen_aweme_ids:
                    if len(self.seen_aweme_ids) >= self.request.max_awemes:
                        break
                    self.seen_aweme_ids.add(aweme_id)
                    await self._save_aweme(item, source_keyword=feed_type)
                await self.storage.save_action(account_hash, aweme_id, feed_type)
                if aweme_id in self.seen_aweme_ids and aweme_id not in page_ids:
                    page_ids.append(aweme_id)
            has_more = response.get("has_more") in (True, 1, "1")
            cursor_key = "max_cursor" if feed_type == "liked" else "cursor"
            next_cursor = response.get(cursor_key)
            await self._save_position(
                cursor=cursor,
                page=page,
                stage="comments",
                pending_aweme_ids=page_ids,
                has_more=has_more,
                next_cursor=next_cursor,
            )
            await self._batch_comments(page_ids, feed_type)
            if not has_more or not page_ids:
                break
            normalized_cursor = str(next_cursor)
            if (
                next_cursor is None
                or normalized_cursor in seen_cursors
                or next_cursor == cursor
            ):
                break
            seen_cursors.add(str(cursor))
            cursor = next_cursor
            page += 1
            await self._save_position(cursor=cursor, page=page, stage="fetch")
            await self._wait_for_next_request()

    async def _save_aweme(self, item: dict[str, Any], *, source_keyword: str) -> None:
        """保存作品；immediate 媒体模式下同时立即入队该作品的媒体处理。"""
        await self.storage.save_aweme(item, source_keyword=source_keyword)
        aweme_id = str(item.get("aweme_id") or "")
        if (
            aweme_id
            and self.request.download_media
            and self.request.media_processing_mode == MediaProcessingMode.immediate
        ):
            await media_manager.enqueue_aweme(
                task_id=self.task_id,
                aweme_id=aweme_id,
                storage_backend=self.request.media_storage,
                translate_subtitles=self.request.translate_subtitles,
                language=self.request.transcription_language,
                headers=self.media_headers,
                temporary_only=self.request.subtitle_only,
            )
