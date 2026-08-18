"""抖音互动浏览器步骤截图的采集、持久化与完整性校验。

通过 CDP 截取已登录浏览器的关键步骤画面，将图片写入受控目录并把
事件元数据落库，作为互动执行的审计证据；读取时做路径与哈希校验。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from crawler.bootstrap.database import engine
from crawler.bootstrap.settings import settings
from crawler.business.douyin.interactions.models import (
    DouyinInteraction,
    DouyinInteractionEvent,
)
from sqlmodel import Session

logger = logging.getLogger(__name__)


class InteractionScreenshotNotFoundError(FileNotFoundError):
    """截图不存在或路径越界时抛出的异常。"""


class InteractionScreenshotIntegrityError(RuntimeError):
    """截图文件大小或哈希校验失败时抛出的异常。"""


class InteractionStepRecorder:
    """持久化已登录浏览器关键步骤的审计证据，同时避免向外部暴露文件路径。"""

    mime_type = "image/jpeg"

    def __init__(self, interaction_id: uuid.UUID) -> None:
        """初始化记录器。

        参数：
            interaction_id: 所属互动任务 ID，用作截图目录名与事件关联键。
        """
        self.interaction_id = interaction_id

    async def record(self, page: Any, step: str, detail: str) -> None:
        """截取当前页面并持久化一步浏览器操作证据。

        截图与落库失败都只记录日志，绝不影响互动动作本身的成败。

        参数：
            page: Playwright 页面对象。
            step: 步骤名称，将作为事件名 `browser_<step>` 落库。
            detail: 步骤说明文本。
        """
        screenshot: bytes | None = None
        if settings.DOUYIN_INTERACTION_SCREENSHOTS_ENABLED:
            try:
                screenshot = await asyncio.wait_for(
                    self._capture_via_cdp(page),
                    timeout=settings.DOUYIN_INTERACTION_SCREENSHOT_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                logger.warning(
                    "Interaction screenshot capture failed at %s (%s)",
                    step,
                    type(exc).__name__,
                )
        try:
            await asyncio.to_thread(self._persist, step, detail, screenshot)
        except Exception:
            # 证据采集绝不能改变已确认的平台操作本身的成败。
            logger.exception("Could not persist interaction browser step %s", step)

    async def _capture_via_cdp(self, page: Any) -> bytes:
        """通过 CDP 截取当前页面 JPEG 图像并返回原始字节。"""
        cdp = await page.context.new_cdp_session(page)
        try:
            payload = await cdp.send(
                "Page.captureScreenshot",
                {
                    "format": "jpeg",
                    "quality": settings.DOUYIN_INTERACTION_SCREENSHOT_QUALITY,
                    "fromSurface": True,
                    "captureBeyondViewport": False,
                },
            )
        finally:
            await cdp.detach()
        encoded = payload.get("data")
        if not isinstance(encoded, str) or not encoded:
            raise RuntimeError("CDP screenshot returned no image data")
        return base64.b64decode(encoded, validate=True)

    def _persist(self, step: str, detail: str, screenshot: bytes | None) -> None:
        """将截图写入受控目录并把浏览器步骤事件落库（同步、线程内执行）。"""
        event_id = uuid.uuid4()
        relative_path: str | None = None
        target: Path | None = None
        digest: str | None = None
        if screenshot:
            relative = Path(str(self.interaction_id)) / f"{event_id}.jpg"
            target = _safe_screenshot_path(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".jpg.tmp")
            temporary.write_bytes(screenshot)
            os.replace(temporary, target)
            relative_path = relative.as_posix()
            digest = hashlib.sha256(screenshot).hexdigest()

        try:
            with Session(engine) as session:
                interaction = session.get(DouyinInteraction, self.interaction_id)
                if interaction is None:
                    if target is not None:
                        target.unlink(missing_ok=True)
                    return
                session.add(
                    DouyinInteractionEvent(
                        id=event_id,
                        interaction_id=interaction.id,
                        event=f"browser_{step}"[:64],
                        from_status=interaction.status,
                        to_status=interaction.status,
                        detail=detail[:1000],
                        attempt_number=interaction.attempt_count,
                        screenshot_path=relative_path,
                        screenshot_mime_type=self.mime_type if screenshot else None,
                        screenshot_size=len(screenshot) if screenshot else None,
                        screenshot_sha256=digest,
                    )
                )
                session.commit()
        except Exception:
            if target is not None:
                target.unlink(missing_ok=True)
            raise


def read_interaction_screenshot(event: DouyinInteractionEvent) -> bytes:
    """读取事件关联的截图文件并校验其完整性。

    参数：
        event: 携带截图元数据（路径、大小、SHA-256）的互动事件。

    返回：
        截图文件的原始字节。

    异常：
        InteractionScreenshotNotFoundError: 事件无截图、文件缺失或路径越界。
        InteractionScreenshotIntegrityError: 文件大小或哈希与记录不一致。
    """
    if not event.screenshot_path:
        raise InteractionScreenshotNotFoundError
    path = _safe_screenshot_path(Path(event.screenshot_path))
    try:
        payload = path.read_bytes()
    except (FileNotFoundError, OSError) as exc:
        raise InteractionScreenshotNotFoundError from exc
    if event.screenshot_size is not None and len(payload) != event.screenshot_size:
        raise InteractionScreenshotIntegrityError("截图文件大小校验失败")
    digest = hashlib.sha256(payload).hexdigest()
    if event.screenshot_sha256 and not hmac.compare_digest(
        digest, event.screenshot_sha256
    ):
        raise InteractionScreenshotIntegrityError("截图文件完整性校验失败")
    return payload


def _safe_screenshot_path(relative: Path) -> Path:
    """把相对路径解析到截图根目录内，拒绝绝对路径与目录穿越。"""
    if relative.is_absolute():
        raise InteractionScreenshotNotFoundError
    root = settings.DOUYIN_INTERACTION_SCREENSHOT_DIR.resolve()
    target = (root / relative).resolve()
    if root != target and root not in target.parents:
        raise InteractionScreenshotNotFoundError
    return target
