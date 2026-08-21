"""抖音达人限界上下文的业务模型与 API 契约。

包含达人名单表实体、达人-任务关联表实体、达人状态枚举，
以及达人增删改查与批量建任务的请求/响应模型。达人名单是用户主动
维护的采集目标（与关键词一致，属用户资产），sec_uid 明文存储；
采集到的第三方作品数据仍按既有隐私策略脱敏。
"""

import uuid
from datetime import datetime
from enum import Enum

from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.accounts.models import (
    DouyinAccountPoolStrategy,
    DouyinBrowserMode,
)
from crawler.business.douyin.keywords.models import DouyinKeywordSyncSource
from crawler.business.douyin.media.models import (
    MediaProcessingMode,
    MediaStorageBackend,
)
from crawler.business.douyin.tasks.models import (
    CrawlTaskPublic,
    CrawlTaskStatus,
    DouyinLoginType,
    DouyinRequestDelayLevel,
)
from pydantic import SecretStr, model_validator
from sqlalchemy import DateTime, ForeignKeyConstraint, UniqueConstraint
from sqlmodel import Field, SQLModel


class DouyinCreatorStatus(str, Enum):
    """达人处理状态（由关联任务状态聚合推导得出，不落库）。"""

    unprocessed = "unprocessed"  # 未处理：从未关联过任何任务
    active = "active"  # 进行中：存在排队/运行中的关联任务
    crawled = "crawled"  # 已采集：存在成功的关联任务
    failed = "failed"  # 失败：存在失败/取消/中断的关联任务且无进行中与成功任务


