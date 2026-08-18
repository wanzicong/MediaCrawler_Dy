"""测试共享的抖音持久化辅助函数。

生产代码通过应用层创建任务，应用层会在首次 flush 前解析显式 track 或属主的
默认 track。直接插入 ORM 行的测试必须显式建模同样的不变量。
"""

from __future__ import annotations

import uuid

from crawler.business.douyin.tracks.bindings import ensure_default_track
from sqlmodel import Session


def default_track_id(session: Session, *, owner_id: uuid.UUID) -> uuid.UUID:
    """返回指定属主的默认 track id（不存在时按生产逻辑自动创建）。"""
    return ensure_default_track(session, owner_id=owner_id).id
