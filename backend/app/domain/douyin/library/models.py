"""Business models and schemas for this bounded context."""

from sqlmodel import Field, SQLModel

from app.domain.douyin.content.models import DouyinAwemePublic
from app.domain.douyin.media.models import DouyinMediaAssetPublic
from app.domain.douyin.tags.models import DouyinTagRefPublic


class DouyinWorkPublic(SQLModel):
    aweme: DouyinAwemePublic
    persisted_comment_count: int
    media: DouyinMediaAssetPublic | None
    tags: list[DouyinTagRefPublic] = Field(default_factory=list)


class DouyinWorksPublic(SQLModel):
    data: list[DouyinWorkPublic]
    count: int


__all__ = [
    "DouyinWorkPublic",
    "DouyinWorksPublic",
]
