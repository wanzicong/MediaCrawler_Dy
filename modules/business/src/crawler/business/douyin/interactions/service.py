"""抖音互动的应用服务与执行编排。

覆盖互动任务的预检（配额/账号状态/查重）、创建（内容加密 + 幂等键）、
状态机流转、异步执行调度（每账号串行、租约管理、超时与失败归类），
以及截图证据读取、配额查询等读写用例，供 HTTP 适配层调用。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import random
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import quote

from crawler.bootstrap.database import engine
from crawler.bootstrap.settings import settings
from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.accounts.models import (
    DouyinAccount,
    DouyinAccountStatus,
)
from crawler.business.douyin.accounts.service import (
    AccountConfigurationError,
    release_account,
    reserve_account,
    resolve_account_browser,
    select_task_accounts,
)
from crawler.business.douyin.comments.models import DouyinComment
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.interactions.models import (
    DouyinBatchCommentCreate,
    DouyinBatchCommentMode,
    DouyinBatchCommentPublic,
    DouyinInteraction,
    DouyinInteractionCreate,
    DouyinInteractionDetailPublic,
    DouyinInteractionEvent,
    DouyinInteractionEventPublic,
    DouyinInteractionPreflightPublic,
    DouyinInteractionPublic,
    DouyinInteractionQuotaPublic,
    DouyinInteractionsPublic,
    DouyinInteractionStatus,
    DouyinInteractionType,
)
from crawler.business.douyin.interactions.screenshots import (
    InteractionScreenshotNotFoundError,
    InteractionStepRecorder,
    read_interaction_screenshot,
)
from crawler.business.douyin.tasks.models import CrawlTask, DouyinSourceType
from crawler.business.douyin.tasks.source_attribution import (
    build_task_source_values,
    resolve_source_filter,
)
from crawler.business.douyin.tracks.models import DouyinTrack
from crawler.douyin_client.interactions import (
    DouyinInteractionExecutor,
    InteractionBrowserConnection,
    InteractionExecutionError,
    InteractionExecutionRequest,
)
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, select

logger = logging.getLogger(__name__)

_CORRUPTED_CONTENT_PLACEHOLDER = (
    "[历史互动内容编码损坏，原文无法恢复]"  # 内容编码损坏时的统一展示占位符
)
_NON_RETRYABLE_FAILURE_CODES = {"target_unavailable"}  # 不允许重试的失败原因码
_RECENT_COMMENT_STATUSES = {
    DouyinInteractionStatus.pending_confirmation.value,
    DouyinInteractionStatus.queued.value,
    DouyinInteractionStatus.running.value,
    DouyinInteractionStatus.succeeded.value,
    DouyinInteractionStatus.needs_review.value,
}  # 会占用近期评论防重复窗口的状态


class InteractionValidationError(ValueError):
    """互动请求校验失败，携带机器可读的失败原因码与可选的关联互动 ID。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        interaction_id: uuid.UUID | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code  # 失败原因码（如 task_not_found、quota_exceeded）
        self.interaction_id = interaction_id  # 关联的既有互动 ID（如查重命中时）


class InteractionStateError(RuntimeError):
    """互动状态机不允许当前操作（如重复确认、非法取消）。"""


class InteractionNotFoundError(LookupError):
    """互动不存在或对当前请求用户不可见。"""


class InteractionCipher:
    """互动内容加解密器：由 SECRET_KEY 派生 Fernet 密钥，落库内容全程密文。"""

    def __init__(self, secret: str) -> None:
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        self._fernet = Fernet(key)

    def encrypt(self, value: str) -> str:
        """加密明文内容，返回可入库的密文字符串。"""
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        """解密密文内容。

        异常：
            InteractionStateError: 密文无法解密（通常是 SECRET_KEY 配置变更）。
        """
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise InteractionStateError(
                "互动内容无法解密，请检查 SECRET_KEY 配置"
            ) from exc


content_cipher = InteractionCipher(settings.SECRET_KEY)  # 模块级内容加解密单例


@dataclass(frozen=True)
class PreflightResult:
    """互动预检的内部结果：对外结论 + 后续创建/执行所需的实体快照。"""

    public: DouyinInteractionPreflightPublic  # 预检结论的对外模型
    task: CrawlTask  # 关联采集任务
    aweme: DouyinAweme  # 目标作品
    account: DouyinAccount  # 执行账号
    comment: DouyinComment | None  # 回复目标评论（仅 comment_reply 类型）
    normalized_content: str  # 规范化后的互动内容
    content_hash: str  # 内容摘要（用于查重与幂等键）


@dataclass(frozen=True)
class InteractionScreenshotPayload:
    """互动步骤截图的读取结果。"""

    content: bytes  # 截图原始字节
    media_type: str  # 截图 MIME 类型
    event_id: uuid.UUID  # 关联事件 ID


@dataclass(frozen=True)
class BatchCommentPlan:
    """一条批量评论子任务的创建计划。"""

    task_id: uuid.UUID
    aweme_id: str
    content: str
    account_id: uuid.UUID
    sequence_index: int
    scheduled_at: datetime


def _content_hash(content: str) -> str:
    """计算内容折叠空白后的 SHA-256 摘要，用于查重与幂等键。"""
    normalized = " ".join(content.split())
    return hashlib.sha256(normalized.encode()).hexdigest()


def _preview(content: str) -> str:
    """生成内容预览：折叠空白并截断到 160 字符以内。"""
    compact = " ".join(content.split())
    return compact if len(compact) <= 157 else f"{compact[:157]}..."


def _has_probable_encoding_damage(content: str) -> bool:
    """检测文本在到达 UTF-8 API 之前是否已被替换损坏。

    Windows 命令行客户端在其活动代码页无法表示请求负载时，可能会把
    非 ASCII 字符静默替换成问号。中文里正常的疑问句必须保持有效，
    因此只把高密度的 ASCII 问号串（或 Unicode 替换字符）视为损坏。
    """
    compact = "".join(content.split())
    if "\ufffd" in compact:
        return True
    question_count = compact.count("?")
    return (
        question_count >= 4
        and "???" in compact
        and question_count / max(len(compact), 1) >= 0.3
    )


def _validate_content_encoding(content: str) -> None:
    """校验互动内容未发生编码损坏，损坏时抛出 InteractionValidationError。"""
    if _has_probable_encoding_damage(content):
        raise InteractionValidationError(
            "invalid_content_encoding",
            "互动内容疑似在提交前发生编码损坏，请使用 UTF-8 重新输入后再发送",
        )


def _display_content(content: str) -> str:
    """返回用于展示的内容：编码损坏时用占位符替代。"""
    if _has_probable_encoding_damage(content):
        return _CORRUPTED_CONTENT_PLACEHOLDER
    return content


