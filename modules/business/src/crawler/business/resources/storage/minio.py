"""通用的 S3 兼容 MinIO 传输驱动。

本模块刻意不了解媒体资产、抖音业务键、数据库模型或应用层错误类型等概念，
只暴露底层对象存储操作，由应用层门面（facade）将其组合为业务用例。
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeAlias, cast
from urllib.parse import urlsplit

from minio import Minio
from minio.error import S3Error
from urllib3 import PoolManager, Retry, Timeout


class MinioConfigurationError(ValueError):
    """MinIO 端点或凭证配置不完整、格式非法。"""


class ObjectResponse(Protocol):
    """MinIO 对象读取响应的结构化协议：流式读取并支持显式释放连接。"""

    def stream(self, amt: int = 2**16) -> Iterator[bytes]: ...

    def close(self) -> None: ...

    def release_conn(self) -> None: ...


class MinioClient(Protocol):
    """存储驱动实际用到的 MinIO SDK 操作集合的结构化边界。"""

    def bucket_exists(self, bucket_name: str) -> bool: ...

    def make_bucket(
        self,
        bucket_name: str,
        location: str | None = None,
    ) -> Any: ...

    def stat_object(self, bucket_name: str, object_name: str) -> Any: ...

    def remove_object(self, bucket_name: str, object_name: str) -> Any: ...

    def get_object(
        self,
        bucket_name: str,
        object_name: str,
        offset: int = 0,
        length: int | None = None,
    ) -> Any: ...

    def fput_object(
        self,
        bucket_name: str,
        object_name: str,
        file_path: str,
        *,
        content_type: str,
        metadata: dict[str, str | list[str] | tuple[str]],
    ) -> Any: ...

    def fget_object(
        self,
        bucket_name: str,
        object_name: str,
        file_path: str,
    ) -> Any: ...


# 应用代码捕获框架层命名的传输错误；底层 SDK 异常对象保持不变，
# 以兼容既有调用方与测试替身（test double）
MinioTransportError: TypeAlias = S3Error


@dataclass(frozen=True)
class MinioConfiguration:
    """MinIO 连接配置。"""

    endpoint: str  # 服务地址（主机名加可选端口，不含协议头）
    access_key: str  # 访问密钥（access key）
    secret_key: str  # 私有密钥（secret key）
    secure: bool  # 是否使用 HTTPS
    region: str | None = None  # 存储区域，可空


MinioClientFactory = Callable[[], MinioClient]
MinioSdkConstructor = Callable[..., MinioClient]
ConfigurationProvider = Callable[[], MinioConfiguration]


def validate_minio_endpoint(endpoint: str) -> str:
    """仅接受「主机名加可选端口」形式的端点，与 Minio SDK 的入参约定保持一致。

    参数：
        endpoint: 原始端点字符串。

    返回：
        去除首尾空白后的端点。

    异常：
        MinioConfigurationError: 端点为空或包含协议头、路径、查询串、
            认证信息等非法成分时抛出。
    """

    normalized = endpoint.strip()
    parsed = urlsplit(f"//{normalized}")
    if (
        not normalized
        or "://" in normalized
        or not parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise MinioConfigurationError(
            "MINIO_ENDPOINT must be a host name with an optional port"
        )
    return normalized


class MinioDriver:
    """轻量的同步 MinIO SDK 适配器，HTTP 超时与重试行为固定可控。"""

    # 视为「对象不存在」的 S3 错误码集合
    missing_codes = frozenset({"NoSuchBucket", "NoSuchKey", "NoSuchObject", "NotFound"})

    def __init__(
        self,
        configuration_provider: ConfigurationProvider,
        client_factory: MinioClientFactory | None = None,
        *,
        sdk_constructor: MinioSdkConstructor | None = None,
    ) -> None:
        """初始化驱动。

        参数：
            configuration_provider: 惰性提供连接配置的回调。
            client_factory: 可选的客户端工厂，提供后优先于 sdk_constructor。
            sdk_constructor: 可选的 SDK 构造器替换点，便于测试注入。
        """
        self._configuration_provider = configuration_provider
        self._client_factory = client_factory
        self._sdk_constructor = sdk_constructor

    def client(self) -> MinioClient:
        """构建一个 MinioClient；凭证缺失或端点非法时抛出 MinioConfigurationError。"""
        if self._client_factory is not None:
            return self._client_factory()
        configuration = self._configuration_provider()
        endpoint = validate_minio_endpoint(configuration.endpoint)
        if not configuration.access_key or not configuration.secret_key:
            raise MinioConfigurationError("MinIO credentials are not configured")
        constructor = self._sdk_constructor or Minio
        return cast(
            MinioClient,
            constructor(
                endpoint,
                access_key=configuration.access_key,
                secret_key=configuration.secret_key,
                secure=configuration.secure,
                region=configuration.region,
                http_client=PoolManager(
                    timeout=Timeout(connect=3.0, read=30.0),
                    retries=Retry(total=0, connect=0, read=0, redirect=0),
                ),
            ),
        )

    @staticmethod
    def ensure_bucket(client: MinioClient, bucket: str, *, region: str | None) -> None:
        """确保存储桶存在，不存在则创建；并发创建导致的「已存在」错误被忽略。"""
        if client.bucket_exists(bucket):
            return
        try:
            client.make_bucket(bucket, location=region)
        except S3Error as exc:
            if exc.code not in {"BucketAlreadyExists", "BucketAlreadyOwnedByYou"}:
                raise

    @classmethod
    def stat_or_none(
        cls, client: MinioClient, bucket: str, object_key: str
    ) -> Any | None:
        """获取对象元信息；对象不存在时返回 None 而不是抛出异常。"""
        try:
            return client.stat_object(bucket, object_key)
        except S3Error as exc:
            if exc.code in cls.missing_codes:
                return None
            raise
        except KeyError:
            # 测试替身与字典型适配器用 KeyError 表示对象不存在
            return None

    @staticmethod
    def stat_object(client: MinioClient, bucket: str, object_key: str) -> Any:
        """获取对象元信息，不存在时透传 SDK 抛出的 S3Error。"""
        return client.stat_object(bucket, object_key)

    @staticmethod
    def remove_object(client: MinioClient, bucket: str, object_key: str) -> None:
        """删除指定对象。"""
        client.remove_object(bucket, object_key)

    @staticmethod
    def verify_object(
        client: MinioClient,
        bucket: str,
        object_key: str,
        expected_size: int,
        expected_sha256: str,
    ) -> bool:
        """流式下载对象并核对大小与 SHA-256，校验其完整性。

        返回：
            大小与哈希均匹配时返回 True，否则返回 False。
        """
        stat: Any = client.stat_object(bucket, object_key)
        if int(stat.size) != expected_size:
            return False
        response = cast(ObjectResponse, client.get_object(bucket, object_key))
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

    @staticmethod
    def upload_file(
        client: MinioClient,
        bucket: str,
        object_key: str,
        source_path: Path,
        *,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> None:
        """将本地文件上传到指定对象键，附带 content_type 与自定义元数据。"""
        sdk_metadata = cast(
            dict[str, str | list[str] | tuple[str]],
            dict(metadata),
        )
        client.fput_object(
            bucket,
            object_key,
            str(source_path),
            content_type=content_type,
            metadata=sdk_metadata,
        )

    @staticmethod
    def download_file(
        client: MinioClient, bucket: str, object_key: str, destination: Path
    ) -> None:
        """将对象下载到本地目标路径。"""
        client.fget_object(bucket, object_key, str(destination))

    @staticmethod
    def open_object(
        client: MinioClient,
        bucket: str,
        object_key: str,
        *,
        offset: int = 0,
        length: int | None = None,
    ) -> ObjectResponse:
        """打开对象读取流，支持可选的字节偏移与长度（用于分段下载）。

        返回：
            可调 stream() 迭代内容的 ObjectResponse；调用方负责关闭并释放连接。
        """
        if length is not None:
            response = client.get_object(
                bucket, object_key, offset=offset, length=length
            )
        elif offset:
            response = client.get_object(bucket, object_key, offset=offset)
        else:
            response = client.get_object(bucket, object_key)
        return cast(ObjectResponse, response)

    @staticmethod
    def iter_object(response: ObjectResponse) -> Iterator[bytes]:
        """按 1 MiB 分块迭代对象内容，结束后自动关闭并释放底层连接。"""
        try:
            yield from response.stream(amt=1024 * 1024)
        finally:
            response.close()
            response.release_conn()


__all__ = [
    "Minio",
    "S3Error",
    "MinioClientFactory",
    "MinioClient",
    "MinioConfiguration",
    "MinioConfigurationError",
    "MinioDriver",
    "MinioSdkConstructor",
    "MinioTransportError",
    "ObjectResponse",
    "validate_minio_endpoint",
]
