"""抖音媒体存储服务的测试：覆盖本地/MinIO 双后端的原子落盘、历史 Windows 路径映射与逃逸防护、对象上传/物化/流式读取、带 sha256 回读校验的复制以及 MinIO 客户端超时重试策略。"""

import asyncio
import hashlib
import importlib
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from crawler.bootstrap.settings import settings
from crawler.business.douyin.media.models import DouyinMediaAsset, MediaStorageBackend
from crawler.business.douyin.media.storage import (
    MediaIntegrityError,
    MediaStorageService,
    MediaStorageUnavailableError,
)
from crawler.business.resources.storage import (
    MinioConfiguration,
    MinioDriver,
    MinioTransportError,
)
from crawler.business.resources.storage import minio as minio_driver_module
from minio import Minio as SdkMinio
from minio.error import S3Error


class FakeObjectResponse:
    """模拟 MinIO get_object 返回的响应体：支持分块流式读取与连接释放标记。"""

    def __init__(self, content: bytes) -> None:
        """以给定字节内容初始化。"""
        self.content = content
        self.closed = False
        self.released = False

    def stream(self, amt: int = 2**16):  # type: ignore[no-untyped-def]
        """按块大小切片产出字节流。"""
        for offset in range(0, len(self.content), amt):
            yield self.content[offset : offset + amt]

    def close(self) -> None:
        """标记响应已关闭。"""
        self.closed = True

    def release_conn(self) -> None:
        """标记连接已释放。"""
        self.released = True