def _daily_window(now: datetime) -> tuple[datetime, datetime]:
    """返回 now 所在 UTC 自然日的 [起始, 结束) 时间窗口。"""
    start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _used_today(session: Session, owner_id: uuid.UUID, account_id: uuid.UUID) -> int:
    """统计账号今日已确认发送且未取消的互动数量（按 UTC 自然日）。"""
    start, end = _daily_window(get_datetime_utc())
    return session.exec(
        select(func.count())
        .select_from(DouyinInteraction)
        .where(
            DouyinInteraction.owner_id == owner_id,
            DouyinInteraction.account_id == account_id,
            col(DouyinInteraction.human_confirmed_at).is_not(None),
            col(DouyinInteraction.human_confirmed_at) >= start,
            col(DouyinInteraction.human_confirmed_at) < end,
            DouyinInteraction.status != DouyinInteractionStatus.cancelled.value,
        )
    ).one()


def _daily_limit(account: DouyinAccount) -> int:
    """计算账号的每日互动上限：账号自身上限与全局配置取较小值。"""
    return min(account.daily_task_limit, settings.DOUYIN_INTERACTION_DAILY_LIMIT)


def interaction_target_comment_contents(
    session: Session, interactions: Sequence[DouyinInteraction]
) -> dict[tuple[uuid.UUID, str, str], str]:
    """为互动列表响应一次性批量加载回复目标评论的内容。"""
    target_keys = {
        (
            interaction.task_id,
            interaction.aweme_id,
            interaction.target_comment_id,
        )
        for interaction in interactions
        if interaction.target_comment_id
    }
    if not target_keys:
        return {}
    task_ids = {task_id for task_id, _, _ in target_keys}
    aweme_ids = {aweme_id for _, aweme_id, _ in target_keys}
    comment_ids = {comment_id for _, _, comment_id in target_keys}
    comments = session.exec(
        select(DouyinComment).where(
            col(DouyinComment.task_id).in_(task_ids),
            col(DouyinComment.aweme_id).in_(aweme_ids),
            col(DouyinComment.comment_id).in_(comment_ids),
        )
    ).all()
    return {
        (comment.task_id, comment.aweme_id, comment.comment_id): comment.content
        for comment in comments
        if (comment.task_id, comment.aweme_id, comment.comment_id) in target_keys
    }


def interaction_public_values(
    interaction: DouyinInteraction, *, target_comment_content: str | None = None
) -> dict[str, object]:
    """构建互动对外模型的字段字典，附带 can_confirm/can_retry/can_cancel 操作位。"""
    status = DouyinInteractionStatus(interaction.status)
    content_damaged = _has_probable_encoding_damage(interaction.content_preview)
    return {
        "id": interaction.id,
        "task_id": interaction.task_id,
        "batch_id": interaction.batch_id,
        "sequence_index": interaction.sequence_index,
        "scheduled_at": interaction.scheduled_at,
        "account_id": interaction.account_id,
        "account_name": interaction.account_name,
        "account_pool_id": interaction.account_pool_id,
        "aweme_id": interaction.aweme_id,
        "target_video_url": (
            f"https://www.douyin.com/video/{quote(interaction.aweme_id, safe='')}"
        ),
        "target_comment_id": interaction.target_comment_id,
        "target_comment_content": target_comment_content,
        "interaction_type": interaction.interaction_type,
        "content_preview": _display_content(interaction.content_preview),
        "status": status,
        "failure_code": interaction.failure_code,
        "error": interaction.error,
        "attempt_count": interaction.attempt_count,
        "result_platform_id": interaction.result_platform_id,
        "human_confirmed_at": interaction.human_confirmed_at,
        "started_at": interaction.started_at,
        "finished_at": interaction.finished_at,
        "created_at": interaction.created_at,
        "updated_at": interaction.updated_at,
        "can_confirm": (
            status == DouyinInteractionStatus.pending_confirmation
            and not content_damaged
        ),
        # 除已成功外的任何状态都允许手动重试。
        # 对排队中/执行中的重试是幂等的，只会确保 worker 被调度，
        # 绝不会并发启动第二个浏览器操作。
        "can_retry": status != DouyinInteractionStatus.succeeded
        and not content_damaged
        and interaction.failure_code not in _NON_RETRYABLE_FAILURE_CODES,
        "can_cancel": status
        in {
            DouyinInteractionStatus.pending_confirmation,
            DouyinInteractionStatus.queued,
        },
    }


def interaction_public(
    interaction: DouyinInteraction,
    *,
    target_comment_content: str | None = None,
    source_values: dict[str, object] | None = None,
) -> DouyinInteractionPublic:
    """把互动实体转换为对外概要模型。"""
    return DouyinInteractionPublic(
        **interaction_public_values(
            interaction, target_comment_content=target_comment_content
        ),
        **(source_values or {}),
    )


def interaction_public_with_target(
    session: Session, interaction: DouyinInteraction
) -> DouyinInteractionPublic:
    """转换为对外概要模型，并补充回复目标评论的内容。"""
    target_contents = interaction_target_comment_contents(session, [interaction])
    target_content = (
        target_contents.get(
            (
                interaction.task_id,
                interaction.aweme_id,
                interaction.target_comment_id,
            )
        )
        if interaction.target_comment_id
        else None
    )
    task = session.get(CrawlTask, interaction.task_id)
    source_values = (
        build_task_source_values(session, [task]).get(task.id, {})
        if task is not None
        else None
    )
    return interaction_public(
        interaction,
        target_comment_content=target_content,
        source_values=source_values,
    )


def interaction_detail(
    session: Session, interaction: DouyinInteraction
) -> DouyinInteractionDetailPublic:
    """构建互动详情：概要字段 + 解密后的完整内容 + 事件时间线。"""
    events = session.exec(
        select(DouyinInteractionEvent)
        .where(DouyinInteractionEvent.interaction_id == interaction.id)
        .order_by(col(DouyinInteractionEvent.created_at).asc())
    ).all()
    public = interaction_public_with_target(session, interaction)
    return DouyinInteractionDetailPublic(
        **public.model_dump(),
        content=_display_content(content_cipher.decrypt(interaction.content_encrypted)),
        events=[interaction_event_public(event) for event in events],
    )


def interaction_event_public(
    event: DouyinInteractionEvent,
) -> DouyinInteractionEventPublic:
    """把互动事件实体转换为对外模型（截图只暴露有无，不暴露路径）。"""
    return DouyinInteractionEventPublic(
        id=event.id,
        event=event.event,
        from_status=event.from_status,
        to_status=event.to_status,
        detail=event.detail,
        attempt_number=event.attempt_number,
        has_screenshot=bool(event.screenshot_path),
        created_at=event.created_at,
    )


def get_owned_interaction(
    session: Session,
    *,
    owner_id: uuid.UUID,
    interaction_id: uuid.UUID,
    is_superuser: bool = False,
) -> DouyinInteraction | None:
    """按可见性加载互动：不存在或对非超管不可见时返回 None。"""
    interaction = session.get(DouyinInteraction, interaction_id)
    if interaction is None:
        return None
    if not is_superuser and interaction.owner_id != owner_id:
        return None
    return interaction


