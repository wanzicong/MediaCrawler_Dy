"""Business models and schemas for this bounded context."""

from datetime import datetime, timezone

from sqlmodel import SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


class Message(SQLModel):
    message: str


__all__ = [
    "get_datetime_utc",
    "Message",
]
