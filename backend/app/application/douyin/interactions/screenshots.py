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

from sqlmodel import Session

from app.bootstrap.settings import settings
from app.domain.douyin.interactions.models import (
    DouyinInteraction,
    DouyinInteractionEvent,
)
from app.framework.database import engine

logger = logging.getLogger(__name__)


class InteractionScreenshotNotFoundError(FileNotFoundError):
    pass


class InteractionScreenshotIntegrityError(RuntimeError):
    pass


class InteractionStepRecorder:
    """Persist authenticated browser-step evidence without exposing file paths."""

    mime_type = "image/jpeg"

    def __init__(self, interaction_id: uuid.UUID) -> None:
        self.interaction_id = interaction_id

    async def record(self, page: Any, step: str, detail: str) -> None:
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
            # Evidence collection must never change whether the confirmed platform
            # action itself succeeds or fails.
            logger.exception("Could not persist interaction browser step %s", step)

    async def _capture_via_cdp(self, page: Any) -> bytes:
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
    if relative.is_absolute():
        raise InteractionScreenshotNotFoundError
    root = settings.DOUYIN_INTERACTION_SCREENSHOT_DIR.resolve()
    target = (root / relative).resolve()
    if root != target and root not in target.parents:
        raise InteractionScreenshotNotFoundError
    return target
