"""抖音爬取任务限界上下文的业务模型与请求/响应 schema。

包含爬取类型、任务状态等枚举，任务创建/恢复请求模型，
以及 CrawlTask、CrawlTaskShard 两张表的 SQLModel 实体和对外展示模型。
"""

import uuid
from datetime import datetime
from enum import Enum

from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.accounts.models import (
    DouyinAccountPoolStrategy,
    DouyinBrowserMode,
)
from crawler.business.douyin.media.models import (
    MediaProcessingMode,
    MediaStorageBackend,
)
from pydantic import SecretStr, model_validator
from sqlalchemy import DateTime, ForeignKeyConstraint, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class DouyinCrawlType(str, Enum):
    """抖音爬取类型。"""

    search = "search"  # 关键词搜索
    detail = "detail"  # 指定作品 ID/链接抓详情
    creator = "creator"  # 指定创作者主页抓作品
    creator_from_aweme = "creator_from_aweme"  # 由作品反查其创作者主页再抓作品
    liked = "liked"  # 当前登录账号的点赞列表
    collected = "collected"  # 当前登录账号的收藏列表


class DouyinSourceType(str, Enum):
    """任务与内容的来源类型。"""

    keyword = "keyword"  # 关键词任务/关键词命中的作品
    creator = "creator"  # 作者任务/作者主页作品
    mixed = "mixed"  # 同一任务同时绑定了关键词和作者
    task = "task"  # 指定作品、点赞、收藏等没有关键词/作者来源的任务


class DouyinLoginType(str, Enum):
    """抖音登录方式。"""

    qrcode = "qrcode"  # 扫码登录
    cookie = "cookie"  # 一次性 Cookie 登录


class CrawlTaskShardStatus(str, Enum):
    """任务分片（多账号并行时单个账号负责的子任务）的状态机。"""

    queued = "queued"  # 排队中
    running = "running"  # 执行中
    succeeded = "succeeded"  # 成功
    failed = "failed"  # 失败
    interrupted = "interrupted"  # 已中断
    cancelled = "cancelled"  # 已取消


class CrawlTaskStatus(str, Enum):
    """爬取任务状态机（后五个为终态或近终态）。"""

    queued = "queued"  # 排队中，等待调度
    waiting_login = "waiting_login"  # 等待扫码登录
    running = "running"  # 爬取执行中
    processing_media = "processing_media"  # 媒体处理中
    cancelling = "cancelling"  # 取消中
    succeeded = "succeeded"  # 成功（终态）
    failed = "failed"  # 失败（终态）
    cancelled = "cancelled"  # 已取消（终态）
    interrupted = "interrupted"  # 已中断（终态，如服务重启导致）


class CrawlTaskPhase(str, Enum):
    """任务断点所处的执行阶段（恢复时据此判断从哪一步继续）。"""

    crawl = "crawl"  # 爬取阶段（作品/评论抓取）
    media = "media"  # 媒体处理阶段（下载/字幕）
    completed = "completed"  # 全部完成


class DouyinRequestDelayLevel(str, Enum):
    """请求延迟档位，决定请求间隔随机区间的基准范围。"""

    fast = "fast"  # 快速（约 1~2 秒）
    steady = "steady"  # 稳健（约 3~6 秒）
    ultra_steady = "ultra_steady"  # 超稳健（约 6~12 秒）


