"""Preview-ticket signing and byte-range streaming for Douyin media."""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid

from app.bootstrap.settings import settings
from app.framework.http.ranges import (
    MediaByteRange,
    RangeNotSatisfiable,
    iter_local_file,
    parse_range_header,
)

PREVIEW_COOKIE_NAME = "douyin_media_preview"
_TICKET_VERSION = "v1"


def create_preview_ticket(
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
    *,
    now: int | None = None,
) -> str:
    issued_at = int(time.time()) if now is None else now
    expires_at = issued_at + settings.MEDIA_PREVIEW_TTL_SECONDS
    payload = f"{_TICKET_VERSION}:{task_id}:{asset_id}:{expires_at}"
    return f"{payload}:{_sign(payload)}"


def validate_preview_ticket(
    ticket: str | None,
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
    *,
    now: int | None = None,
) -> bool:
    if not ticket:
        return False
    try:
        version, task_value, asset_value, expires_value, signature = ticket.split(":")
        expires_at = int(expires_value)
    except (TypeError, ValueError):
        return False
    payload = f"{version}:{task_value}:{asset_value}:{expires_value}"
    current_time = int(time.time()) if now is None else now
    return (
        version == _TICKET_VERSION
        and task_value == str(task_id)
        and asset_value == str(asset_id)
        and expires_at >= current_time
        and hmac.compare_digest(signature, _sign(payload))
    )


def _sign(payload: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


__all__ = [
    "MediaByteRange",
    "PREVIEW_COOKIE_NAME",
    "RangeNotSatisfiable",
    "create_preview_ticket",
    "iter_local_file",
    "parse_range_header",
    "validate_preview_ticket",
]
