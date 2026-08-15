import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import (
    CrawlTask,
    CrawlTaskStatus,
    DouyinAweme,
    DouyinComment,
    UserCreate,
)
from tests.utils.douyin import default_track_id
from tests.utils.utils import random_email, random_lower_string


def _task(db: Session, owner_id: uuid.UUID, keyword: str) -> CrawlTask:
    return CrawlTask(
        owner_id=owner_id,
        track_id=default_track_id(db, owner_id=owner_id),
        crawl_type="search",
        status=CrawlTaskStatus.succeeded.value,
        request_json=f'{{"keywords":["{keyword}"]}}',
        created_at=datetime.now(timezone.utc),
    )


def test_comment_library_filters_sorts_and_summarizes(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    owner = crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=random_lower_string()),
    )
    task = _task(db, owner.id, "露营")
    db.add(task)
    db.flush()
    aweme = DouyinAweme(
        task_id=task.id,
        aweme_id="library-video-1",
        title="海边露营攻略",
        nickname="露营作者",
        source_keyword="露营",
        create_time=1_710_000_000,
    )
    db.add(aweme)
    db.flush()
    top_level = DouyinComment(
        task_id=task.id,
        comment_id="library-comment-top",
        aweme_id=aweme.aweme_id,
        content="这个帐篷真的很好用",
        nickname="户外玩家",
        create_time=1_710_000_100,
        like_count=28,
        sub_comment_count=2,
        pictures="https://example.invalid/comment.jpg",
    )
    reply = DouyinComment(
        task_id=task.id,
        comment_id="library-comment-reply",
        aweme_id=aweme.aweme_id,
        parent_comment_id=top_level.comment_id,
        content="请问是什么型号",
        nickname="提问者",
        create_time=1_710_000_200,
        like_count=4,
    )
    db.add(top_level)
    db.add(reply)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/douyin/comments",
        params={
            "search": "帐篷",
            "video_creator": "露营作者",
            "source_keyword": "露营",
            "comment_type": "top_level",
            "has_pictures": "yes",
            "min_likes": 20,
            "published_from": 1_710_000_000,
            "published_to": 1_710_000_300,
            "sort_by": "like_count",
            "sort_order": "desc",
        },
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["data"][0]["comment"]["comment_id"] == top_level.comment_id
    assert payload["data"][0]["aweme"]["title"] == "海边露营攻略"
    assert payload["data"][0]["task_status"] == "succeeded"
    assert payload["summary"] == {
        "matched_count": 1,
        "top_level_count": 1,
        "reply_count": 0,
        "picture_count": 1,
        "total_like_count": 28,
    }

    content_match = client.get(
        f"{settings.API_V1_STR}/douyin/comments",
        params={"comment_content": "帐篷真的"},
        headers=superuser_token_headers,
    )
    assert content_match.status_code == 200
    assert content_match.json()["count"] == 1
    assert (
        content_match.json()["data"][0]["comment"]["comment_id"]
        == top_level.comment_id
    )

    title_only_match = client.get(
        f"{settings.API_V1_STR}/douyin/comments",
        params={"comment_content": "海边露营攻略"},
        headers=superuser_token_headers,
    )
    assert title_only_match.status_code == 200
    assert title_only_match.json()["count"] == 0

    invalid = client.get(
        f"{settings.API_V1_STR}/douyin/comments",
        params={"min_likes": 10, "max_likes": 2},
        headers=superuser_token_headers,
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "最小点赞数不能大于最大点赞数"

    db.delete(task)
    db.delete(owner)
    db.commit()


def test_comment_library_enforces_ownership_and_exports_selection(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    current_user = crud.get_user_by_email(session=db, email=settings.EMAIL_TEST_USER)
    assert current_user is not None
    other = crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=random_lower_string()),
    )
    own_task = _task(db, current_user.id, "自己的任务")
    other_task = _task(db, other.id, "其他人的任务")
    db.add(own_task)
    db.add(other_task)
    db.flush()
    own_aweme = DouyinAweme(
        task_id=own_task.id,
        aweme_id="owned-video",
        title="自己的视频",
        nickname="自己的作者",
    )
    other_aweme = DouyinAweme(
        task_id=other_task.id,
        aweme_id="hidden-video",
        title="不可见视频",
        nickname="其他作者",
    )
    db.add(own_aweme)
    db.add(other_aweme)
    db.flush()
    own_comment = DouyinComment(
        task_id=own_task.id,
        comment_id="owned-comment",
        aweme_id=own_aweme.aweme_id,
        content="可以导出的评论",
        nickname="自己的评论人",
        like_count=7,
    )
    other_comment = DouyinComment(
        task_id=other_task.id,
        comment_id="hidden-comment",
        aweme_id=other_aweme.aweme_id,
        content="不能看到的评论",
        nickname="其他评论人",
    )
    db.add(own_comment)
    db.add(other_comment)
    db.commit()

    listing = client.get(
        f"{settings.API_V1_STR}/douyin/comments",
        headers=normal_user_token_headers,
    )
    assert listing.status_code == 200
    ids = {item["comment"]["id"] for item in listing.json()["data"]}
    assert str(own_comment.id) in ids
    assert str(other_comment.id) not in ids

    exported = client.post(
        f"{settings.API_V1_STR}/douyin/comments/export",
        headers=normal_user_token_headers,
        json={"comment_ids": [str(own_comment.id), str(other_comment.id)]},
    )
    assert exported.status_code == 200
    assert exported.content.startswith(b"\xef\xbb\xbf")
    text = exported.content.decode("utf-8-sig")
    assert "可以导出的评论" in text
    assert "不能看到的评论" not in text
    assert "https://www.douyin.com/video/owned-video" in text

    db.delete(own_task)
    db.delete(other_task)
    db.delete(other)
    db.commit()
