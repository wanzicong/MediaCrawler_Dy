"""账号本人资料（抖音昵称 / 头像 / 抖音号）的提取与展示测试。"""

import uuid

from crawler.bootstrap.settings import settings
from crawler.business.douyin.accounts.models import DouyinAccount
from crawler.business.douyin.accounts.service import _profile_public_fields
from crawler.business.identity.models import User
from fastapi.testclient import TestClient
from sqlmodel import Session, select


def test_profile_public_fields_extracts_avatar_nickname_and_douyin_id() -> None:
    """验证从本人资料接口响应里取出昵称、头像与抖音号，缺失时给出空串。"""
    payload = {
        "user": {
            "nickname": "测试昵称",
            "unique_id": "test_douyin_id",
            "avatar_larger": {"url_list": ["http://a/1.jpg", "http://a/2.jpg"]},
        }
    }
    assert _profile_public_fields(payload) == {
        "nickname": "测试昵称",
        "avatar_url": "http://a/2.jpg",
        "douyin_id": "test_douyin_id",
    }
    # 兼容 data.user 包裹与 avatar_thumb 兜底；缺失字段不影响其它字段
    nested = {
        "data": {"user_info": {"nickname": "嵌套昵称", "short_id": "12345"}},
        "status_code": 0,
    }
    assert _profile_public_fields(nested) == {
        "nickname": "嵌套昵称",
        "avatar_url": "",
        "douyin_id": "12345",
    }
    # 资料接口被限流时返回空响应：整体给空串，调用方据此不覆盖已有值
    assert _profile_public_fields({}) == {
        "nickname": "",
        "avatar_url": "",
        "douyin_id": "",
    }


def test_accounts_api_exposes_profile_fields(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证账号列表对外返回抖音昵称、头像、抖音号与同步时间。"""
    base = f"{settings.API_V1_STR}/douyin/accounts"
    suffix = uuid.uuid4().hex[:8]
    created = client.post(
        base,
        headers=superuser_token_headers,
        # 本机模式且不绑定槽位：使用账号独立 Profile，不与其它用例争抢槽位
        json={"name": f"资料账号{suffix}", "browser_mode": "local"},
    )
    assert created.status_code == 201, created.text
    created_body = created.json()
    # 新账号还没同步过资料：字段存在但为空
    assert created_body["nickname"] == ""
    assert created_body["avatar_url"] == ""
    assert created_body["douyin_id"] == ""
    assert created_body["profile_synced_at"] is None

    # 模拟「验证登录」回填本人资料后，列表接口应原样返回
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    account = db.get(DouyinAccount, uuid.UUID(created_body["id"]))
    assert account is not None and account.owner_id == owner.id
    account.nickname = "抖音昵称"
    account.avatar_url = "http://cdn/avatar.jpg"
    account.douyin_id = "douyin_001"
    db.add(account)
    db.commit()

    listing = client.get(f"{base}?limit=100", headers=superuser_token_headers)
    assert listing.status_code == 200
    row = next(
        item for item in listing.json()["data"] if item["id"] == created_body["id"]
    )
    assert row["nickname"] == "抖音昵称"
    assert row["avatar_url"] == "http://cdn/avatar.jpg"
    assert row["douyin_id"] == "douyin_001"

    assert (
        client.delete(
            f"{base}/by-id/{created_body['id']}", headers=superuser_token_headers
        ).status_code
        == 200
    )
