"""抖音作品标签的测试：覆盖话题标签提取（描述文本与抖音元数据）、采集入库时自动打标与按标签筛选作品、历史作品标签回填同步。"""

import json
import uuid

from crawler.bootstrap.settings import settings
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.tags.models import DouyinAwemeTag, DouyinTag
from crawler.business.douyin.tags.service import extract_hashtags
from crawler.business.douyin.tasks.models import CrawlTask, CrawlTaskStatus
from crawler.business.douyin.tasks.persistence import DouyinStorage
from crawler.business.identity.models import User
from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from tests.utils.douyin import default_track_id


def test_extract_hashtags_from_description_and_douyin_metadata() -> None:
    """验证从作品描述与 text_extra 元数据中提取话题标签：去重、保序、大小写合并。"""
    assert extract_hashtags(
        {
            "desc": "今天学习 #FastAPI，顺便看 #Python_开发 #FastAPI",
            "text_extra": [
                {"hashtag_name": "容器化"},
                {"hashtag_name": "python_开发"},
            ],
        }
    ) == ["FastAPI", "Python_开发", "容器化"]


def test_crawl_storage_extracts_tags_and_task_works_can_filter(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证作品入库时按标签建立关联，标签列表含作品/任务统计，且作品列表支持按标签筛选并回显全部标签。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    suffix = uuid.uuid4().hex[:8]
    primary_tag = f"自动标签{suffix}"
    secondary_tag = f"共同标签{suffix}"
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="detail",
        status=CrawlTaskStatus.succeeded.value,
        request_json=json.dumps({"crawl_type": "detail", "video_ids": [suffix]}),
        checkpoint_json='{"version":1,"phase":"completed","position":{}}',
    )
    db.add(task)
    db.commit()
    storage = DouyinStorage(task.id)
    storage._save_aweme_sync(
        {
            "aweme_id": f"tag-aweme-{suffix}",
            "aweme_type": "0",
            "title": f"#{primary_tag} #{secondary_tag}",
            "description": f"#{primary_tag} #{secondary_tag}",
            "create_time": None,
            "creator_hash": "tag-creator",
            "sec_uid": "",
            "nickname": "标签作者",
            "liked_count": 0,
            "collected_count": 0,
            "comment_count": 0,
            "share_count": 0,
            "aweme_url": "",
            "cover_url": "",
            "video_download_url": "",
            "music_download_url": "",
            "note_download_url": "",
            "source_keyword": "detail",
        },
        [primary_tag, secondary_tag],
    )
    db.expire_all()

    listing = client.get(
        f"{settings.API_V1_STR}/douyin/tags/",
        headers=superuser_token_headers,
        params={"task_id": str(task.id), "search": suffix},
    )
    assert listing.status_code == 200
    assert listing.json()["count"] == 2
    tag_rows = {item["name"]: item for item in listing.json()["data"]}
    assert tag_rows[primary_tag]["aweme_count"] == 1
    assert tag_rows[primary_tag]["task_count"] == 1

    filtered = client.get(
        f"{settings.API_V1_STR}/douyin/tasks/{task.id}/works",
        headers=superuser_token_headers,
        params={"tag_id": tag_rows[primary_tag]["id"]},
    )
    assert filtered.status_code == 200
    assert filtered.json()["count"] == 1
    assert {item["name"] for item in filtered.json()["data"][0]["tags"]} == {
        primary_tag,
        secondary_tag,
    }

    db.delete(task)
    for tag in db.exec(
        select(DouyinTag).where(
            DouyinTag.owner_id == owner.id,
            col(DouyinTag.name).in_({primary_tag, secondary_tag}),
        )
    ):
        db.delete(tag)
    db.commit()


def test_sync_endpoint_backfills_historical_aweme_tags(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证标签同步接口为历史作品补建标签与作品-标签关联。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    suffix = uuid.uuid4().hex[:8]
    tag_name = f"历史标签{suffix}"
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="search",
        status=CrawlTaskStatus.succeeded.value,
        request_json='{"crawl_type":"search","keywords":["历史"]}',
        checkpoint_json='{"version":1,"phase":"completed","position":{}}',
    )
    db.add(task)
    db.flush()
    aweme = DouyinAweme(
        task_id=task.id,
        aweme_id=f"history-tag-{suffix}",
        title=f"历史作品 #{tag_name}",
        description=f"历史作品 #{tag_name}",
    )
    db.add(aweme)
    db.commit()

    synced = client.post(
        f"{settings.API_V1_STR}/douyin/tags/sync",
        headers=superuser_token_headers,
    )
    assert synced.status_code == 200
    assert synced.json()["created_count"] >= 1
    tag = db.exec(
        select(DouyinTag).where(
            DouyinTag.owner_id == owner.id,
            DouyinTag.normalized_name == tag_name.casefold(),
        )
    ).one()
    assert db.exec(
        select(DouyinAwemeTag).where(
            DouyinAwemeTag.aweme_record_id == aweme.id,
            DouyinAwemeTag.tag_id == tag.id,
        )
    ).one()

    db.delete(task)
    db.delete(tag)
    db.commit()
