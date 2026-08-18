"""抖音互动（评论/回复）链路的测试：覆盖互动请求校验与内容加密脱敏、归属筛选校验、预检-确认-去重流程、重试语义、账号占用与释放、执行超时治理、回复目标核验及浏览器步骤截图存证。"""

import asyncio
import base64
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from crawler.bootstrap.settings import settings
from crawler.business.douyin.accounts.models import DouyinAccount
from crawler.business.douyin.accounts.service import release_account
from crawler.business.douyin.comments.models import DouyinComment
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.interactions.models import (
    DouyinInteraction,
    DouyinInteractionCreate,
    DouyinInteractionEvent,
    DouyinInteractionStatus,
    DouyinInteractionType,
)
from crawler.business.douyin.interactions.screenshots import InteractionStepRecorder
from crawler.business.douyin.interactions.service import (
    InteractionCipher,
    interaction_detail,
    interaction_manager,
    interaction_public,
)
from crawler.business.douyin.tasks.models import CrawlTask
from crawler.business.douyin.tracks.service import create_track
from crawler.business.identity.models import User
from crawler.douyin_client.interactions import (
    InteractionExecutionError,
    InteractionExecutionResult,
)
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlmodel import Session, select

from tests.utils.douyin import default_track_id


def _interaction_fixture(db: Session) -> tuple[CrawlTask, DouyinAccount, DouyinComment]:
    """构造互动测试数据：就绪账号 + 已完成任务 + 一条待回复评论，返回三元组。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    account = DouyinAccount(
        owner_id=owner.id,
        name=f"互动测试账号-{uuid.uuid4().hex[:8]}",
        browser_mode="local",
        profile_key=uuid.uuid4().hex,
        identity_hash=uuid.uuid4().hex,
        status="ready",
    )
    db.add(account)
    db.flush()
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        account_id=account.id,
        crawl_type="detail",
        status="succeeded",
        request_json='{"crawl_type":"detail","video_ids":["interaction-aweme"]}',
    )
    db.add(task)
    db.flush()
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id="interaction-aweme",
            title="互动测试作品",
            nickname="作**者",
            sec_uid="hashed-author-id",
        )
    )
    comment = DouyinComment(
        task_id=task.id,
        comment_id="interaction-comment",
        aweme_id="interaction-aweme",
        content="需要回复的评论",
        nickname="评**者",
    )
    db.add(comment)
    db.commit()
    db.refresh(task)
    db.refresh(account)
    db.refresh(comment)
    return task, account, comment


def test_interaction_request_requires_reply_target_and_hides_content() -> None:
    """验证评论回复类互动必须提供目标评论 id，且互动内容不出现在 repr 中（防泄密）。"""
    with pytest.raises(ValidationError, match="目标评论"):
        DouyinInteractionCreate(
            task_id=uuid.uuid4(),
            aweme_id="123",
            account_id=uuid.uuid4(),
            interaction_type=DouyinInteractionType.comment_reply,
            content="测试回复",
        )

    request = DouyinInteractionCreate(
        task_id=uuid.uuid4(),
        aweme_id="123",
        account_id=uuid.uuid4(),
        interaction_type=DouyinInteractionType.video_comment,
        content="不能出现在 repr 中的内容",
    )
    assert "不能出现在" not in repr(request)


def test_interaction_list_validates_task_and_track_filters(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证互动列表接口对 task_id/track_id 筛选的校验：不存在报 404，任务与赛道不匹配报 422。"""
    task, _account, _comment = _interaction_fixture(db)
    owner = db.get(User, task.owner_id)
    assert owner is not None
    other_track = create_track(
        db,
        owner_id=owner.id,
        name=f"互动筛选-{uuid.uuid4().hex[:8]}",
        description="",
        prompt="",
        keywords=[],
    )
    db.commit()

    missing = client.get(
        f"{settings.API_V1_STR}/douyin/interactions",
        params={"task_id": str(uuid.uuid4())},
        headers=superuser_token_headers,
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "任务不存在或无权访问"

    missing_track = client.get(
        f"{settings.API_V1_STR}/douyin/interactions",
        params={"track_id": str(uuid.uuid4())},
        headers=superuser_token_headers,
    )
    assert missing_track.status_code == 404
    assert missing_track.json()["detail"] == "赛道不存在或无权访问"

    mismatch = client.get(
        f"{settings.API_V1_STR}/douyin/interactions",
        params={"task_id": str(task.id), "track_id": str(other_track.id)},
        headers=superuser_token_headers,
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["detail"]["code"] == "task_track_mismatch"


def test_interaction_cipher_round_trip_and_rejects_other_key() -> None:
    """验证互动内容加密器同密钥可往返解密、密文不含明文，异密钥解密抛出带 SECRET_KEY 提示的错误。"""
    first = InteractionCipher("first-secret")
    second = InteractionCipher("second-secret")
    encrypted = first.encrypt("仅加密保存的互动内容")

    assert "互动内容" not in encrypted
    assert first.decrypt(encrypted) == "仅加密保存的互动内容"
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        second.decrypt(encrypted)


def test_prepare_confirm_and_duplicate_protection(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证互动全链路：预检放行、创建后为待确认状态且内容加密落库、重复提交 409、确认后入队并记录事件时间线。"""
    task, account, _ = _interaction_fixture(db)
    payload = {
        "task_id": str(task.id),
        "aweme_id": "interaction-aweme",
        "account_id": str(account.id),
        "interaction_type": "video_comment",
        "content": "这是一条需要人工确认的评论",
    }

    checked = client.post(
        f"{settings.API_V1_STR}/douyin/interactions/preflight",
        headers=superuser_token_headers,
        json=payload,
    )
    assert checked.status_code == 200
    assert checked.json()["allowed"] is True

    prepared = client.post(
        f"{settings.API_V1_STR}/douyin/interactions",
        headers=superuser_token_headers,
        json=payload,
    )
    assert prepared.status_code == 201
    body = prepared.json()
    assert body["status"] == "pending_confirmation"
    assert body["target_video_url"] == (
        "https://www.douyin.com/video/interaction-aweme"
    )
    assert body["target_comment_content"] is None
    assert "content" not in body
    assert "需要人工确认" in body["content_preview"]

    persisted = db.get(DouyinInteraction, uuid.UUID(body["id"]))
    assert persisted is not None
    assert "需要人工确认" not in persisted.content_encrypted
    assert persisted.account_name == account.name

    duplicate = client.post(
        f"{settings.API_V1_STR}/douyin/interactions",
        headers=superuser_token_headers,
        json=payload,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "duplicate_interaction"

    schedule = AsyncMock()
    monkeypatch.setattr(interaction_manager, "_schedule", schedule)
    confirmed = client.post(
        f"{settings.API_V1_STR}/douyin/interactions/{body['id']}/confirm",
        headers=superuser_token_headers,
    )
    assert confirmed.status_code == 202
    assert confirmed.json()["status"] == "queued"
    schedule.assert_awaited_once_with(uuid.UUID(body["id"]))

    detail = client.get(
        f"{settings.API_V1_STR}/douyin/interactions/{body['id']}",
        headers=superuser_token_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["content"] == payload["content"]
    assert [event["event"] for event in detail.json()["events"]] == [
        "created",
        "confirmed",
    ]

    db.delete(task)
    db.delete(account)
    db.commit()


def test_reply_target_must_belong_to_selected_aweme(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证回复目标评论必须属于所选作品，否则预检返回 409 target_not_found。"""
    task, account, comment = _interaction_fixture(db)
    response = client.post(
        f"{settings.API_V1_STR}/douyin/interactions/preflight",
        headers=superuser_token_headers,
        json={
            "task_id": str(task.id),
            "aweme_id": "interaction-aweme",
            "account_id": str(account.id),
            "interaction_type": "comment_reply",
            "target_comment_id": f"{comment.comment_id}-missing",
            "content": "回复内容",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "target_not_found"

    db.delete(task)
    db.delete(account)
    db.commit()


def test_interaction_list_and_detail_show_replied_comment_content(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证互动列表与详情均回显被回复评论的原文，详情返回解密后的完整互动内容。"""
    task, account, comment = _interaction_fixture(db)
    payload = {
        "task_id": str(task.id),
        "aweme_id": comment.aweme_id,
        "account_id": str(account.id),
        "interaction_type": "comment_reply",
        "target_comment_id": comment.comment_id,
        "content": "这是发送给原评论的回复",
    }

    prepared = client.post(
        f"{settings.API_V1_STR}/douyin/interactions",
        headers=superuser_token_headers,
        json=payload,
    )
    assert prepared.status_code == 201
    interaction_id = prepared.json()["id"]
    assert prepared.json()["target_comment_content"] == comment.content

    listed = client.get(
        f"{settings.API_V1_STR}/douyin/interactions",
        headers=superuser_token_headers,
        params={"task_id": str(task.id), "interaction_type": "comment_reply"},
    )
    assert listed.status_code == 200
    listed_item = next(
        item for item in listed.json()["data"] if item["id"] == interaction_id
    )
    assert listed_item["target_comment_id"] == comment.comment_id
    assert listed_item["target_comment_content"] == "需要回复的评论"
    assert listed_item["content_preview"] == payload["content"]

    detail = client.get(
        f"{settings.API_V1_STR}/douyin/interactions/{interaction_id}",
        headers=superuser_token_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["target_comment_content"] == comment.content
    assert detail.json()["content"] == payload["content"]

    db.delete(task)
    db.delete(account)
    db.commit()


def test_interaction_rejects_probable_question_mark_encoding_damage(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证预检与创建接口拒绝疑似编码损坏（连串问号）的互动内容，正常中文内容（含半角问号）不受影响。"""
    task, account, _ = _interaction_fixture(db)
    payload = {
        "task_id": str(task.id),
        "aweme_id": "interaction-aweme",
        "account_id": str(account.id),
        "interaction_type": "video_comment",
        "content": "????????,?????????",
    }

    for path in (
        f"{settings.API_V1_STR}/douyin/interactions/preflight",
        f"{settings.API_V1_STR}/douyin/interactions",
    ):
        response = client.post(
            path,
            headers=superuser_token_headers,
            json=payload,
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "invalid_content_encoding"

    payload["content"] = "这条中文评论可以正常发送吗?"
    response = client.post(
        f"{settings.API_V1_STR}/douyin/interactions/preflight",
        headers=superuser_token_headers,
        json=payload,
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is True

    db.delete(task)
    db.delete(account)
    db.commit()


def test_interaction_hides_unrecoverable_historical_encoding_damage(
    db: Session,
) -> None:
    """验证历史编码损坏的互动内容以占位文案对外展示、禁止重试，且执行前准备阶段直接拒绝。"""
    task, account, _ = _interaction_fixture(db)
    damaged = "?????????????????"
    interaction = DouyinInteraction(
        owner_id=task.owner_id,
        task_id=task.id,
        account_id=account.id,
        account_name=account.name,
        aweme_id="interaction-aweme",
        interaction_type="video_comment",
        content_encrypted=InteractionCipher(settings.SECRET_KEY).encrypt(damaged),
        content_preview=damaged,
        content_hash="d" * 64,
        idempotency_key=uuid.uuid4().hex,
        status=DouyinInteractionStatus.failed.value,
        attempt_count=1,
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)

    public = interaction_public(interaction)
    assert public.content_preview == ("[历史互动内容编码损坏，原文无法恢复]")
    assert public.can_retry is False
    assert interaction_detail(db, interaction).content == (
        "[历史互动内容编码损坏，原文无法恢复]"
    )

    interaction.status = DouyinInteractionStatus.queued.value
    db.add(interaction)
    db.commit()
    with pytest.raises(InteractionExecutionError) as exc_info:
        interaction_manager._prepare_execution(interaction.id)
    assert exc_info.value.code == "invalid_content_encoding"

    db.delete(task)
    db.delete(account)
    db.commit()


def test_needs_review_retry_requires_explicit_not_sent_confirmation(
    db: Session,
) -> None:
    """验证 needs_review 状态的互动重试前必须显式确认抖音侧未发送成功，防止重复发送。"""
    task, account, _ = _interaction_fixture(db)
    owner_id = task.owner_id
    interaction = DouyinInteraction(
        owner_id=owner_id,
        task_id=task.id,
        account_id=account.id,
        account_name=account.name,
        aweme_id="interaction-aweme",
        interaction_type="video_comment",
        content_encrypted=InteractionCipher(settings.SECRET_KEY).encrypt("待核对内容"),
        content_preview="待核对内容",
        content_hash="a" * 64,
        idempotency_key=uuid.uuid4().hex,
        status=DouyinInteractionStatus.needs_review.value,
        attempt_count=1,
    )
    db.add(interaction)
    db.commit()

    with pytest.raises(RuntimeError, match="确认抖音中没有发送成功"):
        asyncio.run(
            interaction_manager.retry(
                interaction_id=interaction.id,
                owner_id=owner_id,
                confirm_not_sent=False,
            )
        )

    db.delete(task)
    db.delete(account)
    db.commit()


def test_every_non_successful_interaction_can_be_retried_without_attempt_cap(
    db: Session,
) -> None:
    """验证除成功态外所有状态的互动都可重试，且不存在尝试次数上限。"""
    task, account, _ = _interaction_fixture(db)
    interaction = DouyinInteraction(
        owner_id=task.owner_id,
        task_id=task.id,
        account_id=account.id,
        account_name=account.name,
        aweme_id="interaction-aweme",
        interaction_type="video_comment",
        content_encrypted=InteractionCipher(settings.SECRET_KEY).encrypt("待重试评论"),
        content_preview="待重试评论",
        content_hash="b" * 64,
        idempotency_key=uuid.uuid4().hex,
        status=DouyinInteractionStatus.failed.value,
        failure_code="comment_submit_failed",
        attempt_count=99,
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)

    for status in DouyinInteractionStatus:
        interaction.status = status.value
        assert interaction_public(interaction).can_retry is (
            status != DouyinInteractionStatus.succeeded
        )

    db.delete(task)
    db.delete(account)
    db.commit()


def test_unavailable_target_is_terminal_and_cannot_be_retried(db: Session) -> None:
    """验证目标已不可用（target_unavailable）的失败为终态：不可重试且重试请求直接报错。"""
    task, account, _ = _interaction_fixture(db)
    interaction = DouyinInteraction(
        owner_id=task.owner_id,
        task_id=task.id,
        account_id=account.id,
        account_name=account.name,
        aweme_id="interaction-aweme",
        target_comment_id="missing-comment",
        interaction_type="comment_reply",
        content_encrypted=InteractionCipher(settings.SECRET_KEY).encrypt("无法发送"),
        content_preview="无法发送",
        content_hash="e" * 64,
        idempotency_key=uuid.uuid4().hex,
        status=DouyinInteractionStatus.failed.value,
        failure_code="target_unavailable",
        attempt_count=2,
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)

    assert interaction_public(interaction).can_retry is False
    with pytest.raises(RuntimeError, match="目标评论已不可用"):
        asyncio.run(
            interaction_manager.retry(
                interaction_id=interaction.id,
                owner_id=task.owner_id,
                confirm_not_sent=False,
            )
        )

    db.delete(task)
    db.delete(account)
    db.commit()


def test_cancelled_interaction_can_be_queued_while_account_is_busy(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证已取消的互动在账号租约占满时仍可重新入队（排队等待而非拒绝）。"""
    task, account, _ = _interaction_fixture(db)
    account.active_leases = account.concurrency_limit
    db.add(account)
    interaction = DouyinInteraction(
        owner_id=task.owner_id,
        task_id=task.id,
        account_id=account.id,
        account_name=account.name,
        aweme_id="interaction-aweme",
        interaction_type="video_comment",
        content_encrypted=InteractionCipher(settings.SECRET_KEY).encrypt("重新发送"),
        content_preview="重新发送",
        content_hash="c" * 64,
        idempotency_key=uuid.uuid4().hex,
        status=DouyinInteractionStatus.cancelled.value,
        attempt_count=20,
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)
    scheduled = AsyncMock()
    monkeypatch.setattr(interaction_manager, "_schedule", scheduled)

    retried = asyncio.run(
        interaction_manager.retry(
            interaction_id=interaction.id,
            owner_id=task.owner_id,
            confirm_not_sent=False,
        )
    )

    assert retried.status == DouyinInteractionStatus.queued.value
    scheduled.assert_awaited_once_with(interaction.id)

    db.delete(task)
    db.delete(account)
    db.commit()


def test_prepare_execution_returns_readable_detached_account(db: Session) -> None:
    """验证执行前准备返回脱离会话的可读账号快照（默认请求间隔、未使用时间）与解密后的执行请求。"""
    task, account, _ = _interaction_fixture(db)
    interaction = DouyinInteraction(
        owner_id=task.owner_id,
        task_id=task.id,
        account_id=account.id,
        account_name=account.name,
        aweme_id="interaction-aweme",
        interaction_type="video_comment",
        content_encrypted=InteractionCipher(settings.SECRET_KEY).encrypt("回归测试"),
        content_preview="回归测试",
        content_hash="b" * 64,
        idempotency_key=uuid.uuid4().hex,
        status=DouyinInteractionStatus.queued.value,
    )
    db.add(interaction)
    db.commit()

    _, detached_account, request = interaction_manager._prepare_execution(
        interaction.id
    )

    assert detached_account.min_request_interval_seconds == 1.0
    assert detached_account.last_used_at is None
    assert request.content == "回归测试"
    assert request.target_parent_comment_id is None

    db.delete(task)
    db.delete(account)
    db.commit()


def test_interaction_manager_resolves_account_into_neutral_browser_connection(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证执行器接收的是中立浏览器连接描述（模式/端口/用户数据目录）而非账号实体，执行成功后状态流转为 succeeded。"""
    task, account, _ = _interaction_fixture(db)
    interaction = DouyinInteraction(
        owner_id=task.owner_id,
        task_id=task.id,
        account_id=account.id,
        account_name=account.name,
        aweme_id="interaction-aweme",
        interaction_type="video_comment",
        content_encrypted=InteractionCipher(settings.SECRET_KEY).encrypt(
            "连接边界测试"
        ),
        content_preview="连接边界测试",
        content_hash="a" * 64,
        idempotency_key=uuid.uuid4().hex,
        status=DouyinInteractionStatus.queued.value,
    )
    db.add(interaction)
    db.commit()
    executor = AsyncMock(return_value=InteractionExecutionResult())
    monkeypatch.setattr(interaction_manager._executor, "execute", executor)

    asyncio.run(interaction_manager._run(interaction.id))

    executor.assert_awaited_once()
    call = executor.await_args.kwargs
    assert "account" not in call
    assert call["connection"].browser_mode == "local"
    assert call["connection"].debug_port == settings.DOUYIN_CDP_PORT + (
        account.id.int % 500
    )
    assert call["connection"].user_data_dir.name == account.profile_key
    assert call["request"].interaction_type == "video_comment"
    db.expire_all()
    stored = db.get(DouyinInteraction, interaction.id)
    assert stored is not None
    assert stored.status == DouyinInteractionStatus.succeeded.value

    db.delete(task)
    db.delete(account)
    db.commit()


def test_failed_interaction_release_does_not_cool_account(db: Session) -> None:
    """验证互动执行失败释放账号时不触发冷却，仅累计失败次数并记录错误，账号保持 ready。"""
    task, account, _ = _interaction_fixture(db)

    release_account(account.id, success=False, error="互动任务执行失败")

    db.expire_all()
    refreshed = db.get(DouyinAccount, account.id)
    assert refreshed is not None
    assert refreshed.status == "ready"
    assert refreshed.cooldown_until is None
    assert refreshed.failure_streak == 1
    assert refreshed.last_error == "互动任务执行失败"

    db.delete(task)
    db.delete(refreshed)
    db.commit()


def test_interaction_execution_timeout_releases_account_and_allows_retry(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证互动执行超时后标记 execution_timeout 失败、释放账号租约且允许重试。"""
    task, account, _ = _interaction_fixture(db)
    interaction = DouyinInteraction(
        owner_id=task.owner_id,
        task_id=task.id,
        account_id=account.id,
        account_name=account.name,
        aweme_id="interaction-aweme",
        interaction_type="video_comment",
        content_encrypted=InteractionCipher(settings.SECRET_KEY).encrypt(
            "超时释放测试"
        ),
        content_preview="超时释放测试",
        content_hash="d" * 64,
        idempotency_key=uuid.uuid4().hex,
        status=DouyinInteractionStatus.queued.value,
    )
    db.add(interaction)
    db.commit()
    interaction_id = interaction.id
    account_id = account.id

    async def never_finishes(**_kwargs: object) -> None:
        """模拟永不返回的执行器（用于触发超时路径）。"""
        await asyncio.Event().wait()

    monkeypatch.setattr(
        interaction_manager._executor,
        "execute",
        AsyncMock(side_effect=never_finishes),
    )
    monkeypatch.setattr(settings, "DOUYIN_INTERACTION_EXECUTION_TIMEOUT_SECONDS", 0.01)

    asyncio.run(interaction_manager._run(interaction_id))

    db.expire_all()
    refreshed_interaction = db.get(DouyinInteraction, interaction_id)
    refreshed_account = db.get(DouyinAccount, account_id)
    assert refreshed_interaction is not None
    assert refreshed_account is not None
    assert refreshed_interaction.status == DouyinInteractionStatus.failed.value
    assert refreshed_interaction.failure_code == "execution_timeout"
    assert interaction_public(refreshed_interaction).can_retry is True
    assert refreshed_account.active_leases == 0
    assert refreshed_account.cooldown_until is None

    db.delete(task)
    db.delete(refreshed_account)
    db.commit()


def test_reply_target_mismatch_requires_manual_review(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证回复发布未绑定到预期评论（歧义结果）时转入 needs_review 等待人工核对，并释放账号租约。"""
    task, account, _ = _interaction_fixture(db)
    interaction = DouyinInteraction(
        owner_id=task.owner_id,
        task_id=task.id,
        account_id=account.id,
        account_name=account.name,
        aweme_id="interaction-aweme",
        interaction_type="video_comment",
        content_encrypted=InteractionCipher(settings.SECRET_KEY).encrypt(
            "目标绑定核验"
        ),
        content_preview="目标绑定核验",
        content_hash="f" * 64,
        idempotency_key=uuid.uuid4().hex,
        status=DouyinInteractionStatus.queued.value,
    )
    db.add(interaction)
    db.commit()
    interaction_id = interaction.id
    account_id = account.id
    monkeypatch.setattr(
        interaction_manager._executor,
        "execute",
        AsyncMock(
            side_effect=InteractionExecutionError(
                "reply_target_mismatch",
                "回复发布请求没有绑定到预期评论",
                ambiguous=True,
            )
        ),
    )

    asyncio.run(interaction_manager._run(interaction_id))

    db.expire_all()
    refreshed_interaction = db.get(DouyinInteraction, interaction_id)
    refreshed_account = db.get(DouyinAccount, account_id)
    assert refreshed_interaction is not None
    assert refreshed_account is not None
    assert refreshed_interaction.status == DouyinInteractionStatus.needs_review.value
    assert refreshed_interaction.failure_code == "reply_target_mismatch"
    assert interaction_public(refreshed_interaction).can_retry is True
    assert refreshed_account.active_leases == 0

    db.delete(task)
    db.delete(refreshed_account)
    db.commit()


def test_browser_step_screenshot_is_private_and_available_in_detail(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """验证浏览器步骤截图经 CDP 采集后私有落盘：事件记录不含绝对路径、详情仅暴露标记位、图片接口需鉴权且禁缓存。"""
    task, account, _ = _interaction_fixture(db)
    interaction = DouyinInteraction(
        owner_id=task.owner_id,
        task_id=task.id,
        account_id=account.id,
        account_name=account.name,
        aweme_id="interaction-aweme",
        interaction_type="video_comment",
        content_encrypted=InteractionCipher(settings.SECRET_KEY).encrypt("截图测试"),
        content_preview="截图测试",
        content_hash="c" * 64,
        idempotency_key=uuid.uuid4().hex,
        status=DouyinInteractionStatus.running.value,
        attempt_count=2,
    )
    db.add(interaction)
    db.commit()
    monkeypatch.setattr(settings, "DOUYIN_INTERACTION_SCREENSHOT_DIR", tmp_path)
    page = AsyncMock()
    screenshot = b"fake-jpeg-browser-evidence"
    cdp = AsyncMock()
    cdp.send.return_value = {
        "data": base64.b64encode(screenshot).decode(),
    }
    page.context.new_cdp_session.return_value = cdp

    asyncio.run(
        InteractionStepRecorder(interaction.id).record(
            page, "video_opened", "已打开目标视频页面"
        )
    )
    page.context.new_cdp_session.assert_awaited_once_with(page)
    cdp.send.assert_awaited_once_with(
        "Page.captureScreenshot",
        {
            "format": "jpeg",
            "quality": settings.DOUYIN_INTERACTION_SCREENSHOT_QUALITY,
            "fromSurface": True,
            "captureBeyondViewport": False,
        },
    )
    cdp.detach.assert_awaited_once()

    db.expire_all()
    event = db.exec(
        select(DouyinInteractionEvent).where(
            DouyinInteractionEvent.interaction_id == interaction.id,
            DouyinInteractionEvent.event == "browser_video_opened",
        )
    ).one()
    assert event.attempt_number == 2
    assert event.screenshot_path
    assert str(tmp_path) not in event.screenshot_path
    assert event.screenshot_size == len(screenshot)

    detail = client.get(
        f"{settings.API_V1_STR}/douyin/interactions/{interaction.id}",
        headers=superuser_token_headers,
    )
    assert detail.status_code == 200
    public_event = next(
        item
        for item in detail.json()["events"]
        if item["event"] == "browser_video_opened"
    )
    assert public_event["attempt_number"] == 2
    assert public_event["has_screenshot"] is True
    assert "screenshot_path" not in public_event

    unauthorized = client.get(
        f"{settings.API_V1_STR}/douyin/interactions/{interaction.id}"
        f"/events/{event.id}/screenshot"
    )
    assert unauthorized.status_code == 401

    image = client.get(
        (
            f"{settings.API_V1_STR}/douyin/interactions/{interaction.id}"
            f"/events/{event.id}/screenshot"
        ),
        headers=superuser_token_headers,
    )
    assert image.status_code == 200
    assert image.content == screenshot
    assert image.headers["cache-control"] == "private, no-store"
    assert image.headers["content-type"].startswith("image/jpeg")

    db.delete(task)
    db.delete(account)
    db.commit()
