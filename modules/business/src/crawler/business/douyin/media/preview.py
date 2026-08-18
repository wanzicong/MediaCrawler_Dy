"""抖音媒体预览凭证的签发与校验，复用通用字节区间（Range）流式读取能力。"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid

from crawler.bootstrap.settings import settings
from crawler.business.resources.http.ranges import (
    MediaByteRange,
    RangeNotSatisfiable,
    iter_local_file,
    parse_range_header,
)

PREVIEW_COOKIE_NAME = "douyin_media_preview"  # 预览凭证写入的 cookie 名称
_TICKET_VERSION = "v1"  # 凭证格式版本


def create_preview_ticket(
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
    *,
    now: int | None = None,
) -> str:
    """生成带 HMAC 签名的媒体预览凭证。

    参数：
        task_id: 所属采集任务 ID。
        asset_id: 媒体资产 ID。
        now: 注入的当前时间（秒级时间戳），仅用于测试；为 None 时取系统时间。

    返回：
        格式为 ``v1:{task_id}:{asset_id}:{expires_at}:{signature}`` 的凭证字符串，
        有效期由 settings.MEDIA_PREVIEW_TTL_SECONDS 决定。
    """
    issued_at = int(time.time()) if now is None else now
    expires_at = issued_at + settings.MEDIA_PREVIEW_TTL_SECONDS
    payload = f"{_TICKET_VERSION}:{task_id}:{asset_id}:{expires_at}"
    return f"{payload}:{_sign(payload)}"


def validate_preview_ticket(
    ticket: str | None,
    task_id: uuid.UUID,
    asset_id: uuid.UUID,
    *,
    now: int | None = None,
) -> bool:
    """校验预览凭证的版本、归属、有效期与签名。

    参数：
        ticket: 待校验的凭证字符串，通常为预览 cookie 的值。
        task_id: 请求访问的采集任务 ID。
        asset_id: 请求访问的媒体资产 ID。
        now: 注入的当前时间（秒级时间戳），仅用于测试。

    返回：
        凭证格式正确、归属匹配、未过期且签名一致时返回 True，否则返回 False。
    """
    if not ticket:
        return False
    try:
        version, task_value, asset_value, expires_value, signature = ticket.split(":")
        expires_at = int(expires_value)
    except (TypeError, ValueError):
        return False
    payload = f"{version}:{task_value}:{asset_value}:{expires_value}"
    current_time = int(time.time()) if now is None else now
    return (
        version == _TICKET_VERSION
        and task_value == str(task_id)
        and asset_value == str(asset_id)
        and expires_at >= current_time
        and hmac.compare_digest(signature, _sign(payload))
    )


def _sign(payload: str) -> str:
    """使用服务端 SECRET_KEY 对 payload 计算 HMAC-SHA256 签名（十六进制）。"""
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


__all__ = [
    "MediaByteRange",
    "PREVIEW_COOKIE_NAME",
    "RangeNotSatisfiable",
    "create_preview_ticket",
    "iter_local_file",
    "parse_range_header",
    "validate_preview_ticket",
]
