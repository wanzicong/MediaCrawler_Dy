# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

import hashlib
import hmac
from typing import Any


def anonymize_user_id(user_id: Any) -> str:
    normalized = str(user_id or "").strip()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16] if normalized else ""


def anonymize_account_id(account_id: Any, secret_key: str) -> str:
    normalized = str(account_id or "").strip()
    if not normalized:
        return ""
    return hmac.new(
        secret_key.encode(), normalized.encode(), hashlib.sha256
    ).hexdigest()[:32]


def mask_nickname(nickname: Any) -> str:
    value = str(nickname or "")
    if len(value) <= 1:
        return "*" if value else ""
    if len(value) == 2:
        return value[0] + "*"
    return value[0] + "***" + value[-1]


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _note_images(item: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for image in item.get("images") or []:
        urls = image.get("url_list") or []
        if urls:
            result.append(str(urls[-1]))
    return result


def _comment_images(item: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for image in item.get("image_list") or []:
        urls = (image.get("origin_url") or {}).get("url_list") or []
        if urls:
            result.append(str(urls[-1]))
    return result


def map_aweme(item: dict[str, Any], source_keyword: str) -> dict[str, Any]:
    aweme_id = str(item.get("aweme_id") or "")
    author = item.get("author") or {}
    stats = item.get("statistics") or {}
    video = item.get("video") or {}
    cover_urls = (video.get("raw_cover") or video.get("origin_cover") or {}).get(
        "url_list"
    ) or []
    video_urls = (
        (video.get("play_addr_h264") or {}).get("url_list")
        or (video.get("play_addr_256") or {}).get("url_list")
        or (video.get("play_addr") or {}).get("url_list")
        or []
    )
    music_url = ((item.get("music") or {}).get("play_url") or {}).get("uri") or ""
    return {
        "aweme_id": aweme_id,
        "aweme_type": str(item.get("aweme_type") or ""),
        "title": str(item.get("desc") or ""),
        "description": str(item.get("desc") or ""),
        "create_time": _as_int(item.get("create_time")) or None,
        "creator_hash": anonymize_user_id(author.get("uid")),
        "sec_uid": anonymize_user_id(author.get("sec_uid")),
        "nickname": mask_nickname(author.get("nickname")),
        "liked_count": _as_int(stats.get("digg_count")),
        "collected_count": _as_int(stats.get("collect_count")),
        "comment_count": _as_int(stats.get("comment_count")),
        "share_count": _as_int(stats.get("share_count")),
        "aweme_url": f"https://www.douyin.com/video/{aweme_id}",
        "cover_url": str(cover_urls[-1]) if cover_urls else "",
        "video_download_url": str(video_urls[-1]) if video_urls else "",
        "music_download_url": str(music_url),
        "note_download_url": ",".join(_note_images(item)),
        "source_keyword": source_keyword,
    }


def map_comment(item: dict[str, Any], aweme_id: str) -> dict[str, Any] | None:
    if str(item.get("aweme_id") or "") != aweme_id:
        return None
    user = item.get("user") or {}
    comment_id = str(item.get("cid") or "")
    if not comment_id:
        return None
    return {
        "comment_id": comment_id,
        "aweme_id": aweme_id,
        "parent_comment_id": str(item.get("reply_id") or "0"),
        "content": str(item.get("text") or ""),
        "create_time": _as_int(item.get("create_time")) or None,
        "creator_hash": anonymize_user_id(user.get("uid")),
        "sec_uid": anonymize_user_id(user.get("sec_uid")),
        "nickname": mask_nickname(user.get("nickname")),
        "sub_comment_count": _as_int(item.get("reply_comment_total")),
        "like_count": _as_int(item.get("digg_count")),
        "pictures": ",".join(_comment_images(item)),
    }
