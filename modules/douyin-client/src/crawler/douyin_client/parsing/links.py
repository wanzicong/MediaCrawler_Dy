# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""从用户输入解析抖音作品 ID 与创作者 sec_user_id。"""

import re
from urllib.parse import parse_qsl, urlparse

from crawler.douyin_client.parsing.types import CreatorUrlInfo, VideoUrlInfo


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


__all__ = ["parse_creator_info", "parse_video_info"]
