"""为 HTTP 适配层准备带鉴权的本地/MinIO 媒体下载与预览交付。"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from crawler.bootstrap.settings import settings
from crawler.business.douyin.media.models import (
    DouyinMediaAsset,
    MediaDownloadStatus,
    MediaStorageBackend,
)
from crawler.business.douyin.media.preview import (
    PREVIEW_COOKIE_NAME,
    RangeNotSatisfiable,
    create_preview_ticket,
    iter_local_file,
    parse_range_header,
    validate_preview_ticket,
)
from crawler.business.douyin.media.query_service import require_media_asset_access
from crawler.business.douyin.media.storage import (
    MediaObjectNotFoundError,
    MediaStorageUnavailableError,
    media_storage,
)
from crawler.business.errors import (
    ConflictError,
    ResourceNotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
)
from sqlmodel import Session


@dataclass(frozen=True)
class MediaDelivery:
    """一次媒体交付的描述：本地文件直发或字节流，由 HTTP 适配层落地为响应。"""

    kind: Literal["file", "stream"]  # 交付方式：file 本地文件直发，stream 迭代字节流
    media_type: str  # 响应 Content-Type
    headers: dict[str, str] = field(default_factory=dict)  # 附加响应头
    path: Path | None = None  # kind=file 时的本地文件路径
    filename: str | None = None  # kind=file 时的下载文件名
    body: Iterator[bytes] | None = None  # kind=stream 时的字节流迭代器
    status_code: int = 200  # HTTP 状态码（Range 请求时为 206）


@dataclass(frozen=True)
class PreviewSession:
    """预览会话：HTTP 层据此向客户端写回预览 cookie。"""

    cookie_name: str  # cookie 名称
    cookie_value: str  # 签发的预览凭证
    max_age: int  # cookie 有效期（秒）
    secure: bool  # 是否仅通过 HTTPS 发送
    path: str  # cookie 生效路径（限定为对应预览接口）


class MediaRangeNotSatisfiableError(Exception):
    """请求的字节区间无法满足时抛出（HTTP 层据此返回 416）。"""

    def __init__(self, file_size: int) -> None:
        super().__init__("Requested media range is not satisfiable")
        self.file_size = (
            file_size  # 媒体文件总大小，用于构造 416 的 Content-Range 响应头
        )


def prepare_download_delivery(
    session: Session,
    *,
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
    owner_id: uuid.UUID | None,
) -> MediaDelivery:
    """准备整文件下载交付：按存储后端选择本地文件直发或 MinIO 字节流。

    参数：
        session: 数据库会话。
        task_id: 所属采集任务 ID。
        asset_id: 媒体资产 ID。
        owner_id: 当前用户 ID，用于归属校验。

    返回：
        描述本次下载响应的 MediaDelivery。

    异常：
        ResourceNotFoundError: 资产不存在、无权访问，或已下载的文件/对象缺失。
        ServiceUnavailableError: MinIO 存储不可用。
    """
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
    """校验资产可预览并签发预览会话 cookie。

    参数：
        session: 数据库会话。
        task_id: 所属采集任务 ID。
        asset_id: 媒体资产 ID。
        owner_id: 当前用户 ID，用于归属校验。

    返回：
        预览会话 cookie 配置。

    异常：
        ConflictError: 媒体尚未下载完成。
        ResourceNotFoundError: 本地文件缺失或 MinIO 对象不可用/为空。
    """
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
    """基于预览凭证准备支持 Range 的流式预览交付。

    参数：
        session: 数据库会话。
        task_id: 所属采集任务 ID。
        asset_id: 媒体资产 ID。
        preview_ticket: 预览 cookie 中的凭证。
        range_header: 请求 Range 头，None 表示返回完整内容。

    返回：
        字节流形式的 MediaDelivery；带合法 Range 时状态码为 206 并附 Content-Range。

    异常：
        UnauthorizedError: 预览凭证无效或已过期。
        ResourceNotFoundError: 资产不存在或媒体文件/对象缺失。
        ConflictError: 媒体尚未下载完成。
        MediaRangeNotSatisfiableError: Range 区间超出文件大小。
    """
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
    """返回本地预览文件路径，文件缺失或为空时抛出 ResourceNotFoundError。"""
    path = media_storage.local_path(asset)
    if path is None or not path.is_file() or path.stat().st_size <= 0:
        raise ResourceNotFoundError("Downloaded media file not found")
    return path


def _minio_preview_size(asset: DouyinMediaAsset) -> int:
    """返回 MinIO 对象大小（字节），对象缺失、为空或存储不可用时抛出对应异常。"""
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
