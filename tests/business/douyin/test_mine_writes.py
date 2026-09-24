"""「我的」模块写入侧的回归测试：按账号幂等 upsert。"""

import uuid

from crawler.bootstrap.settings import settings
from crawler.business.douyin.creators.models import DouyinCreator
from crawler.business.douyin.mine.service import (
    list_account_awemes,
    list_followings,
    mine_summary,
    promote_followings_to_creators,
    save_account_awemes,
    save_followings,
)
from crawler.business.identity.models import User
from crawler.douyin_client import anonymize_user_id
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select

from tests.utils.douyin import default_track_id


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


def test_promote_followings_respects_batch_limit_and_skips_known(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证批量加入达人名单：每批受 limit 限制、粉丝多的先加入、已入名单的跳过且可重复调用。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    base = f"{settings.API_V1_STR}/douyin"
    suffix = uuid.uuid4().hex[:8]
    account = client.post(
        f"{base}/accounts",
        headers=superuser_token_headers,
        json={"name": f"加入名单账号{suffix}", "browser_mode": "local"},
    )
    assert account.status_code == 201, account.text
    account_id = uuid.UUID(account.json()["id"])

    sec_uids = [f"MS4wLjABAAAA-promote-{suffix}-{index}" for index in range(3)]
    followings = [
        {
            "uid_hash": anonymize_user_id(sec_uid),
            "sec_uid": sec_uid,
            "nickname": f"关注博主{index}",
            # 粉丝数递减：批量加入按粉丝从多到少推进
            "follower_count": 100 - index,
        }
        for index, sec_uid in enumerate(sec_uids)
    ]
    assert (
        save_followings(db, owner_id=owner.id, account_id=account_id, items=followings)
        == 3
    )

    def promoted_sec_uids() -> set[str]:
        return {
            str(value)
            for value in db.exec(
                select(DouyinCreator.sec_uid).where(
                    DouyinCreator.owner_id == owner.id,
                    col(DouyinCreator.sec_uid).in_(sec_uids),
                )
            ).all()
        }

    first = promote_followings_to_creators(
        db, owner_id=owner.id, account_id=account_id, limit=2
    )
    assert (first.added_count, first.existing_count, first.remaining_count) == (2, 0, 1)
    assert promoted_sec_uids() == set(sec_uids[:2])
    # 未指定赛道时落到默认赛道
    track_ids = set(
        db.exec(
            select(DouyinCreator.track_id).where(
                DouyinCreator.owner_id == owner.id,
                col(DouyinCreator.sec_uid).in_(sec_uids),
            )
        ).all()
    )
    assert track_ids == {default_track_id(db, owner_id=owner.id)}

    second = promote_followings_to_creators(
        db, owner_id=owner.id, account_id=account_id, limit=2
    )
    assert (second.added_count, second.remaining_count) == (1, 0)
    assert promoted_sec_uids() == set(sec_uids)
    # 全部已在名单后再调用是幂等的空操作
    third = promote_followings_to_creators(
        db, owner_id=owner.id, account_id=account_id, limit=2
    )
    assert (third.added_count, third.existing_count, third.remaining_count) == (0, 0, 0)

    listing = list_followings(db, owner_id=owner.id, account_id=account_id, limit=10)
    assert listing.count == 3
    assert all(row.in_creator_list for row in listing.data)

    # 清理本次加入的达人，避免影响其他用例对名单总数的断言
    db.exec(
        delete(DouyinCreator).where(
            DouyinCreator.owner_id == owner.id,
            col(DouyinCreator.sec_uid).in_(sec_uids),
        )
    )
    db.commit()
    assert (
        client.delete(
            f"{base}/accounts/by-id/{account_id}", headers=superuser_token_headers
        ).status_code
        == 200
    )
