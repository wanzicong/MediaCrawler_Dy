# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

import re
from enum import Enum
from urllib.parse import parse_qsl, urlparse

from pydantic import BaseModel


class SearchChannelType(str, Enum):
    general = "aweme_general"
    video = "aweme_video_web"
    user = "aweme_user_web"
    live = "aweme_live"


class SearchSortType(int, Enum):
    general = 0
    most_like = 1
    latest = 2


class PublishTimeType(int, Enum):
    unlimited = 0
    one_day = 1
    one_week = 7
    six_months = 180


class VideoUrlInfo(BaseModel):
    aweme_id: str
    url_type: str = "normal"


class CreatorUrlInfo(BaseModel):
    sec_user_id: str


def parse_video_info(value: str) -> VideoUrlInfo:
    value = value.strip()
    if value.isdigit():
        return VideoUrlInfo(aweme_id=value)
    if "v.douyin.com" in value:
        return VideoUrlInfo(aweme_id="", url_type="short")
    query = dict(parse_qsl(urlparse(value).query))
    if query.get("modal_id"):
        return VideoUrlInfo(aweme_id=query["modal_id"], url_type="modal")
    match = re.search(r"/video/(\d+)", value)
    if match:
        return VideoUrlInfo(aweme_id=match.group(1))
    raise ValueError(f"无法解析抖音作品 ID: {value}")


def parse_creator_info(value: str) -> CreatorUrlInfo:
    value = value.strip()
    if value and not value.startswith("http") and "douyin.com" not in value:
        return CreatorUrlInfo(sec_user_id=value)
    match = re.search(r"/user/([^/?]+)", value)
    if match:
        return CreatorUrlInfo(sec_user_id=match.group(1))
    raise ValueError(f"无法解析抖音创作者 ID: {value}")