class CrawlTaskCreate(SQLModel):
    """创建抖音爬取任务的请求模型（HTTP/MCP 入参）。

    校验爬取目标与登录方式的一致性，并对评论开关、媒体下载、字幕翻译等选项做联动修正；
    cookies 使用 SecretStr 存储，序列化与日志输出时自动脱敏。
    """

    track_id: uuid.UUID | None = None  # 归属赛道 ID，为空时由服务端解析默认赛道
    crawl_type: DouyinCrawlType = DouyinCrawlType.search  # 爬取类型
    login_type: DouyinLoginType = DouyinLoginType.qrcode  # 登录方式
    browser_mode: DouyinBrowserMode | None = None  # 浏览器模式，为空使用服务端默认
    cookies: SecretStr | None = Field(
        default=None, repr=False
    )  # 一次性 Cookie（不落库）
    keywords: list[str] = Field(
        default_factory=list, max_length=20
    )  # 搜索关键词列表，最多 20 个
    video_ids: list[str] = Field(
        default_factory=list, max_length=1000
    )  # 作品 ID/短链/链接列表，最多 1000 个
    comment_source_task_id: uuid.UUID | None = None  # 评论补采复用作品的来源任务
    creator_ids: list[str] = Field(
        default_factory=list, max_length=100
    )  # 创作者 sec_uid/主页链接列表，最多 100 个
    start_page: int = Field(default=1, ge=1)  # 搜索起始页码，从 1 开始
    max_awemes: int = Field(default=10, ge=1, le=1000)  # 单任务最多采集的作品数
    fetch_comments: bool = True  # 是否抓取一级评论
    fetch_sub_comments: bool = False  # 是否抓取二级评论（依赖 fetch_comments）
    max_comments_per_aweme: int = Field(
        default=10, ge=1, le=1000
    )  # 单个作品最多抓取的评论数
    concurrency: int = Field(default=1, ge=1, le=5)  # 抓取并发数
    request_delay_level: DouyinRequestDelayLevel = (
        DouyinRequestDelayLevel.fast
    )  # 请求延迟档位
    request_interval_seconds: float = Field(
        default=1.0, ge=0.2, le=60.0
    )  # 请求间隔下限（秒），与档位合成随机区间
    task_interval_seconds: float | None = Field(
        default=None, ge=0.0, le=3600.0
    )  # 任务完成后到下一采集任务开始前的间隔（秒）；为空时沿用请求风控区间
    publish_time: int = (
        0  # 搜索的发布时间过滤：0 不限 / 1 一天内 / 7 一周内 / 180 半年内
    )
    media_processing_mode: MediaProcessingMode = (
        MediaProcessingMode.none
    )  # 媒体处理模式
    media_storage: MediaStorageBackend | None = None  # 媒体存储后端，为空使用服务端默认
    download_media: bool = False  # 是否下载媒体文件
    translate_subtitles: bool = False  # 是否转写/翻译字幕（隐含 download_media）
    subtitle_only: bool = False  # 仅为字幕转写临时下载，不保留视频文件
    transcription_language: str = Field(
        default="auto", min_length=2, max_length=32
    )  # 字幕转写语言，auto 表示自动识别
    account_id: uuid.UUID | None = None  # 指定单个托管账号
    account_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=20
    )  # 指定多个托管账号（分片执行），最多 20 个
    account_pool_id: uuid.UUID | None = None  # 指定账号池
    account_strategy: DouyinAccountPoolStrategy = (
        DouyinAccountPoolStrategy.least_loaded
    )  # 账号池调度策略

    @model_validator(mode="after")
    def validate_crawl_target(self) -> "CrawlTaskCreate":
        """校验并联动修正任务参数。

        按爬取类型校验必填目标（keywords/video_ids/creator_ids），处理 Cookie 登录、
        评论开关、媒体下载与字幕翻译之间的联动，并保证账号三选一（单账号/多账号/账号池）。

        返回：校验通过并可能修正后的自身。
        异常：ValueError —— 参数组合不合法时抛出。
        """
        if self.cookies and self.cookies.get_secret_value().strip():
            self.login_type = DouyinLoginType.cookie
        if self.login_type == DouyinLoginType.cookie and not (
            self.cookies and self.cookies.get_secret_value().strip()
        ):
            raise ValueError("cookie 登录必须提供 cookies")
        if self.crawl_type == DouyinCrawlType.search and not any(
            value.strip() for value in self.keywords
        ):
            raise ValueError("search 模式必须提供 keywords")
        if self.crawl_type == DouyinCrawlType.detail and not any(
            value.strip() for value in self.video_ids
        ):
            raise ValueError("detail 模式必须提供 video_ids")
        if self.comment_source_task_id is not None:
            if self.crawl_type != DouyinCrawlType.detail:
                raise ValueError("评论补采来源任务只能用于 detail 模式")
            if len([value for value in self.video_ids if value.strip()]) != 1:
                raise ValueError("评论补采任务必须且只能包含一个作品")
            if not self.fetch_comments:
                raise ValueError("评论补采任务必须开启评论采集")
        if self.crawl_type == DouyinCrawlType.creator and not any(
            value.strip() for value in self.creator_ids
        ):
            raise ValueError("creator 模式必须提供 creator_ids")
        if self.crawl_type == DouyinCrawlType.creator_from_aweme and not any(
            value.strip() for value in self.video_ids
        ):
            raise ValueError("creator_from_aweme 模式必须提供 video_ids")
        if self.publish_time not in {0, 1, 7, 180}:
            raise ValueError("publish_time 只能是 0、1、7 或 180")
        if not self.fetch_comments:
            self.fetch_sub_comments = False
        if self.subtitle_only:
            self.translate_subtitles = True
            self.media_storage = None
        if self.translate_subtitles:
            self.download_media = True
        if (
            self.download_media
            and self.media_processing_mode == MediaProcessingMode.none
        ):
            self.media_processing_mode = MediaProcessingMode.immediate
        if not self.download_media:
            self.translate_subtitles = False
            self.media_processing_mode = MediaProcessingMode.none
        selection_count = sum(
            bool(value)
            for value in (self.account_id, self.account_ids, self.account_pool_id)
        )
        if selection_count > 1:
            raise ValueError("账号、多个账号和账号池只能选择一种")
        if self.cookies and selection_count:
            raise ValueError("选择已管理账号时不能再提交一次性 Cookie")
        return self

    def public_request(self) -> dict[str, object]:
        """返回脱敏后的请求字典（剔除 cookies），用于落库与对外展示，并附带实际请求间隔区间。"""
        payload = self.model_dump(mode="json", exclude={"cookies"})
        payload["request_interval_range_seconds"] = list(
            self.request_interval_range_seconds()
        )
        return payload

    def request_interval_range_seconds(self) -> tuple[float, float]:
        """由延迟档位与自定义间隔合成每次请求的随机间隔区间（秒）。

        返回：(下限, 上限)；下限不小于 request_interval_seconds，上限不低于下限的 1.2 倍。
        """
        preset_min, preset_max = {
            DouyinRequestDelayLevel.fast: (1.0, 2.0),
            DouyinRequestDelayLevel.steady: (3.0, 6.0),
            DouyinRequestDelayLevel.ultra_steady: (6.0, 12.0),
        }[self.request_delay_level]
        minimum = max(preset_min, self.request_interval_seconds)
        maximum = max(preset_max, minimum * 1.2)
        return round(minimum, 3), round(maximum, 3)

    def task_interval_range_seconds(self) -> tuple[float, float]:
        """返回任务之间的冷却区间（秒）。

        显式设置任务间隔时使用固定间隔；历史请求未提供该字段时，
        继续沿用原先由请求风控档位推导的区间，避免旧任务行为突变。
        """
        if self.task_interval_seconds is not None:
            value = round(self.task_interval_seconds, 3)
            return value, value
        return self.request_interval_range_seconds()


