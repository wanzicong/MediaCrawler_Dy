"""媒体对象存储服务：本地磁盘与 MinIO 双后端的存取、校验与清理。

处于应用服务层，封装 crawler.business.resources.storage 中的 MinIO 驱动，
为媒体管道（pipeline）、迁移（migration）与交付（delivery）提供统一的存储抽象。
"""

from __future__ import annotations

import asyncio
import hmac
import re
import tempfile
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from crawler.bootstrap.settings import settings
from crawler.business.douyin.media.models import DouyinMediaAsset, MediaStorageBackend
from crawler.business.resources.storage import (
    Minio,
    MinioClient,
    MinioClientFactory,
    MinioConfiguration,
    MinioConfigurationError,
    MinioDriver,
    MinioSdkConstructor,
    MinioTransportError,
    ObjectResponse,
    atomic_replace,
    resolve_within_root,
    validate_minio_endpoint,
)
from crawler.business.resources.storage import (
    S3Error as S3Error,
)


class MediaObjectNotFoundError(FileNotFoundError):
    """媒体文件/对象不存在。"""


class MediaStorageUnavailableError(RuntimeError):
    """存储后端不可用（连接失败、配置错误等）。"""


class MediaIntegrityError(MediaStorageUnavailableError):
    """上传后的对象完整性校验失败（归类为存储不可用）。"""


@dataclass(frozen=True)
class StoredMedia:
    """一次成功存储的结果描述：后端、位置、大小与内容摘要。"""

    backend: MediaStorageBackend  # 实际写入的存储后端
    local_path: str  # 本地文件路径（local 后端时有效）
    bucket: str  # MinIO bucket 名称（minio 后端时有效）
    object_key: str  # MinIO 对象 key（minio 后端时有效）
    file_size: int  # 文件大小（字节）
    sha256: str  # 文件内容 SHA-256 摘要


# MinIO 客户端工厂类型别名，便于依赖注入与测试替换
ClientFactory = MinioClientFactory


