import asyncio
import base64
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlmodel import Session, select

from app.core.config import settings
from app.douyin.interactions import InteractionExecutionError
from app.models import (
    CrawlTask,
    DouyinAccount,
    DouyinAweme,
    DouyinComment,
    DouyinInteraction,
    DouyinInteractionCreate,
    DouyinInteractionEvent,
    DouyinInteractionStatus,
    DouyinInteractionType,
    User,
)
from app.services.douyin_accounts import release_account
from app.services.douyin_interactions import (
    InteractionCipher,
    interaction_detail,
    interaction_manager,
    interaction_public,
)
from app.services.interaction_screenshots import InteractionStepRecorder


def _interaction_fixture(db: Session) -> tuple[CrawlTask, DouyinAccount, DouyinComment]:
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


def test_interaction_cipher_round_trip_and_rejects_other_key() -> None:
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


def test_interaction_rejects_probable_question_mark_encoding_damage(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
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
    assert public.content_preview == (
        "[历史互动内容编码损坏，原文无法恢复]"
    )
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


def test_pre_submit_page_failure_has_four_safe_recovery_retries(db: Session) -> None:
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
        failure_code="page_load_timeout",
        attempt_count=settings.DOUYIN_INTERACTION_MAX_ATTEMPTS,
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)

    assert interaction_public(interaction).can_retry is True
    interaction.attempt_count = settings.DOUYIN_INTERACTION_MAX_ATTEMPTS + 3
    assert interaction_public(interaction).can_retry is True
    interaction.attempt_count = settings.DOUYIN_INTERACTION_MAX_ATTEMPTS + 4
    assert interaction_public(interaction).can_retry is False
    interaction.attempt_count = settings.DOUYIN_INTERACTION_MAX_ATTEMPTS
    interaction.failure_code = "comment_not_available"
    assert interaction_public(interaction).can_retry is True
    interaction.failure_code = "page_interrupted"
    assert interaction_public(interaction).can_retry is True
    interaction.failure_code = "submit_not_triggered"
    assert interaction_public(interaction).can_retry is True
    interaction.failure_code = "comment_submit_failed"
    assert interaction_public(interaction).can_retry is False

    db.delete(task)
    db.delete(account)
    db.commit()


def test_prepare_execution_returns_readable_detached_account(db: Session) -> None:
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

    db.delete(task)
    db.delete(account)
    db.commit()


def test_failed_interaction_release_does_not_cool_account(db: Session) -> None:
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
        await asyncio.Event().wait()

    monkeypatch.setattr(
        interaction_manager._executor,
        "execute",
        AsyncMock(side_effect=never_finishes),
    )
    monkeypatch.setattr(
        settings, "DOUYIN_INTERACTION_EXECUTION_TIMEOUT_SECONDS", 0.01
    )

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


def test_browser_step_screenshot_is_private_and_available_in_detail(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
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
