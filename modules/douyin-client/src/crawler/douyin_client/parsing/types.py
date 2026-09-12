# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音客户端的枚举与链接解析结果模型。"""

from enum import Enum

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


__all__ = [
    "CreatorUrlInfo",
    "PublishTimeType",
    "SearchChannelType",
    "SearchSortType",
    "VideoUrlInfo",
]
