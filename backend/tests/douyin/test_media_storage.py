import asyncio
import hashlib
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models import DouyinMediaAsset, MediaStorageBackend
from app.services.media_storage import MediaIntegrityError, MediaStorageService


class FakeObjectResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.closed = False
        self.released = False

    def stream(self, amt: int = 2**16):  # type: ignore[no-untyped-def]
        for offset in range(0, len(self.content), amt):
            yield self.content[offset : offset + amt]

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class FakeMinio:
    def __init__(self, readback_override: bytes | None = None) -> None:
        self.buckets: set[str] = set()
        self.objects: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}
        self.readback_override = readback_override
        self.fput_object_calls = 0
        self.get_object_calls = 0
        self.remove_object_calls = 0

    def bucket_exists(self, bucket: str) -> bool:
        return bucket in self.buckets

    def make_bucket(self, bucket: str, location: str | None = None) -> None:
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
        assert content_type == "video/mp4"
        self.fput_object_calls += 1
        self.objects[(bucket, object_key)] = (
            Path(path).read_bytes(),
            {f"x-amz-meta-{key}": value for key, value in metadata.items()},
        )

    def stat_object(self, bucket: str, object_key: str):  # type: ignore[no-untyped-def]
        content, metadata = self.objects[(bucket, object_key)]
        return SimpleNamespace(size=len(content), metadata=metadata)

    def fget_object(self, bucket: str, object_key: str, path: str) -> None:
        Path(path).write_bytes(self.objects[(bucket, object_key)][0])

    def get_object(
        self,
        bucket: str,
        object_key: str,
        offset: int = 0,
        length: int | None = None,
    ) -> FakeObjectResponse:
        self.get_object_calls += 1
        content = self.objects[(bucket, object_key)][0]
        if self.readback_override is not None:
            content = self.readback_override
        end = None if length is None else offset + length
        return FakeObjectResponse(content[offset:end])

    def remove_object(self, bucket: str, object_key: str) -> None:
        self.remove_object_calls += 1
        self.objects.pop((bucket, object_key), None)


def make_asset(backend: MediaStorageBackend) -> DouyinMediaAsset:
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


def test_local_storage_atomically_moves_staged_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    service = MediaStorageService()
    asset = make_asset(MediaStorageBackend.local)
    relative_path = Path("douyin") / str(asset.task_id) / "legacy" / "source.mp4"
    container_path = tmp_path / relative_path
    container_path.parent.mkdir(parents=True)
    container_path.write_bytes(b"legacy-video")
    legacy_suffix = str(relative_path).replace("/", "\\")
    asset.local_path = (
        "D:\\WorkSpaceCoding\\MediaCrawler_Dy\\data\\media\\"
        f"{legacy_suffix}"
    )

    stored = asyncio.run(service.existing(asset))

    assert stored is not None
    assert Path(stored.local_path) == container_path.resolve()
    assert Path(stored.local_path).read_bytes() == b"legacy-video"


def test_legacy_local_path_cannot_escape_media_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "MEDIA_OUTPUT_DIR", tmp_path)
    asset = make_asset(MediaStorageBackend.local)
    asset.local_path = (
        "D:\\WorkSpaceCoding\\MediaCrawler_Dy\\data\\media\\..\\outside.mp4"
    )

    assert MediaStorageService._validated_local_path(asset) is None


def test_minio_storage_uploads_materializes_and_streams_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
