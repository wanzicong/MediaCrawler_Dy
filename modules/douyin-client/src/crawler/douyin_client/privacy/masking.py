# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""用户标识脱敏：哈希匿名化与昵称打码。"""

import hashlib
import hmac
from typing import Any


def anonymize_user_id(user_id: Any) -> str:
    """将用户 ID（uid/sec_uid）做 SHA-256 哈希并截取前 16 位，空输入返回空字符串。"""
    normalized = str(user_id or "").strip()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16] if normalized else ""


def anonymize_account_id(account_id: Any, secret_key: str) -> str:
    """以 secret_key 为密钥对账号 ID 做 HMAC-SHA256 匿名化，截取前 32 位。

    参数：
        account_id: 原始账号 ID。
        secret_key: HMAC 密钥。

    返回：
        匿名化后的标识；空输入返回空字符串。
    """
    normalized = str(account_id or "").strip()
    if not normalized:
        return ""
    return hmac.new(
        secret_key.encode(), normalized.encode(), hashlib.sha256
    ).hexdigest()[:32]


def mask_nickname(nickname: Any) -> str:
    """对昵称打码：保留首尾字符、中间以星号替代；长度不超过 1 时整体打码。"""
    value = str(nickname or "")
    if len(value) <= 1:
        return "*" if value else ""
    if len(value) == 2:
        return value[0] + "*"
    return value[0] + "***" + value[-1]


__all__ = ["anonymize_account_id", "anonymize_user_id", "mask_nickname"]