class CrawlTaskResumeRequest(SQLModel):
    """恢复（继续执行）已终止任务的请求模型。"""

    resume_crawl: bool | None = None  # 是否恢复爬取阶段，None 表示按断点自动判断
    resume_media: bool | None = (
        None  # 是否恢复媒体处理阶段，None 表示按任务配置自动判断
    )
    cookies: SecretStr | None = Field(
        default=None, repr=False
    )  # 恢复时替换使用的一次性 Cookie
    account_id: uuid.UUID | None = None  # 恢复爬取时改用的托管账号；为空则沿用原配置
    task_interval_seconds: float | None = Field(
        default=None, ge=0.0, le=3600.0
    )  # 本次恢复后任务之间的间隔；为空沿用任务原配置

    @model_validator(mode="after")
    def validate_resume_scope(self) -> "CrawlTaskResumeRequest":
        """校验至少恢复一个阶段（爬取与媒体处理不能同时显式关闭）。"""
        if self.resume_crawl is False and self.resume_media is False:
            raise ValueError("至少需要恢复爬取或媒体处理中的一项")
        if self.account_id is not None and self.resume_crawl is False:
            raise ValueError("仅恢复爬取阶段时才能更换执行账号")
        if self.account_id is not None and self.cookies is not None:
            raise ValueError("更换托管账号时不能同时提交一次性 Cookie")
        return self


class CrawlTaskBulkDeleteRequest(SQLModel):
    """批量删除已结束采集任务的请求体。"""

    ids: list[uuid.UUID] = Field(
        min_length=1, max_length=500
    )  # 待删除的任务 ID，最多 500 条


class CrawlTaskBulkResumeRequest(SQLModel):
    """批量恢复失效采集任务的请求体。"""

    ids: list[uuid.UUID] = Field(
        min_length=1, max_length=500
    )  # 待恢复的任务 ID，最多 500 条
    task_interval_seconds: float | None = Field(
        default=None, ge=0.0, le=3600.0
    )  # 批量恢复时统一覆盖的任务间隔；为空保留各任务原配置


