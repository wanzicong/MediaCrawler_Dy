"""抖音接口请求日志的写侧应用服务：落盘调用记录、按任务解析归属用户。"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

from crawler.bootstrap.database import engine
from crawler.business.douyin.request_logs.models import DouyinRequestLog
from crawler.business.douyin.tasks.models import CrawlTask
from crawler.douyin_client.client import (
    DouyinClient,
    DouyinRequestLogEntry,
    RequestLogCallback,
)
from sqlmodel import Session, select

REDACTED = "[REDACTED]"
MAX_FAILURE_DETAIL_CHARS = 8192
MAX_FAILURE_STRING_CHARS = 2048
_SENSITIVE_KEY_MARKERS = {
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
_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)\b(msToken|a_bogus|authorization|cookie|token|verifyFp|webid|"
    r"sec_uid|sec_user_id|user_id|uid)\b([\s\"']*[:=][\s\"']*)"
    r"([^&\s\"'<>,}\]]+)"
)


def _normalized_key(value: object) -> str:
    """把字段名归一化为仅含字母数字的小写形式，供脱敏规则匹配。"""
    return "".join(
        character for character in str(value).casefold() if character.isalnum()
    )


def _sensitive_key(value: object) -> bool:
    """判断字段名是否可能承载 Cookie、签名、令牌或原始账号标识。"""
    normalized = _normalized_key(value)
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)


def sanitize_mapping(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """递归脱敏请求映射；保留诊断所需字段结构，但不保留敏感值。"""
    if value is None:
        return None
    output: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key)
        if _sensitive_key(key):
            output[key] = REDACTED
        elif isinstance(raw_value, dict):
            output[key] = sanitize_mapping(raw_value)
        elif isinstance(raw_value, list):
            output[key] = [
                sanitize_mapping(item) if isinstance(item, dict) else item
                for item in raw_value
            ]
        else:
            output[key] = raw_value
    return output


def sanitize_url(value: str) -> str:
    """移除 URL 的查询串与片段，防止签名或令牌绕过字段级脱敏。"""
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _sanitize_text(value: str) -> str:
    """清理自由文本中的令牌/账号参数，并限制单个字符串长度。"""
    redacted = _SENSITIVE_TEXT_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}", value
    )
    if len(redacted) <= MAX_FAILURE_STRING_CHARS:
        return redacted
    return f"{redacted[:MAX_FAILURE_STRING_CHARS]}…[TRUNCATED]"


def _sanitize_failure_value(value: Any) -> Any:
    """递归脱敏失败响应中的映射、列表与自由文本。"""
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            output[key] = (
                REDACTED if _sensitive_key(key) else _sanitize_failure_value(raw_value)
            )
        return output
    if isinstance(value, (list, tuple)):
        return [_sanitize_failure_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _sanitize_text(str(value))


def sanitize_failure_detail(
    value: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """脱敏并限制失败响应总长度，防止日志泄密或被超大响应撑爆。"""
    if value is None:
        return None
    sanitized = _sanitize_failure_value(value)
    serialized = json.dumps(sanitized, ensure_ascii=False, default=str)
    if len(serialized) <= MAX_FAILURE_DETAIL_CHARS:
        return cast(dict[str, Any], sanitized)
    return {
        "truncated": True,
        "preview": _sanitize_text(serialized[:MAX_FAILURE_DETAIL_CHARS]),
    }


def record_sync(
    owner_id: uuid.UUID,
    task_id: uuid.UUID | None,
    entry: DouyinRequestLogEntry,
) -> None:
    """同步落盘一条抖音请求日志（在 asyncio.to_thread 线程池中执行）。

    参数：
        owner_id: 归属用户 ID。
        task_id: 关联采集任务 ID；登录校验等非任务请求为 None。
        entry: 客户端记录的请求快照。
    """
    query_params = sanitize_mapping(entry.query_params) or {}
    request_headers = sanitize_mapping(entry.request_headers) or {}
    request_body = sanitize_mapping(entry.request_body)
    failure_detail = sanitize_failure_detail(entry.failure_detail)
    with Session(engine) as session:
        session.add(
            DouyinRequestLog(
                owner_id=owner_id,
                task_id=task_id,
                method=entry.method,
                path=entry.path,
                url=sanitize_url(entry.url),
                query_params=query_params,
                request_headers=request_headers,
                request_body=request_body,
                response_status=entry.response_status,
                duration_ms=entry.duration_ms,
                error=entry.error,
                failure_detail=failure_detail,
            )
        )
        session.commit()


async def record(
    owner_id: uuid.UUID,
    task_id: uuid.UUID | None,
    entry: DouyinRequestLogEntry,
) -> None:
    """异步落盘一条抖音请求日志（内部转线程池执行）。"""
    await asyncio.to_thread(record_sync, owner_id, task_id, entry)


def load_task_owner_sync(task_id: uuid.UUID) -> uuid.UUID | None:
    """同步查询任务归属用户（在 asyncio.to_thread 线程池中执行）。"""
    with Session(engine) as session:
        return session.exec(
            select(CrawlTask.owner_id).where(CrawlTask.id == task_id)
        ).first()


async def load_task_owner(task_id: uuid.UUID) -> uuid.UUID | None:
    """查询任务的归属用户；任务不存在时返回 None。"""
    return await asyncio.to_thread(load_task_owner_sync, task_id)


def build_request_logger(owner_id: uuid.UUID, task_id: uuid.UUID) -> RequestLogCallback:
    """构造绑定任务上下文的抖音请求日志回调，供 DouyinClient.request_logger 使用。"""

    async def logger(_client: DouyinClient, entry: DouyinRequestLogEntry) -> None:
        await record(owner_id, task_id, entry)

    return logger


__all__ = [
    "build_request_logger",
    "load_task_owner",
    "load_task_owner_sync",
    "record",
    "record_sync",
    "sanitize_mapping",
    "sanitize_failure_detail",
    "sanitize_url",
]
