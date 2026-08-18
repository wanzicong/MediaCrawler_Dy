"""纯技术存储驱动包。

面向业务的存储服务位于应用层；本包只包含可复用的本地文件系统
与 S3 兼容（MinIO）传输机制。
"""

from .local import atomic_replace, resolve_within_root
from .minio import (
    Minio,
    MinioClient,
    MinioClientFactory,
    MinioConfiguration,
    MinioConfigurationError,
    MinioDriver,
    MinioSdkConstructor,
    MinioTransportError,
    ObjectResponse,
    S3Error,
    validate_minio_endpoint,
)

__all__ = [
    "Minio",
    "MinioClient",
    "MinioClientFactory",
    "MinioConfiguration",
    "MinioConfigurationError",
    "MinioDriver",
    "MinioSdkConstructor",
    "MinioTransportError",
    "ObjectResponse",
    "S3Error",
    "atomic_replace",
    "resolve_within_root",
    "validate_minio_endpoint",
]