class DouyinCreator(SQLModel, table=True):
    """达人表实体，表示用户维护的达人采集名单中的一个达人。

    以 (owner_id, sec_uid) 作为业务唯一键；track_id 与 owner_id
    通过复合外键保证达人归属的赛道必须属于同一用户。sec_uid 为
    用户主动录入的主页 ID（用户资产，明文存储）；creator_hash 为
    脱敏哈希，用于与采集作品数据（douyin_aweme）关联。
    """

    __tablename__ = "douyin_creator"
    __table_args__ = (
        UniqueConstraint("owner_id", "sec_uid", name="uq_douyin_creator_owner_sec_uid"),
        ForeignKeyConstraint(
            ["track_id", "owner_id"],
            ["douyin_track.id", "douyin_track.owner_id"],
            name="fk_douyin_creator_track_owner",
            ondelete="NO ACTION",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4, primary_key=True
    )  # 主键，达人 UUID
    owner_id: uuid.UUID = Field(  # 归属用户 ID，用户删除时级联删除
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    track_id: uuid.UUID = Field(nullable=False, index=True)  # 归属赛道 ID
    sec_uid: str = Field(
        max_length=256, index=True
    )  # 达人主页 sec_user_id（用户录入，明文）
    creator_hash: str = Field(
        max_length=64, index=True
    )  # 脱敏身份哈希（由 sec_uid 计算），用于关联采集作品数据
    nickname: str = Field(
        default="", max_length=255
    )  # 达人昵称（可编辑，任务采集后回填）
    enabled: bool = Field(
        default=True, index=True
    )  # 是否启用，停用的达人不能用于批量建任务
    is_placeholder: bool = Field(
        default=False, index=True
    )  # 是否待补全占位达人（由历史采集作品导入，sec_uid 为脱敏哈希，补全主页后转正）
    notes: str = Field(default="", max_length=1000)  # 用户备注
    created_at: datetime = Field(  # 创建时间（UTC）
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    updated_at: datetime = Field(  # 最近更新时间（UTC）
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinCreatorTaskLink(SQLModel, table=True):
    """达人-任务关联表实体，记录达人与采集任务的多对多绑定关系。"""

    __tablename__ = "douyin_creator_task_link"
    __table_args__ = (
        UniqueConstraint("creator_id", "task_id", name="uq_douyin_creator_task_link"),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4, primary_key=True
    )  # 主键，关联记录 UUID
    creator_id: uuid.UUID = Field(  # 达人 ID，达人删除时级联删除
        foreign_key="douyin_creator.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    task_id: uuid.UUID = Field(  # 采集任务 ID，任务删除时级联删除
        foreign_key="crawl_task.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    source: str = Field(
        default=DouyinKeywordSyncSource.automatic.value, max_length=32
    )  # 绑定来源，见 DouyinKeywordSyncSource
    created_at: datetime = Field(  # 绑定创建时间（UTC）
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinCreatorPublic(SQLModel):
    """达人对外展示模型，聚合所属赛道信息与关联任务的统计汇总。"""

    id: uuid.UUID  # 达人 UUID
    track_id: uuid.UUID  # 归属赛道 ID
    track_name: str  # 归属赛道名称
    track_is_default: bool  # 归属赛道是否为默认赛道
    sec_uid: str  # 达人主页 sec_user_id
    creator_hash: str  # 脱敏身份哈希（sec_uid 的 SHA-256 前 16 位），用于作品深链
    nickname: str  # 达人昵称
    enabled: bool  # 是否启用
    is_placeholder: bool  # 是否待补全占位达人（由历史作品导入，补全主页链接后转正）
    notes: str  # 用户备注
    status: DouyinCreatorStatus  # 达人处理状态（由关联任务状态聚合推导）
    task_count: int  # 关联任务总数
    active_task_count: int  # 进行中（排队/运行等）的关联任务数
    success_task_count: int  # 成功的关联任务数
    failed_task_count: int  # 失败/取消/中断的关联任务数
    aweme_count: int  # 该达人采集到的作品总数
    last_task_id: uuid.UUID | None  # 最近一次关联任务 ID，无任务时为 None
    last_task_status: CrawlTaskStatus | None  # 最近一次关联任务状态，无任务时为 None
    last_crawled_at: datetime | None  # 最近一次任务完成时间，无完成任务时为 None
    created_at: datetime  # 达人创建时间（UTC）
    updated_at: datetime  # 达人最近更新时间（UTC）


class DouyinCreatorsPublic(SQLModel):
    """达人分页列表响应模型。"""

    data: list[DouyinCreatorPublic]  # 当前页达人列表
    count: int  # 满足条件的达人总数


class DouyinCreatorBulkCreateRequest(SQLModel):
    """批量创建达人请求体。"""

    creators: list[str] = Field(
        min_length=1, max_length=500
    )  # 达人主页链接或 sec_user_id 列表，1~500 个
    track_id: uuid.UUID | None = None  # 目标赛道 ID，None 表示使用默认赛道
    notes: str = Field(default="", max_length=1000)  # 统一写入的备注
    enabled: bool = True  # 创建后是否启用


class DouyinTrackCreatorAdd(SQLModel):
    """向赛道批量追加达人的请求模型。"""

    creators: list[str] = Field(
        min_length=1, max_length=200
    )  # 待追加的达人主页链接/sec_user_id


class DouyinBulkDeleteRequest(SQLModel):
    """批量删除请求体（按记录 ID）。"""

    ids: list[uuid.UUID] = Field(
        min_length=1, max_length=500
    )  # 待删除的记录 ID，1~500 个


class DouyinCreatorBulkCreateResult(SQLModel):
    """批量创建达人的结果响应。"""

    data: list[DouyinCreatorPublic]  # 本次涉及的达人（含新建与已存在）
    created_count: int  # 实际新建数量
    existing_count: int  # 已存在（复用）的数量


class DouyinCreatorUpdate(SQLModel):
    """达人更新请求体，所有字段可选，仅更新传入的字段。

    sec_uid 仅用于补全待补全占位达人：服务端会校验新主页与
    creator_hash 的脱敏哈希一致，通过后达人转为正式状态。
    """

    nickname: str | None = Field(default=None, max_length=255)  # 新昵称
    track_id: uuid.UUID | None = None  # 调整后的赛道 ID
    enabled: bool | None = None  # 启用/停用开关
    notes: str | None = Field(default=None, max_length=1000)  # 新备注
    sec_uid: str | None = Field(
        default=None, max_length=256
    )  # 补全用的主页 sec_user_id


class DouyinAwemeSyncResult(SQLModel):
    """从历史采集作品导入占位达人的结果统计。"""

    total_count: int  # 聚合出的去重达人数（按赛道×脱敏身份哈希）
    created_count: int  # 实际新建的占位达人数
    existing_count: int  # 已存在（跳过）的数量


class DouyinCreatorSyncResult(SQLModel):
    """达人同步（单任务或历史回填）的结果统计。"""

    task_count: int  # 本次同步涉及的任务数
    creator_count: int  # 本次同步涉及的达人总数
    created_count: int  # 新建达人数
    binding_count: int  # 新建达人-任务绑定数


class DouyinCreatorBatchTaskRequest(SQLModel):
    """达人批量创建采集任务的请求体。"""

    creator_ids: list[uuid.UUID] = Field(
        min_length=1, max_length=100
    )  # 选中的达人 ID，1~100 个
    track_id: uuid.UUID | None = None  # 指定赛道 ID；None 时要求所选达人同属一个赛道
    mode: str = Field(
        default="separate", max_length=32
    )  # 分组模式（达人任务固定独立模式）
    login_type: DouyinLoginType = DouyinLoginType.qrcode  # 登录方式
    browser_mode: DouyinBrowserMode | None = None  # 浏览器运行模式，None 表示用系统默认
    cookies: SecretStr | None = Field(
        default=None, repr=False
    )  # 一次性 Cookie（不落库）
    start_page: int = Field(default=1, ge=1)  # 主页起始页码
    max_awemes: int = Field(default=10, ge=1, le=1000)  # 单任务最大作品采集数
    fetch_comments: bool = True  # 是否采集评论
    fetch_sub_comments: bool = False  # 是否采集子评论（回复）
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
    publish_time: int = 0  # 作品发布时间筛选：0 不限 / 1 一天内 / 7 一周内 / 180 半年内
    media_processing_mode: MediaProcessingMode = (
        MediaProcessingMode.none
    )  # 媒体处理模式
    media_storage: MediaStorageBackend | None = (
        None  # 媒体存储后端，None 表示用系统默认
    )
    download_media: bool = False  # 是否下载媒体文件
    translate_subtitles: bool = False  # 是否翻译字幕
    transcription_language: str = Field(
        default="auto", min_length=2, max_length=32
    )  # 字幕转写语言，auto 表示自动识别
    account_id: uuid.UUID | None = None  # 指定账号 ID（与账号池二选一）
    account_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=20
    )  # 指定多个账号并行分片
    account_pool_id: uuid.UUID | None = None  # 指定账号池 ID（与指定账号二选一）
    account_strategy: DouyinAccountPoolStrategy = (
        DouyinAccountPoolStrategy.least_loaded
    )  # 账号池调度策略

    @model_validator(mode="after")
    def normalize_options(self) -> "DouyinCreatorBatchTaskRequest":
        """归一化互斥/联动选项并校验取值合法性。

        规则：不采评论则不采子评论；翻译字幕必须先下载媒体；
        下载媒体而未指定处理模式时默认 immediate；不下载媒体则关闭
        字幕翻译并重置处理模式；账号与账号池互斥；publish_time 仅允许
        0/1/7/180。

        异常：
            ValueError: 账号与账号池同时指定，或 publish_time 取值非法。
        """
        has_cookies = bool(self.cookies and self.cookies.get_secret_value().strip())
        if has_cookies:
            self.login_type = DouyinLoginType.cookie
        if self.login_type == DouyinLoginType.cookie and not has_cookies:
            raise ValueError("cookie 登录必须提供 cookies")
        if not self.fetch_comments:
            self.fetch_sub_comments = False
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
        if (
            sum(
                bool(value)
                for value in (self.account_id, self.account_ids, self.account_pool_id)
            )
            > 1
        ):
            raise ValueError("账号、多个账号和账号池只能选择一种")
        if has_cookies and any(
            (self.account_id, self.account_ids, self.account_pool_id)
        ):
            raise ValueError("选择已管理账号时不能再提交一次性 Cookie")
        if self.publish_time not in {0, 1, 7, 180}:
            raise ValueError("publish_time 只能是 0、1、7 或 180")
        return self


class DouyinCreatorTaskBatchResult(SQLModel):
    """达人批量建任务的结果响应。"""

    data: list[CrawlTaskPublic]  # 本次创建的采集任务列表
    count: int  # 创建的任务数


__all__ = [
    "DouyinCreatorStatus",
    "DouyinCreator",
    "DouyinCreatorTaskLink",
    "DouyinCreatorPublic",
    "DouyinCreatorsPublic",
    "DouyinCreatorBulkCreateRequest",
    "DouyinBulkDeleteRequest",
    "DouyinCreatorBulkCreateResult",
    "DouyinCreatorUpdate",
    "DouyinCreatorSyncResult",
    "DouyinAwemeSyncResult",
    "DouyinCreatorBatchTaskRequest",
    "DouyinCreatorTaskBatchResult",
]
