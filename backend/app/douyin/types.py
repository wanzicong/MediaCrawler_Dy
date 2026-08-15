"""Compatibility alias for :mod:`app.integrations.douyin.types`."""

import sys

from app.integrations.douyin import types as _implementation
from app.integrations.douyin.types import (
    CreatorUrlInfo,
    PublishTimeType,
    SearchChannelType,
    SearchSortType,
    VideoUrlInfo,
    parse_creator_info,
    parse_video_info,
)

__all__ = [
    "CreatorUrlInfo",
    "PublishTimeType",
    "SearchChannelType",
    "SearchSortType",
    "VideoUrlInfo",
    "parse_creator_info",
    "parse_video_info",
]

sys.modules[__name__] = _implementation