def preflight(
    session: Session,
    *,
    owner_id: uuid.UUID,
    request: DouyinInteractionCreate,
    exclude_interaction_id: uuid.UUID | None = None,
) -> PreflightResult:
    """互动发送前预检：目标存在性、账号可用性、当日配额与重复内容检查。

    依次校验任务/作品/账号/目标评论是否存在且归属当前用户，再按序判定
    账号停用、登录失效、状态异常、并发占用、配额耗尽，最后做时间窗口内
    的同目标同内容查重；任一条件命中都会写入失败原因码与提示信息。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 ID。
        request: 互动创建请求。
        exclude_interaction_id: 查重时要排除的互动 ID（重试场景传自身）。

    返回：
        预检结果，包含对外结论与创建/执行所需的实体快照。

    异常：
        InteractionValidationError: 内容编码损坏或目标对象不存在时抛出。
    """
    content = request.content.get_secret_value().strip()
    _validate_content_encoding(content)
    digest = _content_hash(content)
    task = session.get(CrawlTask, request.task_id)
    if task is None or task.owner_id != owner_id:
        raise InteractionValidationError("task_not_found", "抖音任务不存在")
    aweme = session.exec(
        select(DouyinAweme).where(
            DouyinAweme.task_id == request.task_id,
            DouyinAweme.aweme_id == request.aweme_id,
        )
    ).first()
    if aweme is None:
        raise InteractionValidationError("target_not_found", "目标作品不存在")
    account = session.get(DouyinAccount, request.account_id)
    if account is None or account.owner_id != owner_id:
        raise InteractionValidationError("account_not_found", "所选账号不存在")
    comment: DouyinComment | None = None
    if request.interaction_type == DouyinInteractionType.comment_reply:
        comment = session.exec(
            select(DouyinComment).where(
                DouyinComment.task_id == request.task_id,
                DouyinComment.aweme_id == request.aweme_id,
                DouyinComment.comment_id == request.target_comment_id,
            )
        ).first()
        if comment is None:
            raise InteractionValidationError("target_not_found", "目标评论不存在")

    now = get_datetime_utc()
    limit = _daily_limit(account)
    used = _used_today(session, owner_id, account.id)
    account_tasks_today = account.tasks_today if account.usage_date == now.date() else 0
    remaining = max(
        min(limit - used, account.daily_task_limit - account_tasks_today), 0
    )
    failure_code: str | None = None
    message = "发送前检查通过，确认后将进入队列"
    if not account.enabled or account.status == DouyinAccountStatus.disabled.value:
        failure_code, message = "account_disabled", "所选账号已停用"
    elif (
        not account.identity_hash
        or account.status == DouyinAccountStatus.login_required.value
    ):
        failure_code, message = "login_required", "所选账号尚未登录或登录已失效"
    elif account.status == DouyinAccountStatus.unhealthy.value:
        failure_code, message = "account_unhealthy", "所选账号当前状态异常"
    elif account.active_leases >= account.concurrency_limit:
        failure_code, message = "account_busy", "所选账号正在执行其他任务"
    elif remaining <= 0:
        failure_code, message = "quota_exceeded", "所选账号已达到今日互动上限"

    duplicate_since = now - timedelta(
        hours=settings.DOUYIN_INTERACTION_DUPLICATE_WINDOW_HOURS
    )
    duplicate_filters: list[Any] = [
        DouyinInteraction.owner_id == owner_id,
        DouyinInteraction.account_id == account.id,
        DouyinInteraction.aweme_id == request.aweme_id,
        DouyinInteraction.interaction_type == request.interaction_type.value,
        DouyinInteraction.content_hash == digest,
        DouyinInteraction.created_at >= duplicate_since,
        col(DouyinInteraction.status).in_(
            [
                DouyinInteractionStatus.pending_confirmation.value,
                DouyinInteractionStatus.queued.value,
                DouyinInteractionStatus.running.value,
                DouyinInteractionStatus.succeeded.value,
                DouyinInteractionStatus.needs_review.value,
            ]
        ),
    ]
    if request.target_comment_id:
        duplicate_filters.append(
            DouyinInteraction.target_comment_id == request.target_comment_id
        )
    else:
        duplicate_filters.append(col(DouyinInteraction.target_comment_id).is_(None))
    if exclude_interaction_id:
        duplicate_filters.append(DouyinInteraction.id != exclude_interaction_id)
    duplicate = session.exec(
        select(DouyinInteraction)
        .where(*duplicate_filters)
        .order_by(col(DouyinInteraction.created_at).desc())
    ).first()
    if duplicate is not None:
        failure_code, message = (
            "duplicate_interaction",
            "24 小时内存在相同目标和内容的互动任务",
        )

    return PreflightResult(
        public=DouyinInteractionPreflightPublic(
            allowed=failure_code is None,
            failure_code=failure_code,
            message=message,
            account_name=account.name,
            remaining_daily_quota=remaining,
            cooldown_until=None,
            duplicate_interaction_id=duplicate.id if duplicate else None,
        ),
        task=task,
        aweme=aweme,
        account=account,
        comment=comment,
        normalized_content=content,
        content_hash=digest,
    )


def create_interaction(
    session: Session,
    *,
    owner_id: uuid.UUID,
    request: DouyinInteractionCreate,
) -> DouyinInteraction:
    """预检通过后创建互动任务（待确认状态）并写入创建事件，提交事务。

    内容加密落库，同时按「用户+账号+类型+目标+内容摘要+当日」生成幂等键，
    依靠数据库唯一约束防止同日重复提交。

    返回：
        新建并刷新后的互动实体。

    异常：
        InteractionValidationError: 预检未通过或幂等键冲突时抛出。
    """
    checked = preflight(session, owner_id=owner_id, request=request)
    if not checked.public.allowed:
        raise InteractionValidationError(
            checked.public.failure_code or "preflight_failed",
            checked.public.message,
            interaction_id=checked.public.duplicate_interaction_id,
        )
    day = get_datetime_utc().date().isoformat()
    key_material = "|".join(
        (
            str(owner_id),
            str(request.account_id),
            request.interaction_type.value,
            request.aweme_id,
            request.target_comment_id or "",
            checked.content_hash,
            day,
        )
    )
    interaction = DouyinInteraction(
        owner_id=owner_id,
        task_id=request.task_id,
        account_id=request.account_id,
        account_name=checked.account.name,
        aweme_id=request.aweme_id,
        target_comment_id=request.target_comment_id,
        interaction_type=request.interaction_type.value,
        content_encrypted=content_cipher.encrypt(checked.normalized_content),
        content_preview=_preview(checked.normalized_content),
        content_hash=checked.content_hash,
        idempotency_key=hashlib.sha256(key_material.encode()).hexdigest(),
    )
    session.add(interaction)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise InteractionValidationError(
            "duplicate_interaction", "相同互动任务已经存在"
        ) from exc
    session.add(
        DouyinInteractionEvent(
            interaction_id=interaction.id,
            event="created",
            to_status=DouyinInteractionStatus.pending_confirmation.value,
            detail="等待用户确认",
        )
    )
    if request.interaction_type in {
        DouyinInteractionType.video_comment,
        DouyinInteractionType.comment_reply,
    }:
        track = session.get(DouyinTrack, checked.task.track_id)
        if track is not None:
            templates = list(track.reply_templates)
            normalized = checked.normalized_content.casefold()
            if all(item.casefold() != normalized for item in templates):
                templates.append(checked.normalized_content)
                track.reply_templates = templates[-100:]
                track.updated_at = get_datetime_utc()
                session.add(track)
    session.commit()
    session.refresh(interaction)
    return interaction


