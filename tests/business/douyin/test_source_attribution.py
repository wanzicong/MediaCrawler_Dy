"""任务、作品与互动列表来源归因的业务测试。"""

import json
import uuid

import pytest
from crawler.bootstrap.settings import settings
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.creators.service import (
    create_creators,
    sync_task_creators_in_session,
)
from crawler.business.douyin.keywords.service import (
    create_keywords,
    sync_task_keywords_in_session,
)
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskStatus,
    DouyinSourceType,
)
from crawler.business.douyin.tasks.query_service import build_tasks_public
from crawler.business.douyin.tasks.source_attribution import (
    build_aweme_source_values,
    list_source_options,
    resolve_source_filter,
)
from crawler.business.errors import InvalidRequestError
from crawler.business.identity.models import User
from sqlmodel import Session, select

from tests.utils.douyin import default_track_id


def test_source_attribution_and_track_scoped_options(db: Session) -> None:
    """验证关键词/作者来源展示、作品归因和赛道限定的来源选项。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    track_id = default_track_id(db, owner_id=owner.id)
    suffix = uuid.uuid4().hex[:8]
    keyword_value = f"来源词-{suffix}"
    keyword, _, _ = create_keywords(
        db,
        owner_id=owner.id,
        values=[keyword_value],
        track_id=track_id,
    )
    sec_uid = f"source-creator-{suffix}"
    creator, _, _ = create_creators(
        db,
        owner_id=owner.id,
        creators=[sec_uid],
        track_id=track_id,
    )
    creator[0].nickname = f"作者-{suffix}"

    keyword_task = CrawlTask(
        owner_id=owner.id,
        track_id=track_id,
        crawl_type="search",
        status=CrawlTaskStatus.succeeded.value,
        request_json=json.dumps({"crawl_type": "search", "keywords": [keyword_value]}),
        checkpoint_json='{"version":1,"phase":"completed"}',
    )
    creator_task = CrawlTask(
        owner_id=owner.id,
        track_id=track_id,
        crawl_type="creator",
        status=CrawlTaskStatus.succeeded.value,
        request_json=json.dumps({"crawl_type": "creator", "creator_ids": [sec_uid]}),
        checkpoint_json='{"version":1,"phase":"completed"}',
    )
    db.add(keyword_task)
    db.add(creator_task)
    db.flush()
    sync_task_keywords_in_session(
        db,
        task_id=keyword_task.id,
        owner_id=owner.id,
        values=[keyword_value],
        track_id=track_id,
    )
    sync_task_creators_in_session(
        db,
        task_id=creator_task.id,
        owner_id=owner.id,
        sec_uids=[sec_uid],
        track_id=track_id,
    )
    keyword_aweme = DouyinAweme(
        task_id=keyword_task.id,
        aweme_id=f"keyword-aweme-{suffix}",
        source_keyword=keyword_value,
    )
    creator_aweme = DouyinAweme(
        task_id=creator_task.id,
        aweme_id=f"creator-aweme-{suffix}",
        creator_hash=creator[0].creator_hash,
        nickname=creator[0].nickname,
    )
    db.add_all([keyword_aweme, creator_aweme])
    db.commit()

    tasks = build_tasks_public(db, tasks=[keyword_task, creator_task])
    assert tasks[0].source_type == DouyinSourceType.keyword
    assert tasks[0].source_label == f"关键词：{keyword_value}"
    assert tasks[1].source_type == DouyinSourceType.creator
    assert tasks[1].source_label == f"作者：作者-{suffix}"

    sources = build_aweme_source_values(db, [keyword_aweme, creator_aweme])
    assert sources[keyword_aweme.id]["source_label"] == f"关键词：{keyword_value}"
    assert sources[creator_aweme.id]["source_label"] == f"作者：作者-{suffix}"

    options = list_source_options(db, owner_id=owner.id, track_id=track_id)
    assert {(item.source_type, item.name) for item in options.data} >= {
        (DouyinSourceType.keyword, keyword_value),
        (DouyinSourceType.creator, f"作者-{suffix}"),
    }
    resolved = resolve_source_filter(
        db,
        owner_id=owner.id,
        track_id=track_id,
        source_type=DouyinSourceType.keyword,
        source_id=keyword[0].id,
    )
    assert resolved is not None
    assert resolved.task_ids == {keyword_task.id}
    with pytest.raises(InvalidRequestError, match="必须先选择赛道"):
        resolve_source_filter(
            db,
            owner_id=owner.id,
            track_id=None,
            source_type=DouyinSourceType.keyword,
            source_id=keyword[0].id,
        )
