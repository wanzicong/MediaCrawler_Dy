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

    async def run(self) -> None:
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
                await self._dispatch()
                if self.request.download_media:
                    await self.storage.update_task(
                        status=CrawlTaskStatus.processing_media
                    )
                    if (
                        self.request.media_processing_mode
                        == MediaProcessingMode.batch
                    ):
                        await media_manager.enqueue_task(
                            task_id=self.task_id,
                            translate_subtitles=self.request.translate_subtitles,
                            language=self.request.transcription_language,
                            headers=self.media_headers,
                        )
                    await media_manager.wait_for_task(self.task_id)
            finally:
                self.media_headers = {}
                await client.close()
                self.client = None

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
        for raw_keyword in self.request.keywords:
            keyword = raw_keyword.strip()
            if not keyword or len(self.seen_aweme_ids) >= self.request.max_awemes:
                continue
            page = self.request.start_page
            search_id = ""
            while len(self.seen_aweme_ids) < self.request.max_awemes:
                response = await self.api.search(
                    keyword,
                    offset=(page - 1) * 10,
                    search_id=search_id,
                    publish_time=publish_time,
                )
                data = response.get("data")
                if not isinstance(data, list) or not data:
                    break
                search_id = str((response.get("extra") or {}).get("logid") or "")
                page_aweme_ids: list[str] = []
                for post in data:
                    mix_items = (post.get("aweme_mix_info") or {}).get("mix_items") or []
                    item = post.get("aweme_info") or (mix_items[0] if mix_items else None)
                    if not isinstance(item, dict):
                        continue
                    aweme_id = str(item.get("aweme_id") or "")
                    if not aweme_id or aweme_id in self.seen_aweme_ids:
                        continue
                    if len(self.seen_aweme_ids) >= self.request.max_awemes:
                        break
                    self.seen_aweme_ids.add(aweme_id)
                    await self._save_aweme(item, source_keyword=keyword)
                    page_aweme_ids.append(aweme_id)
                await self._batch_comments(page_aweme_ids, keyword)
                if not page_aweme_ids:
                    break
                page += 1
                await asyncio.sleep(self.request.request_interval_seconds)

    async def _details(self) -> None:
        aweme_ids: list[str] = []
        for value in self.request.video_ids:
            parsed = parse_video_info(value)
            if parsed.url_type == "short":
                parsed = parse_video_info(await self.api.resolve_short_url(value))
            if parsed.aweme_id and parsed.aweme_id not in aweme_ids:
                aweme_ids.append(parsed.aweme_id)
        aweme_ids = aweme_ids[: self.request.max_awemes]
        await self._fetch_details(aweme_ids, source_keyword="detail")
        await self._batch_comments(aweme_ids, "detail")

    async def _creators(self) -> None:
        for value in self.request.creator_ids:
            if len(self.seen_aweme_ids) >= self.request.max_awemes:
                break
            sec_user_id = parse_creator_info(value).sec_user_id
            source_keyword = "creator:" + anonymize_account_id(
                f"dy:sec_uid:{sec_user_id}", self.settings.SECRET_KEY
            )
            # Keep source-project privacy behaviour: request creator profile for
            # session validation, but do not persist the profile itself.
            await self.api.get_user_info(sec_user_id)
            cursor = ""
            seen_cursors: set[str] = set()
            while len(self.seen_aweme_ids) < self.request.max_awemes:
                response = await self.api.get_user_posts(sec_user_id, cursor)
                items = response.get("aweme_list") or []
                if not isinstance(items, list) or not items:
                    break
                ids = []
                for item in items:
                    aweme_id = str(item.get("aweme_id") or "")
                    if aweme_id and aweme_id not in self.seen_aweme_ids:
                        self.seen_aweme_ids.add(aweme_id)
                        ids.append(aweme_id)
                    if len(self.seen_aweme_ids) >= self.request.max_awemes:
                        break
                await self._fetch_details(ids, source_keyword=source_keyword)
                await self._batch_comments(ids, source_keyword)
                if response.get("has_more") not in (True, 1, "1"):
                    break
                next_cursor = str(response.get("max_cursor") or "")
                if not next_cursor or next_cursor == cursor or next_cursor in seen_cursors:
                    break
                seen_cursors.add(cursor)
                cursor = next_cursor

    async def _fetch_details(
        self, aweme_ids: list[str], *, source_keyword: str
    ) -> None:
        semaphore = asyncio.Semaphore(self.request.concurrency)

        async def fetch(aweme_id: str) -> None:
            async with semaphore:
                try:
                    item = await self.api.get_video(aweme_id)
                    if item:
                        self.seen_aweme_ids.add(aweme_id)
                        await self._save_aweme(item, source_keyword=source_keyword)
                except DataFetchError:
                    logger.exception("Failed to fetch Douyin aweme %s", aweme_id)
                await asyncio.sleep(self.request.request_interval_seconds)

        await asyncio.gather(*(fetch(aweme_id) for aweme_id in aweme_ids))

    async def _batch_comments(
        self, aweme_ids: list[str], source_keyword: str
    ) -> None:
        if not self.request.fetch_comments or not aweme_ids:
            return
        semaphore = asyncio.Semaphore(self.request.concurrency)

        async def fetch(aweme_id: str) -> None:
            async with semaphore:
                try:
                    await self.api.get_all_comments(
                        aweme_id,
                        interval=self.request.request_interval_seconds,
                        include_sub_comments=self.request.fetch_sub_comments,
                        callback=self.storage.save_comments,
                        max_count=self.request.max_comments_per_aweme,
                        keyword=source_keyword,
                    )
                except DataFetchError:
                    logger.exception("Failed to fetch comments for %s", aweme_id)

        await asyncio.gather(*(fetch(aweme_id) for aweme_id in aweme_ids))

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
        profile = await self.api.get_self_profile()
        if profile.get("status_code") not in (0, "0"):
            raise DataFetchError(f"抖音 {feed_type} 模式无法验证登录账号")
        _, sec_uid = self._extract_self_ids(profile)
        if not sec_uid:
            raise DataFetchError("抖音账号资料缺少稳定 sec_uid")
        account_hash = anonymize_account_id(
            f"dy:sec_uid:{sec_uid}", self.settings.SECRET_KEY
        )
        cursor: int | str = 0
        seen_cursors: set[str] = set()
        page = 1
        while len(self.seen_aweme_ids) < self.request.max_awemes:
            count = min(20, self.request.max_awemes - len(self.seen_aweme_ids))
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
                if not aweme_id or aweme_id in self.seen_aweme_ids:
                    continue
                self.seen_aweme_ids.add(aweme_id)
                await self._save_aweme(item, source_keyword=feed_type)
                await self.storage.save_action(account_hash, aweme_id, feed_type)
                page_ids.append(aweme_id)
                if len(self.seen_aweme_ids) >= self.request.max_awemes:
                    break
            await self._batch_comments(page_ids, feed_type)
            has_more = response.get("has_more") in (True, 1, "1")
            if not has_more or not page_ids:
                break
            cursor_key = "max_cursor" if feed_type == "liked" else "cursor"
            next_cursor = response.get(cursor_key)
            normalized_cursor = str(next_cursor)
            if next_cursor is None or normalized_cursor in seen_cursors or next_cursor == cursor:
                break
            seen_cursors.add(str(cursor))
            cursor = next_cursor
            page += 1
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
                translate_subtitles=self.request.translate_subtitles,
                language=self.request.transcription_language,
                headers=self.media_headers,
            )