def create_batch_comments(
    session: Session,
    *,
    owner_id: uuid.UUID,
    request: DouyinBatchCommentCreate,
) -> DouyinBatchCommentPublic:
    """创建一批自动确认并按计划排队的视频评论互动任务。

    账号池会先按现有调度策略选出可用成员，再按批次顺序轮换分配；
    每条子任务仍复用普通互动的预检、加密、幂等与执行状态机。
    """
    selected_target_count = len(request.targets)
    target_task_ids = {target.task_id for target in request.targets}
    owned_task_ids = set(
        session.exec(
            select(CrawlTask.id).where(
                col(CrawlTask.id).in_(target_task_ids),
                CrawlTask.owner_id == owner_id,
            )
        ).all()
    )
    if owned_task_ids != target_task_ids:
        raise InteractionValidationError("task_not_found", "抖音任务不存在")
    target_aweme_ids = {target.aweme_id for target in request.targets}
    existing_target_keys = set(
        session.exec(
            select(DouyinAweme.task_id, DouyinAweme.aweme_id).where(
                col(DouyinAweme.task_id).in_(target_task_ids),
                col(DouyinAweme.aweme_id).in_(target_aweme_ids),
            )
        ).all()
    )
    if any(
        (target.task_id, target.aweme_id) not in existing_target_keys
        for target in request.targets
    ):
        raise InteractionValidationError("target_not_found", "目标作品不存在")

    recent_aweme_ids: set[str] = set()
    if request.filter_recently_commented:
        duplicate_since = get_datetime_utc() - timedelta(
            hours=settings.DOUYIN_INTERACTION_DUPLICATE_WINDOW_HOURS
        )
        selected_aweme_ids = {target.aweme_id for target in request.targets}
        recent_aweme_ids = set(
            session.exec(
                select(DouyinInteraction.aweme_id).where(
                    DouyinInteraction.owner_id == owner_id,
                    DouyinInteraction.interaction_type
                    == DouyinInteractionType.video_comment.value,
                    col(DouyinInteraction.aweme_id).in_(selected_aweme_ids),
                    DouyinInteraction.created_at >= duplicate_since,
                    col(DouyinInteraction.status).in_(_RECENT_COMMENT_STATUSES),
                )
            ).all()
        )
    targets = [
        target for target in request.targets if target.aweme_id not in recent_aweme_ids
    ]
    filtered_target_count = selected_target_count - len(targets)
    if not targets:
        batch_id = uuid.uuid4()
        return DouyinBatchCommentPublic(
            batch_id=batch_id,
            interaction_ids=[],
            selected_target_count=selected_target_count,
            filtered_target_count=filtered_target_count,
            submitted_target_count=0,
            total_count=0,
            message=(
                f"所选 {selected_target_count} 个视频均在 24 小时内评论过，"
                "已自动过滤，未创建重复任务"
            ),
        )

    try:
        accounts = select_task_accounts(
            owner_id=owner_id,
            account_id=request.account_id,
            account_ids=[],
            pool_id=request.account_pool_id,
            strategy=request.account_strategy,
        )
    except AccountConfigurationError as exc:
        raise InteractionValidationError("account_unavailable", str(exc)) from exc
    if not accounts:
        raise InteractionValidationError(
            "account_unavailable", "所选账号或账号池当前没有可用账号"
        )

    comments = [item.get_secret_value().strip() for item in request.comments]
    now = get_datetime_utc()
    cursor = now
    plans: list[BatchCommentPlan] = []
    sequence_index = 0
    for target_index, target in enumerate(targets):
        target_comments = (
            [comments[target_index % len(comments)]]
            if request.mode == DouyinBatchCommentMode.one_per_video
            else comments
        )
        for content in target_comments:
            if sequence_index > 0:
                interval = (
                    request.delay_min_seconds
                    if request.delay_min_seconds == request.delay_max_seconds
                    else random.SystemRandom().uniform(
                        request.delay_min_seconds,
                        request.delay_max_seconds,
                    )
                )
                cursor += timedelta(seconds=interval)
            plans.append(
                BatchCommentPlan(
                    task_id=target.task_id,
                    aweme_id=target.aweme_id,
                    content=content,
                    account_id=accounts[sequence_index % len(accounts)].id,
                    sequence_index=sequence_index,
                    scheduled_at=cursor,
                )
            )
            sequence_index += 1

    # 先完整预检，避免目标视频或账号配置错误时只创建半个批次。
    for plan in plans:
        checked = preflight(
            session,
            owner_id=owner_id,
            request=DouyinInteractionCreate(
                task_id=plan.task_id,
                aweme_id=plan.aweme_id,
                account_id=plan.account_id,
                interaction_type=DouyinInteractionType.video_comment,
                content=plan.content,
            ),
        )
        if not checked.public.allowed:
            raise InteractionValidationError(
                checked.public.failure_code or "preflight_failed",
                checked.public.message,
                interaction_id=checked.public.duplicate_interaction_id,
            )

    batch_id = uuid.uuid4()
    created_ids: list[uuid.UUID] = []
    try:
        for plan in plans:
            interaction = create_interaction(
                session,
                owner_id=owner_id,
                request=DouyinInteractionCreate(
                    task_id=plan.task_id,
                    aweme_id=plan.aweme_id,
                    account_id=plan.account_id,
                    interaction_type=DouyinInteractionType.video_comment,
                    content=plan.content,
                ),
            )
            current = session.get(DouyinInteraction, interaction.id)
            if current is None:
                raise InteractionStateError("批量评论子任务创建失败")
            current.batch_id = batch_id
            current.sequence_index = plan.sequence_index
            current.scheduled_at = plan.scheduled_at
            current.account_pool_id = request.account_pool_id
            current.human_confirmed_at = now
            _transition(
                session,
                current,
                status=DouyinInteractionStatus.queued,
                event="batch_queued",
                detail=(f"批量评论第 {plan.sequence_index + 1}/{len(plans)} 条已排队"),
            )
            session.commit()
            created_ids.append(current.id)
    except Exception:
        if created_ids:
            created = session.exec(
                select(DouyinInteraction).where(
                    col(DouyinInteraction.id).in_(created_ids)
                )
            ).all()
            for item in created:
                session.delete(item)
            session.commit()
        raise

    message_prefix = (
        f"已过滤 {filtered_target_count} 个 24 小时内已评论视频，"
        if filtered_target_count
        else ""
    )
    return DouyinBatchCommentPublic(
        batch_id=batch_id,
        interaction_ids=created_ids,
        selected_target_count=selected_target_count,
        filtered_target_count=filtered_target_count,
        submitted_target_count=len(targets),
        total_count=len(created_ids),
        message=(
            f"{message_prefix}已创建 {len(created_ids)} 条评论任务，按计划进入发送队列"
        ),
    )


