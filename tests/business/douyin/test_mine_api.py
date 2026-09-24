"""「我的」模块读侧接口的回归测试。"""

import uuid

from crawler.bootstrap.settings import settings
from crawler.business.douyin.creators.models import DouyinCreator
from crawler.business.douyin.mine.service import save_followings
from crawler.business.identity.models import User
from crawler.douyin_client import anonymize_user_id
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select


def test_mine_endpoints_return_empty_until_crawled(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证新账号的关注/点赞/收藏为空、概览为零，且越权账号返回 404。"""
    base = f"{settings.API_V1_STR}/douyin"
    suffix = uuid.uuid4().hex[:8]
    account = client.post(
        f"{base}/accounts",
        headers=superuser_token_headers,
        json={"name": f"我的模块账号{suffix}", "browser_mode": "local"},
    )
    assert account.status_code == 201, account.text
    account_id = account.json()["id"]

    summary = client.get(
        f"{base}/my/summary",
        headers=superuser_token_headers,
        params={"account_id": account_id},
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["following_count"] == 0
    assert summary.json()["liked_count"] == 0
    assert summary.json()["collected_count"] == 0

    for path in ("followings", "awemes"):
        params = {"account_id": account_id}
        if path == "awemes":
            params["kind"] = "liked"
        response = client.get(
            f"{base}/my/{path}", headers=superuser_token_headers, params=params
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"data": [], "count": 0}

    missing = client.get(
        f"{base}/my/summary",
        headers=superuser_token_headers,
        params={"account_id": str(uuid.uuid4())},
    )
    assert missing.status_code == 404

    assert (
        client.delete(
            f"{base}/accounts/by-id/{account_id}", headers=superuser_token_headers
        ).status_code
        == 200
    )


def test_promote_followings_endpoint_adds_to_creator_list(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证「我的关注 → 达人名单」接口：写入达人名单、我的关注标记已入名单、重复调用幂等。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    base = f"{settings.API_V1_STR}/douyin"
    suffix = uuid.uuid4().hex[:8]
    account = client.post(
        f"{base}/accounts",
        headers=superuser_token_headers,
        json={"name": f"加入名单接口账号{suffix}", "browser_mode": "local"},
    )
    assert account.status_code == 201, account.text
    account_id = uuid.UUID(account.json()["id"])
    sec_uid = f"MS4wLjABAAAA-api-promote-{suffix}"
    assert (
        save_followings(
            db,
            owner_id=owner.id,
            account_id=account_id,
            items=[
                {
                    "uid_hash": anonymize_user_id(sec_uid),
                    "sec_uid": sec_uid,
                    "nickname": "接口关注博主",
                }
            ],
        )
        == 1
    )
    url = f"{base}/my/followings/to-creators"

    response = client.post(
        url,
        headers=superuser_token_headers,
        json={"account_id": str(account_id), "limit": 10},
    )

    assert response.status_code == 200, response.text
    assert response.json()["added_count"] == 1
    assert response.json()["remaining_count"] == 0
    # 我的关注列表同步标记为「已在名单」
    listing = client.get(
        f"{base}/my/followings",
        headers=superuser_token_headers,
        params={"account_id": str(account_id)},
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["data"][0]["in_creator_list"] is True
    # 再次调用不会重复创建
    again = client.post(
        url,
        headers=superuser_token_headers,
        json={"account_id": str(account_id), "limit": 10},
    )
    assert again.status_code == 200, again.text
    assert (again.json()["added_count"], again.json()["remaining_count"]) == (0, 0)

    created = {
        row.id
        for row in db.exec(
            select(DouyinCreator).where(
                DouyinCreator.owner_id == owner.id,
                DouyinCreator.sec_uid == sec_uid,
            )
        ).all()
    }
    assert len(created) == 1

    # 清理本次写入，避免影响其他用例对达人名单总数的断言
    db.exec(
        delete(DouyinCreator).where(
            DouyinCreator.owner_id == owner.id,
            col(DouyinCreator.sec_uid).in_([sec_uid]),
        )
    )
    db.commit()
    assert (
        client.delete(
            f"{base}/accounts/by-id/{account_id}", headers=superuser_token_headers
        ).status_code
        == 200
    )


def test_promote_followings_endpoint_requires_auth_and_owned_account(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证加入达人名单接口未认证返回 401，账号不属于当前用户返回 404。"""
    url = f"{settings.API_V1_STR}/douyin/my/followings/to-creators"

    unauthenticated = client.post(url, json={"account_id": str(uuid.uuid4())})
    assert unauthenticated.status_code == 401

    missing = client.post(
        url,
        headers=superuser_token_headers,
        json={"account_id": str(uuid.uuid4()), "limit": 10},
    )
    assert missing.status_code == 404
