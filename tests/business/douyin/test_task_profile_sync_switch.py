"""任务级「采集后补齐达人主页信息」开关的回归测试。"""

import uuid

from crawler.bootstrap.settings import settings
from crawler.business.douyin.creators.models import DouyinCreator
from crawler.business.douyin.creators.profile_sync import sync_creators_of_task
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskStatus,
    DouyinCrawlType,
)
from crawler.business.identity.models import User
from sqlmodel import Session, select

from tests.utils.douyin import default_track_id


def test_sync_creator_profiles_defaults_to_off() -> None:
    """验证开关默认关闭：不勾选时请求体不带该行为。"""
    request = CrawlTaskCreate(crawl_type=DouyinCrawlType.search, keywords=["测试"])
    assert request.sync_creator_profiles is False
    assert (
        CrawlTaskCreate(
            crawl_type=DouyinCrawlType.search,
            keywords=["测试"],
            sync_creator_profiles=True,
        ).sync_creator_profiles
        is True
    )


def test_sync_creators_of_task_only_targets_missing_profiles(db: Session) -> None:
    """验证任务级补齐只挑「未同步过」的达人，且没有目标时不做任何请求。"""
    import asyncio

    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    suffix = uuid.uuid4().hex[:8]
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type=DouyinCrawlType.creator.value,
        status=CrawlTaskStatus.succeeded.value,
        request_json='{"crawl_type":"creator"}',
        checkpoint_json='{"version":1,"phase":"completed","position":{}}',
    )
    db.add(task)
    db.flush()
    # 任务里没有任何达人 → 直接返回 0，不会去连抖音
    assert (
        asyncio.run(
            sync_creators_of_task(task_id=task.id, owner_id=owner.id, batch_size=10)
        )
        == 0
    )

    # 挂一位已经同步过的达人：同样不应成为目标
    creator = DouyinCreator(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        sec_uid=f"MS4wLjABAAAA-{suffix}",
        creator_hash=f"hash-{suffix}",
        nickname="已同步达人",
    )
    db.add(creator)
    db.commit()
    from crawler.business.douyin.creators.models import DouyinCreatorTaskLink

    db.add(DouyinCreatorTaskLink(creator_id=creator.id, task_id=task.id))
    creator.profile_synced_at = creator.created_at
    db.add(creator)
    db.commit()
    assert (
        asyncio.run(
            sync_creators_of_task(task_id=task.id, owner_id=owner.id, batch_size=10)
        )
        == 0
    )

    db.delete(task)
    db.delete(creator)
    db.commit()
