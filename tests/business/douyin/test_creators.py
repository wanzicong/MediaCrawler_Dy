"""抖音达人名单的服务层测试：覆盖达人状态推导、创建去重与赛道归属、
任务同步绑定、公开模型统计（任务/作品）、任务落库自动绑定达人、
基于达人批量建任务，以及从历史作品导入/补全占位达人。"""

import asyncio
import json
import uuid

import pytest
from crawler.bootstrap.settings import settings
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.creators.models import (
    DouyinCreator,
    DouyinCreatorBatchTaskRequest,
    DouyinCreatorTaskLink,
)
from crawler.business.douyin.creators.service import (
    CreatorConflictError,
    CreatorValidationError,
    _status_for,
    build_creator_public_rows,
    create_creator_crawl_tasks,
    create_creators,
    edit_creator_record,
    import_aweme_creators,
    sync_task_creators_in_session,
)
from crawler.business.douyin.library.service import list_library_works
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskStatus,
)
from crawler.business.douyin.tasks.persistence import DouyinStorage
from crawler.business.douyin.tasks.query_service import build_tasks_public
from crawler.business.douyin.tasks.service import task_manager
from crawler.business.douyin.tracks.models import DouyinTrack
from crawler.business.douyin.tracks.service import create_track
from crawler.business.identity.models import User
from crawler.douyin_client.privacy import anonymize_user_id
from pytest import MonkeyPatch
from sqlmodel import Session, delete, select

from tests.utils.douyin import default_track_id


def test_creator_status_prioritizes_active_recrawl() -> None:
    """验证达人状态推导：存在进行中的重采任务时优先标记为 active 而非 succeeded。"""
    owner_id = uuid.uuid4()
    track_id = uuid.uuid4()
    tasks = [
        CrawlTask(
            owner_id=owner_id,
            track_id=track_id,
            crawl_type="creator",
            status=CrawlTaskStatus.succeeded.value,
            request_json="{}",
            checkpoint_json="{}",
        ),
        CrawlTask(
            owner_id=owner_id,
            track_id=track_id,
            crawl_type="creator",
            status=CrawlTaskStatus.running.value,
            request_json="{}",
            checkpoint_json="{}",
        ),
    ]

    assert _status_for(tasks).value == "active"