class CrawlTask(SQLModel, table=True):
    """抖音爬取任务表：一条记录对应一次采集任务，多账号执行时再拆分为分片。"""

    __tablename__ = "crawl_task"
    __table_args__ = (
        ForeignKeyConstraint(
            ["track_id", "owner_id"],
            ["douyin_track.id", "douyin_track.owner_id"],
            name="fk_crawl_task_track_owner",
            ondelete="NO ACTION",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4, primary_key=True
    )  # 任务 ID（主键）
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )  # 归属用户 ID，删除用户时级联删除任务
    track_id: uuid.UUID = Field(nullable=False, index=True)  # 归属赛道 ID
    account_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="douyin_account.id",
        nullable=True,
        ondelete="SET NULL",
        index=True,
    )  # 关联的托管账号 ID，账号删除后置空
    account_pool_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="douyin_account_pool.id",
        nullable=True,
        ondelete="SET NULL",
        index=True,
    )  # 关联的账号池 ID，账号池删除后置空
    account_strategy: str = Field(
        default=DouyinAccountPoolStrategy.least_loaded.value, max_length=32
    )  # 账号池调度策略（DouyinAccountPoolStrategy 值）
    crawl_type: str = Field(max_length=32, index=True)  # 爬取类型（DouyinCrawlType 值）
    status: str = Field(
        default=CrawlTaskStatus.queued.value, max_length=32, index=True
    )  # 任务状态（CrawlTaskStatus 值）
    request_json: str = Field(sa_type=Text)  # 任务请求参数快照（JSON，不含 cookies）
    aweme_count: int = 0  # 已采集作品数（冗余计数）
    comment_count: int = 0  # 已采集评论数（冗余计数）
    action_count: int = 0  # 已记录的点赞/收藏行为数（冗余计数）
    checkpoint_json: str = Field(
        default="{}", sa_type=Text
    )  # 断点续爬检查点（JSON：version/phase/crawl_type/position）
    resume_count: int = 0  # 恢复（继续执行）次数
    error: str | None = Field(default=None, sa_type=Text)  # 最近一次失败原因
    qrcode_path: str | None = Field(
        default=None, sa_type=Text
    )  # 扫码登录二维码图片路径
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 创建时间
    started_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 首次开始执行时间
    finished_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 结束时间
    last_resumed_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 最近一次恢复时间


class CrawlTaskPublic(SQLModel):
    """爬取任务对外展示模型（含赛道信息、代表性作品与可恢复性标记）。"""

    id: uuid.UUID  # 任务 ID
    owner_id: uuid.UUID  # 归属用户 ID
    track_id: uuid.UUID  # 归属赛道 ID
    track_name: str  # 赛道名称
    track_is_default: bool  # 是否默认赛道
    account_id: uuid.UUID | None  # 关联的托管账号 ID
    account_name: str | None  # 关联账号名称（账号删除后为空）
    account_pool_id: uuid.UUID | None  # 关联的账号池 ID
    account_pool_name: str | None  # 关联账号池名称（账号池删除后为空）
    account_strategy: DouyinAccountPoolStrategy  # 账号池调度策略
    crawl_type: DouyinCrawlType  # 爬取类型
    status: CrawlTaskStatus  # 任务状态
    request: dict[str, object]  # 脱敏后的请求参数快照
    display_title: str | None = None  # 代表性作品标题（列表页展示用）
    display_author: str | None = None  # 代表性作品作者昵称
    creator_names: list[str] = Field(
        default_factory=list
    )  # 关联达人昵称列表（达人名单驱动，按任务绑定表推导）
    source_type: DouyinSourceType = DouyinSourceType.task  # 统一来源类型
    source_names: list[str] = Field(default_factory=list)  # 来源关键词或作者名称列表
    source_label: str = "指定作品"  # 列表页直接展示的来源文案
    display_aweme_id: str | None = None  # 代表性作品 aweme_id
    aweme_count: int  # 已采集作品数
    comment_count: int  # 已采集评论数
    action_count: int  # 已记录行为数
    checkpoint_phase: CrawlTaskPhase  # 当前断点所处阶段
    resume_count: int  # 恢复次数
    can_resume_crawl: bool  # 是否可恢复爬取阶段
    can_resume_media: bool  # 是否可恢复媒体处理阶段
    error: str | None  # 最近一次失败原因
    has_qrcode: bool  # 当前是否有可用的登录二维码
    created_at: datetime  # 创建时间
    started_at: datetime | None  # 首次开始执行时间
    finished_at: datetime | None  # 结束时间
    last_resumed_at: datetime | None  # 最近一次恢复时间


