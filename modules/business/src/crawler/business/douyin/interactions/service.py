from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import quote

from crawler.bootstrap.database import engine
from crawler.bootstrap.settings import settings
from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.accounts.models import DouyinAccount, DouyinAccountStatus
from crawler.business.douyin.accounts.service import (
    AccountConfigurationError,
    release_account,
    reserve_account,
    resolve_account_browser,
)
from crawler.business.douyin.comments.models import DouyinComment
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.interactions.models import (
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
from crawler.business.douyin.tasks.models import CrawlTask
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

_CORRUPTED_CONTENT_PLACEHOLDER = "[历史互动内容编码损坏，原文无法恢复]"
_NON_RETRYABLE_FAILURE_CODES = {"target_unavailable"}


class InteractionValidationError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        interaction_id: uuid.UUID | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.interaction_id = interaction_id


class InteractionStateError(RuntimeError):
    pass


class InteractionNotFoundError(LookupError):
    """The interaction is absent or not visible to the requesting user."""


class InteractionCipher:
    def __init__(self, secret: str) -> None:
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        self._fernet = Fernet(key)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise InteractionStateError(
                "互动内容无法解密，请检查 SECRET_KEY 配置"
            ) from exc


content_cipher = InteractionCipher(settings.SECRET_KEY)


@dataclass(frozen=True)
class PreflightResult:
    public: DouyinInteractionPreflightPublic
    task: CrawlTask
    aweme: DouyinAweme
    account: DouyinAccount
    comment: DouyinComment | None
    normalized_content: str
    content_hash: str


@dataclass(frozen=True)
class InteractionScreenshotPayload:
    content: bytes
    media_type: str
    event_id: uuid.UUID


def _content_hash(content: str) -> str:
    normalized = " ".join(content.split())
    return hashlib.sha256(normalized.encode()).hexdigest()


def _preview(content: str) -> str:
    compact = " ".join(content.split())
    return compact if len(compact) <= 157 else f"{compact[:157]}..."


def _has_probable_encoding_damage(content: str) -> bool:
    """Detect text that was replaced before it reached the UTF-8 API.

    Windows command-line clients can silently replace non-ASCII characters with
    question marks when their active code page cannot represent the payload.
    A normal question in Chinese must remain valid, so only dense runs of ASCII
    question marks (or the Unicode replacement character) are treated as damage.
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
    if _has_probable_encoding_damage(content):
        raise InteractionValidationError(
            "invalid_content_encoding",
            "互动内容疑似在提交前发生编码损坏，请使用 UTF-8 重新输入后再发送",
        )


def _display_content(content: str) -> str:
    if _has_probable_encoding_damage(content):
        return _CORRUPTED_CONTENT_PLACEHOLDER
    return content


def _daily_window(now: datetime) -> tuple[datetime, datetime]:
    start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _used_today(session: Session, owner_id: uuid.UUID, account_id: uuid.UUID) -> int:
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
    return min(account.daily_task_limit, settings.DOUYIN_INTERACTION_DAILY_LIMIT)


def interaction_target_comment_contents(
    session: Session, interactions: Sequence[DouyinInteraction]
) -> dict[tuple[uuid.UUID, str, str], str]:
    """Load reply targets in one query for interaction list responses."""
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
    status = DouyinInteractionStatus(interaction.status)
    content_damaged = _has_probable_encoding_damage(interaction.content_preview)
    return {
        "id": interaction.id,
        "task_id": interaction.task_id,
        "account_id": interaction.account_id,
        "account_name": interaction.account_name,
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
        # A manual retry is available for every state that has not succeeded.
        # Queued/running retries are idempotent and only ensure the worker is
        # scheduled; they never start a second concurrent browser operation.
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
    interaction: DouyinInteraction, *, target_comment_content: str | None = None
) -> DouyinInteractionPublic:
    return DouyinInteractionPublic(
        **interaction_public_values(
            interaction, target_comment_content=target_comment_content
        )
    )


def interaction_public_with_target(
    session: Session, interaction: DouyinInteraction
) -> DouyinInteractionPublic:
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
    return interaction_public(interaction, target_comment_content=target_content)


def interaction_detail(
    session: Session, interaction: DouyinInteraction
) -> DouyinInteractionDetailPublic:
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
    session.commit()
    session.refresh(interaction)
    return interaction


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
    def __init__(self) -> None:
        self._handles: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._account_locks: dict[uuid.UUID, asyncio.Lock] = {}
        self._lock = asyncio.Lock()
        self._executor = DouyinInteractionExecutor(settings)

    async def startup(self) -> None:
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
                # The existing worker owns the only account/browser lease.
                # Treat retry as an idempotent acknowledgement to avoid a
                # duplicate platform submission.
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
        # An occupied account is a transient execution condition, not a queue
        # admission failure. The per-account asyncio lock serializes queued
        # interactions and guarantees that only one browser operation runs at
        # a time for the account.
        if not checked.public.allowed and checked.public.failure_code != "account_busy":
            raise InteractionValidationError(
                checked.public.failure_code or "preflight_failed",
                checked.public.message,
                interaction_id=checked.public.duplicate_interaction_id,
            )

    async def _schedule(self, interaction_id: uuid.UUID) -> None:
        async with self._lock:
            active = self._handles.get(interaction_id)
            if active is not None and not active.done():
                return
            self._handles[interaction_id] = asyncio.create_task(
                self._run(interaction_id),
                name=f"douyin-interaction-{interaction_id}",
            )

    async def _run(self, interaction_id: uuid.UUID) -> None:
        reserved: DouyinAccount | None = None
        account_lock: asyncio.Lock | None = None
        account_lock_acquired = False
        account_healthy = True
        try:
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
            # Native Chrome dialogs can suspend CDP commands without closing
            # the socket. Bound the confirmed attempt so the account lease and
            # queue always recover instead of remaining permanently running.
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
            # commit expires ORM attributes by default. Refresh the account before
            # detaching it because the async worker reads its scheduling fields
            # outside this session.
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
        async with self._lock:
            tasks = list(self._handles.values())
            for task in tasks:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


interaction_manager = DouyinInteractionManager()


def require_owned_interaction(
    session: Session,
    *,
    owner_id: uuid.UUID,
    interaction_id: uuid.UUID,
    is_superuser: bool = False,
) -> DouyinInteraction:
    """Load a visible interaction or raise a transport-neutral not-found error."""

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
    return preflight(session, owner_id=owner_id, request=request).public


def create_interaction_public(
    session: Session,
    *,
    owner_id: uuid.UUID,
    request: DouyinInteractionCreate,
) -> DouyinInteractionPublic:
    interaction = create_interaction(session, owner_id=owner_id, request=request)
    return interaction_public_with_target(session, interaction)


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
    skip: int = 0,
    limit: int = 100,
) -> DouyinInteractionsPublic:
    """Query visible interactions and enrich reply targets in one use case."""

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
            )
            for interaction in interactions
        ],
        count=count,
    )


def list_interaction_quotas(
    session: Session, *, owner_id: uuid.UUID
) -> list[DouyinInteractionQuotaPublic]:
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
