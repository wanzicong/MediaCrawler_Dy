"""抖音媒体预览能力的测试：覆盖预览票据的绑定/过期/防篡改校验、HTTP Range 头解析以及本地文件按区间流式读取。"""

import uuid
from pathlib import Path

import pytest
from crawler.bootstrap.settings import settings
from crawler.business.douyin.media.preview import (
    MediaByteRange,
    RangeNotSatisfiable,
    create_preview_ticket,
    iter_local_file,
    parse_range_header,
    validate_preview_ticket,
)


def test_preview_ticket_is_bound_to_asset_and_expires() -> None:
    """验证预览票据与 task_id+asset_id 绑定、在 TTL 内有效、过期或篡改后失效。"""
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
    """验证合法的单段字节区间（含首尾省略写法）被解析并裁剪到文件实际范围内。

    参数：
        header: Range 请求头原始值，None 表示未提供。
        expected: 期望解析出的字节区间，None 表示不切片。
    """
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
    """验证非法单位、空区间、越界、倒置、多段等不支持的 Range 头均抛出 RangeNotSatisfiable。"""
    with pytest.raises(RangeNotSatisfiable):
        parse_range_header(header, 10)


def test_iter_local_file_reads_only_requested_bytes(tmp_path: Path) -> None:
    """验证本地文件迭代器严格按 start/length 读取指定字节段，不多读不漏读。"""
    media_path = tmp_path / "source.mp4"
    media_path.write_bytes(b"0123456789")

    body = b"".join(iter_local_file(media_path, start=3, length=4, chunk_size=2))

    assert body == b"3456"