def _transition(
    session: Session,
    interaction: DouyinInteraction,
    *,
    status: DouyinInteractionStatus,
    event: str,
    detail: str | None = None,
    failure_code: str | None = None,
    error: str | None = None,
) -> None:
    """推进互动状态机并追加事件记录（不提交事务）。

    running 时记录开始时间并累加尝试次数；进入成功/失败/阻断/待复核/取消
    等终态时记录完成时间。调用方负责提交事务。
    """
    previous = interaction.status
    now = get_datetime_utc()
    interaction.status = status.value
    interaction.failure_code = failure_code
    interaction.error = error
    interaction.updated_at = now
    if status == DouyinInteractionStatus.running:
        interaction.started_at = now
        interaction.finished_at = None
        interaction.attempt_count += 1
    elif status in {
        DouyinInteractionStatus.succeeded,
        DouyinInteractionStatus.failed,
        DouyinInteractionStatus.blocked,
        DouyinInteractionStatus.needs_review,
        DouyinInteractionStatus.cancelled,
    }:
        interaction.finished_at = now
    session.add(interaction)
    session.add(
        DouyinInteractionEvent(
            interaction_id=interaction.id,
            event=event,
            from_status=previous,
            to_status=status.value,
            detail=detail,
            attempt_number=interaction.attempt_count,
        )
    )


def account_quota(
    session: Session, *, owner_id: uuid.UUID, account: DouyinAccount
) -> DouyinInteractionQuotaPublic:
    """计算单个账号的互动配额视图：上限、今日用量、剩余量与可用性。"""
    now = get_datetime_utc()
    used = _used_today(session, owner_id, account.id)
    limit = _daily_limit(account)
    account_tasks_today = account.tasks_today if account.usage_date == now.date() else 0
    remaining = max(
        min(limit - used, account.daily_task_limit - account_tasks_today), 0
    )
    available = bool(
        account.enabled
        and account.identity_hash
        and account.status
        not in {
            DouyinAccountStatus.disabled.value,
            DouyinAccountStatus.login_required.value,
            DouyinAccountStatus.unhealthy.value,
        }
        and remaining > 0
    )
    return DouyinInteractionQuotaPublic(
        account_id=account.id,
        account_name=account.name,
        daily_limit=limit,
        used_today=used,
        remaining_today=remaining,
        min_interval_seconds=0.0,
        cooldown_until=None,
        available=available,
    )


