from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

PREVIEW_COOKIE_NAME = "douyin_media_preview"
_TICKET_VERSION = "v1"
_STREAM_CHUNK_SIZE = 1024 * 1024


class RangeNotSatisfiable(ValueError):
    pass


@dataclass(frozen=True)
class MediaByteRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


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


def parse_range_header(value: str | None, file_size: int) -> MediaByteRange | None:
    if value is None:
        return None
    if file_size <= 0 or not value.startswith("bytes="):
        raise RangeNotSatisfiable
    spec = value[6:].strip()
    if not spec or "," in spec or "-" not in spec:
        raise RangeNotSatisfiable
    start_value, end_value = (part.strip() for part in spec.split("-", 1))
    try:
        if not start_value:
            suffix_length = int(end_value)
            if suffix_length <= 0:
                raise RangeNotSatisfiable
            start = max(file_size - suffix_length, 0)
            return MediaByteRange(start=start, end=file_size - 1)

        start = int(start_value)
        if start < 0 or start >= file_size:
            raise RangeNotSatisfiable
        if not end_value:
            return MediaByteRange(start=start, end=file_size - 1)
        end = int(end_value)
        if end < start:
            raise RangeNotSatisfiable
        return MediaByteRange(start=start, end=min(end, file_size - 1))
    except ValueError as exc:
        raise RangeNotSatisfiable from exc


def iter_local_file(
    path: Path,
    *,
    start: int,
    length: int,
    chunk_size: int = _STREAM_CHUNK_SIZE,
) -> Iterator[bytes]:
    remaining = length
    with path.open("rb") as media_file:
        media_file.seek(start)
        while remaining > 0:
            chunk = media_file.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _sign(payload: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
