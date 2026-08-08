import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskPhase,
    DouyinAccount,
    DouyinAweme,
    DouyinComment,
    DouyinMediaAsset,
    DouyinSubtitle,
    MediaDownloadStatus,
    SubtitleStatus,
    User,
)
from app.services.douyin_tasks import DouyinTaskManager


def test_managed_account_and_pool_crud(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    account_response = client.post(
        f"{settings.API_V1_STR}/douyin/accounts",
        headers=superuser_token_headers,
        json={
            "name": "测试本机账号",
            "browser_mode": "local",
            "daily_task_limit": 12,
        },
    )
    assert account_response.status_code == 201
    account = account_response.json()
    assert account["status"] == "login_required"
    assert "identity_hash" not in account
    assert "profile_key" not in account

    pool_response = client.post(
        f"{settings.API_V1_STR}/douyin/accounts/pools",
        headers=superuser_token_headers,
        json={
            "name": "测试账号池",
            "account_ids": [account["id"]],
            "strategy": "least_loaded",
            "max_parallel_accounts": 1,
        },
    )
    assert pool_response.status_code == 201
    pool = pool_response.json()
    assert [item["id"] for item in pool["accounts"]] == [account["id"]]

    list_response = client.get(
        f"{settings.API_V1_STR}/douyin/accounts/pools",
        headers=superuser_token_headers,
    )
    assert list_response.status_code == 200
    assert any(item["id"] == pool["id"] for item in list_response.json()["data"])

    disabled = client.patch(
        f"{settings.API_V1_STR}/douyin/accounts/by-id/{account['id']}",
        headers=superuser_token_headers,
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"

    assert (
        client.delete(
            f"{settings.API_V1_STR}/douyin/accounts/pools/{pool['id']}",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )
    assert (
        client.delete(
            f"{settings.API_V1_STR}/douyin/accounts/by-id/{account['id']}",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )


def test_task_targets_are_split_across_managed_accounts() -> None:
    owner_id = uuid.uuid4()
    accounts = [
        DouyinAccount(
            owner_id=owner_id,
            name=f"账号 {index}",
            browser_mode="local",
            profile_key=uuid.uuid4().hex,
            identity_hash=uuid.uuid4().hex,
            status="ready",
        )
        for index in range(2)
    ]
    request = CrawlTaskCreate(
        crawl_type="search",
        keywords=["FastAPI", "Python", "SQLModel"],
        max_awemes=9,
        account_ids=[item.id for item in accounts],
    )
    assignments = DouyinTaskManager._split_assignments(request, accounts)
    assert len(assignments) == 2
    assert sum(len(item.keywords) for _, item in assignments) == 3
    assert sum(item.max_awemes for _, item in assignments) == 9
    assert all(not item.download_media for _, item in assignments)


def test_unified_works_sort_time_and_exports(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
        crawl_type="detail",
        status="succeeded",
        request_json='{"crawl_type":"detail","video_ids":["work-a","work-b"]}',
        checkpoint_json=(
            '{"version":1,"phase":"'
            + CrawlTaskPhase.completed.value
            + '","crawl_type":"detail","position":{}}'
        ),
        aweme_count=2,
        comment_count=2,
    )
    db.add(task)
    db.flush()
    first = DouyinAweme(
        task_id=task.id,
        aweme_id="work-a",
        creator_hash="creator-a",
        title="较早作品",
        nickname="甲***者",
        create_time=1_700_000_000,
        liked_count=10,
        comment_count=20,
    )
    second = DouyinAweme(
        task_id=task.id,
        aweme_id="work-b",
        creator_hash="creator-b",
        title="高赞作品",
        nickname="乙***者",
        create_time=1_710_000_000,
        liked_count=999,
        comment_count=3,
    )
    db.add(first)
    db.add(second)
    db.flush()
    db.add(
        DouyinComment(
            task_id=task.id,
            comment_id="comment-a",
            aweme_id=first.aweme_id,
            content="第一条评论",
            nickname="评***者",
            create_time=1_700_000_100,
            like_count=3,
        )
    )
    db.add(
        DouyinComment(
            task_id=task.id,
            comment_id="comment-b",
            aweme_id=first.aweme_id,
            content="第二条评论",
            nickname="另***者",
            create_time=1_700_000_200,
            like_count=9,
        )
    )
    asset = DouyinMediaAsset(
        task_id=task.id,
        aweme_id=first.aweme_id,
        status=MediaDownloadStatus.downloaded.value,
        progress=100,
    )
    db.add(asset)
    db.flush()
    db.add(
        DouyinSubtitle(
            asset_id=asset.id,
            task_id=task.id,
            aweme_id=first.aweme_id,
            status=SubtitleStatus.completed.value,
            progress=100,
            full_text="测试字幕正文",
            segments_json=(
                '[{"start":0.0,"end":1.5,"text":"测试字幕正文"}]'
            ),
        )
    )
    db.commit()

    works = client.get(
        f"{settings.API_V1_STR}/douyin/tasks/{task.id}/works",
        params={"sort_by": "liked_count", "sort_order": "desc"},
        headers=superuser_token_headers,
    )
    assert works.status_code == 200
    payload = works.json()
    assert [row["aweme"]["aweme_id"] for row in payload["data"]] == [
        "work-b",
        "work-a",
    ]
    assert payload["data"][1]["persisted_comment_count"] == 2
    assert payload["data"][1]["aweme"]["create_time"] == 1_700_000_000
    assert payload["data"][1]["media"]["subtitle"]["full_text"] == "测试字幕正文"

    library = client.get(
        f"{settings.API_V1_STR}/douyin/library/works",
        params={
            "task_id": str(task.id),
            "creator_hash": "creator-a",
            "search": "work-a",
            "sort_by": "file_size",
        },
        headers=superuser_token_headers,
    )
    assert library.status_code == 200
    assert library.json()["count"] == 1
    assert library.json()["data"][0]["aweme"]["aweme_id"] == "work-a"

    creators = client.get(
        f"{settings.API_V1_STR}/douyin/library/creators",
        params={"task_id": str(task.id)},
        headers=superuser_token_headers,
    )
    assert creators.status_code == 200
    assert creators.json()["data"][0]["creator_hash"] == "creator-a"
    assert creators.json()["data"][0]["work_count"] == 1

    comments = client.get(
        f"{settings.API_V1_STR}/douyin/tasks/{task.id}/comments",
        params={
            "aweme_id": first.aweme_id,
            "sort_by": "like_count",
            "sort_order": "desc",
        },
        headers=superuser_token_headers,
    )
    assert comments.status_code == 200
    assert [item["like_count"] for item in comments.json()["data"]] == [9, 3]
    assert comments.json()["data"][0]["create_time"] == 1_700_000_200

    comment_export = client.post(
        f"{settings.API_V1_STR}/douyin/tasks/{task.id}/exports/comments",
        headers=superuser_token_headers,
        json={"aweme_ids": [first.aweme_id]},
    )
    assert comment_export.status_code == 200
    assert comment_export.content.startswith(b"\xef\xbb\xbf")
    exported_text = comment_export.content.decode("utf-8-sig")
    assert "第一条评论" in exported_text
    assert "评论时间：2023" in exported_text

    subtitle_export = client.post(
        f"{settings.API_V1_STR}/douyin/tasks/{task.id}/exports/subtitles",
        headers=superuser_token_headers,
        json={"aweme_ids": [first.aweme_id], "format": "srt"},
    )
    assert subtitle_export.status_code == 200
    assert "00:00:00,000 --> 00:00:01,500" in subtitle_export.text
    assert "测试字幕正文" in subtitle_export.text

    db.delete(task)
    db.commit()
