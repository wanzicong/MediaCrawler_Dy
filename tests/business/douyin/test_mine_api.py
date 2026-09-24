"""「我的」模块读侧接口的回归测试。"""

import uuid

from crawler.bootstrap.settings import settings
from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.accounts.models import DouyinAccount
from crawler.business.douyin.creators import profile_sync
from crawler.business.douyin.creators.models import DouyinCreator
from crawler.business.douyin.creators.profile_sync import apply_profile_payload
from crawler.business.douyin.mine.service import save_followings
from crawler.business.identity.models import User
from crawler.douyin_client import anonymize_user_id
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlmodel import Session, col, delete, select

from tests.utils.douyin import default_track_id


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


def test_followings_carry_creator_profile_and_search_by_cleaned_fields(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证关注列表带上达人名单的清洗结果，并可按清洗后的昵称/抖音号搜索。

    背景：关注列表接口只给平台脱敏昵称（一***学），真实昵称在达人名单的主页
    信息里（一里同学）。两个列表要展示同一份数据，关注列表就不能只回原始昵称。
    """
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    base = f"{settings.API_V1_STR}/douyin"
    suffix = uuid.uuid4().hex[:8]
    account = client.post(
        f"{base}/accounts",
        headers=superuser_token_headers,
        json={"name": f"关注清洗展示账号{suffix}", "browser_mode": "local"},
    )
    assert account.status_code == 201, account.text
    account_id = uuid.UUID(account.json()["id"])
    sec_uid = f"MS4wLjABAAAA-masked-{suffix}"
    assert (
        save_followings(
            db,
            owner_id=owner.id,
            account_id=account_id,
            items=[
                {
                    "uid_hash": anonymize_user_id(sec_uid),
                    "sec_uid": sec_uid,
                    "nickname": "一***学",  # 平台给的脱敏昵称
                    "avatar_url": "",
                    "signature": "关注列表里的签名",
                    "follower_count": 100,
                    "aweme_count": 7,
                    "is_mutual": False,
                }
            ],
        )
        == 1
    )
    creator = DouyinCreator(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        sec_uid=sec_uid,
        creator_hash=anonymize_user_id(sec_uid),
        nickname="一里同学",  # 主页同步后的真实昵称
        unique_id="c664c",
        follower_count=309_076,
        aweme_total_count=414,
        profile_synced_at=get_datetime_utc(),
    )
    db.add(creator)
    db.commit()

    listing = client.get(
        f"{base}/my/followings",
        headers=superuser_token_headers,
        params={"account_id": str(account_id)},
    )
    assert listing.status_code == 200, listing.text
    row = listing.json()["data"][0]
    # 原始脱敏昵称仍然保留，前端展示时优先用 creator 里的清洗结果
    assert row["nickname"] == "一***学"
    assert row["in_creator_list"] is True
    assert row["creator"]["nickname"] == "一里同学"
    assert row["creator"]["unique_id"] == "c664c"
    assert row["creator"]["follower_count"] == 309_076

    # 清洗后的昵称、抖音号、平台脱敏昵称都能命中同一条关注
    for term in ("一里同学", "c664c", "一***学"):
        hit = client.get(
            f"{base}/my/followings",
            headers=superuser_token_headers,
            params={"account_id": str(account_id), "search": term},
        )
        assert hit.status_code == 200, hit.text
        assert hit.json()["count"] == 1, term

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


def test_sync_followings_profiles_promotes_then_fills_cleaned_profile(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: MonkeyPatch,
) -> None:
    """验证关注主页清洗接口：没进名单的先加入名单，再把主页信息写回名单。

    主页接口不可在单测里真连，这里只替换 IO 边界（挑账号 + 拉主页），字段映射
    仍走生产代码 ``apply_profile_payload``。
    """
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    base = f"{settings.API_V1_STR}/douyin"
    suffix = uuid.uuid4().hex[:8]
    account = client.post(
        f"{base}/accounts",
        headers=superuser_token_headers,
        json={"name": f"关注清洗账号{suffix}", "browser_mode": "local"},
    )
    assert account.status_code == 201, account.text
    account_id = uuid.UUID(account.json()["id"])
    cleaned = {
        f"MS4wLjABAAAA-clean-a-{suffix}": ("清洗后甲", f"clean_a_{suffix}"),
        f"MS4wLjABAAAA-clean-b-{suffix}": ("清洗后乙", f"clean_b_{suffix}"),
    }
    assert (
        save_followings(
            db,
            owner_id=owner.id,
            account_id=account_id,
            items=[
                {
                    "uid_hash": anonymize_user_id(sec_uid),
                    "sec_uid": sec_uid,
                    "nickname": "清***甲",
                    "avatar_url": "",
                    "signature": "",
                    "follower_count": index,
                    "aweme_count": 0,
                    "is_mutual": False,
                }
                for index, sec_uid in enumerate(cleaned, start=1)
            ],
        )
        == 2
    )

    # 替换生产实现的 IO 边界，签名保持一致（owner_id 在本用例里用不到）
    def fake_pick_account(
        *,
        owner_id: uuid.UUID,  # noqa: ARG001 - 必须与生产签名同名
        account_id: uuid.UUID | None,
    ):
        return db.get(DouyinAccount, account_id)

    # account 只用于生产侧的浏览器会话，这里同样只保留签名
    async def fake_fetch_profiles(
        *,
        account: DouyinAccount,  # noqa: ARG001 - 必须与生产签名同名
        creators: list[DouyinCreator],
        results: dict,
    ) -> None:
        for item in creators:
            nickname, unique_id = cleaned[item.sec_uid]
            results[item.id] = apply_profile_payload(
                item,
                {
                    "user": {
                        "nickname": nickname,
                        "unique_id": unique_id,
                        "follower_count": 1234,
                        "total_favorited": 5678,
                        "aweme_count": 9,
                        "signature": "主页签名",
                        "ip_location": "IP属地：上海",
                        "avatar_larger": {"url_list": ["https://example.com/a.jpg"]},
                    }
                },
            )

    monkeypatch.setattr(profile_sync, "_pick_account", fake_pick_account)
    monkeypatch.setattr(profile_sync, "_fetch_profiles", fake_fetch_profiles)

    response = client.post(
        f"{base}/my/followings/profile-sync",
        headers=superuser_token_headers,
        json={"account_id": str(account_id), "limit": 10},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["synced_count"] == 2
    assert payload["failed_count"] == 0
    assert payload["promoted_count"] == 2  # 两位都不在名单里，先自动加入
    assert payload["remaining_count"] == 0
    assert {item["creator"]["nickname"] for item in payload["data"]} == {
        "清洗后甲",
        "清洗后乙",
    }

    # 关注列表随后展示的也是清洗结果，并能按真实昵称搜到
    listing = client.get(
        f"{base}/my/followings",
        headers=superuser_token_headers,
        params={"account_id": str(account_id), "search": "清洗后甲"},
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["count"] == 1
    assert listing.json()["data"][0]["creator"]["unique_id"].startswith("clean_a_")

    db.exec(
        delete(DouyinCreator).where(
            DouyinCreator.owner_id == owner.id,
            col(DouyinCreator.sec_uid).in_(list(cleaned)),
        )
    )
    db.commit()
    assert (
        client.delete(
            f"{base}/accounts/by-id/{account_id}", headers=superuser_token_headers
        ).status_code
        == 200
    )
