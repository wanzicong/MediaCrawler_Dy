# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""请求数据脱敏的唯一真源。

集中敏感字段名标记集与键名归一化规则：传输层在**构造**请求日志记录时立即
调用 ``redact_headers`` 抹除 Cookie、Authorization 等敏感值，避免完整凭据随
对象在进程内扩散；上层日志落库/查询服务复用同一份规则做纵深防御，
不再各自维护标记表，消除多处规则漂移。
"""

from __future__ import annotations

from collections.abc import Mapping

# 敏感值统一占位符
REDACTED = "[REDACTED]"

# 敏感字段名标记集：键名归一化（仅保留字母数字并小写）后包含任一标记即视为敏感
SENSITIVE_KEY_MARKERS: frozenset[str] = frozenset(
    {
        "abogus",
        "accountid",
        "authorization",
        "cookie",
        "csrf",
        "mstoken",
        "odin",
        "passport",
        "secuid",
        "secuserid",
        "session",
        "token",
        "uid",
        "userid",
        "verifyfp",
        "webid",
    }
)


def normalize_key(value: object) -> str:
    """把字段名归一化为仅含字母数字的小写形式，供脱敏规则匹配。"""
    return "".join(
        character for character in str(value).casefold() if character.isalnum()
    )


def is_sensitive_key(value: object) -> bool:
    """判断字段名是否可能承载 Cookie、签名、令牌或原始账号标识。"""
    normalized = normalize_key(value)
    return any(marker in normalized for marker in SENSITIVE_KEY_MARKERS)


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """按敏感键标记集脱敏请求头，返回新字典（不修改入参）。

    参数：
        headers: 实际发送到抖音的请求头。

    返回：
        新的请求头字典；敏感键的值替换为 ``REDACTED``，其余字段原样保留。

    说明：
        规则与上层 ``sanitize_mapping`` 对请求头的结果一致，因此重复调用幂等。
    """
    return {
        key: (REDACTED if is_sensitive_key(key) else value)
        for key, value in headers.items()
    }


__all__ = [
    "REDACTED",
    "SENSITIVE_KEY_MARKERS",
    "is_sensitive_key",
    "normalize_key",
    "redact_headers",
]
