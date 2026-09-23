"""「我的」模块写入侧的回归测试：按账号幂等 upsert。"""

import uuid

from crawler.bootstrap.settings import settings
from crawler.business.douyin.mine.service import (
    list_account_awemes,
    list_followings,
    mine_summary,
    save_account_awemes,
    save_followings,
)
from crawler.business.identity.models import User
from fastapi.testclient import TestClient
from sqlmodel import Session, select


def test_save_is_idempotent_and_summary_counts(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证重复写入不产生重复行、字段被更新、概览计数与列表口径一致。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    base = f"{settings.API_V1_STR}/douyin"
    suffix = uuid.uuid4().hex[:8]
    account = client.post(
        f"{base}/accounts",
        headers=superuser_token_headers,
        json={"name": f"写入账号{suffix}", "browser_mode": "local"},
    )
    account_id = uuid.UUID(account.json()["id"])

    followings = [
        {
            "uid_hash": f"uid-{suffix}-{index}",
            "sec_uid": f"MS4wLjABAAAA-{suffix}-{index}",
            "nickname": f"博主{index}",
            "follower_count": 100 + index,
        }
        for index in range(3)
    ]
    assert (
        save_followings(db, owner_id=owner.id, account_id=account_id, items=followings)
        == 3
    )
    # 重复写入同一批：只更新不新增
    followings[0]["nickname"] = "改名后的博主"
    assert (
        save_followings(db, owner_id=owner.id, account_id=account_id, items=followings)
        == 3
    )
    listing = list_followings(db, owner_id=owner.id, account_id=account_id, limit=10)
    assert listing.count == 3
    assert {row.nickname for row in listing.data} >= {"改名后的博主"}

    awemes = [
        {"aweme_id": f"aweme-{suffix}-{index}", "title": f"作品{index}"}
        for index in range(2)
    ]
    assert (
        save_account_awemes(
            db,
            owner_id=owner.id,
            account_id=account_id,
            kind="liked",
            items=awemes,
        )
        == 2
    )
    assert (
        save_account_awemes(
            db,
            owner_id=owner.id,
            account_id=account_id,
            kind="liked",
            items=awemes,
        )
        == 2
    )
    aweme_list = list_account_awemes(
        db, owner_id=owner.id, account_id=account_id, kind="liked", limit=10
    )
    assert aweme_list.count == 2
    # 收藏与点赞互不影响
    collected = list_account_awemes(
        db, owner_id=owner.id, account_id=account_id, kind="collected", limit=10
    )
    assert collected.count == 0

    summary = mine_summary(db, owner_id=owner.id, account_id=account_id)
    assert summary.following_count == 3
    assert summary.liked_count == 2
    assert summary.collected_count == 0
    assert summary.following_fetched_at is not None

    assert (
        client.delete(
            f"{base}/accounts/by-id/{account_id}", headers=superuser_token_headers
        ).status_code
        == 200
    )
