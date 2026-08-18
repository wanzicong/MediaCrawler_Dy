"""抖音互动限界上下文的业务模型与 API schema。

定义互动任务（评论/回复/私信）的数据库实体、状态枚举以及
预检、配额、详情等对外传输模型，供互动服务与 HTTP 适配层共用。
"""

import uuid
from datetime import datetime
from enum import Enum

from crawler.business.common.models import get_datetime_utc
from pydantic import SecretStr, model_validator
from sqlalchemy import DateTime, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class DouyinInteractionType(str, Enum):
    """抖音互动类型枚举。"""

    video_comment = "video_comment"  # 评论视频
    comment_reply = "comment_reply"  # 回复评论
    creator_message = "creator_message"  # 私信创作者


class DouyinInteractionStatus(str, Enum):
    """抖音互动任务状态机枚举。"""

    pending_confirmation = "pending_confirmation"  # 待人工确认
    queued = "queued"  # 已排队等待执行
    running = "running"  # 正在执行
    succeeded = "succeeded"  # 执行成功
    failed = "failed"  # 执行失败
    blocked = "blocked"  # 被阻断（如登录失效、风控）
    needs_review = "needs_review"  # 结果存疑，需要人工复核
    cancelled = "cancelled"  # 已取消


class DouyinInteractionCreate(SQLModel):
    """创建互动任务的请求模型。"""

    task_id: uuid.UUID  # 关联的采集任务 ID
    aweme_id: str = Field(min_length=1, max_length=128)  # 目标作品 aweme_id
    account_id: uuid.UUID  # 执行互动的抖音账号 ID
    interaction_type: DouyinInteractionType  # 互动类型
    target_comment_id: str | None = Field(
        default=None, max_length=128
    )  # 回复评论时的目标评论 ID
    content: SecretStr = Field(
        min_length=1, max_length=2200, repr=False
    )  # 互动内容（密文处理，不回显）

    @model_validator(mode="after")
    def validate_target(self) -> "DouyinInteractionCreate":
        """校验互动内容与目标评论的组合约束。

        返回：
            校验通过的自身实例。

        异常：
            ValueError: 内容为空、回复评论缺少目标评论，
                或非回复类型却携带目标评论时抛出。
        """
        content = self.content.get_secret_value().strip()
        if not content:
            raise ValueError("互动内容不能为空")
        if (
            self.interaction_type == DouyinInteractionType.comment_reply
            and not self.target_comment_id
        ):
            raise ValueError("回复评论必须指定目标评论")
        if (
            self.interaction_type != DouyinInteractionType.comment_reply
            and self.target_comment_id
        ):
            raise ValueError("只有回复评论可以指定目标评论")
        return self


class DouyinInteractionPreflightPublic(SQLModel):
    """互动发送前预检结果的对外模型。"""

    allowed: bool  # 是否允许发送
    failure_code: str | None = None  # 预检失败原因码
    message: str  # 预检结果说明（用户可见）
    account_name: str  # 所选账号名称
    remaining_daily_quota: int  # 账号今日剩余互动配额
    cooldown_until: datetime | None = None  # 冷却截止时间（当前未使用）
    duplicate_interaction_id: uuid.UUID | None = None  # 命中的重复互动任务 ID


class DouyinInteractionRetryRequest(SQLModel):
    """互动重试请求模型。"""

    confirm_not_sent: bool = False  # 用户已确认抖音端未发送成功，允许安全重试


class DouyinInteraction(SQLModel, table=True):
    """互动任务数据库实体，记录一次评论/回复/私信的完整生命周期。"""

    __tablename__ = "douyin_interaction"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key", name="uq_douyin_interaction_idempotency_key"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)  # 互动任务 ID
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )  # 归属用户 ID
    task_id: uuid.UUID = Field(
        foreign_key="crawl_task.id", nullable=False, ondelete="CASCADE", index=True
    )  # 关联的采集任务 ID
    account_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="douyin_account.id",
        nullable=True,
        ondelete="SET NULL",
        index=True,
    )  # 执行互动的抖音账号 ID（账号删除后置空）
    account_name: str = Field(default="", max_length=80)  # 账号名称冗余快照
    aweme_id: str = Field(max_length=128, index=True)  # 目标作品 aweme_id
    target_comment_id: str | None = Field(
        default=None, max_length=128, index=True
    )  # 回复的目标评论 ID
    interaction_type: str = Field(
        max_length=32, index=True
    )  # 互动类型（DouyinInteractionType 的值）
    content_encrypted: str = Field(sa_type=Text, repr=False)  # 加密后的互动内容
    content_preview: str = Field(default="", max_length=160)  # 内容明文预览（截断）
    content_hash: str = Field(max_length=64)  # 内容规范化后的 SHA-256 摘要，用于查重
    idempotency_key: str = Field(max_length=64, index=True)  # 幂等键，防同日重复提交
    status: str = Field(
        default=DouyinInteractionStatus.pending_confirmation.value,
        max_length=32,
        index=True,
    )  # 互动状态（DouyinInteractionStatus 的值）
    failure_code: str | None = Field(
        default=None, max_length=64, index=True
    )  # 失败原因码
    error: str | None = Field(default=None, sa_type=Text)  # 失败详情（用户可见）
    attempt_count: int = Field(default=0, ge=0)  # 已尝试执行次数
    result_platform_id: str | None = Field(
        default=None, max_length=128
    )  # 成功后平台返回的评论/消息 ID
    human_confirmed_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 用户确认发送的时间
    started_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 最近一次开始执行时间
    finished_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 最近一次终态完成时间
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 创建时间
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 更新时间


