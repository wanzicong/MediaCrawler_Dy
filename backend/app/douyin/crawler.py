# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.core.config import Settings
from app.douyin.browser import CDPBrowserSession
from app.douyin.client import DouyinClient
from app.douyin.exceptions import DataFetchError
from app.douyin.login import DouyinLogin
from app.douyin.privacy import anonymize_account_id
from app.douyin.storage import DouyinStorage
from app.douyin.types import PublishTimeType, parse_creator_info, parse_video_info
from app.models import (
    CrawlTaskCreate,
    CrawlTaskPhase,
    CrawlTaskStatus,
    DouyinBrowserMode,
    DouyinCrawlType,
    DouyinLoginType,
    MediaProcessingMode,
)
from app.services.media_pipeline import media_manager

logger = logging.getLogger(__name__)
QRCodeCallback = Callable[[Path | None], Awaitable[None]]


class DouyinCrawlerService:
    """Task-scoped orchestration for the extracted Douyin crawling logic."""

    index_url = "https://www.douyin.com"

    def __init__(
        self,
        *,
        task_id: uuid.UUID,
        request: CrawlTaskCreate,
        settings: Settings,
        storage: DouyinStorage,
        on_qrcode: QRCodeCallback,
    ):
        self.task_id = task_id
        self.request = request
        self.settings = settings
        self.storage = storage
        self.on_qrcode = on_qrcode
        self.client: DouyinClient | None = None
        self.seen_aweme_ids: set[str] = set()
        self.media_headers: dict[str, str] = {}

    async def run(
        self, *, crawl_enabled: bool = True, media_enabled: bool = True
    ) -> None:
        if not crawl_enabled:
            if media_enabled:
                await self._run_media(headers=self._one_time_media_headers())
            return
        browser_mode = self.request.browser_mode or DouyinBrowserMode(
            self.settings.DOUYIN_BROWSER_MODE
        )
        browser = CDPBrowserSession(self.settings, browser_mode=browser_mode)
        async with browser:
            if browser.page is None or browser.context is None:
                raise RuntimeError("CDP 浏览器未创建页面")
            try:
                await browser.page.goto(
                    self.index_url, wait_until="domcontentloaded", timeout=30_000
                )
            except PlaywrightTimeoutError:
                logger.warning("Douyin home page timed out; continuing with loaded DOM")

            client = await DouyinClient.create(
                page=browser.page,
                browser_context=browser.context,
                timeout=self.settings.DOUYIN_REQUEST_TIMEOUT,
                verify_ssl=self.settings.DOUYIN_REQUEST_SSL_VERIFY,
            )
            self.client = client
            try:
                login = DouyinLogin(
                    browser_context=browser.context,
                    page=browser.page,
                    qrcode_path=Path("../data/qrcode") / f"{self.task_id}.png",
                    timeout=self.settings.DOUYIN_LOGIN_TIMEOUT,
                    on_qrcode=self.on_qrcode,
                )
                require_profile = self.request.crawl_type in {
                    DouyinCrawlType.liked,
                    DouyinCrawlType.collected,
                }
                if self.request.login_type == DouyinLoginType.cookie:
                    assert self.request.cookies is not None
                    await login.login_with_cookie(
                        self.request.cookies.get_secret_value(), client
                    )
                elif not await client.pong(
                    browser.context, require_self_profile=require_profile
                ):
                    await login.login_with_qrcode(
                        client, require_self_profile=require_profile
                    )
                await client.update_cookies(browser.context)
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
                if media_enabled:
                    await self._run_media(headers=self.media_headers)
            finally:
                self.media_headers = {}
                await client.close()
                self.client = None

    def _one_time_media_headers(self) -> dict[str, str] | None:
        if not self.request.cookies:
            return None
        cookie = self.request.cookies.get_secret_value().strip()
        if not cookie:
            return None
        return {"Cookie": cookie, "Referer": f"{self.index_url}/"}

    async def _run_media(self, headers: dict[str, str] | None = None) -> None:
        if not self.request.download_media:
            return
        await self.storage.update_task(status=CrawlTaskStatus.processing_media)
        # Enqueue every persisted aweme even for immediate mode. The media
        # manager is idempotent, so this also fills the crash window between
        # saving an aweme and creating its media asset.
        await media_manager.enqueue_task(
            task_id=self.task_id,
            storage_backend=self.request.media_storage,
            translate_subtitles=self.request.translate_subtitles,
            language=self.request.transcription_language,
            headers=headers,
        )
        await media_manager.wait_for_task(self.task_id)

    async def _resume_position(self) -> dict[str, Any]:
        checkpoint = await self.storage.load_checkpoint()
        if (
            checkpoint.get("phase") != CrawlTaskPhase.crawl.value
            or checkpoint.get("crawl_type") != self.request.crawl_type.value
        ):
            return {}
        position = checkpoint.get("position")
        return position if isinstance(position, dict) else {}

    async def _save_position(self, **position: Any) -> None:
        await self.storage.save_checkpoint(
            phase=CrawlTaskPhase.crawl,
            crawl_type=self.request.crawl_type.value,
            position=position,
        )

    @property
    def api(self) -> DouyinClient:
        if self.client is None:
            raise RuntimeError("Douyin client is not initialized")
        return self.client

    async def _dispatch(self) -> None:
        if self.request.crawl_type == DouyinCrawlType.search:
            await self._search()
        elif self.request.crawl_type == DouyinCrawlType.detail:
            await self._details()
        elif self.request.crawl_type == DouyinCrawlType.creator:
            await self._creators()
        elif self.request.crawl_type == DouyinCrawlType.liked:
            await self._personal_feed("liked")
        elif self.request.crawl_type == DouyinCrawlType.collected:
            await self._personal_feed("collected")

    async def _search(self) -> None:
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
            if (
                len(self.seen_aweme_ids) >= self.request.max_awemes
                and not same_target
            ):
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
                response = await self.api.search(
                    keyword,
                    offset=(page - 1) * 10,
                    search_id=search_id,
                    publish_time=publish_time,
                )
                data = response.get("data")
                if not isinstance(data, list) or not data:
                    await self._save_position(
                        target_index=target_index + 1,
                        page=self.request.start_page,
                        stage="fetch",
                    )
                    break
                search_id = str((response.get("extra") or {}).get("logid") or "")
                page_aweme_ids: list[str] = []
                for post in data:
                    mix_items = (post.get("aweme_mix_info") or {}).get("mix_items") or []
                    item = post.get("aweme_info") or (mix_items[0] if mix_items else None)
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
                    if aweme_id in self.seen_aweme_ids and aweme_id not in page_aweme_ids:
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
                await asyncio.sleep(self.request.request_interval_seconds)

    async def _details(self) -> None:
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
                    parsed = parse_video_info(await self.api.resolve_short_url(value))
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
        item = await self.api.get_video(aweme_id)
        if not item:
            raise DataFetchError(f"作品 {aweme_id} 没有返回详情")
        self.seen_aweme_ids.add(aweme_id)
        await self._save_aweme(item, source_keyword="detail")
        await self._batch_comments([aweme_id], "detail")
        await asyncio.sleep(self.request.request_interval_seconds)
        return index

    async def _creators(self) -> None:
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
            # Keep source-project privacy behaviour: request creator profile for
            # session validation, but do not persist the profile itself.
            await self.api.get_user_info(sec_user_id)
            cursor = str(position.get("cursor") or "") if same_target else ""
            seen_cursors: set[str] = set()
            if same_target and position.get("stage") == "comments":
                pending = [
                    str(item)
                    for item in position.get("pending_aweme_ids", [])
                    if str(item)
                ]
                await self._batch_comments(pending, source_keyword)
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
                response = await self.api.get_user_posts(sec_user_id, cursor)
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
                    aweme_id = str(item.get("aweme_id") or "")
                    if not aweme_id:
                        continue
                    if aweme_id not in self.seen_aweme_ids:
                        if len(self.seen_aweme_ids) >= self.request.max_awemes:
                            break
                        self.seen_aweme_ids.add(aweme_id)
                    if aweme_id in self.seen_aweme_ids and aweme_id not in ids:
                        ids.append(aweme_id)
                await self._fetch_details(ids, source_keyword=source_keyword)
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
                await self._batch_comments(ids, source_keyword)
                if not has_more:
                    await self._save_position(
                        target_index=target_index + 1,
                        cursor="",
                        stage="fetch",
                    )
                    break
                if not next_cursor or next_cursor == cursor or next_cursor in seen_cursors:
                    break
                seen_cursors.add(cursor)
                cursor = next_cursor
                await self._save_position(
                    target_index=target_index,
                    cursor=cursor,
                    stage="fetch",
                )

    async def _fetch_details(
        self, aweme_ids: list[str], *, source_keyword: str
    ) -> None:
        semaphore = asyncio.Semaphore(self.request.concurrency)

        async def fetch(aweme_id: str) -> None:
            async with semaphore:
                item = await self.api.get_video(aweme_id)
                if not item:
                    raise DataFetchError(f"作品 {aweme_id} 没有返回详情")
                self.seen_aweme_ids.add(aweme_id)
                await self._save_aweme(item, source_keyword=source_keyword)
                await asyncio.sleep(self.request.request_interval_seconds)

        results = await asyncio.gather(
            *(fetch(aweme_id) for aweme_id in aweme_ids),
            return_exceptions=True,
        )
        errors = [result for result in results if isinstance(result, BaseException)]
        if errors:
            raise DataFetchError(
                f"当前页面仍有 {len(errors)} 个作品详情未完成，可继续任务重试"
            ) from errors[0]

    async def _batch_comments(
        self, aweme_ids: list[str], source_keyword: str
    ) -> None:
        if not self.request.fetch_comments or not aweme_ids:
            return
        semaphore = asyncio.Semaphore(self.request.concurrency)

        async def fetch(aweme_id: str) -> None:
            async with semaphore:
                await self.api.get_all_comments(
                    aweme_id,
                    interval=self.request.request_interval_seconds,
                    include_sub_comments=self.request.fetch_sub_comments,
                    callback=self.storage.save_comments,
                    max_count=self.request.max_comments_per_aweme,
                    keyword=source_keyword,
                )

        results = await asyncio.gather(
            *(fetch(aweme_id) for aweme_id in aweme_ids),
            return_exceptions=True,
        )
        errors = [result for result in results if isinstance(result, BaseException)]
        if errors:
            raise DataFetchError(
                f"当前页面仍有 {len(errors)} 个作品评论未完成，可继续任务重试"
            ) from errors[0]

    @staticmethod
    def _extract_self_ids(payload: dict[str, Any]) -> tuple[str, str]:
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

    async def _personal_feed(self, feed_type: str) -> None:
        position = await self._resume_position()
        profile = await self.api.get_self_profile()
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
                await self.api.get_liked(sec_uid, cursor, count)
                if feed_type == "liked"
                else await self.api.get_collected(cursor, count)
            )
            if response.get("status_code") not in (0, "0"):
                raise DataFetchError(
                    f"抖音 {feed_type} 第 {page} 页业务状态失败"
                )
            items = response.get("aweme_list")
            if not isinstance(items, list):
                raise DataFetchError(f"抖音 {feed_type} 响应缺少 aweme_list")
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
            if next_cursor is None or normalized_cursor in seen_cursors or next_cursor == cursor:
                break
            seen_cursors.add(str(cursor))
            cursor = next_cursor
            page += 1
            await self._save_position(cursor=cursor, page=page, stage="fetch")
            await asyncio.sleep(self.request.request_interval_seconds)

    async def _save_aweme(
        self, item: dict[str, Any], *, source_keyword: str
    ) -> None:
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
            )
