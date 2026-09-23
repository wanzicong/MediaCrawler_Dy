"""「我的」模块读侧接口的回归测试。"""

import uuid

from crawler.bootstrap.settings import settings
from fastapi.testclient import TestClient


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
