"""本机浏览器实例管理的测试：默认槽位物化、页面上扩容/删除、账号多绑定与占用约束。"""

import uuid

from crawler.bootstrap.settings import settings
from fastapi.testclient import TestClient


def test_local_browser_instances_crud_and_multi_binding(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证默认 4 个本机浏览器、页面扩容、账号多绑定，以及占用时禁止删除。"""
    base = f"{settings.API_V1_STR}/douyin/accounts"
    headers = superuser_token_headers

    # 首次访问物化默认槽位（DOUYIN_LOCAL_CDP_SLOT_COUNT 默认 4）
    listing = client.get(f"{base}/local-browsers", headers=headers)
    assert listing.status_code == 200, listing.text
    initial = listing.json()["data"]
    # 默认槽位必须齐全；同库中可能已存在其它用例新增的实例，因此取前缀断言
    assert listing.json()["count"] >= settings.DOUYIN_LOCAL_CDP_SLOT_COUNT
    assert [item["name"] for item in initial][
        : settings.DOUYIN_LOCAL_CDP_SLOT_COUNT
    ] == [
        f"local-{index}" for index in range(1, settings.DOUYIN_LOCAL_CDP_SLOT_COUNT + 1)
    ]
    assert all(item["port"] > 0 for item in initial)

    # 页面上扩容：服务端按下一个空闲序号分配槽位名与端口
    created = client.post(
        f"{base}/local-browsers", headers=headers, json={"label": "扩展浏览器"}
    )
    assert created.status_code == 201, created.text
    extra = created.json()
    # 槽位名按下一个空闲序号分配，且不与既有实例重名
    taken = {item["name"] for item in initial}
    assert extra["name"].startswith("local-")
    assert extra["name"] not in taken
    assert extra["label"] == "扩展浏览器"

    suffix = uuid.uuid4().hex[:8]
    account = client.post(
        f"{base}",
        headers=headers,
        json={
            "name": f"多绑定账号{suffix}",
            "browser_mode": "local",
            "slot": "local-1",
        },
    )
    assert account.status_code == 201, account.text
    account_id = account.json()["id"]

    # 一个账号可以绑定多个本机浏览器（首个为主槽位）
    bound = client.put(
        f"{base}/by-id/{account_id}/local-browsers",
        headers=headers,
        json={"slot_names": ["local-1", extra["name"]]},
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["slot_names"] == ["local-1", extra["name"]]
    fetched = client.get(f"{base}/by-id/{account_id}/local-browsers", headers=headers)
    assert fetched.json()["slot_names"] == ["local-1", extra["name"]]

    # 被绑定的实例不允许删除
    blocked = client.delete(f"{base}/local-browsers/{extra['id']}", headers=headers)
    assert blocked.status_code == 409, blocked.text

    # 同一槽位不能被第二个账号抢占
    other = client.post(
        f"{base}",
        headers=headers,
        json={"name": f"抢占账号{suffix}", "browser_mode": "local", "slot": "local-1"},
    )
    assert other.status_code == 422, other.text

    # 解绑后即可删除
    assert (
        client.put(
            f"{base}/by-id/{account_id}/local-browsers",
            headers=headers,
            json={"slot_names": []},
        ).status_code
        == 200
    )
    removed = client.delete(f"{base}/local-browsers/{extra['id']}", headers=headers)
    assert removed.status_code == 200, removed.text

    # 清理：删除测试账号，避免影响其它用例的槽位占用统计
    assert (
        client.delete(f"{base}/by-id/{account_id}", headers=headers).status_code == 200
    )
    assert (
        client.delete(
            f"{base}/local-browsers/{extra['id']}", headers=headers
        ).status_code
        == 404
    )
