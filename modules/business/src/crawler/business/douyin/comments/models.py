"""抖音评论限界上下文的业务模型与 API 契约。

包含评论表实体（DouyinComment）、评论库查询/汇总的公开模型，
以及评论采集、导出等请求体模型。
"""

import uuid
from datetime import datetime

from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.accounts.models import DouyinBrowserMode
from crawler.business.douyin.content.models import DouyinAwemePublic
from crawler.business.douyin.tasks.models import (
    CrawlTaskStatus,
    DouyinRequestDelayLevel,
)
from pydantic import SecretStr
from sqlalchemy import DateTime, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class DouyinComment(SQLModel, table=True):
    """抖音评论表实体，记录一次采集任务下抓取到的单条评论（含回复）。

    以 (task_id, comment_id) 作为业务唯一键，重复采集同一任务时按此去重。
    """

    __tablename__ = "douyin_comment"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "comment_id", name="uq_douyin_comment_task_comment"
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4, primary_key=True
    )  # 主键，记录 UUID
    task_id: uuid.UUID = Field(  # 所属采集任务 ID，任务删除时级联删除
        foreign_key="crawl_task.id", nullable=False, ondelete="CASCADE", index=True
    )
    comment_id: str = Field(max_length=128, index=True)  # 抖音平台评论 ID
    aweme_id: str = Field(max_length=128, index=True)  # 评论所属作品号
    parent_comment_id: str = Field(
        default="0", max_length=128
    )  # 父评论 ID，"0" 或空表示主评论
    content: str = Field(default="", sa_type=Text)  # 评论正文内容
    create_time: int | None = None  # 评论发布的 Unix 秒级时间戳
    creator_hash: str = Field(default="", max_length=64)  # 评论者脱敏标识（哈希）
    sec_uid: str = Field(default="", max_length=256)  # 评论者的 sec_uid
    nickname: str = Field(default="", max_length=255)  # 评论者昵称
    sub_comment_count: int = 0  # 该评论下的回复数
    like_count: int = 0  # 评论点赞数
    pictures: str = Field(default="", sa_type=Text)  # 评论附带图片（JSON 序列化存储）
    fetched_at: datetime = Field(  # 本记录抓取入库时间（UTC）
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinCommentPublic(SQLModel):
    """单条评论的对外展示模型，字段与 DouyinComment 实体一一对应。"""

    id: uuid.UUID  # 评论记录 UUID
    task_id: uuid.UUID  # 所属采集任务 ID
    comment_id: str  # 抖音平台评论 ID
    aweme_id: str  # 评论所属作品号
    parent_comment_id: str  # 父评论 ID，"0" 或空表示主评论
    content: str  # 评论正文内容
    create_time: int | None  # 评论发布的 Unix 秒级时间戳
    creator_hash: str  # 评论者脱敏标识（哈希）
    sec_uid: str  # 评论者的 sec_uid
    nickname: str  # 评论者昵称
    sub_comment_count: int  # 该评论下的回复数
    like_count: int  # 评论点赞数
    pictures: str  # 评论附带图片（JSON 序列化字符串）
    fetched_at: datetime  # 记录抓取入库时间（UTC）


class DouyinCommentsPublic(SQLModel):
    """评论分页列表响应模型。"""

    data: list[DouyinCommentPublic]  # 当前页评论列表
    count: int  # 满足条件的评论总数


class DouyinCommentLibraryItemPublic(SQLModel):
    """评论库列表项，聚合评论、所属作品与任务状态信息。"""

    comment: DouyinCommentPublic  # 评论详情
    aweme: DouyinAwemePublic  # 评论所属作品详情
    track_id: uuid.UUID  # 评论来源任务所属赛道
    track_name: str  # 评论来源任务所属赛道名称
    task_title: str  # 评论来源任务的可读标题
    task_status: CrawlTaskStatus  # 评论来源任务的当前状态
    task_created_at: datetime  # 评论来源任务的创建时间


class DouyinCommentLibrarySummaryPublic(SQLModel):
    """评论库筛选结果的全量统计汇总（不受分页影响）。"""

    matched_count: int  # 命中筛选条件的评论总数
    top_level_count: int  # 其中主评论数量
    reply_count: int  # 其中回复数量
    picture_count: int  # 带图评论数量
    total_like_count: int  # 命中评论的点赞数总和


class DouyinCommentLibraryPublic(SQLModel):
    """评论库分页查询响应模型，附带统计汇总。"""

    data: list[DouyinCommentLibraryItemPublic]  # 当前页评论库列表
    count: int  # 满足条件的评论总数
    summary: DouyinCommentLibrarySummaryPublic  # 全量统计汇总


class DouyinCommentSelectionExportRequest(SQLModel):
    """评论精选导出请求体，按评论记录 ID 导出。"""

    comment_ids: list[uuid.UUID] = Field(
        min_length=1, max_length=500
    )  # 待导出的评论记录 ID，1~500 个


class DouyinAwemeCommentCrawlRequest(SQLModel):
    """针对单个作品重新采集评论的任务创建请求体。"""

    browser_mode: DouyinBrowserMode | None = None  # 浏览器运行模式，None 表示用系统默认
    cookies: SecretStr | None = Field(
        default=None, repr=False
    )  # 抖音登录 cookies，为空则走扫码登录
    fetch_sub_comments: bool = False  # 是否同时采集子评论（回复）
    max_comments_per_aweme: int = Field(
        default=10, ge=1, le=1000
    )  # 单作品最大评论采集数
    concurrency: int = Field(default=1, ge=1, le=5)  # 采集并发数
    request_delay_level: DouyinRequestDelayLevel = (
        DouyinRequestDelayLevel.fast
    )  # 请求延迟档位
    request_interval_seconds: float = Field(
        default=1.0, ge=0.2, le=60.0
    )  # 自定义请求间隔秒数
    account_id: uuid.UUID | None = None  # 指定使用的账号池账号 ID，None 表示不指定


class DouyinCommentExportRequest(SQLModel):
    """按作品号批量导出评论的请求体。"""

    aweme_ids: list[str] = Field(
        min_length=1, max_length=1000
    )  # 待导出的作品号列表，1~1000 个


__all__ = [
    "DouyinComment",
    "DouyinCommentPublic",
    "DouyinCommentsPublic",
    "DouyinCommentLibraryItemPublic",
    "DouyinCommentLibrarySummaryPublic",
    "DouyinCommentLibraryPublic",
    "DouyinCommentSelectionExportRequest",
    "DouyinAwemeCommentCrawlRequest",
    "DouyinCommentExportRequest",
]