class CrawlTasksPublic(SQLModel):
    """爬取任务分页列表响应。"""

    data: list[CrawlTaskPublic]  # 当前页任务列表
    count: int  # 满足条件的任务总数


class CrawlTaskResumeFailure(SQLModel):
    """批量恢复中单个任务未能受理时的错误明细。"""

    task_id: uuid.UUID
    error: str


class CrawlTaskBulkResumePublic(SQLModel):
    """批量恢复任务的受理结果。"""

    data: list[CrawlTaskPublic]
    count: int
    failures: list[CrawlTaskResumeFailure]
    failed_count: int


class DouyinSourceOptionPublic(SQLModel):
    """按赛道返回的关键词/作者筛选项。"""

    id: uuid.UUID  # 关键词或作者的业务 UUID
    source_type: DouyinSourceType  # keyword 或 creator
    name: str  # 关键词原文或作者昵称
    usage_count: int  # 在该赛道下绑定的任务数


class DouyinSourceOptionsPublic(SQLModel):
    """关键词/作者来源筛选项列表。"""

    data: list[DouyinSourceOptionPublic]
    count: int


class CrawlTaskShard(SQLModel, table=True):
    """爬取任务分片表：多账号并行时每个账号负责的一个目标子集。"""

    __tablename__ = "crawl_task_shard"
    __table_args__ = (
        UniqueConstraint("task_id", "shard_index", name="uq_crawl_task_shard_index"),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4, primary_key=True
    )  # 分片 ID（主键）
    task_id: uuid.UUID = Field(
        foreign_key="crawl_task.id", nullable=False, ondelete="CASCADE", index=True
    )  # 所属任务 ID，任务删除时级联删除
    account_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="douyin_account.id",
        nullable=True,
        ondelete="SET NULL",
        index=True,
    )  # 分片使用的账号 ID，账号删除后置空
    shard_index: int = Field(ge=0)  # 分片序号（同一任务内唯一，从 0 开始）
    status: str = Field(
        default=CrawlTaskShardStatus.queued.value, max_length=32, index=True
    )  # 分片状态（CrawlTaskShardStatus 值）
    request_json: str = Field(sa_type=Text)  # 分片请求参数快照（JSON）
    checkpoint_json: str = Field(default="{}", sa_type=Text)  # 分片断点检查点（JSON）
    aweme_count: int = 0  # 分片采集作品数
    comment_count: int = 0  # 分片采集评论数
    error: str | None = Field(default=None, sa_type=Text)  # 分片失败原因
    started_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 分片开始时间
    finished_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 分片结束时间
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 创建时间


class CrawlTaskShardPublic(SQLModel):
    """任务分片对外展示模型。"""

    id: uuid.UUID  # 分片 ID
    task_id: uuid.UUID  # 所属任务 ID
    account_id: uuid.UUID | None  # 分片使用的账号 ID
    account_name: str | None  # 分片使用的账号名称
    shard_index: int  # 分片序号
    status: CrawlTaskShardStatus  # 分片状态
    request: dict[str, object]  # 分片请求参数快照
    aweme_count: int  # 分片采集作品数
    comment_count: int  # 分片采集评论数
    error: str | None  # 分片失败原因
    started_at: datetime | None  # 分片开始时间
    finished_at: datetime | None  # 分片结束时间
    created_at: datetime  # 创建时间


class CrawlTaskShardsPublic(SQLModel):
    """任务分片列表响应。"""

    data: list[CrawlTaskShardPublic]  # 分片列表
    count: int  # 分片总数


__all__ = [
    "DouyinCrawlType",
    "DouyinLoginType",
    "CrawlTaskShardStatus",
    "CrawlTaskStatus",
    "CrawlTaskPhase",
    "DouyinRequestDelayLevel",
    "CrawlTaskCreate",
    "CrawlTaskResumeRequest",
    "CrawlTaskBulkDeleteRequest",
    "CrawlTask",
    "CrawlTaskPublic",
    "CrawlTasksPublic",
    "CrawlTaskShard",
    "CrawlTaskShardPublic",
    "CrawlTaskShardsPublic",
]