def test_creator_service_create_dedupe_and_track(db: Session) -> None:
    """验证达人批量创建：主页链接与 sec_uid 解析去重、脱敏哈希落库、赛道归属与移动。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    track = default_track_id(db, owner_id=owner.id)
    sec_uid = f"MS{uuid.uuid4().hex}"
    link = f"https://www.douyin.com/user/{sec_uid}"

    creators, created, existing = create_creators(
        db, owner_id=owner.id, creators=[link, sec_uid], track_id=track
    )
    assert created == 1
    assert existing == 0
    assert len(creators) == 1
    creator = creators[0]
    assert creator.sec_uid == sec_uid
    assert creator.creator_hash == anonymize_user_id(sec_uid)
    assert creator.track_id == track
    assert creator.enabled is True

    creators, created, existing = create_creators(
        db, owner_id=owner.id, creators=[sec_uid], track_id=track
    )
    assert created == 0
    assert existing == 1
    assert creators[0].id == creator.id

    other_track = db.exec(
        select(DouyinTrack).where(
            DouyinTrack.owner_id == owner.id,
            DouyinTrack.id != track,
        )
    ).first()
    if other_track is not None and other_track.id != track:
        creators, created, _ = create_creators(
            db,
            owner_id=owner.id,
            creators=[sec_uid],
            track_id=other_track.id,
        )
        assert created == 0
        assert creators[0].track_id == other_track.id
        creators, _, _ = create_creators(
            db,
            owner_id=owner.id,
            creators=[sec_uid],
            track_id=track,
            move_existing=False,
        )
        assert creators[0].track_id == other_track.id

    db.delete(creator)
    db.commit()


def test_creator_sync_bindings_and_public_rows(db: Session) -> None:
    """验证任务同步绑定：create-or-reuse 达人、建 link、状态推导与任务/作品统计。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    track = default_track_id(db, owner_id=owner.id)
    sec_uid = f"MC{uuid.uuid4().hex}"

    creators, created, _ = create_creators(
        db, owner_id=owner.id, creators=[sec_uid], track_id=track
    )
    assert created == 1
    creator = creators[0]

    task = CrawlTask(
        owner_id=owner.id,
        track_id=track,
        crawl_type="creator",
        status=CrawlTaskStatus.succeeded.value,
        request_json=json.dumps({"crawl_type": "creator", "creator_ids": [sec_uid]}),
        checkpoint_json='{"version":1,"phase":"completed","position":{}}',
    )
    db.add(task)
    db.flush()
    created_n, bound = sync_task_creators_in_session(
        db,
        task_id=task.id,
        owner_id=owner.id,
        sec_uids=[sec_uid],
        track_id=track,
    )
    assert created_n == 0
    assert bound == 1
    link = db.exec(
        select(DouyinCreatorTaskLink).where(
            DouyinCreatorTaskLink.creator_id == creator.id,
            DouyinCreatorTaskLink.task_id == task.id,
        )
    ).one()
    assert link.source == "automatic"

    aweme_id = f"creator-work-{uuid.uuid4().hex[:8]}"
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id=aweme_id,
            title="达人作品",
            sec_uid=creator.creator_hash,
        )
    )
    db.commit()

    rows = build_creator_public_rows(db, owner_id=owner.id, track_id=track)
    row = next(item for item in rows if item.sec_uid == sec_uid)
    assert row.task_count == 1
    assert row.success_task_count == 1
    assert row.failed_task_count == 0
    assert row.aweme_count == 1
    assert row.status.value == "crawled"
    assert row.last_task_id == task.id
    assert row.last_task_status == CrawlTaskStatus.succeeded

    public = build_tasks_public(db, tasks=[db.get(CrawlTask, task.id)])
    assert public[0].creator_names == ["未命名达人"]

    moved_track = create_track(
        db,
        owner_id=owner.id,
        name=f"达人移动赛道-{uuid.uuid4().hex[:8]}",
        description="",
        prompt="",
        keywords=[],
    )
    moved = edit_creator_record(
        db,
        creator_id=creator.id,
        actor_id=owner.id,
        is_superuser=True,
        nickname=None,
        track_id=moved_track.id,
        enabled=None,
        notes=None,
    )
    assert moved.task_count == 1
    assert moved.aweme_count == 1
    moved_works = list_library_works(
        db,
        owner_id=owner.id,
        search=None,
        task_id=None,
        track_id=moved_track.id,
        creator_hash=None,
        tag_id=None,
        download_status="all",
        subtitle_status="all",
        storage_backend="all",
        sort_by="fetched_at",
        sort_order="desc",
        skip=0,
        limit=10,
    )
    original_works = list_library_works(
        db,
        owner_id=owner.id,
        search=None,
        task_id=None,
        track_id=track,
        creator_hash=None,
        tag_id=None,
        download_status="all",
        subtitle_status="all",
        storage_backend="all",
        sort_by="fetched_at",
        sort_order="desc",
        skip=0,
        limit=10,
    )
    assert any(item.aweme.aweme_id == aweme_id for item in moved_works.data)
    assert all(item.aweme.aweme_id != aweme_id for item in original_works.data)

    db.delete(task)
    db.delete(creator)
    db.delete(moved_track)
    db.commit()