class DouyinInteractionEvent(SQLModel, table=True):
    """互动任务事件实体，记录状态流转与浏览器步骤截图等审计证据。"""

    __tablename__ = "douyin_interaction_event"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)  # 事件 ID
    interaction_id: uuid.UUID = Field(
        foreign_key="douyin_interaction.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )  # 所属互动任务 ID
    event: str = Field(
        max_length=64, index=True
    )  # 事件名称（如 created、confirmed、browser_*）
    from_status: str | None = Field(default=None, max_length=32)  # 流转前状态
    to_status: str = Field(max_length=32)  # 流转后状态
    detail: str | None = Field(default=None, max_length=1000)  # 事件说明（用户可见）
    attempt_number: int = Field(default=0, ge=0)  # 发生时的尝试次数
    screenshot_path: str | None = Field(
        default=None, max_length=500, repr=False
    )  # 截图相对路径
    screenshot_mime_type: str | None = Field(
        default=None, max_length=64
    )  # 截图 MIME 类型
    screenshot_size: int | None = Field(default=None, ge=0)  # 截图字节数
    screenshot_sha256: str | None = Field(
        default=None, max_length=64, repr=False
    )  # 截图 SHA-256 摘要
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 事件发生时间


class DouyinInteractionEventPublic(SQLModel):
    """互动事件的对外模型。"""

    id: uuid.UUID  # 事件 ID
    event: str  # 事件名称
    from_status: DouyinInteractionStatus | None  # 流转前状态
    to_status: DouyinInteractionStatus  # 流转后状态
    detail: str | None  # 事件说明
    attempt_number: int  # 发生时的尝试次数
    has_screenshot: bool  # 是否附带步骤截图
    created_at: datetime  # 事件发生时间


class DouyinInteractionPublic(SQLModel):
    """互动任务的对外列表/概要模型。"""

    id: uuid.UUID  # 互动任务 ID
    task_id: uuid.UUID  # 关联采集任务 ID
    account_id: uuid.UUID | None  # 执行账号 ID
    account_name: str  # 执行账号名称
    aweme_id: str  # 目标作品 aweme_id
    target_video_url: str  # 目标作品链接
    target_comment_id: str | None  # 回复的目标评论 ID
    target_comment_content: str | None  # 目标评论内容快照
    interaction_type: DouyinInteractionType  # 互动类型
    content_preview: str  # 内容预览
    status: DouyinInteractionStatus  # 当前状态
    failure_code: str | None  # 失败原因码
    error: str | None  # 失败详情
    attempt_count: int  # 已尝试执行次数
    result_platform_id: str | None  # 平台返回的结果 ID
    human_confirmed_at: datetime | None  # 人工确认时间
    started_at: datetime | None  # 开始执行时间
    finished_at: datetime | None  # 完成时间
    created_at: datetime  # 创建时间
    updated_at: datetime  # 更新时间
    can_confirm: bool  # 当前是否可确认发送
    can_retry: bool  # 当前是否可重试
    can_cancel: bool  # 当前是否可取消


class DouyinInteractionDetailPublic(DouyinInteractionPublic):
    """互动任务详情的对外模型，包含解密后的完整内容与事件时间线。"""

    content: str  # 解密后的完整互动内容
    events: list[DouyinInteractionEventPublic]  # 事件时间线


class DouyinInteractionsPublic(SQLModel):
    """互动任务分页列表的对外模型。"""

    data: list[DouyinInteractionPublic]  # 当前页数据
    count: int  # 满足条件的总条数


class DouyinInteractionQuotaPublic(SQLModel):
    """账号互动配额的对外模型。"""

    account_id: uuid.UUID  # 账号 ID
    account_name: str  # 账号名称
    daily_limit: int  # 每日互动上限
    used_today: int  # 今日已用配额
    remaining_today: int  # 今日剩余配额
    min_interval_seconds: float  # 两次互动最小间隔秒数（当前固定为 0）
    cooldown_until: datetime | None  # 冷却截止时间（当前未使用）
    available: bool  # 当前是否可用于互动


__all__ = [
    "DouyinInteractionType",
    "DouyinInteractionStatus",
    "DouyinInteractionCreate",
    "DouyinInteractionPreflightPublic",
    "DouyinInteractionRetryRequest",
    "DouyinInteraction",
    "DouyinInteractionEvent",
    "DouyinInteractionEventPublic",
    "DouyinInteractionPublic",
    "DouyinInteractionDetailPublic",
    "DouyinInteractionsPublic",
    "DouyinInteractionQuotaPublic",
]
