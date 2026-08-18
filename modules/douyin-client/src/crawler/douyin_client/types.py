# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音客户端的类型定义与链接解析工具。

包含搜索接口枚举（频道/排序/发布时间）、作品与创作者链接解析结果模型，
以及从用户输入解析作品 ID、创作者 sec_user_id 的工具函数。
"""

import re
from enum import Enum
from urllib.parse import parse_qsl, urlparse

from pydantic import BaseModel


class SearchChannelType(str, Enum):
    """抖音搜索频道类型，对应搜索接口的 search_channel 参数。"""

    general = "aweme_general"  # 综合搜索
    video = "aweme_video_web"  # 视频搜索
    user = "aweme_user_web"  # 用户搜索
    live = "aweme_live"  # 直播搜索


class SearchSortType(int, Enum):
    """抖音搜索结果排序方式，对应筛选参数 sort_type。"""

    general = 0  # 综合排序（默认）
    most_like = 1  # 最多点赞
    latest = 2  # 最新发布


class PublishTimeType(int, Enum):
    """抖音搜索的发布时间筛选范围（数值为天数，0 表示不限）。"""

    unlimited = 0  # 不限时间
    one_day = 1  # 一天内
    one_week = 7  # 一周内
    six_months = 180  # 半年内


class VideoUrlInfo(BaseModel):
    """解析后的抖音作品链接信息。"""

    aweme_id: str  # 作品 ID；短链场景下暂为空串，待短链解析后回填
    url_type: str = "normal"  # 链接形态：normal（常规）/ short（短链）/ modal（带 modal_id 参数的分享链接）


class CreatorUrlInfo(BaseModel):
    """解析后的抖音创作者主页链接信息。"""

    sec_user_id: str  # 创作者的 sec_user_id


def parse_video_info(value: str) -> VideoUrlInfo:
    """从用户输入中解析抖音作品 ID。

    支持纯数字 aweme_id、v.douyin.com 短链、带 modal_id 参数的分享链接
    以及 /video/<id> 形式的作品页链接。

    参数：
        value: 用户输入的作品 ID 或链接文本。

    返回：
        解析出的作品链接信息。

    异常：
        ValueError: 无法从输入中解析出作品 ID 时抛出。
    """
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
    """从用户输入中解析抖音创作者的 sec_user_id。

    支持直接传入 sec_user_id 文本，或 /user/<sec_user_id> 形式的主页链接。

    参数：
        value: 用户输入的 sec_user_id 或创作者主页链接。

    返回：
        解析出的创作者链接信息。

    异常：
        ValueError: 无法从输入中解析出创作者 ID 时抛出。
    """
    value = value.strip()
    if value and not value.startswith("http") and "douyin.com" not in value:
        return CreatorUrlInfo(sec_user_id=value)
    match = re.search(r"/user/([^/?]+)", value)
    if match:
        return CreatorUrlInfo(sec_user_id=match.group(1))
    raise ValueError(f"无法解析抖音创作者 ID: {value}")