class DouyinInteractionManager:
    """互动执行的进程内编排器。

    管理每个互动的异步执行任务句柄与每账号串行锁，负责确认、重试、
    取消、服务重启恢复（running 标记待复核、queued 重新入队）以及
    浏览器执行的租约获取/释放与失败归类。
    """

    def __init__(self) -> None:
        self._handles: dict[
            uuid.UUID, asyncio.Task[None]
        ] = {}  # 互动 ID -> 执行任务句柄
        self._account_locks: dict[uuid.UUID, asyncio.Lock] = {}  # 账号 ID -> 串行执行锁
        self._lock = asyncio.Lock()  # 句柄表的全局互斥锁
        self._executor = DouyinInteractionExecutor(settings)

    async def startup(self) -> None:
        """服务启动时恢复队列：running 标记为待复核，queued 重新调度。"""
        queued: list[uuid.UUID] = []
        with Session(engine) as session:
            running = session.exec(
                select(DouyinInteraction).where(
                    DouyinInteraction.status == DouyinInteractionStatus.running.value
                )
            ).all()
            for interaction in running:
                _transition(
                    session,
                    interaction,
                    status=DouyinInteractionStatus.needs_review,
                    event="service_restarted",
                    detail="服务重启时任务正在执行，结果需要人工确认",
                    failure_code="ambiguous_result",
                    error="服务重启导致发送结果无法确认",
                )
            queued = list(
                session.exec(
                    select(DouyinInteraction.id).where(
                        DouyinInteraction.status == DouyinInteractionStatus.queued.value
                    )
                ).all()
            )
            session.commit()
        for interaction_id in queued:
            await self._schedule(interaction_id)

    async def confirm(
        self, *, interaction_id: uuid.UUID, owner_id: uuid.UUID
    ) -> DouyinInteraction:
        """用户确认发送：复检预检条件后转入排队并调度执行。

        异常：
            InteractionStateError: 互动不存在、无权操作或不处于待确认状态。
            InteractionValidationError: 预检条件不再满足。
        """
        with Session(engine) as session:
            interaction = session.get(DouyinInteraction, interaction_id)
            if interaction is None or interaction.owner_id != owner_id:
                raise InteractionStateError("互动任务不存在")
            if interaction.status != DouyinInteractionStatus.pending_confirmation.value:
                raise InteractionStateError("只有待确认任务可以确认发送")
            self._ensure_preflight(session, interaction)
            interaction.human_confirmed_at = get_datetime_utc()
            _transition(
                session,
                interaction,
                status=DouyinInteractionStatus.queued,
                event="confirmed",
                detail="用户已确认发送",
            )
            session.commit()
            session.refresh(interaction)
            session.expunge(interaction)
        await self._schedule(interaction_id)
        return interaction

    async def retry(
        self,
        *,
        interaction_id: uuid.UUID,
        owner_id: uuid.UUID,
        confirm_not_sent: bool,
    ) -> DouyinInteraction:
        """重试互动：按当前状态幂等处理，必要时复检预检并重新排队。

        参数：
            interaction_id: 互动 ID。
            owner_id: 归属用户 ID。
            confirm_not_sent: 对「待复核」状态必须置 True，表示用户已确认
                抖音端未发送成功，避免重复提交。

        异常：
            InteractionStateError: 已成功、内容损坏、不可重试的失败原因，
                或待复核但未确认未发送。
            InteractionValidationError: 预检条件不再满足。
        """
        schedule = False
        with Session(engine) as session:
            interaction = session.get(DouyinInteraction, interaction_id)
            if interaction is None or interaction.owner_id != owner_id:
                raise InteractionStateError("互动任务不存在")
            current = DouyinInteractionStatus(interaction.status)
            if current == DouyinInteractionStatus.succeeded:
                raise InteractionStateError("已成功的互动任务无需重试")
            if _has_probable_encoding_damage(interaction.content_preview):
                raise InteractionStateError("历史互动内容已损坏，无法安全重试")
            if interaction.failure_code in _NON_RETRYABLE_FAILURE_CODES:
                raise InteractionStateError("目标评论已不可用，无法安全重试")
            if current == DouyinInteractionStatus.needs_review and not confirm_not_sent:
                raise InteractionStateError("请先确认抖音中没有发送成功，再执行重试")

            if current == DouyinInteractionStatus.running:
                # 既有 worker 持有唯一的账号/浏览器租约。
                # 把重试视为幂等确认，避免产生重复的平台提交。
                session.expunge(interaction)
                return interaction

            if current == DouyinInteractionStatus.queued:
                schedule = True
            else:
                self._ensure_preflight(session, interaction)
                interaction.human_confirmed_at = get_datetime_utc()
                _transition(
                    session,
                    interaction,
                    status=DouyinInteractionStatus.queued,
                    event="retried",
                    detail="用户确认后重新排队",
                )
                session.commit()
                schedule = True
            session.refresh(interaction)
            session.expunge(interaction)
        if schedule:
            await self._schedule(interaction_id)
        return interaction

    async def cancel(
        self, *, interaction_id: uuid.UUID, owner_id: uuid.UUID
    ) -> DouyinInteraction:
        """取消互动：仅待确认/排队状态可取消，同时取消已调度的执行任务。

        异常：
            InteractionStateError: 互动不存在、无权操作或当前状态不允许取消。
        """
        async with self._lock:
            with Session(engine) as session:
                interaction = session.get(DouyinInteraction, interaction_id)
                if interaction is None or interaction.owner_id != owner_id:
                    raise InteractionStateError("互动任务不存在")
                if interaction.status not in {
                    DouyinInteractionStatus.pending_confirmation.value,
                    DouyinInteractionStatus.queued.value,
                }:
                    raise InteractionStateError("当前状态不能取消")
                handle = self._handles.pop(interaction_id, None)
                if handle is not None:
                    handle.cancel()
                _transition(
                    session,
                    interaction,
                    status=DouyinInteractionStatus.cancelled,
                    event="cancelled",
                    detail="用户取消任务",
                )
                session.commit()
                session.refresh(interaction)
                session.expunge(interaction)
                return interaction

    def _ensure_preflight(
        self, session: Session, interaction: DouyinInteraction
    ) -> None:
        """对已入库互动重新执行预检（排除自身查重），不满足时抛出校验异常。"""
        if interaction.account_id is None:
            raise InteractionValidationError("account_not_found", "原账号已被删除")
        request = DouyinInteractionCreate(
            task_id=interaction.task_id,
            aweme_id=interaction.aweme_id,
            account_id=interaction.account_id,
            interaction_type=DouyinInteractionType(interaction.interaction_type),
            target_comment_id=interaction.target_comment_id,
            content=content_cipher.decrypt(interaction.content_encrypted),
        )
        checked = preflight(
            session,
            owner_id=interaction.owner_id,
            request=request,
            exclude_interaction_id=interaction.id,
        )
        # 账号被占用属于瞬时执行条件，而非入队准入失败。
        # 每账号的 asyncio 锁会把排队的互动串行化，保证同一时刻
        # 该账号只有一个浏览器操作在执行。
        if not checked.public.allowed and checked.public.failure_code != "account_busy":
            raise InteractionValidationError(
                checked.public.failure_code or "preflight_failed",
                checked.public.message,
                interaction_id=checked.public.duplicate_interaction_id,
            )

    async def _schedule(self, interaction_id: uuid.UUID) -> None:
        """为互动创建异步执行任务；已有未完成任务时幂等跳过。"""
        async with self._lock:
            active = self._handles.get(interaction_id)
            if active is not None and not active.done():
                return
            self._handles[interaction_id] = asyncio.create_task(
                self._run(interaction_id),
                name=f"douyin-interaction-{interaction_id}",
            )

    async def enqueue(self, interaction_ids: Sequence[uuid.UUID]) -> None:
        """批量调度已进入队列的互动任务。"""
        for interaction_id in interaction_ids:
            await self._schedule(interaction_id)

    @staticmethod
    async def _wait_until_scheduled(interaction_id: uuid.UUID) -> None:
        """等待子任务的计划时间，同时允许取消操作及时终止等待。"""
        with Session(engine) as session:
            interaction = session.get(DouyinInteraction, interaction_id)
            scheduled_at = interaction.scheduled_at if interaction else None
        if scheduled_at is None:
            return
        delay = (scheduled_at - get_datetime_utc()).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)

    async def _run(self, interaction_id: uuid.UUID) -> None:
        """执行单个互动：获取账号锁与租约，驱动浏览器执行并归类结果。

        成功写入平台结果 ID；取消转待复核；超时/执行异常按失败原因码归类；
        无论成败都在 finally 中释放账号租约、账号锁与任务句柄。
        """
        reserved: DouyinAccount | None = None
        account_lock: asyncio.Lock | None = None
        account_lock_acquired = False
        account_healthy = True
        try:
            await self._wait_until_scheduled(interaction_id)
            account_id = await asyncio.to_thread(
                self._queued_account_id, interaction_id
            )
            account_lock = self._account_locks.setdefault(account_id, asyncio.Lock())
            await account_lock.acquire()
            account_lock_acquired = True
            interaction, account, request = await asyncio.to_thread(
                self._prepare_execution, interaction_id
            )
            reserved = await asyncio.to_thread(reserve_account, account.id)
            recorder = InteractionStepRecorder(interaction.id)
            resolved_connection = resolve_account_browser(reserved)
            interaction_connection = InteractionBrowserConnection(
                browser_mode=resolved_connection.browser_mode.value,
                remote_host=resolved_connection.remote_host,
                remote_port=resolved_connection.remote_port,
                user_data_dir=resolved_connection.user_data_dir,
                debug_port=resolved_connection.debug_port,
            )
            result = await asyncio.wait_for(
                self._executor.execute(
                    connection=interaction_connection,
                    request=request,
                    step_callback=recorder.record,
                ),
                timeout=settings.DOUYIN_INTERACTION_EXECUTION_TIMEOUT_SECONDS,
            )
            with Session(engine) as session:
                current = session.get(DouyinInteraction, interaction.id)
                if current is not None:
                    current.result_platform_id = result.platform_id
                    _transition(
                        session,
                        current,
                        status=DouyinInteractionStatus.succeeded,
                        event="succeeded",
                        detail="抖音已接受互动请求",
                    )
                    session.commit()
        except asyncio.CancelledError:
            with Session(engine) as session:
                current = session.get(DouyinInteraction, interaction_id)
                if (
                    current is not None
                    and current.status == DouyinInteractionStatus.running.value
                ):
                    _transition(
                        session,
                        current,
                        status=DouyinInteractionStatus.needs_review,
                        event="worker_cancelled",
                        detail="执行进程被中断，结果需要人工确认",
                        failure_code="ambiguous_result",
                        error="执行进程中断，发送结果无法确认",
                    )
                    session.commit()
            raise
        except TimeoutError:
            # Chrome 原生对话框可能在不关闭 socket 的情况下挂起 CDP 命令。
            # 为已确认的尝试设置超时上限，保证账号租约与队列总能恢复，
            # 而不是永远停留在执行中状态。
            self._record_failure(
                interaction_id,
                DouyinInteractionStatus.failed,
                "execution_timeout",
                "浏览器操作超时，任务已安全释放，可确认未发送后重试",
            )
        except InteractionExecutionError as exc:
            account_healthy = not exc.affects_account_health
            status = (
                DouyinInteractionStatus.needs_review
                if exc.ambiguous
                else DouyinInteractionStatus.blocked
                if exc.code in {"login_required", "risk_controlled"}
                else DouyinInteractionStatus.failed
            )
            self._record_failure(interaction_id, status, exc.code, str(exc))
        except AccountConfigurationError:
            account_healthy = False
            self._record_failure(
                interaction_id,
                DouyinInteractionStatus.blocked,
                "account_unavailable",
                "所选账号当前不可调度，请检查登录和并发状态",
            )
        except Exception:
            account_healthy = False
            logger.exception("Douyin interaction %s failed", interaction_id)
            self._record_failure(
                interaction_id,
                DouyinInteractionStatus.failed,
                "internal_error",
                "互动任务执行时发生内部错误",
            )
        finally:
            if reserved is not None:
                await asyncio.to_thread(
                    release_account,
                    reserved.id,
                    success=account_healthy,
                    error=(
                        None
                        if account_healthy
                        else "互动任务检测到账号登录、连接或平台验证异常"
                    ),
                )
            if account_lock is not None and account_lock_acquired:
                account_lock.release()
            async with self._lock:
                self._handles.pop(interaction_id, None)

    @staticmethod
    def _queued_account_id(interaction_id: uuid.UUID) -> uuid.UUID:
        """读取排队中互动的账号 ID，用于定位串行锁；非法状态抛出异常。"""
        with Session(engine) as session:
            interaction = session.get(DouyinInteraction, interaction_id)
            if interaction is None:
                raise InteractionStateError("互动任务不存在")
            if interaction.status != DouyinInteractionStatus.queued.value:
                raise InteractionStateError("互动任务不在队列中")
            if interaction.account_id is None:
                raise AccountConfigurationError("原账号已被删除")
            return interaction.account_id

    @staticmethod
    def _prepare_execution(
        interaction_id: uuid.UUID,
    ) -> tuple[DouyinInteraction, DouyinAccount, InteractionExecutionRequest]:
        """把排队中的互动转为执行中，并组装浏览器执行请求。

        回复类型会附带目标评论内容与父评论 ID；返回前把实体从会话
        分离，供异步 worker 在会话外安全读取。
        """
        with Session(engine) as session:
            interaction = session.get(DouyinInteraction, interaction_id)
            if interaction is None:
                raise InteractionStateError("互动任务不存在")
            if interaction.status != DouyinInteractionStatus.queued.value:
                raise InteractionStateError("互动任务不在队列中")
            if interaction.account_id is None:
                raise AccountConfigurationError("原账号已被删除")
            account = session.get(DouyinAccount, interaction.account_id)
            if account is None:
                raise AccountConfigurationError("原账号已被删除")
            target_content: str | None = None
            target_parent_comment_id: str | None = None
            if interaction.target_comment_id:
                comment = session.exec(
                    select(DouyinComment).where(
                        DouyinComment.task_id == interaction.task_id,
                        DouyinComment.aweme_id == interaction.aweme_id,
                        DouyinComment.comment_id == interaction.target_comment_id,
                    )
                ).first()
                if comment is None:
                    raise InteractionExecutionError(
                        "target_not_found", "目标评论不存在"
                    )
                target_content = comment.content
                target_parent_comment_id = comment.parent_comment_id
            content = content_cipher.decrypt(interaction.content_encrypted)
            try:
                _validate_content_encoding(content)
            except InteractionValidationError as exc:
                raise InteractionExecutionError(exc.code, str(exc)) from exc
            request = InteractionExecutionRequest(
                interaction_type=interaction.interaction_type,
                aweme_id=interaction.aweme_id,
                content=content,
                target_comment_id=interaction.target_comment_id,
                target_comment_content=target_content,
                target_parent_comment_id=target_parent_comment_id,
            )
            _transition(
                session,
                interaction,
                status=DouyinInteractionStatus.running,
                event="started",
                detail="CDP 互动任务开始执行",
            )
            session.commit()
            session.refresh(interaction)
            # commit 默认会使 ORM 属性过期。异步 worker 会在本会话外
            # 读取账号的调度字段，因此分离前必须先刷新账号。
            session.refresh(account)
            session.expunge(interaction)
            session.expunge(account)
            return interaction, account, request

    @staticmethod
    def _record_failure(
        interaction_id: uuid.UUID,
        status: DouyinInteractionStatus,
        code: str,
        message: str,
    ) -> None:
        """把排队中/执行中的互动流转为失败类终态并记录失败原因（独立会话提交）。"""
        with Session(engine) as session:
            interaction = session.get(DouyinInteraction, interaction_id)
            if interaction is None or interaction.status not in {
                DouyinInteractionStatus.queued.value,
                DouyinInteractionStatus.running.value,
            }:
                return
            _transition(
                session,
                interaction,
                status=status,
                event="execution_failed",
                detail=message,
                failure_code=code,
                error=message,
            )
            session.commit()

    async def shutdown(self) -> None:
        """优雅停机：取消全部执行中任务并等待其收尾。"""
        async with self._lock:
            tasks = list(self._handles.values())
            for task in tasks:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


