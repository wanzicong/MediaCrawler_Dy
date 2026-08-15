"""RFC 7233 single-range parsing and bounded local-file iteration."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

STREAM_CHUNK_SIZE = 1024 * 1024


class RangeNotSatisfiable(ValueError):
    """The requested byte range cannot be served for this representation."""


@dataclass(frozen=True)
class MediaByteRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def parse_range_header(value: str | None, file_size: int) -> MediaByteRange | None:
    if value is None:
        return None
    if file_size <= 0 or not value.startswith("bytes="):
        raise RangeNotSatisfiable
    spec = value[6:].strip()
    if not spec or "," in spec or "-" not in spec:
        raise RangeNotSatisfiable
    start_value, end_value = (part.strip() for part in spec.split("-", 1))
    try:
        if not start_value:
            suffix_length = int(end_value)
            if suffix_length <= 0:
                raise RangeNotSatisfiable
            start = max(file_size - suffix_length, 0)
            return MediaByteRange(start=start, end=file_size - 1)

        start = int(start_value)
        if start < 0 or start >= file_size:
            raise RangeNotSatisfiable
        if not end_value:
            return MediaByteRange(start=start, end=file_size - 1)
        end = int(end_value)
        if end < start:
            raise RangeNotSatisfiable
        return MediaByteRange(start=start, end=min(end, file_size - 1))
    except ValueError as exc:
        raise RangeNotSatisfiable from exc


def iter_local_file(
    path: Path,
    *,
    start: int,
    length: int,
    chunk_size: int = STREAM_CHUNK_SIZE,
) -> Iterator[bytes]:
    remaining = length
    with path.open("rb") as media_file:
        media_file.seek(start)
        while remaining > 0:
            chunk = media_file.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


__all__ = [
    "MediaByteRange",
    "RangeNotSatisfiable",
    "STREAM_CHUNK_SIZE",
    "iter_local_file",
    "parse_range_header",
]
