"""抖音作品库限界上下文的公开模型。

聚合作品、媒体资产、字幕、标签、已保存评论数等信息，
作为作品库列表与详情的统一对外展示契约。
"""

from crawler.business.douyin.content.models import DouyinAwemePublic
from crawler.business.douyin.media.models import DouyinMediaAssetPublic
from crawler.business.douyin.tags.models import DouyinTagRefPublic
from sqlmodel import Field, SQLModel


class DouyinWorkPublic(SQLModel):
    """作品库单个作品的对外展示模型，聚合作品元数据与其关联资源。"""

    aweme: DouyinAwemePublic  # 作品基础信息
    persisted_comment_count: int  # 已入库保存的评论数
    media: DouyinMediaAssetPublic | None  # 媒体资产信息（含字幕），未下载时为 None
    tags: list[DouyinTagRefPublic] = Field(default_factory=list)  # 作品关联的标签列表


class DouyinWorksPublic(SQLModel):
    """作品库分页列表响应模型。"""

    data: list[DouyinWorkPublic]  # 当前页作品列表
    count: int  # 满足条件的作品总数


__all__ = [
    "DouyinWorkPublic",
    "DouyinWorksPublic",
]