interaction_manager = DouyinInteractionManager()  # 进程级互动编排单例


def require_owned_interaction(
    session: Session,
    *,
    owner_id: uuid.UUID,
    interaction_id: uuid.UUID,
    is_superuser: bool = False,
) -> DouyinInteraction:
    """加载对当前用户可见的互动，否则抛出传输层无关的未找到异常。"""

    interaction = get_owned_interaction(
        session,
        owner_id=owner_id,
        interaction_id=interaction_id,
        is_superuser=is_superuser,
    )
    if interaction is None:
        raise InteractionNotFoundError
    return interaction


def preflight_interaction_public(
    session: Session,
    *,
    owner_id: uuid.UUID,
    request: DouyinInteractionCreate,
) -> DouyinInteractionPreflightPublic:
    """执行互动预检，返回对外预检结论（允许否、原因码、剩余配额等）。"""
    return preflight(session, owner_id=owner_id, request=request).public


def create_interaction_public(
    session: Session,
    *,
    owner_id: uuid.UUID,
    request: DouyinInteractionCreate,
) -> DouyinInteractionPublic:
    """创建互动任务并返回对外概要模型。"""
    interaction = create_interaction(session, owner_id=owner_id, request=request)
    return interaction_public_with_target(session, interaction)


async def create_batch_comments_public(
    session: Session,
    *,
    owner_id: uuid.UUID,
    request: DouyinBatchCommentCreate,
) -> DouyinBatchCommentPublic:
    """创建并调度批量评论任务。"""
    result = create_batch_comments(session, owner_id=owner_id, request=request)
    await interaction_manager.enqueue(result.interaction_ids)
    return result


