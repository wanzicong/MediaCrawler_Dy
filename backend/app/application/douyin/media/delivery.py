"""Prepare authenticated local and MinIO media deliveries for HTTP adapters."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from sqlmodel import Session

from app.application.douyin.media.preview import (
    PREVIEW_COOKIE_NAME,
    RangeNotSatisfiable,
    create_preview_ticket,
    iter_local_file,
    parse_range_header,
    validate_preview_ticket,
)
from app.application.douyin.media.query_service import require_media_asset_access
from app.application.douyin.media.storage import (
    MediaObjectNotFoundError,
    MediaStorageUnavailableError,
    media_storage,
)
from app.application.errors import (
    ConflictError,
    ResourceNotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
)
from app.bootstrap.settings import settings
from app.domain.douyin.media.models import (
    DouyinMediaAsset,
    MediaDownloadStatus,
    MediaStorageBackend,
)


@dataclass(frozen=True)
class MediaDelivery:
    kind: Literal["file", "stream"]
    media_type: str
    headers: dict[str, str] = field(default_factory=dict)
    path: Path | None = None
    filename: str | None = None
    body: Iterator[bytes] | None = None
    status_code: int = 200


@dataclass(frozen=True)
class PreviewSession:
    cookie_name: str
    cookie_value: str
    max_age: int
    secure: bool
    path: str


class MediaRangeNotSatisfiableError(Exception):
    def __init__(self, file_size: int) -> None:
        super().__init__("Requested media range is not satisfiable")
        self.file_size = file_size


def prepare_download_delivery(
    session: Session,
    *,
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> MediaDelivery:
    asset = require_media_asset_access(
        session,
        task_id=task_id,
        asset_id=asset_id,
        owner_id=owner_id,
    )
    if asset.storage_backend == MediaStorageBackend.minio.value:
        try:
            remote = media_storage.open_object(asset)
        except MediaObjectNotFoundError as exc:
            raise ResourceNotFoundError("Downloaded media object not found") from exc
        except MediaStorageUnavailableError as exc:
            raise ServiceUnavailableError("Media storage is unavailable") from exc
        filename = quote(f"douyin-{asset.aweme_id}.mp4")
        return MediaDelivery(
            kind="stream",
            body=media_storage.iter_object(remote),
            media_type=asset.mime_type or "application/octet-stream",
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
                **(
                    {"Content-Length": str(asset.file_size)}
                    if asset.file_size > 0
                    else {}
                ),
            },
        )
    path = media_storage.local_path(asset)
    if path is None or not path.is_file():
        raise ResourceNotFoundError("Downloaded media file not found")
    return MediaDelivery(
        kind="file",
        path=path,
        media_type=asset.mime_type or "application/octet-stream",
        filename=f"douyin-{asset.aweme_id}{path.suffix or '.mp4'}",
        headers={"Cache-Control": "private, no-store"},
    )


def prepare_preview_session(
    session: Session,
    *,
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> PreviewSession:
    asset = require_media_asset_access(
        session,
        task_id=task_id,
        asset_id=asset_id,
        owner_id=owner_id,
    )
    if asset.status != MediaDownloadStatus.downloaded.value:
        raise ConflictError("Media has not been downloaded")
    if asset.storage_backend == MediaStorageBackend.minio.value:
        _minio_preview_size(asset)
    else:
        _local_preview_path(asset)
    return PreviewSession(
        cookie_name=PREVIEW_COOKIE_NAME,
        cookie_value=create_preview_ticket(task_id, asset_id),
        max_age=settings.MEDIA_PREVIEW_TTL_SECONDS,
        secure=settings.ENVIRONMENT != "local",
        path=(f"{settings.API_V1_STR}/douyin/tasks/{task_id}/media/{asset_id}/preview"),
    )


def prepare_preview_delivery(
    session: Session,
    *,
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
    preview_ticket: str | None,
    range_header: str | None,
) -> MediaDelivery:
    if not validate_preview_ticket(preview_ticket, task_id, asset_id):
        raise UnauthorizedError("Invalid media preview session")
    asset = session.get(DouyinMediaAsset, asset_id)
    if asset is None or asset.task_id != task_id:
        raise ResourceNotFoundError("Douyin media asset not found")
    if asset.status != MediaDownloadStatus.downloaded.value:
        raise ConflictError("Media has not been downloaded")
    path: Path | None = None
    if asset.storage_backend == MediaStorageBackend.minio.value:
        file_size = (
            asset.file_size if asset.file_size > 0 else _minio_preview_size(asset)
        )
    else:
        path = _local_preview_path(asset)
        file_size = path.stat().st_size
    try:
        byte_range = parse_range_header(range_header, file_size)
    except RangeNotSatisfiable as exc:
        raise MediaRangeNotSatisfiableError(file_size) from exc
    start = byte_range.start if byte_range else 0
    length = byte_range.length if byte_range else file_size
    if path is not None:
        body = iter_local_file(path, start=start, length=length)
    else:
        try:
            remote = media_storage.open_object(asset, offset=start, length=length)
        except MediaObjectNotFoundError as exc:
            raise ResourceNotFoundError("Downloaded media object not found") from exc
        except MediaStorageUnavailableError as exc:
            raise ServiceUnavailableError("Media storage is unavailable") from exc
        body = media_storage.iter_object(remote)
    filename = quote(f"douyin-{asset.aweme_id}.mp4")
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "Content-Disposition": f"inline; filename*=UTF-8''{filename}",
        "Content-Length": str(length),
    }
    if byte_range:
        headers["Content-Range"] = (
            f"bytes {byte_range.start}-{byte_range.end}/{file_size}"
        )
    return MediaDelivery(
        kind="stream",
        body=body,
        media_type=asset.mime_type or "application/octet-stream",
        headers=headers,
        status_code=206 if byte_range else 200,
    )


def _local_preview_path(asset: DouyinMediaAsset) -> Path:
    path = media_storage.local_path(asset)
    if path is None or not path.is_file() or path.stat().st_size <= 0:
        raise ResourceNotFoundError("Downloaded media file not found")
    return path


def _minio_preview_size(asset: DouyinMediaAsset) -> int:
    try:
        file_size = media_storage.object_size(asset)
    except MediaObjectNotFoundError as exc:
        raise ResourceNotFoundError("Downloaded media object not found") from exc
    except MediaStorageUnavailableError as exc:
        raise ServiceUnavailableError("Media storage is unavailable") from exc
    if file_size <= 0:
        raise ResourceNotFoundError("Downloaded media object is empty")
    return file_size


__all__ = [
    "MediaDelivery",
    "MediaRangeNotSatisfiableError",
    "PreviewSession",
    "prepare_download_delivery",
    "prepare_preview_delivery",
    "prepare_preview_session",
]