def test_task_storage_auto_binds_creators(db: Session) -> None:
    """验证任务落库时自动创建缺失达人并建立 automatic 来源的任务-达人关联。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    sec_uid = f"MA{uuid.uuid4().hex}"
    from crawler.business.douyin.tasks.persistence import DouyinStorage

    task = DouyinStorage._create_task_sync(
        owner.id,
        CrawlTaskCreate(
            crawl_type="creator", creator_ids=[sec_uid], fetch_comments=False
        ),
    )
    db.expire_all()
    creator = db.exec(
        select(DouyinCreator).where(
            DouyinCreator.owner_id == owner.id,
            DouyinCreator.sec_uid == sec_uid,
        )
    ).one()
    link = db.exec(
        select(DouyinCreatorTaskLink).where(
            DouyinCreatorTaskLink.creator_id == creator.id,
            DouyinCreatorTaskLink.task_id == task.id,
        )
    ).one()
    assert link.source == "automatic"
    db.delete(db.get(CrawlTask, task.id))
    db.delete(creator)
    db.commit()


def test_creator_batch_task_creation(db: Session, monkeypatch: MonkeyPatch) -> None:
    """验证按达人批量发起采集任务：每人一个独立任务、sec_uid 完整透传且归属赛道已解析。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    track = default_track_id(db, owner_id=owner.id)
    sec_uids = [f"MB{uuid.uuid4().hex}", f"MB{uuid.uuid4().hex}"]
    creators, created, _ = create_creators(
        db, owner_id=owner.id, creators=sec_uids, track_id=track
    )
    assert created == 2
    requests: list[CrawlTaskCreate] = []

    async def fake_create(
        *, owner_id: uuid.UUID, request: CrawlTaskCreate
    ) -> CrawlTask:
        """模拟任务创建：捕获请求并返回一条排队中的任务记录（不入库）。"""
        assert owner_id == owner.id
        assert request.track_id is not None
        requests.append(request)
        return CrawlTask(
            owner_id=owner_id,
            track_id=request.track_id,
            crawl_type="creator",
            status="queued",
            request_json=json.dumps(request.public_request(), ensure_ascii=False),
            checkpoint_json='{"version":1,"phase":"crawl","position":{}}',
        )

    monkeypatch.setattr(task_manager, "create", fake_create)
    result = asyncio.run(
        create_creator_crawl_tasks(
            db,
            owner_id=owner.id,
            request=DouyinCreatorBatchTaskRequest(
                creator_ids=[creators[0].id, creators[1].id],
                max_awemes=30,
                fetch_comments=False,
            ),
        )
    )
    assert result.count == 2
    assert len(requests) == 2
    assert {item.creator_ids[0] for item in requests} == set(sec_uids)
    assert all(item.crawl_type.value == "creator" for item in requests)
    assert all(item.max_awemes == 30 for item in requests)
    assert all(item.fetch_comments is False for item in requests)
    assert all(item.track_id == track for item in requests)

    for creator in creators:
        db.delete(creator)
    db.commit()


