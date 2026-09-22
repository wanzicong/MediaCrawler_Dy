"""内容分类模块的测试：两级分类树 CRUD、视频/达人归类、大类带子类的筛选语义与用户隔离。"""

import uuid

from crawler.bootstrap.settings import settings
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.creators.models import DouyinCreator
from crawler.business.douyin.tasks.models import CrawlTask, CrawlTaskStatus
from crawler.business.identity.models import User
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from tests.utils.douyin import default_track_id


def test_category_tree_crud_assign_and_filters(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证分类树的两级限制、同级去重、视频/达人归类与按分类筛选作品、达人。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    suffix = uuid.uuid4().hex[:8]
    base = f"{settings.API_V1_STR}/douyin/categories"
    headers = superuser_token_headers

    parent = client.post(base, headers=headers, json={"name": f"大类{suffix}"})
    assert parent.status_code == 201, parent.text
    parent_id = parent.json()["id"]
    assert parent.json()["level"] == 1
    assert parent.json()["parent_id"] is None

    child = client.post(
        base,
        headers=headers,
        json={"name": f"子类{suffix}", "parent_id": parent_id},
    )
    assert child.status_code == 201, child.text
    child_id = child.json()["id"]
    assert child.json()["level"] == 2

    # 分类最多两级：子类下不能再建分类
    third = client.post(
        base, headers=headers, json={"name": "三级", "parent_id": child_id}
    )
    assert third.status_code == 422

    # 同级同名冲突
    duplicated = client.post(base, headers=headers, json={"name": f"大类{suffix}"})
    assert duplicated.status_code == 409

    # 造一条作品与一位达人，用于验证归类与筛选
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="detail",
        status=CrawlTaskStatus.succeeded.value,
        request_json='{"crawl_type":"detail"}',
        checkpoint_json='{"version":1,"phase":"completed","position":{}}',
    )
    db.add(task)
    db.flush()
    aweme_id = f"cat-aweme-{suffix}"
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id=aweme_id,
            title=f"分类作品{suffix}",
            creator_hash=f"hash-{suffix}",
            nickname="分类作者",
        )
    )
    creator = DouyinCreator(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        sec_uid=f"sec-{suffix}",
        creator_hash=f"hash-{suffix}",
        nickname=f"分类达人{suffix}",
    )
    db.add(creator)
    db.commit()

    # 视频归到子类，达人归到大类
    assigned_video = client.post(
        f"{base}/{child_id}/items", headers=headers, json={"aweme_ids": [aweme_id]}
    )
    assert assigned_video.status_code == 200, assigned_video.text
    assert assigned_video.json()["video_count"] == 1
    assigned_creator = client.post(
        f"{base}/{parent_id}/items",
        headers=headers,
        json={"creator_ids": [str(creator.id)]},
    )
    assert assigned_creator.status_code == 200, assigned_creator.text
    assert assigned_creator.json()["creator_count"] == 1

    listing = client.get(base, headers=headers)
    assert listing.status_code == 200
    rows = {item["id"]: item for item in listing.json()["data"]}
    assert rows[child_id]["video_count"] == 1
    assert rows[parent_id]["creator_count"] == 1
    assert rows[parent_id]["video_count"] == 0

    def work_ids(category_id: str) -> set[str]:
        """按分类查询作品库并返回命中的平台作品号集合。"""
        response = client.get(
            f"{settings.API_V1_STR}/douyin/library/works",
            headers=headers,
            params={"category_id": category_id, "download_status": "all"},
        )
        assert response.status_code == 200, response.text
        return {item["aweme"]["aweme_id"] for item in response.json()["data"]}

    # 选大类要带出全部子类归类的作品
    assert aweme_id in work_ids(parent_id)
    assert aweme_id in work_ids(child_id)

    empty = client.post(base, headers=headers, json={"name": f"空类{suffix}"})
    empty_id = empty.json()["id"]
    assert work_ids(empty_id) == set()

    creators = client.get(
        f"{settings.API_V1_STR}/douyin/creators/",
        headers=headers,
        params={"category_id": parent_id},
    )
    assert creators.status_code == 200
    assert str(creator.id) in {item["id"] for item in creators.json()["data"]}

    # 移出归类后筛选不再命中
    removed = client.request(
        "DELETE",
        f"{base}/{child_id}/items",
        headers=headers,
        json={"aweme_ids": [aweme_id]},
    )
    assert removed.status_code == 200
    assert removed.json()["video_count"] == 1
    assert aweme_id not in work_ids(parent_id)

    # 删除大类会一并删除子类，但作品与达人本身不受影响
    deleted = client.delete(f"{base}/{parent_id}", headers=headers)
    assert deleted.status_code == 204
    remaining = {
        item["id"] for item in client.get(base, headers=headers).json()["data"]
    }
    assert parent_id not in remaining
    assert child_id not in remaining
    assert (
        db.get(
            DouyinAweme,
            db.exec(
                select(DouyinAweme.id).where(DouyinAweme.aweme_id == aweme_id)
            ).one(),
        )
        is not None
    )
    assert db.get(DouyinCreator, creator.id) is not None

    client.delete(f"{base}/{empty_id}", headers=headers)
    db.delete(creator)
    db.delete(task)
    db.commit()


def test_category_is_isolated_between_users(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    """验证分类是用户私有资产：普通用户的分类不会出现在超管列表里，也不能被超管筛选到。"""
    base = f"{settings.API_V1_STR}/douyin/categories"
    suffix = uuid.uuid4().hex[:8]

    created = client.post(
        base, headers=normal_user_token_headers, json={"name": f"私有分类{suffix}"}
    )
    assert created.status_code == 201, created.text
    private_id = created.json()["id"]

    superuser_view = client.get(base, headers=superuser_token_headers)
    assert superuser_view.status_code == 200
    assert private_id not in {item["id"] for item in superuser_view.json()["data"]}

    # 超管用别人的分类筛选作品时按「分类不存在」处理，而不是越权读取
    filtered = client.get(
        f"{settings.API_V1_STR}/douyin/library/works",
        headers=superuser_token_headers,
        params={"category_id": private_id, "download_status": "all"},
    )
    assert filtered.status_code == 404

    # 本人可以看到并删除自己的分类
    own_view = client.get(base, headers=normal_user_token_headers)
    assert private_id in {item["id"] for item in own_view.json()["data"]}
    assert (
        client.delete(
            f"{base}/{private_id}", headers=normal_user_token_headers
        ).status_code
        == 204
    )
