"""评论导出不再有人为条数上限的回归测试。"""

import uuid

from crawler.bootstrap.settings import settings
from crawler.business.douyin.comments.models import DouyinComment
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.tasks.models import CrawlTask, CrawlTaskStatus
from crawler.business.identity.models import User
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from tests.utils.douyin import default_track_id


def test_selection_export_accepts_more_than_old_500_cap(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证「导出已选」不再受 500 条限制：一次导出 600 条评论也能成功。

    背景：导出请求体的 comment_ids 曾限制 1~500，用户勾选超过 500 条会被后端
    422 拒绝，看起来就是「导出有上限」。
    """
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    suffix = uuid.uuid4().hex[:8]
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
    aweme_id = f"export-aweme-{suffix}"
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id=aweme_id,
            title=f"导出用例{suffix}",
            creator_hash=f"hash-{suffix}",
            nickname="导出作者",
        )
    )
    comments: list[DouyinComment] = []
    for index in range(600):
        comments.append(
            DouyinComment(
                task_id=task.id,
                aweme_id=aweme_id,
                comment_id=f"c-{suffix}-{index}",
                content=f"第 {index} 条评论",
                user_nickname="导出用户",
            )
        )
    db.add_all(comments)
    db.commit()

    exported = client.post(
        f"{settings.API_V1_STR}/douyin/comments/export",
        headers=superuser_token_headers,
        json={"comment_ids": [str(item.id) for item in comments]},
    )
    assert exported.status_code == 200, exported.text
    assert "第 599 条评论" in exported.text
    assert exported.headers["content-type"].startswith("text/plain")

    db.delete(task)
    db.commit()
