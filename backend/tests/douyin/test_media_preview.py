import uuid
from pathlib import Path

import pytest

from app.application.douyin.media.preview import (
    MediaByteRange,
    RangeNotSatisfiable,
    create_preview_ticket,
    iter_local_file,
    parse_range_header,
    validate_preview_ticket,
)
from app.bootstrap.settings import settings


def test_preview_ticket_is_bound_to_asset_and_expires() -> None:
    task_id = uuid.uuid4()
    asset_id = uuid.uuid4()
    ticket = create_preview_ticket(task_id, asset_id, now=1_000)

    assert validate_preview_ticket(ticket, task_id, asset_id, now=1_000)
    assert validate_preview_ticket(
        ticket,
        task_id,
        asset_id,
        now=1_000 + settings.MEDIA_PREVIEW_TTL_SECONDS,
    )
    assert not validate_preview_ticket(ticket, task_id, uuid.uuid4(), now=1_000)
    assert not validate_preview_ticket(
        ticket,
        task_id,
        asset_id,
        now=1_001 + settings.MEDIA_PREVIEW_TTL_SECONDS,
    )
    assert not validate_preview_ticket(f"{ticket}tampered", task_id, asset_id)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("bytes=0-3", MediaByteRange(0, 3)),
        ("bytes=4-", MediaByteRange(4, 9)),
        ("bytes=-4", MediaByteRange(6, 9)),
        ("bytes=7-99", MediaByteRange(7, 9)),
        ("bytes=-99", MediaByteRange(0, 9)),
    ],
)
def test_parse_single_byte_range(
    header: str | None, expected: MediaByteRange | None
) -> None:
    assert parse_range_header(header, 10) == expected


@pytest.mark.parametrize(
    "header",
    [
        "items=0-1",
        "bytes=",
        "bytes=10-",
        "bytes=4-2",
        "bytes=-0",
        "bytes=0-1,3-4",
        "bytes=invalid",
    ],
)
def test_rejects_invalid_or_multiple_ranges(header: str) -> None:
    with pytest.raises(RangeNotSatisfiable):
        parse_range_header(header, 10)


def test_iter_local_file_reads_only_requested_bytes(tmp_path: Path) -> None:
    media_path = tmp_path / "source.mp4"
    media_path.write_bytes(b"0123456789")

    body = b"".join(iter_local_file(media_path, start=3, length=4, chunk_size=2))

    assert body == b"3456"