def test_import_aweme_creators_aggregates_placeholders(db: Session) -> None:
    """验证从历史作品导入占位达人：按赛道×哈希聚合、跨赛道归作品最多、已有达人跳过。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    # 建立基线：历史作品哈希全部导入为占位达人，使本次计数只反映测试新增
    import_aweme_creators(db, owner_id=owner.id)
    track = default_track_id(db, owner_id=owner.id)
    other_track = create_track(
        db,
        owner_id=owner.id,
        name=f"导入赛道-{uuid.uuid4().hex[:8]}",
        description="",
        prompt="",
        keywords=[],
    ).id
    existing_uid = f"ME{uuid.uuid4().hex}"
    create_creators(db, owner_id=owner.id, creators=[existing_uid], track_id=track)
    db.commit()
    hash_existing = anonymize_user_id(existing_uid)
    hash_a = anonymize_user_id(f"MF{uuid.uuid4().hex}")
    hash_b = anonymize_user_id(f"MG{uuid.uuid4().hex}")

    def _task(track_id: uuid.UUID) -> CrawlTask:
        task = CrawlTask(
            owner_id=owner.id,
            track_id=track_id,
            crawl_type="creator",
            status=CrawlTaskStatus.succeeded.value,
            request_json="{}",
            checkpoint_json="{}",
        )
        db.add(task)
        db.flush()
        return task

    task_a = _task(track)
    task_b = _task(track)
    task_c = _task(other_track)
    db.add_all(
        [
            DouyinAweme(
                task_id=task_a.id,
                aweme_id="ph-a1",
                title="",
                sec_uid=hash_a,
                nickname="尘***客",
            ),
            DouyinAweme(
                task_id=task_a.id,
                aweme_id="ph-a2",
                title="",
                sec_uid=hash_a,
                nickname="尘***客",
            ),
            DouyinAweme(
                task_id=task_b.id,
                aweme_id="ph-b1",
                title="",
                sec_uid=hash_b,
                nickname="鲁***魔",
            ),
            DouyinAweme(
                task_id=task_c.id,
                aweme_id="ph-c1",
                title="",
                sec_uid=hash_a,
                nickname="尘***客",
            ),
            DouyinAweme(
                task_id=task_c.id,
                aweme_id="ph-c2",
                title="",
                sec_uid=hash_a,
                nickname="尘***客",
            ),
            DouyinAweme(
                task_id=task_c.id,
                aweme_id="ph-c3",
                title="",
                sec_uid=hash_a,
                nickname="尘***客",
            ),
            DouyinAweme(
                task_id=task_b.id,
                aweme_id="ph-b2",
                title="",
                sec_uid=hash_existing,
                nickname="已存在",
            ),
        ]
    )
    db.commit()

    result = import_aweme_creators(db, owner_id=owner.id)
    assert result.created_count == 2  # 库中可能还有其他历史作品，只看本次新建
    assert result.existing_count == result.total_count - 2

    placeholders = {
        item.creator_hash: item
        for item in db.exec(
            select(DouyinCreator).where(
                DouyinCreator.owner_id == owner.id,
                DouyinCreator.is_placeholder.is_(True),
            )
        ).all()
    }
    ph_a = placeholders[hash_a]
    assert ph_a.sec_uid == hash_a  # 占位时 sec_uid 暂存脱敏哈希
    assert ph_a.track_id == other_track  # 跨赛道归作品数最多的赛道
    assert ph_a.nickname == "尘***客"
    assert ph_a.enabled is True
    ph_b = placeholders[hash_b]
    assert ph_b.track_id == track
    assert ph_b.nickname == "鲁***魔"
    existing = db.exec(
        select(DouyinCreator).where(
            DouyinCreator.owner_id == owner.id,
            DouyinCreator.sec_uid == existing_uid,
        )
    ).one()
    assert existing.is_placeholder is False  # 名单中已有该达人，跳过

    for aweme in [task_a, task_b, task_c]:
        db.delete(db.get(CrawlTask, aweme.id))
    for row in [ph_a, ph_b, existing]:
        db.delete(row)
    db.exec(
        delete(DouyinCreator).where(
            DouyinCreator.owner_id == owner.id,
            DouyinCreator.is_placeholder.is_(True),
        )
    )
    db.delete(db.get(DouyinTrack, other_track))
    db.commit()


def test_import_aweme_creators_real_sec_uid_creates_formal(db: Session) -> None:
    """验证带真实标识的新采集作品：直接创建正式达人、已有占位升级转正、再次导入跳过。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    # 建立基线：历史作品哈希全部导入为占位达人
    import_aweme_creators(db, owner_id=owner.id)
    track = default_track_id(db, owner_id=owner.id)
    raw_a = f"MR1{uuid.uuid4().hex}"
    raw_b = f"MR2{uuid.uuid4().hex}"
    hash_a = anonymize_user_id(raw_a)
    hash_b = anonymize_user_id(raw_b)
    # 模拟：hash_b 的历史作品先以占位导入，之后才采集到真实标识
    placeholder = DouyinCreator(
        owner_id=owner.id,
        track_id=track,
        sec_uid=hash_b,
        creator_hash=hash_b,
        nickname="旧占位",
        enabled=True,
        is_placeholder=True,
    )
    db.add(placeholder)
    db.commit()

    task = CrawlTask(
        owner_id=owner.id,
        track_id=track,
        crawl_type="creator",
        status=CrawlTaskStatus.succeeded.value,
        request_json="{}",
        checkpoint_json="{}",
    )
    db.add(task)
    db.flush()
    db.add_all(
        [
            DouyinAweme(
                task_id=task.id,
                aweme_id="real-a1",
                title="",
                sec_uid=hash_a,
                nickname="真实甲",
                creator_real_sec_uid=raw_a,
            ),
            DouyinAweme(
                task_id=task.id,
                aweme_id="real-b1",
                title="",
                sec_uid=hash_b,
                nickname="真实乙",
                creator_real_sec_uid=raw_b,
            ),
        ]
    )
    db.commit()

    result = import_aweme_creators(db, owner_id=owner.id)
    assert result.created_count == 2
    assert result.existing_count == result.total_count - 2

    formal_a = db.exec(
        select(DouyinCreator).where(
            DouyinCreator.owner_id == owner.id,
            DouyinCreator.sec_uid == raw_a,
        )
    ).one()
    assert formal_a.is_placeholder is False
    assert formal_a.creator_hash == hash_a
    assert formal_a.nickname == "真实甲"
    # 占位升级为正式：sec_uid 换成真实标识、标记解除
    db.expire_all()
    upgraded = db.get(DouyinCreator, placeholder.id)
    assert upgraded.sec_uid == raw_b
    assert upgraded.is_placeholder is False
    assert upgraded.nickname == "真实乙"
    assert "待补全" not in upgraded.notes  # 升级后备注不再提示补全

    # 再次导入全部跳过
    again = import_aweme_creators(db, owner_id=owner.id)
    assert again.created_count == 0
    assert again.existing_count == again.total_count

    db.delete(db.get(CrawlTask, task.id))
    for row in db.exec(
        select(DouyinCreator).where(DouyinCreator.owner_id == owner.id)
    ).all():
        db.delete(row)
    db.commit()