class MediaStorageService:
    """将媒体存储到本地磁盘或配置好的 S3 兼容 MinIO 服务。"""

    # 视为"对象不存在"的 S3 错误码集合
    _missing_codes = {"NoSuchBucket", "NoSuchKey", "NoSuchObject", "NotFound"}

    def __init__(self, client_factory: ClientFactory | None = None) -> None:
        self._client_factory = client_factory

    def _driver(self) -> MinioDriver:
        """按当前 settings 构造 MinIO 驱动（延迟读取配置）。"""

        def configuration() -> MinioConfiguration:
            return MinioConfiguration(
                endpoint=self._validated_endpoint(),
                access_key=settings.MINIO_ACCESS_KEY.get_secret_value(),
                secret_key=settings.MINIO_SECRET_KEY.get_secret_value(),
                secure=settings.MINIO_SECURE,
                region=settings.MINIO_REGION or None,
            )

        return MinioDriver(
            configuration,
            self._client_factory,
            sdk_constructor=cast(MinioSdkConstructor, Minio),
        )

    @staticmethod
    def object_key(task_id: uuid.UUID, aweme_id: str) -> str:
        """生成媒体在 MinIO 中的对象 key（按任务与作品分目录）。"""
        component = MediaStorageService._safe_component(task_id, aweme_id)
        return f"douyin/{task_id}/{component}/source.mp4"

    @staticmethod
    def _safe_component(task_id: uuid.UUID, aweme_id: str) -> str:
        """把 aweme_id 清洗为路径安全且带唯一后缀的目录名（防碰撞、防路径注入）。"""
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
        """解析目标存储后端及其 bucket 与对象 key（local 后端时后两者为空串）。"""
        resolved = MediaStorageBackend(backend or settings.MEDIA_STORAGE_BACKEND)
        if resolved == MediaStorageBackend.minio:
            return resolved, settings.MINIO_BUCKET, self.object_key(task_id, aweme_id)
        return resolved, "", ""

    async def ensure_minio_ready(self) -> None:
        """确认 MinIO 可用且目标 bucket 存在（不存在则创建）。

        异常：
            MediaStorageUnavailableError: MinIO 连接失败或配置错误。
        """
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
        """确保 MinIO 上存在与本地文件一致的已校验副本。

        远端已有大小与 sha256 元数据一致且内容校验通过的对象时直接复用，
        否则重新上传并校验；校验失败会删除远端对象。

        参数：
            asset: 媒体资产记录。
            source_path: 本地源文件路径。
            file_size: 期望的文件大小（字节）。
            sha256: 期望的 SHA-256 摘要。
            mime_type: 上传时声明的 Content-Type。

        返回：
            描述远端副本的 StoredMedia。

        异常：
            MediaObjectNotFoundError: 本地源文件缺失或为空。
            MediaIntegrityError: 上传后完整性校验失败。
            MediaStorageUnavailableError: MinIO 不可用。
        """
        return await asyncio.to_thread(
            self._ensure_verified_minio_copy,
            asset,
            source_path,
            file_size,
            sha256,
            mime_type,
        )

    async def remove_minio_copy(self, stored: StoredMedia) -> None:
        """删除 MinIO 上的副本（非 minio 后端或无 object_key 时为空操作）。"""
        if stored.backend != MediaStorageBackend.minio or not stored.object_key:
            return
        await asyncio.to_thread(
            self._remove_minio_object, stored.bucket, stored.object_key
        )

    async def existing(self, asset: DouyinMediaAsset) -> StoredMedia | None:
        """探测资产当前后端上是否已存在可用副本，不存在或为空时返回 None。"""
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

    def local_path(self, asset: DouyinMediaAsset) -> Path | None:
        """在配置的媒体根目录内解析资产的本地路径，越界或缺失时返回 None。"""
        return self._validated_local_path(asset)

    async def store(
        self,
        asset: DouyinMediaAsset,
        staged_path: Path,
        *,
        file_size: int,
        sha256: str,
        mime_type: str,
    ) -> StoredMedia:
        """把已暂存的文件写入目标存储后端。

        local 后端原子替换到目标路径；minio 后端上传对象并删除暂存文件。

        参数：
            asset: 媒体资产记录（决定存储后端与目标位置）。
            staged_path: 已下载完成的暂存文件路径。
            file_size: 文件大小（字节）。
            sha256: 文件内容 SHA-256 摘要。
            mime_type: 上传时声明的 Content-Type。

        返回：
            描述已存储媒体的 StoredMedia。

        异常：
            MediaStorageUnavailableError: MinIO 上传失败。
        """
        backend = MediaStorageBackend(asset.storage_backend)
        if backend == MediaStorageBackend.local:
            destination = self._local_destination(asset)
            destination.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(atomic_replace, staged_path, destination)
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
        """把资产物化为本地文件路径：local 直接返回原路径；minio 下载到临时目录，退出时自动清理。

        异常：
            MediaObjectNotFoundError: 本地文件缺失。
            MediaStorageUnavailableError: MinIO 下载失败或对象超过大小限制。
        """
        backend = MediaStorageBackend(asset.storage_backend)
        if backend == MediaStorageBackend.local:
            path = self._validated_local_path(asset)
            if path is None or not path.is_file():
                raise MediaObjectNotFoundError("Local media file not found")
            yield path
            return

        temp_root = settings.MEDIA_OUTPUT_DIR.resolve() / ".tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="minio-media-", dir=temp_root
        ) as folder:
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
        """打开 MinIO 对象的字节流响应，支持按偏移与长度分段读取。

        参数：
            asset: 媒体资产记录。
            offset: 起始字节偏移。
            length: 读取字节数，None 表示读到末尾。

        返回：
            MinIO 对象响应。

        异常：
            MediaObjectNotFoundError: 资产不在 MinIO、缺少 object_key 或对象不存在。
            MediaStorageUnavailableError: MinIO 请求失败。
        """
        if MediaStorageBackend(asset.storage_backend) != MediaStorageBackend.minio:
            raise MediaObjectNotFoundError("Media is not stored in MinIO")
        bucket = asset.storage_bucket or settings.MINIO_BUCKET
        if not asset.object_key:
            raise MediaObjectNotFoundError("MinIO object key is missing")
        try:
            client = self._client()
            if length is not None:
                response = self._driver().open_object(
                    client,
                    bucket,
                    asset.object_key,
                    offset=offset,
                    length=length,
                )
            elif offset:
                response = self._driver().open_object(
                    client,
                    bucket,
                    asset.object_key,
                    offset=offset,
                )
            else:
                response = self._driver().open_object(
                    client,
                    bucket,
                    asset.object_key,
                )
        except MinioTransportError as exc:
            self._raise_storage_error(exc)
        except Exception as exc:
            raise MediaStorageUnavailableError("MinIO download failed") from exc
        return response

    def object_size(self, asset: DouyinMediaAsset) -> int:
        """返回 MinIO 对象大小（字节），对象不存在或存储不可用时抛出对应异常。"""
        if MediaStorageBackend(asset.storage_backend) != MediaStorageBackend.minio:
            raise MediaObjectNotFoundError("Media is not stored in MinIO")
        bucket = asset.storage_bucket or settings.MINIO_BUCKET
        if not asset.object_key:
            raise MediaObjectNotFoundError("MinIO object key is missing")
        try:
            stat: Any = self._driver().stat_object(
                self._client(), bucket, asset.object_key
            )
        except MinioTransportError as exc:
            self._raise_storage_error(exc)
        except Exception as exc:
            raise MediaStorageUnavailableError("MinIO stat failed") from exc
        return int(stat.size)

    @staticmethod
    def iter_object(response: ObjectResponse) -> Iterator[bytes]:
        """迭代读取对象响应的字节内容，调用方负责消费完成后关闭。"""
        yield from MinioDriver.iter_object(response)

    def _client(self) -> MinioClient:
        """构造 MinIO 客户端，配置错误统一转换为 MediaStorageUnavailableError。"""
        try:
            return self._driver().client()
        except MinioConfigurationError as exc:
            raise MediaStorageUnavailableError(str(exc)) from None

    def _ensure_minio_ready(self) -> None:
        """同步检查 MinIO 连通性并确保目标 bucket 存在。"""
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
        """ensure_verified_minio_copy 的同步实现（由异步入口放到线程池执行）。"""
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
                self._driver().upload_file(
                    client,
                    bucket,
                    object_key,
                    source_path,
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
        except MinioTransportError as exc:
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
    def _ensure_bucket(client: MinioClient, bucket: str) -> None:
        """确保 bucket 存在（不存在则按配置区域创建）。"""
        MinioDriver.ensure_bucket(
            client,
            bucket,
            region=settings.MINIO_REGION or None,
        )

    def _stat_or_none(
        self, client: MinioClient, bucket: str, object_key: str
    ) -> Any | None:
        """查询对象元数据，不存在时返回 None。"""
        return self._driver().stat_or_none(client, bucket, object_key)

    @staticmethod
    def _verify_minio_object(
        client: MinioClient,
        bucket: str,
        object_key: str,
        expected_size: int,
        expected_sha256: str,
    ) -> bool:
        """重新读取对象内容并校验大小与 SHA-256 是否与期望一致。"""
        return MinioDriver.verify_object(
            client,
            bucket,
            object_key,
            expected_size,
            expected_sha256,
        )

    def _remove_minio_object(
        self,
        bucket: str,
        object_key: str,
        *,
        client: MinioClient | None = None,
    ) -> None:
        """删除 MinIO 对象；忽略"不存在"类错误，其余错误转为存储不可用。"""
        try:
            resolved_client = client or self._client()
            self._driver().remove_object(resolved_client, bucket, object_key)
        except MinioTransportError as exc:
            if exc.code not in self._missing_codes:
                raise MediaStorageUnavailableError("MinIO cleanup failed") from exc
        except Exception as exc:
            raise MediaStorageUnavailableError("MinIO cleanup failed") from exc

    @staticmethod
    def _validated_endpoint() -> str:
        """校验并规范化 MinIO endpoint 配置，非法时转为存储不可用异常。"""
        try:
            return validate_minio_endpoint(settings.MINIO_ENDPOINT)
        except MinioConfigurationError as exc:
            raise MediaStorageUnavailableError(str(exc)) from None

    @staticmethod
    def _local_destination(asset: DouyinMediaAsset) -> Path:
        """计算资产在本地媒体根目录下的目标路径。"""
        component = MediaStorageService._safe_component(asset.task_id, asset.aweme_id)
        return (
            settings.MEDIA_OUTPUT_DIR.resolve()
            / "douyin"
            / str(asset.task_id)
            / component
            / "source.mp4"
        )

    @staticmethod
    def _validated_local_path(asset: DouyinMediaAsset) -> Path | None:
        """把资产记录的 local_path 解析为媒体根目录内的安全路径。

        兼容历史遗留的 "/data/media/" 前缀（旧容器部署路径）；所有候选路径
        都必须位于 MEDIA_OUTPUT_DIR 之内，否则返回 None。
        """
        root = settings.MEDIA_OUTPUT_DIR.resolve()
        raw_path = asset.local_path.strip()
        if not raw_path:
            return None

        candidates = [Path(raw_path)]
        normalized = raw_path.replace("\\", "/")
        legacy_marker = "/data/media/"
        marker_index = normalized.casefold().find(legacy_marker)
        if marker_index >= 0:
            relative = normalized[marker_index + len(legacy_marker) :]
            candidates.append(root.joinpath(*relative.split("/")))

        for candidate in candidates:
            resolved = resolve_within_root(candidate, root)
            if resolved is not None:
                return resolved
        return None

    def _existing_minio(self, asset: DouyinMediaAsset) -> StoredMedia | None:
        """探测 MinIO 上的对象并组装 StoredMedia，对象不存在时返回 None。"""
        bucket = asset.storage_bucket or settings.MINIO_BUCKET
        try:
            stat: Any = self._driver().stat_object(
                self._client(), bucket, asset.object_key
            )
        except MinioTransportError as exc:
            if exc.code in self._missing_codes:
                return None
            raise MediaStorageUnavailableError("MinIO stat failed") from exc
        except Exception as exc:
            raise MediaStorageUnavailableError("MinIO stat failed") from exc
        metadata = getattr(stat, "metadata", {}) or {}
        # 优先取上传时写入的 sha256 元数据，缺失时回退到资产记录中的摘要
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
        """上传暂存文件到 MinIO 并写入 sha256 元数据，成功后删除暂存文件。"""
        bucket = asset.storage_bucket or settings.MINIO_BUCKET
        object_key = asset.object_key or self.object_key(asset.task_id, asset.aweme_id)
        try:
            client = self._client()
            self._driver().ensure_bucket(
                client,
                bucket,
                region=settings.MINIO_REGION or None,
            )
            self._driver().upload_file(
                client,
                bucket,
                object_key,
                staged_path,
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
        """下载 MinIO 对象到本地路径，对象超过配置大小限制时拒绝下载。"""
        bucket = asset.storage_bucket or settings.MINIO_BUCKET
        if not asset.object_key:
            raise MediaObjectNotFoundError("MinIO object key is missing")
        try:
            client = self._client()
            stat: Any = self._driver().stat_object(client, bucket, asset.object_key)
            if int(stat.size) > settings.MEDIA_MAX_SIZE_MB * 1024 * 1024:
                raise MediaStorageUnavailableError("Stored media exceeds size limit")
            self._driver().download_file(client, bucket, asset.object_key, path)
        except MinioTransportError as exc:
            self._raise_storage_error(exc)
        except MediaStorageUnavailableError:
            raise
        except Exception as exc:
            raise MediaStorageUnavailableError("MinIO download failed") from exc

    def _raise_storage_error(self, exc: MinioTransportError) -> None:
        """把 MinIO 传输错误按错误码转换为"不存在"或"不可用"异常。"""
        if exc.code in self._missing_codes:
            raise MediaObjectNotFoundError("MinIO object not found") from exc
        raise MediaStorageUnavailableError("MinIO request failed") from exc


# 全局共享的媒体存储服务实例
media_storage = MediaStorageService()