def list_interactions_public(
    session: Session,
    *,
    owner_id: uuid.UUID,
    is_superuser: bool,
    task_id: uuid.UUID | None = None,
    track_id: uuid.UUID | None = None,
    aweme_id: str | None = None,
    interaction_type: DouyinInteractionType | None = None,
    interaction_status: DouyinInteractionStatus | None = None,
    source_type: DouyinSourceType | None = None,
    source_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = 100,
) -> DouyinInteractionsPublic:
    """分页查询可见互动，并在同一用例内补充回复目标评论内容。

    支持按任务、赛道、作品、类型、状态组合过滤；非超管只能看到
    自己的互动。任务与赛道同时传入且不一致时抛出校验异常。
    """

    filters: list[Any] = []
    if not is_superuser:
        filters.append(DouyinInteraction.owner_id == owner_id)
    selected_task: CrawlTask | None = None
    if task_id:
        selected_task = session.get(CrawlTask, task_id)
        if selected_task is None or (
            not is_superuser and selected_task.owner_id != owner_id
        ):
            raise InteractionNotFoundError("任务不存在或无权访问")
        filters.append(DouyinInteraction.task_id == task_id)
    if track_id:
        track = session.get(DouyinTrack, track_id)
        if track is None or (not is_superuser and track.owner_id != owner_id):
            raise InteractionNotFoundError("赛道不存在或无权访问")
        if selected_task is not None and selected_task.track_id != track_id:
            raise InteractionValidationError(
                "task_track_mismatch",
                "任务不属于所选赛道，请调整筛选条件",
            )
        filters.append(
            col(DouyinInteraction.task_id).in_(
                select(CrawlTask.id).where(CrawlTask.track_id == track_id)
            )
        )
    source_filter = resolve_source_filter(
        session,
        owner_id=None if is_superuser else owner_id,
        track_id=track_id,
        source_type=source_type,
        source_id=source_id,
    )
    if source_filter is not None:
        filters.append(col(DouyinInteraction.task_id).in_(set(source_filter.task_ids)))
    if aweme_id:
        filters.append(DouyinInteraction.aweme_id == aweme_id)
    if interaction_type:
        filters.append(DouyinInteraction.interaction_type == interaction_type.value)
    if interaction_status:
        filters.append(DouyinInteraction.status == interaction_status.value)

    count = session.exec(
        select(func.count()).select_from(DouyinInteraction).where(*filters)
    ).one()
    interactions = session.exec(
        select(DouyinInteraction)
        .where(*filters)
        .order_by(col(DouyinInteraction.created_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    target_contents = interaction_target_comment_contents(session, interactions)
    tasks = session.exec(
        select(CrawlTask).where(
            col(CrawlTask.id).in_({interaction.task_id for interaction in interactions})
        )
    ).all()
    source_values_by_task = build_task_source_values(session, list(tasks))
    return DouyinInteractionsPublic(
        data=[
            interaction_public(
                interaction,
                target_comment_content=(
                    target_contents.get(
                        (
                            interaction.task_id,
                            interaction.aweme_id,
                            interaction.target_comment_id,
                        )
                    )
                    if interaction.target_comment_id
                    else None
                ),
                source_values=source_values_by_task.get(interaction.task_id),
            )
            for interaction in interactions
        ],
        count=count,
    )


def list_interaction_quotas(
    session: Session, *, owner_id: uuid.UUID
) -> list[DouyinInteractionQuotaPublic]:
    """列出用户全部抖音账号的互动配额视图，按账号名排序。"""
    accounts = session.exec(
        select(DouyinAccount)
        .where(DouyinAccount.owner_id == owner_id)
        .order_by(col(DouyinAccount.name).asc())
    ).all()
    return [
        account_quota(session, owner_id=owner_id, account=account)
        for account in accounts
    ]


def get_interaction_detail_public(
    session: Session,
    *,
    owner_id: uuid.UUID,
    interaction_id: uuid.UUID,
    is_superuser: bool,
) -> DouyinInteractionDetailPublic:
    """查询互动详情（含解密内容与事件时间线），无权限时抛出未找到异常。"""
    interaction = require_owned_interaction(
        session,
        owner_id=owner_id,
        interaction_id=interaction_id,
        is_superuser=is_superuser,
    )
    return interaction_detail(session, interaction)


def get_interaction_screenshot_payload(
    session: Session,
    *,
    owner_id: uuid.UUID,
    interaction_id: uuid.UUID,
    event_id: uuid.UUID,
    is_superuser: bool,
) -> InteractionScreenshotPayload:
    """读取互动事件的步骤截图（校验归属与完整性）。

    异常：
        InteractionNotFoundError: 互动不存在或不可见。
        InteractionScreenshotNotFoundError: 事件不属于该互动或无截图。
    """
    interaction = require_owned_interaction(
        session,
        owner_id=owner_id,
        interaction_id=interaction_id,
        is_superuser=is_superuser,
    )
    event = session.get(DouyinInteractionEvent, event_id)
    if event is None or event.interaction_id != interaction.id:
        raise InteractionScreenshotNotFoundError
    return InteractionScreenshotPayload(
        content=read_interaction_screenshot(event),
        media_type=event.screenshot_mime_type or "image/jpeg",
        event_id=event.id,
    )


async def confirm_owned_interaction(
    session: Session,
    *,
    owner_id: uuid.UUID,
    interaction_id: uuid.UUID,
    is_superuser: bool,
) -> DouyinInteractionPublic:
    """确认发送指定互动并返回最新概要（归属校验后委托编排器）。"""
    interaction = require_owned_interaction(
        session,
        owner_id=owner_id,
        interaction_id=interaction_id,
        is_superuser=is_superuser,
    )
    result = await interaction_manager.confirm(
        interaction_id=interaction.id,
        owner_id=interaction.owner_id,
    )
    return interaction_public_with_target(session, result)


async def retry_owned_interaction(
    session: Session,
    *,
    owner_id: uuid.UUID,
    interaction_id: uuid.UUID,
    is_superuser: bool,
    confirm_not_sent: bool,
) -> DouyinInteractionPublic:
    """重试指定互动并返回最新概要（归属校验后委托编排器）。"""
    interaction = require_owned_interaction(
        session,
        owner_id=owner_id,
        interaction_id=interaction_id,
        is_superuser=is_superuser,
    )
    result = await interaction_manager.retry(
        interaction_id=interaction.id,
        owner_id=interaction.owner_id,
        confirm_not_sent=confirm_not_sent,
    )
    return interaction_public_with_target(session, result)


async def cancel_owned_interaction(
    session: Session,
    *,
    owner_id: uuid.UUID,
    interaction_id: uuid.UUID,
    is_superuser: bool,
) -> DouyinInteractionPublic:
    """取消指定互动并返回最新概要（归属校验后委托编排器）。"""
    interaction = require_owned_interaction(
        session,
        owner_id=owner_id,
        interaction_id=interaction_id,
        is_superuser=is_superuser,
    )
    result = await interaction_manager.cancel(
        interaction_id=interaction.id,
        owner_id=interaction.owner_id,
    )
    return interaction_public_with_target(session, result)
