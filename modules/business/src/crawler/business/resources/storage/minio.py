"""Generic S3-compatible MinIO transport driver.

This module intentionally knows nothing about media assets, Douyin keys, database
models, or application error types.  It exposes the exact low-level operations the
application facade composes into business use cases.
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
    """The MinIO endpoint or credentials are incomplete or malformed."""


class ObjectResponse(Protocol):
    def stream(self, amt: int = 2**16) -> Iterator[bytes]: ...

    def close(self) -> None: ...

    def release_conn(self) -> None: ...


class MinioClient(Protocol):
    """Structural boundary for the SDK operations used by storage drivers."""

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


# Application code catches a framework-owned transport name while the underlying
# SDK exception object remains unchanged for callers and existing test doubles.
MinioTransportError: TypeAlias = S3Error


@dataclass(frozen=True)
class MinioConfiguration:
    endpoint: str
    access_key: str
    secret_key: str
    secure: bool
    region: str | None = None


MinioClientFactory = Callable[[], MinioClient]
MinioSdkConstructor = Callable[..., MinioClient]
ConfigurationProvider = Callable[[], MinioConfiguration]


def validate_minio_endpoint(endpoint: str) -> str:
    """Accept only a host name with an optional port, matching Minio's API."""

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
    """Thin, synchronous MinIO SDK adapter with deterministic HTTP behavior."""

    missing_codes = frozenset({"NoSuchBucket", "NoSuchKey", "NoSuchObject", "NotFound"})

    def __init__(
        self,
        configuration_provider: ConfigurationProvider,
        client_factory: MinioClientFactory | None = None,
        *,
        sdk_constructor: MinioSdkConstructor | None = None,
    ) -> None:
        self._configuration_provider = configuration_provider
        self._client_factory = client_factory
        self._sdk_constructor = sdk_constructor

    def client(self) -> MinioClient:
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
        try:
            return client.stat_object(bucket, object_key)
        except S3Error as exc:
            if exc.code in cls.missing_codes:
                return None
            raise
        except KeyError:
            # Test doubles and dictionary-backed adapters use KeyError for a miss.
            return None

    @staticmethod
    def stat_object(client: MinioClient, bucket: str, object_key: str) -> Any:
        return client.stat_object(bucket, object_key)

    @staticmethod
    def remove_object(client: MinioClient, bucket: str, object_key: str) -> None:
        client.remove_object(bucket, object_key)

    @staticmethod
    def verify_object(
        client: MinioClient,
        bucket: str,
        object_key: str,
        expected_size: int,
        expected_sha256: str,
    ) -> bool:
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