def test_complete_placeholder_creator_validation(db: Session) -> None:
    """验证补全占位达人：哈希匹配转正、不匹配拒绝、非占位拒绝、主页占用冲突。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    track = default_track_id(db, owner_id=owner.id)
    real_uid = f"MH{uuid.uuid4().hex}"
    creator = DouyinCreator(
        owner_id=owner.id,
        track_id=track,
        sec_uid=anonymize_user_id(real_uid),
        creator_hash=anonymize_user_id(real_uid),
        nickname="尘***客",
        enabled=True,
        is_placeholder=True,
        notes="由历史采集作品自动导入，待补全主页链接",
    )
    db.add(creator)
    db.commit()

    # 用户实际粘贴的是主页链接，链接需被解析为 sec_user_id 后再做哈希校验
    updated = edit_creator_record(
        db,
        creator_id=creator.id,
        actor_id=owner.id,
        is_superuser=True,
        nickname=None,
        track_id=None,
        enabled=None,
        notes=None,
        sec_uid=f"https://www.douyin.com/user/{real_uid}",
    )
    assert updated.is_placeholder is False
    assert updated.sec_uid == real_uid
    assert updated.nickname == "尘***客"  # 昵称/备注保持不变
    db.expire_all()
    row = db.get(DouyinCreator, creator.id)
    assert row.is_placeholder is False
    assert row.sec_uid == real_uid

    # 补全链接与历史哈希不一致 → 拒绝
    bad = DouyinCreator(
        owner_id=owner.id,
        track_id=track,
        sec_uid=anonymize_user_id(f"MI{uuid.uuid4().hex}"),
        creator_hash=anonymize_user_id(f"MI{uuid.uuid4().hex}"),
        nickname="错误哈希",
        enabled=True,
        is_placeholder=True,
    )
    db.add(bad)
    db.commit()
    with pytest.raises(CreatorValidationError, match="不匹配"):
        edit_creator_record(
            db,
            creator_id=bad.id,
            actor_id=owner.id,
            is_superuser=True,
            nickname=None,
            track_id=None,
            enabled=None,
            notes=None,
            sec_uid=f"MJ{uuid.uuid4().hex}",
        )

    # 非占位达人传 sec_uid → 拒绝
    with pytest.raises(CreatorValidationError, match="不是待补全状态"):
        edit_creator_record(
            db,
            creator_id=creator.id,
            actor_id=owner.id,
            is_superuser=True,
            nickname=None,
            track_id=None,
            enabled=None,
            notes=None,
            sec_uid=f"MK{uuid.uuid4().hex}",
        )

    # 补全主页已被其他达人占用 → 冲突
    other_uid = f"MM{uuid.uuid4().hex}"
    other = DouyinCreator(
        owner_id=owner.id,
        track_id=track,
        sec_uid=other_uid,
        creator_hash=anonymize_user_id(other_uid),
        nickname="占用人",
        enabled=True,
    )
    db.add(other)
    db.commit()
    conflict = DouyinCreator(
        owner_id=owner.id,
        track_id=track,
        sec_uid=anonymize_user_id(other_uid),
        creator_hash=anonymize_user_id(other_uid),
        nickname="同名占位",
        enabled=True,
        is_placeholder=True,
    )
    db.add(conflict)
    db.commit()
    with pytest.raises(CreatorConflictError, match="已存在"):
        edit_creator_record(
            db,
            creator_id=conflict.id,
            actor_id=owner.id,
            is_superuser=True,
            nickname=None,
            track_id=None,
            enabled=None,
            notes=None,
            sec_uid=other_uid,
        )

    for row in [creator, bad, other, conflict]:
        db.delete(row)
    db.commit()


def test_import_aweme_creators_task_id_scoped(db: Session) -> None:
    """验证 task_id 限定时只聚合该任务的作品，不影响其他任务与全量模式。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    track = default_track_id(db, owner_id=owner.id)
    raw_a = f"MS1{uuid.uuid4().hex}"
    raw_b = f"MS2{uuid.uuid4().hex}"
    hash_a = anonymize_user_id(raw_a)
    hash_b = anonymize_user_id(raw_b)

    def _task() -> CrawlTask:
        task = CrawlTask(
            owner_id=owner.id,
            track_id=track,
            crawl_type="search",
            status=CrawlTaskStatus.succeeded.value,
            request_json="{}",
            checkpoint_json="{}",
        )
        db.add(task)
        db.flush()
        return task

    task_x = _task()
    task_y = _task()
    db.add_all(
        [
            DouyinAweme(
                task_id=task_x.id,
                aweme_id="sc-a1",
                title="",
                sec_uid=hash_a,
                nickname="任务甲",
                creator_real_sec_uid=raw_a,
            ),
            DouyinAweme(
                task_id=task_y.id,
                aweme_id="sc-b1",
                title="",
                sec_uid=hash_b,
                nickname="任务乙",
                creator_real_sec_uid=raw_b,
            ),
        ]
    )
    db.commit()

    # 只聚合 task_x：只导入任务甲
    result = import_aweme_creators(db, owner_id=owner.id, task_id=task_x.id)
    assert result.created_count == 1
    assert result.existing_count == 0
    assert result.total_count == 1
    formal_a = db.exec(
        select(DouyinCreator).where(DouyinCreator.sec_uid == raw_a)
    ).one()
    assert formal_a.is_placeholder is False
    assert formal_a.creator_hash == hash_a
    assert (
        db.exec(select(DouyinCreator).where(DouyinCreator.sec_uid == raw_b)).first()
        is None
    )

    # 再限定 task_y：导入任务乙
    result_b = import_aweme_creators(db, owner_id=owner.id, task_id=task_y.id)
    assert result_b.created_count == 1
    formal_b = db.exec(
        select(DouyinCreator).where(DouyinCreator.sec_uid == raw_b)
    ).one()
    assert formal_b.nickname == "任务乙"

    # 幂等：再次限定同任务全部跳过
    again = import_aweme_creators(db, owner_id=owner.id, task_id=task_x.id)
    assert again.created_count == 0
    assert again.existing_count == 1

    for task in [task_x, task_y]:
        db.delete(db.get(CrawlTask, task.id))
    for row in db.exec(
        select(DouyinCreator).where(DouyinCreator.owner_id == owner.id)
    ).all():
        db.delete(row)
    db.commit()


