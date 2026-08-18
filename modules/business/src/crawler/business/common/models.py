"""业务通用基础模型与 schema，被各限界上下文共享引用。"""

from datetime import datetime, timezone

from sqlmodel import SQLModel


def get_datetime_utc() -> datetime:
    """返回当前带 UTC 时区信息的 datetime，用于模型字段的默认创建时间。

    返回：
        当前 UTC 时间（timezone-aware）。
    """
    return datetime.now(timezone.utc)


class Message(SQLModel):
    """通用消息响应模型，用于仅需返回一段提示文本的接口。"""

    message: str  # 提示消息内容


__all__ = [
    "get_datetime_utc",
    "Message",
]
