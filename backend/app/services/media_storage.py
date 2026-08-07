from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
import tempfile
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

from minio import Minio
from minio.error import S3Error

from app.core.config import settings
from app.models import DouyinMediaAsset, MediaStorageBackend


class MediaObjectNotFoundError(FileNotFoundError):
    pass


class MediaStorageUnavailableError(RuntimeError):
    pass


class MediaIntegrityError(MediaStorageUnavailableError):
    pass


class ObjectResponse(Protocol):
    def stream(self, amt: int = 2**16) -> Iterator[bytes]: ...

    def close(self) -> None: ...

    def release_conn(self) -> None: ...


@dataclass(frozen=True)
class StoredMedia:
    backend: MediaStorageBackend
    local_path: str
    bucket: str
    object_key: str
    file_size: int
    sha256: str


ClientFactory = Callable[[], Minio]


class MediaStorageService:
    """Store media locally or in a configured S3-compatible MinIO service."""

    _missing_codes = {"NoSuchBucket", "NoSuchKey", "NoSuchObject", "NotFound"}

    def __init__(self, client_factory: ClientFactory | None = None) -> None:
        self._client_factory = client_factory

    @staticmethod
    def object_key(task_id: uuid.UUID, aweme_id: str) -> str:
        component = MediaStorageService._safe_component(task_id, aweme_id)
        return f"douyin/{task_id}/{component}/source.mp4"

    @staticmethod
    def _safe_component(task_id: uuid.UUID, aweme_id: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", aweme_id.strip())
        cleaned = cleaned[:150].strip("._-") or "aweme"
        suffix = uuid.uuid5(task_id, aweme_id).hex[:16]
        return f"{cleaned}-{suffix}"

    def location_values(
        self,
        *,
        task_id: uuid.UUID,
        aweme_id: str,
        backend: MediaStorageBackend | str | None,
    ) -> tuple[MediaStorageBackend, str, str]:
        resolved = MediaStorageBackend(backend or settings.MEDIA_STORAGE_BACKEND)
        if resolved == MediaStorageBackend.minio:
            return resolved, settings.MINIO_BUCKET, self.object_key(task_id, aweme_id)
        return resolved, "", ""

    async def ensure_minio_ready(self) -> None:
        await asyncio.to_thread(self._ensure_minio_ready)

    async def ensure_verified_minio_copy(
        self,
        asset: DouyinMediaAsset,
        source_path: Path,
        *,
        file_size: int,
        sha256: str,
        mime_type: str,
    ) -> StoredMedia:
        return await asyncio.to_thread(
            self._ensure_verified_minio_copy,
            asset,
            source_path,
            file_size,
            sha256,
            mime_type,
        )

    async def remove_minio_copy(self, stored: StoredMedia) -> None:
        if stored.backend != MediaStorageBackend.minio or not stored.object_key:
            return
        await asyncio.to_thread(
            self._remove_minio_object, stored.bucket, stored.object_key
        )

    async def existing(self, asset: DouyinMediaAsset) -> StoredMedia | None:
        backend = MediaStorageBackend(asset.storage_backend)
        if backend == MediaStorageBackend.local:
            path = self._validated_local_path(asset) or self._local_destination(asset)
            if path is None or not path.is_file() or path.stat().st_size <= 0:
                return None
            return StoredMedia(
                backend=backend,
                local_path=str(path),
                bucket="",
                object_key="",
                file_size=path.stat().st_size,
                sha256=asset.sha256,
            )
        if not asset.object_key:
            return None
        return await asyncio.to_thread(self._existing_minio, asset)

    async def store(
        self,
        asset: DouyinMediaAsset,
        staged_path: Path,
        *,
        file_size: int,
        sha256: str,
        mime_type: str,
    ) -> StoredMedia:
        backend = MediaStorageBackend(asset.storage_backend)
        if backend == MediaStorageBackend.local:
            destination = self._local_destination(asset)
            destination.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(os.replace, staged_path, destination)
            return StoredMedia(
                backend=backend,
                local_path=str(destination),
                bucket="",
                object_key="",
                file_size=file_size,
                sha256=sha256,
            )
        return await asyncio.to_thread(
            self._store_minio,
            asset,
            staged_path,
            file_size,
            sha256,
            mime_type,
        )

    @asynccontextmanager
    async def materialize(self, asset: DouyinMediaAsset) -> AsyncIterator[Path]:
        backend = MediaStorageBackend(asset.storage_backend)
        if backend == MediaStorageBackend.local:
            path = self._validated_local_path(asset)
            if path is None or not path.is_file():
                raise MediaObjectNotFoundError("Local media file not found")
            yield path
            return

        temp_root = settings.MEDIA_OUTPUT_DIR.resolve() / ".tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="minio-media-", dir=temp_root) as folder:
            path = Path(folder) / "source.mp4"
            await asyncio.to_thread(self._download_minio, asset, path)
            yield path

    def open_object(
        self,
        asset: DouyinMediaAsset,
        *,
        offset: int = 0,
        length: int | None = None,
    ) -> ObjectResponse:
        if MediaStorageBackend(asset.storage_backend) != MediaStorageBackend.minio:
            raise MediaObjectNotFoundError("Media is not stored in MinIO")
        bucket = asset.storage_bucket or settings.MINIO_BUCKET
        if not asset.object_key:
            raise MediaObjectNotFoundError("MinIO object key is missing")
        try:
            if length is not None:
                response = self._client().get_object(
                    bucket, asset.object_key, offset=offset, length=length
                )
            elif offset:
                response = self._client().get_object(
                    bucket, asset.object_key, offset=offset
                )
            else:
                response = self._client().get_object(bucket, asset.object_key)
        except S3Error as exc:
            self._raise_storage_error(exc)
        except Exception as exc:
            raise MediaStorageUnavailableError("MinIO download failed") from exc
        return cast(ObjectResponse, response)

    def object_size(self, asset: DouyinMediaAsset) -> int:
        if MediaStorageBackend(asset.storage_backend) != MediaStorageBackend.minio:
            raise MediaObjectNotFoundError("Media is not stored in MinIO")
        bucket = asset.storage_bucket or settings.MINIO_BUCKET
        if not asset.object_key:
            raise MediaObjectNotFoundError("MinIO object key is missing")
        try:
            stat: Any = self._client().stat_object(bucket, asset.object_key)
        except S3Error as exc:
            self._raise_storage_error(exc)
        except Exception as exc:
            raise MediaStorageUnavailableError("MinIO stat failed") from exc
        return int(stat.size)

    @staticmethod
    def iter_object(response: ObjectResponse) -> Iterator[bytes]:
        try:
            yield from response.stream(amt=1024 * 1024)
        finally:
            response.close()
            response.release_conn()

    def _client(self) -> Minio:
        if self._client_factory is not None:
            return self._client_factory()
        endpoint = self._validated_endpoint()
        access_key = settings.MINIO_ACCESS_KEY.get_secret_value()
        secret_key = settings.MINIO_SECRET_KEY.get_secret_value()
        if not access_key or not secret_key:
            raise MediaStorageUnavailableError("MinIO credentials are not configured")
        return Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=settings.MINIO_SECURE,
            region=settings.MINIO_REGION or None,
        )

    def _ensure_minio_ready(self) -> None:
        try:
            client = self._client()
            self._ensure_bucket(client, settings.MINIO_BUCKET)
        except MediaStorageUnavailableError:
            raise
        except Exception as exc:
            raise MediaStorageUnavailableError("MinIO is unavailable") from exc

    def _ensure_verified_minio_copy(
        self,
        asset: DouyinMediaAsset,
        source_path: Path,
        file_size: int,
        sha256: str,
        mime_type: str,
    ) -> StoredMedia:
        if not source_path.is_file() or file_size <= 0:
            raise MediaObjectNotFoundError("Local media file not found")
        bucket = settings.MINIO_BUCKET
        object_key = self.object_key(asset.task_id, asset.aweme_id)
        try:
            client = self._client()
            self._ensure_bucket(client, bucket)
            stat = self._stat_or_none(client, bucket, object_key)
            metadata = getattr(stat, "metadata", {}) or {} if stat else {}
            remote_digest = str(metadata.get("x-amz-meta-sha256") or "")
            reusable = bool(
                stat
                and int(stat.size) == file_size
                and hmac.compare_digest(remote_digest, sha256)
                and self._verify_minio_object(
                    client, bucket, object_key, file_size, sha256
                )
            )
            if not reusable:
                client.fput_object(
                    bucket,
                    object_key,
                    str(source_path),
                    content_type=mime_type or "application/octet-stream",
                    metadata={"sha256": sha256},
                )
                if not self._verify_minio_object(
                    client, bucket, object_key, file_size, sha256
                ):
                    self._remove_minio_object(bucket, object_key, client=client)
                    raise MediaIntegrityError(
                        "MinIO object integrity verification failed"
                    )
        except MediaIntegrityError:
            raise
        except S3Error as exc:
            raise MediaStorageUnavailableError("MinIO upload failed") from exc
        except MediaStorageUnavailableError:
            raise
        except Exception as exc:
            raise MediaStorageUnavailableError("MinIO upload failed") from exc
        return StoredMedia(
            backend=MediaStorageBackend.minio,
            local_path="",
            bucket=bucket,
            object_key=object_key,
            file_size=file_size,
            sha256=sha256,
        )

    @staticmethod
    def _ensure_bucket(client: Minio, bucket: str) -> None:
        if client.bucket_exists(bucket):
            return
        try:
            client.make_bucket(bucket, location=settings.MINIO_REGION or None)
        except S3Error as exc:
            if exc.code not in {"BucketAlreadyExists", "BucketAlreadyOwnedByYou"}:
                raise

    def _stat_or_none(self, client: Minio, bucket: str, object_key: str) -> Any | None:
        try:
            return client.stat_object(bucket, object_key)
        except S3Error as exc:
            if exc.code in self._missing_codes:
                return None
            raise
        except KeyError:
            return None

    @staticmethod
    def _verify_minio_object(
        client: Minio,
        bucket: str,
        object_key: str,
        expected_size: int,
        expected_sha256: str,
    ) -> bool:
        stat: Any = client.stat_object(bucket, object_key)
        if int(stat.size) != expected_size:
            return False
        response: Any = client.get_object(bucket, object_key)
        digest = hashlib.sha256()
        actual_size = 0
        try:
            for chunk in response.stream(amt=1024 * 1024):
                digest.update(chunk)
                actual_size += len(chunk)
        finally:
            response.close()
            response.release_conn()
        return actual_size == expected_size and hmac.compare_digest(
            digest.hexdigest(), expected_sha256
        )

    def _remove_minio_object(
        self,
        bucket: str,
        object_key: str,
        *,
        client: Minio | None = None,
    ) -> None:
        try:
            (client or self._client()).remove_object(bucket, object_key)
        except S3Error as exc:
            if exc.code not in self._missing_codes:
                raise MediaStorageUnavailableError("MinIO cleanup failed") from exc
        except Exception as exc:
            raise MediaStorageUnavailableError("MinIO cleanup failed") from exc

    @staticmethod
    def _validated_endpoint() -> str:
        endpoint = settings.MINIO_ENDPOINT.strip()
        parsed = urlsplit(f"//{endpoint}")
        if (
            not endpoint
            or "://" in endpoint
            or not parsed.hostname
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise MediaStorageUnavailableError(
                "MINIO_ENDPOINT must be a host name with an optional port"
            )
        return endpoint

    @staticmethod
    def _local_destination(asset: DouyinMediaAsset) -> Path:
        component = MediaStorageService._safe_component(
            asset.task_id, asset.aweme_id
        )
        return (
            settings.MEDIA_OUTPUT_DIR.resolve()
            / "douyin"
            / str(asset.task_id)
            / component
            / "source.mp4"
        )

    @staticmethod
    def _validated_local_path(asset: DouyinMediaAsset) -> Path | None:
        path = Path(asset.local_path).resolve() if asset.local_path else None
        root = settings.MEDIA_OUTPUT_DIR.resolve()
        if not path or not path.is_relative_to(root):
            return None
        return path

    def _existing_minio(self, asset: DouyinMediaAsset) -> StoredMedia | None:
        bucket = asset.storage_bucket or settings.MINIO_BUCKET
        try:
            stat: Any = self._client().stat_object(bucket, asset.object_key)
        except S3Error as exc:
            if exc.code in self._missing_codes:
                return None
            raise MediaStorageUnavailableError("MinIO stat failed") from exc
        except Exception as exc:
            raise MediaStorageUnavailableError("MinIO stat failed") from exc
        metadata = getattr(stat, "metadata", {}) or {}
        digest = str(metadata.get("x-amz-meta-sha256") or asset.sha256)
        return StoredMedia(
            backend=MediaStorageBackend.minio,
            local_path="",
            bucket=bucket,
            object_key=asset.object_key,
            file_size=int(stat.size),
            sha256=digest,
        )

    def _store_minio(
        self,
        asset: DouyinMediaAsset,
        staged_path: Path,
        file_size: int,
        sha256: str,
        mime_type: str,
    ) -> StoredMedia:
        bucket = asset.storage_bucket or settings.MINIO_BUCKET
        object_key = asset.object_key or self.object_key(asset.task_id, asset.aweme_id)
        try:
            client = self._client()
            if not client.bucket_exists(bucket):
                try:
                    client.make_bucket(bucket, location=settings.MINIO_REGION or None)
                except S3Error as exc:
                    if exc.code not in {"BucketAlreadyExists", "BucketAlreadyOwnedByYou"}:
                        raise
            client.fput_object(
                bucket,
                object_key,
                str(staged_path),
                content_type=mime_type or "application/octet-stream",
                metadata={"sha256": sha256},
            )
        except Exception as exc:
            raise MediaStorageUnavailableError("MinIO upload failed") from exc
        staged_path.unlink(missing_ok=True)
        return StoredMedia(
            backend=MediaStorageBackend.minio,
            local_path="",
            bucket=bucket,
            object_key=object_key,
            file_size=file_size,
            sha256=sha256,
        )

    def _download_minio(self, asset: DouyinMediaAsset, path: Path) -> None:
        bucket = asset.storage_bucket or settings.MINIO_BUCKET
        if not asset.object_key:
            raise MediaObjectNotFoundError("MinIO object key is missing")
        try:
            client = self._client()
            stat: Any = client.stat_object(bucket, asset.object_key)
            if int(stat.size) > settings.MEDIA_MAX_SIZE_MB * 1024 * 1024:
                raise MediaStorageUnavailableError("Stored media exceeds size limit")
            client.fget_object(bucket, asset.object_key, str(path))
        except S3Error as exc:
            self._raise_storage_error(exc)
        except MediaStorageUnavailableError:
            raise
        except Exception as exc:
            raise MediaStorageUnavailableError("MinIO download failed") from exc

    def _raise_storage_error(self, exc: S3Error) -> None:
        if exc.code in self._missing_codes:
            raise MediaObjectNotFoundError("MinIO object not found") from exc
        raise MediaStorageUnavailableError("MinIO request failed") from exc


media_storage = MediaStorageService()