def test_complete_task_auto_imports_creators(db: Session) -> None:
    """验证任务成功落库时自动把作品达人导入名单（正式），重复任务幂等跳过。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    track = default_track_id(db, owner_id=owner.id)
    raw = f"MT{uuid.uuid4().hex}"
    task = CrawlTask(
        owner_id=owner.id,
        track_id=track,
        crawl_type="search",
        status=CrawlTaskStatus.running.value,
        request_json="{}",
        checkpoint_json="{}",
    )
    db.add(task)
    db.flush()
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id="auto-a1",
            title="",
            sec_uid=anonymize_user_id(raw),
            nickname="自动甲",
            creator_real_sec_uid=raw,
        )
    )
    db.commit()

    DouyinStorage(task.id)._complete_task_sync("search")

    db.expire_all()
    finished = db.get(CrawlTask, task.id)
    assert finished is not None
    assert finished.status == CrawlTaskStatus.succeeded.value
    creator = db.exec(
        select(DouyinCreator).where(
            DouyinCreator.owner_id == owner.id,
            DouyinCreator.sec_uid == raw,
        )
    ).one()
    assert creator.is_placeholder is False
    assert creator.nickname == "自动甲"
    assert creator.track_id == track

    # 另一个任务含同一达人作品：完成后再导入，名单不重复
    task_b = CrawlTask(
        owner_id=owner.id,
        track_id=track,
        crawl_type="search",
        status=CrawlTaskStatus.running.value,
        request_json="{}",
        checkpoint_json="{}",
    )
    db.add(task_b)
    db.flush()
    db.add(
        DouyinAweme(
            task_id=task_b.id,
            aweme_id="auto-b1",
            title="",
            sec_uid=anonymize_user_id(raw),
            nickname="自动甲",
            creator_real_sec_uid=raw,
        )
    )
    db.commit()
    DouyinStorage(task_b.id)._complete_task_sync("search")
    rows = db.exec(
        select(DouyinCreator).where(
            DouyinCreator.owner_id == owner.id,
            DouyinCreator.sec_uid == raw,
        )
    ).all()
    assert len(rows) == 1

    for task_row in [task, task_b]:
        db.delete(db.get(CrawlTask, task_row.id))
    for row in db.exec(
        select(DouyinCreator).where(DouyinCreator.owner_id == owner.id)
    ).all():
        db.delete(row)
    db.commit()


def test_creator_batch_task_blocks_placeholder(db: Session) -> None:
    """验证批量创建任务拦截占位达人：包含待补全项时直接报冲突。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    track = default_track_id(db, owner_id=owner.id)
    ph = DouyinCreator(
        owner_id=owner.id,
        track_id=track,
        sec_uid=anonymize_user_id(f"MN{uuid.uuid4().hex}"),
        creator_hash=anonymize_user_id(f"MN{uuid.uuid4().hex}"),
        nickname="占位达人",
        enabled=True,
        is_placeholder=True,
    )
    normal = DouyinCreator(
        owner_id=owner.id,
        track_id=track,
        sec_uid=f"MO{uuid.uuid4().hex}",
        creator_hash=anonymize_user_id(f"MO{uuid.uuid4().hex}"),
        nickname="正常达人",
        enabled=True,
    )
    db.add_all([ph, normal])
    db.commit()

    with pytest.raises(CreatorConflictError, match="待补全"):
        asyncio.run(
            create_creator_crawl_tasks(
                db,
                owner_id=owner.id,
                request=DouyinCreatorBatchTaskRequest(
                    creator_ids=[ph.id, normal.id], fetch_comments=False
                ),
            )
        )

    for row in [ph, normal]:
        db.delete(row)
    db.commit()
