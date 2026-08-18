"""抖音内容限界上下文的业务模型与 schema：作品（aweme）、用户行为及创作者采集请求。"""

import uuid
from datetime import datetime

from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.accounts.models import DouyinBrowserMode
from crawler.business.douyin.tasks.models import DouyinRequestDelayLevel
from pydantic import SecretStr, model_validator
from sqlalchemy import DateTime, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class DouyinAweme(SQLModel, table=True):
    """抖音作品（aweme）采集记录实体：一行对应某次采集任务抓到的一个作品。"""

    __tablename__ = "douyin_aweme"
    __table_args__ = (
        UniqueConstraint("task_id", "aweme_id", name="uq_douyin_aweme_task_aweme"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)  # 作品记录主键
    task_id: uuid.UUID = Field(
        foreign_key="crawl_task.id", nullable=False, ondelete="CASCADE", index=True
    )  # 所属采集任务 id（外键 crawl_task.id，级联删除）
    aweme_id: str = Field(max_length=128, index=True)  # 抖音作品 id
    aweme_type: str = Field(default="", max_length=32)  # 作品类型（视频/图文等）
    title: str = Field(default="", sa_type=Text)  # 作品标题
    description: str = Field(default="", sa_type=Text)  # 作品描述文案（含 #话题标签）
    create_time: int | None = None  # 作品发布时间（Unix 秒级时间戳）
    creator_hash: str = Field(default="", max_length=64)  # 创作者身份哈希（脱敏）
    sec_uid: str = Field(default="", max_length=256)  # 创作者 sec_uid
    nickname: str = Field(default="", max_length=255)  # 创作者昵称
    liked_count: int = 0  # 点赞数
    collected_count: int = 0  # 收藏数
    comment_count: int = 0  # 评论数
    share_count: int = 0  # 分享数
    aweme_url: str = Field(default="", sa_type=Text)  # 作品详情页链接
    cover_url: str = Field(default="", sa_type=Text)  # 封面图链接
    video_download_url: str = Field(default="", sa_type=Text)  # 视频下载地址
    music_download_url: str = Field(default="", sa_type=Text)  # 配乐下载地址
    note_download_url: str = Field(default="", sa_type=Text)  # 图文下载地址
    source_keyword: str = Field(
        default="", max_length=512
    )  # 命中来源关键词（关键词搜索采集时记录）
    fetched_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 采集入库时间（UTC）


class DouyinAwemePublic(SQLModel):
    """作品对外响应模型。"""

    id: uuid.UUID  # 作品记录 id
    task_id: uuid.UUID  # 所属采集任务 id
    aweme_id: str  # 抖音作品 id
    aweme_type: str  # 作品类型
    title: str  # 作品标题
    description: str  # 作品描述文案
    create_time: int | None  # 作品发布时间（Unix 秒级时间戳）
    creator_hash: str  # 创作者身份哈希
    sec_uid: str  # 创作者 sec_uid
    nickname: str  # 创作者昵称
    liked_count: int  # 点赞数
    collected_count: int  # 收藏数
    comment_count: int  # 评论数
    share_count: int  # 分享数
    aweme_url: str  # 作品详情页链接
    cover_url: str  # 封面图链接
    video_download_url: str  # 视频下载地址
    music_download_url: str  # 配乐下载地址
    note_download_url: str  # 图文下载地址
    source_keyword: str  # 命中来源关键词
    fetched_at: datetime  # 采集入库时间


class DouyinAwemesPublic(SQLModel):
    """作品分页列表响应。"""

    data: list[DouyinAwemePublic]  # 当前页作品列表
    count: int  # 满足条件的作品总数


class DouyinUserAction(SQLModel, table=True):
    """抖音用户行为记录实体：观测到的账号对作品的点赞、收藏等操作。"""

    __tablename__ = "douyin_user_action"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "account_hash",
            "aweme_id",
            "action_type",
            name="uq_douyin_action_task_account_aweme_type",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)  # 行为记录主键
    task_id: uuid.UUID = Field(
        foreign_key="crawl_task.id", nullable=False, ondelete="CASCADE", index=True
    )  # 所属采集任务 id（外键 crawl_task.id，级联删除）
    account_hash: str = Field(max_length=64)  # 执行行为的账号身份哈希（脱敏）
    aweme_id: str = Field(max_length=128, index=True)  # 目标作品 id
    action_type: str = Field(
        max_length=32, index=True
    )  # 行为类型（如 like/collect/comment）
    observed_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 行为观测时间（UTC）


class DouyinUserActionPublic(SQLModel):
    """用户行为对外响应模型。"""

    id: uuid.UUID  # 行为记录 id
    task_id: uuid.UUID  # 所属采集任务 id
    account_hash: str  # 执行行为的账号身份哈希
    aweme_id: str  # 目标作品 id
    action_type: str  # 行为类型
    observed_at: datetime  # 行为观测时间


class DouyinUserActionsPublic(SQLModel):
    """用户行为分页列表响应。"""

    data: list[DouyinUserActionPublic]  # 当前页行为列表
    count: int  # 满足条件的行为总数


class DouyinAwemeCreatorCrawlRequest(SQLModel):
    """按创作者主页批量采集作品的请求模型。"""

    browser_mode: DouyinBrowserMode | None = (
        None  # 浏览器模式覆盖；None 表示沿用执行账号自身配置
    )
    cookies: SecretStr | None = Field(
        default=None, repr=False
    )  # 自定义登录 cookie（不回显、不落库）
    max_awemes: int = Field(default=20, ge=1, le=1000)  # 单创作者最大采集作品数
    fetch_comments: bool = False  # 是否采集评论
    fetch_sub_comments: bool = False  # 是否采集二级评论（依赖 fetch_comments 开启）
    max_comments_per_aweme: int = Field(default=10, ge=1, le=1000)  # 单作品评论采集上限
    concurrency: int = Field(default=1, ge=1, le=5)  # 作品级采集并发数
    request_delay_level: DouyinRequestDelayLevel = (
        DouyinRequestDelayLevel.fast
    )  # 请求延迟档位
    request_interval_seconds: float = Field(
        default=1.0, ge=0.2, le=60.0
    )  # 请求间隔（秒）
    account_id: uuid.UUID | None = None  # 指定执行账号；None 表示由调度器自动选择

    @model_validator(mode="after")
    def normalize_creator_options(self) -> "DouyinAwemeCreatorCrawlRequest":
        """归一化选项：未开启评论采集时强制关闭二级评论采集。

        返回：
            归一化后的请求对象本身。
        """
        if not self.fetch_comments:
            self.fetch_sub_comments = False
        return self


class DouyinCreatorOptionPublic(SQLModel):
    """创作者选项（前端下拉选择用）。"""

    creator_hash: str  # 创作者身份哈希
    nickname: str  # 创作者昵称
    work_count: int  # 已采集的作品数


class DouyinCreatorOptionsPublic(SQLModel):
    """创作者选项列表响应。"""

    data: list[DouyinCreatorOptionPublic]  # 创作者选项列表
    count: int  # 创作者总数


__all__ = [
    "DouyinAweme",
    "DouyinAwemePublic",
    "DouyinAwemesPublic",
    "DouyinUserAction",
    "DouyinUserActionPublic",
    "DouyinUserActionsPublic",
    "DouyinAwemeCreatorCrawlRequest",
    "DouyinCreatorOptionPublic",
    "DouyinCreatorOptionsPublic",
]
