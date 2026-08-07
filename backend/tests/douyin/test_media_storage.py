import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models import DouyinMediaAsset, MediaStorageBackend
from app.services.media_storage import MediaStorageService


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
    def __init__(self) -> None:
        self.buckets: set[str] = set()
        self.objects: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}

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
        content = self.objects[(bucket, object_key)][0]
        end = None if length is None else offset + length
        return FakeObjectResponse(content[offset:end])


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