class FakeMinio:
    """内存态 MinIO 客户端替身：模拟桶与对象存取，统计上传/读取/删除调用次数。"""

    def __init__(self, readback_override: bytes | None = None) -> None:
        """初始化内存桶表与对象表。

        参数：
            readback_override: 非空时 get_object 回读固定返回该内容，用于模拟远端数据损坏。
        """
        self.buckets: set[str] = set()
        self.objects: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}
        self.readback_override = readback_override
        self.fput_object_calls = 0
        self.get_object_calls = 0
        self.remove_object_calls = 0

    def bucket_exists(self, bucket: str) -> bool:
        """判断桶是否已创建。"""
        return bucket in self.buckets

    def make_bucket(self, bucket: str, location: str | None = None) -> None:
        """创建桶（忽略 location 参数）。"""
        del location
        self.buckets.add(bucket)

    def fput_object(
        self,
        bucket: str,
        object_key: str,
        path: str,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        """模拟上传本地文件：读出内容并与元数据一起登记到对象表。"""
        assert content_type == "video/mp4"
        self.fput_object_calls += 1
        self.objects[(bucket, object_key)] = (
            Path(path).read_bytes(),
            {f"x-amz-meta-{key}": value for key, value in metadata.items()},
        )

    def stat_object(self, bucket: str, object_key: str):  # type: ignore[no-untyped-def]
        """返回对象的大小与元数据。"""
        content, metadata = self.objects[(bucket, object_key)]
        return SimpleNamespace(size=len(content), metadata=metadata)

    def fget_object(self, bucket: str, object_key: str, path: str) -> None:
        """模拟下载对象到本地文件。"""
        Path(path).write_bytes(self.objects[(bucket, object_key)][0])

    def get_object(
        self,
        bucket: str,
        object_key: str,
        offset: int = 0,
        length: int | None = None,
    ) -> FakeObjectResponse:
        """模拟按区间读取对象，支持以 readback_override 伪造损坏内容。"""
        self.get_object_calls += 1
        content = self.objects[(bucket, object_key)][0]
        if self.readback_override is not None:
            content = self.readback_override
        end = None if length is None else offset + length
        return FakeObjectResponse(content[offset:end])

    def remove_object(self, bucket: str, object_key: str) -> None:
        """模拟删除对象。"""
        self.remove_object_calls += 1
        self.objects.pop((bucket, object_key), None)


def test_framework_transport_error_preserves_sdk_exception_identity() -> None:
    """验证框架传输层错误类型就是 minio SDK 的 S3Error（保持异常身份一致，便于上层捕获）。"""
    assert MinioTransportError is S3Error


def test_storage_module_exports_sdk_symbols_and_monkeypatches_constructor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证存储模块直接复用 SDK 符号，且客户端构造遵循超时与零重试的连接策略。"""
    storage_module = importlib.import_module("crawler.business.douyin.media.storage")
    captured: dict[str, object] = {}
    sentinel = object()

    assert storage_module.Minio is SdkMinio
    assert storage_module.S3Error is S3Error

    def constructor(endpoint: str, **kwargs: object) -> object:
        """记录 Minio 构造参数并返回哨兵对象。"""
        captured["endpoint"] = endpoint
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(storage_module, "Minio", constructor)

    assert storage_module.MediaStorageService()._client() is sentinel
    assert captured["endpoint"] == settings.MINIO_ENDPOINT
    http_client = captured["http_client"]
    timeout = http_client.connection_pool_kw["timeout"]
    retries = http_client.connection_pool_kw["retries"]
    assert timeout.connect_timeout == 3.0
    assert timeout.read_timeout == 30.0
    assert retries.total == retries.connect == retries.read == retries.redirect == 0


def make_asset(backend: MediaStorageBackend) -> DouyinMediaAsset:
    """构造一条按指定后端解析出存储位置的媒体资产（含特殊字符 aweme_id 的转义验证）。

    参数：
        backend: 目标存储后端。

    返回：
        带有 storage_backend/storage_bucket/object_key 的 DouyinMediaAsset 实例。
    """
    task_id = uuid.uuid4()
    service = MediaStorageService()
    resolved, bucket, object_key = service.location_values(
        task_id=task_id,
        aweme_id="测试/123",
        backend=backend,
    )
    return DouyinMediaAsset(
        task_id=task_id,
        aweme_id="测试/123",
        storage_backend=resolved.value,
        storage_bucket=bucket,
        object_key=object_key,
    )


def test_minio_driver_preserves_timeout_retry_and_header_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 MinioDriver 构造客户端时保留连接/读超时、零重试与重定向剥离敏感头的安全策略。"""
    captured: dict[str, object] = {}
    sentinel = object()

    def constructor(endpoint: str, **kwargs: object) -> object:
        """记录 Minio 构造参数并返回哨兵对象。"""
        captured["endpoint"] = endpoint
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(minio_driver_module, "Minio", constructor)
    driver = MinioDriver(
        lambda: MinioConfiguration(
            endpoint="storage.example.test:9443",
            access_key="access-key",
            secret_key="secret-key",
            secure=True,
            region="cn-test-1",
        )
    )

    assert driver.client() is sentinel
    assert captured["endpoint"] == "storage.example.test:9443"
    assert captured["access_key"] == "access-key"
    assert captured["secret_key"] == "secret-key"
    assert captured["secure"] is True
    assert captured["region"] == "cn-test-1"
    http_client = captured["http_client"]
    timeout = http_client.connection_pool_kw["timeout"]  # type: ignore[attr-defined]
    retries = http_client.connection_pool_kw["retries"]  # type: ignore[attr-defined]
    assert timeout.connect_timeout == 3.0
    assert timeout.read_timeout == 30.0
    assert retries.total == retries.connect == retries.read == retries.redirect == 0
    assert retries.remove_headers_on_redirect == frozenset(
        {"authorization", "cookie", "proxy-authorization"}
    )


@pytest.mark.parametrize(
    "endpoint",
    ["", "https://minio.example.test", "minio.example.test/path", "user@host"],
)
def test_application_keeps_minio_endpoint_error_contract(
    endpoint: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证非法 MINIO_ENDPOINT（空值、含协议、含路径、含用户信息）被统一拒绝并报约定错误文案。"""
    monkeypatch.setattr(settings, "MINIO_ENDPOINT", endpoint)

    with pytest.raises(
        MediaStorageUnavailableError,
        match="MINIO_ENDPOINT must be a host name with an optional port",
    ):
        MediaStorageService._validated_endpoint()


def test_client_factory_still_bypasses_runtime_minio_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证显式注入 client_factory 时跳过运行时 MinIO 配置校验（便于测试注入假客户端）。"""
    fake = FakeMinio()
    monkeypatch.setattr(settings, "MINIO_ENDPOINT", "https://invalid.example.test")

    assert MediaStorageService(client_factory=lambda: fake)._client() is fake  # type: ignore[arg-type]


def test_local_storage_atomically_moves_staged_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证本地存储将暂存文件原子移动到媒体根目录下，移动后暂存文件不复存在。"""
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    service = MediaStorageService()
    asset = make_asset(MediaStorageBackend.local)
    staged = tmp_path / ".staging" / "source.mp4"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"local-video")

    stored = asyncio.run(
        service.store(
            asset,
            staged,
            file_size=11,
            sha256="local-sha",
            mime_type="video/mp4",
        )
    )

    assert stored.backend == MediaStorageBackend.local
    assert Path(stored.local_path).read_bytes() == b"local-video"
    assert Path(stored.local_path).is_relative_to(tmp_path)
    assert not staged.exists()


def test_local_storage_maps_legacy_windows_path_inside_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证历史遗留的 Windows 绝对路径能被映射回当前媒体根目录内的相对路径并正常读取。"""
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    service = MediaStorageService()
    asset = make_asset(MediaStorageBackend.local)
    relative_path = Path("douyin") / str(asset.task_id) / "legacy" / "source.mp4"
    container_path = tmp_path / relative_path
    container_path.parent.mkdir(parents=True)
    container_path.write_bytes(b"legacy-video")
    legacy_suffix = str(relative_path).replace("/", "\\")
    asset.local_path = (
        f"D:\\WorkSpaceCoding\\MediaCrawler_Dy\\data\\media\\{legacy_suffix}"
    )

    stored = asyncio.run(service.existing(asset))

    assert stored is not None
    assert Path(stored.local_path) == container_path.resolve()
    assert Path(stored.local_path).read_bytes() == b"legacy-video"


def test_legacy_local_path_cannot_escape_media_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证包含 .. 的历史路径无法逃逸出媒体根目录（返回 None 拒绝访问）。"""
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    asset = make_asset(MediaStorageBackend.local)
    asset.local_path = (
        "D:\\WorkSpaceCoding\\MediaCrawler_Dy\\data\\media\\..\\outside.mp4"
    )

    assert MediaStorageService().local_path(asset) is None


def test_minio_storage_uploads_materializes_and_streams_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证 MinIO 后端的上传、存在性查询、临时物化、流式与区间读取全流程，物化文件随上下文退出清理。"""
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    fake = FakeMinio()
    service = MediaStorageService(client_factory=lambda: fake)  # type: ignore[arg-type]
    asset = make_asset(MediaStorageBackend.minio)
    staged = tmp_path / ".staging" / "source.mp4"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"remote-video")

    stored = asyncio.run(
        service.store(
            asset,
            staged,
            file_size=12,
            sha256="remote-sha",
            mime_type="video/mp4",
        )
    )
    asset.storage_bucket = stored.bucket
    asset.object_key = stored.object_key
    asset.sha256 = stored.sha256

    assert stored.backend == MediaStorageBackend.minio
    assert not staged.exists()
    assert fake.objects[(stored.bucket, stored.object_key)][0] == b"remote-video"
    assert asyncio.run(service.existing(asset)) == stored

    async def materialize() -> Path:
        """物化远端对象到本地临时文件并断言内容一致。"""
        async with service.materialize(asset) as path:
            assert path.read_bytes() == b"remote-video"
            return path

    materialized = asyncio.run(materialize())
    assert not materialized.exists()

    response = service.open_object(asset)
    assert b"".join(service.iter_object(response)) == b"remote-video"
    assert response.closed is True
    assert response.released is True

    ranged = service.open_object(asset, offset=3, length=4)
    assert b"".join(service.iter_object(ranged)) == b"ote-"
    assert service.object_size(asset) == len(b"remote-video")


def test_verified_minio_copy_reads_back_sha256_and_keeps_source(
    tmp_path: Path,
) -> None:
    """验证带校验的 MinIO 复制会上传后回读比对 sha256，且全程保留本地源文件。"""
    content = b"verified-local-video"
    source = tmp_path / "source.mp4"
    source.write_bytes(content)
    fake = FakeMinio()
    service = MediaStorageService(client_factory=lambda: fake)  # type: ignore[arg-type]
    asset = make_asset(MediaStorageBackend.local)

    stored = asyncio.run(
        service.ensure_verified_minio_copy(
            asset,
            source,
            file_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            mime_type="video/mp4",
        )
    )

    assert stored.backend == MediaStorageBackend.minio
    assert source.read_bytes() == content
    assert fake.get_object_calls == 1


def test_corrupt_minio_readback_raises_and_keeps_source(tmp_path: Path) -> None:
    """验证回读内容损坏时抛出完整性错误、清理远端脏对象，且本地源文件保持权威不被删除。"""
    content = b"local-source-is-authoritative"
    source = tmp_path / "source.mp4"
    source.write_bytes(content)
    fake = FakeMinio(readback_override=b"corrupt")
    service = MediaStorageService(client_factory=lambda: fake)  # type: ignore[arg-type]

    with pytest.raises(MediaIntegrityError):
        asyncio.run(
            service.ensure_verified_minio_copy(
                make_asset(MediaStorageBackend.local),
                source,
                file_size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                mime_type="video/mp4",
            )
        )

    assert source.read_bytes() == content
    assert fake.remove_object_calls == 1


def test_existing_verified_minio_copy_is_reused(tmp_path: Path) -> None:
    """验证远端已存在且 sha256 一致的副本被直接复用，不重复上传。"""
    content = b"already-uploaded"
    source = tmp_path / "source.mp4"
    source.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    fake = FakeMinio()
    service = MediaStorageService(client_factory=lambda: fake)  # type: ignore[arg-type]
    asset = make_asset(MediaStorageBackend.local)
    bucket = settings.MINIO_BUCKET
    object_key = service.object_key(asset.task_id, asset.aweme_id)
    fake.buckets.add(bucket)
    fake.objects[(bucket, object_key)] = (
        content,
        {"x-amz-meta-sha256": digest},
    )

    asyncio.run(
        service.ensure_verified_minio_copy(
            asset,
            source,
            file_size=len(content),
            sha256=digest,
            mime_type="video/mp4",
        )
    )

    assert fake.fput_object_calls == 0
    assert source.exists()
