"""抖音赛道（track）归属绑定的测试：覆盖默认赛道单例与并发幂等、任务/关键词归属绑定、评论筛选的归属校验、默认赛道保护、删除迁移与用户级联删除。"""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from crawler.bootstrap.database import engine
from crawler.business.douyin.comments.models import DouyinComment
from crawler.business.douyin.comments.query_service import list_comment_library
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.keywords.models import (
    DouyinKeyword,
    DouyinKeywordSyncSource,
    DouyinKeywordTaskLink,
)
from crawler.business.douyin.keywords.service import (
    build_keyword_public_rows,
    create_keywords,
    sync_task,
)
from crawler.business.douyin.library.service import list_library_works
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskStatus,
)
from crawler.business.douyin.tasks.persistence import DouyinStorage
from crawler.business.douyin.tracks.bindings import (
    assign_task_track,
    ensure_default_track,
)
from crawler.business.douyin.tracks.models import (
    DouyinTrack,
    DouyinTrackKeywordLink,
    DouyinTrackTaskLink,
)
from crawler.business.douyin.tracks.service import (
    TrackConflictError,
    create_track,
    delete_track_record,
    update_track_record,
)
from crawler.business.errors import InvalidRequestError, ResourceNotFoundError
from crawler.business.identity.models import User
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select


def _owner(db: Session) -> User:
    """创建并入库一个独立的测试用户（每个用例互不干扰）。"""
    owner = User(
        email=f"track-binding-{uuid.uuid4().hex}@example.com",
        hashed_password="not-used-in-this-test",
    )
    db.add(owner)
    db.commit()
    db.refresh(owner)
    return owner


def _task(db: Session, *, owner: User, track: DouyinTrack) -> CrawlTask:
    """创建并入库一条归属指定赛道的已完成搜索任务。"""
    task = CrawlTask(
        owner_id=owner.id,
        track_id=track.id,
        crawl_type="search",
        status=CrawlTaskStatus.succeeded.value,
        request_json=json.dumps(
            {"crawl_type": "search", "keywords": ["归属测试词"]},
            ensure_ascii=False,
        ),
        checkpoint_json='{"version":1,"phase":"completed","position":{}}',
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _comment_filter(
    db: Session,
    *,
    owner_id: uuid.UUID,
    task_id: uuid.UUID | None,
    track_id: uuid.UUID | None,
) -> object:
    """以最简参数调用评论库查询，仅注入归属相关的 task_id/track_id 过滤条件。"""
    return list_comment_library(
        db,
        owner_id=owner_id,
        comment_content=None,
        search=None,
        task_id=task_id,
        track_id=track_id,
        aweme_id=None,
        video_creator=None,
        source_keyword=None,
        comment_type="all",
        has_pictures="all",
        min_likes=None,
        max_likes=None,
        published_from=None,
        published_to=None,
        sort_by="published_at",
        sort_order="desc",
        skip=0,
        limit=10,
    )


def _library_filter(db: Session, *, owner_id: uuid.UUID, track_id: uuid.UUID) -> object:
    """按赛道查询作品库，供动态内容归属测试复用。"""
    return list_library_works(
        db,
        owner_id=owner_id,
        search=None,
        task_id=None,
        track_id=track_id,
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


def test_default_track_is_singleton_and_application_records_are_bound(
    db: Session,
) -> None:
    """验证默认赛道全局唯一（跨会话幂等），且应用层创建的任务与关键词自动绑定默认赛道及关联表记录。"""
    owner = _owner(db)
    first = ensure_default_track(db, owner_id=owner.id)
    db.commit()
    with Session(engine) as other_session:
        second = ensure_default_track(other_session, owner_id=owner.id)
        other_session.commit()
        assert second.id == first.id

    task = DouyinStorage._create_task_sync(
        owner.id,
        CrawlTaskCreate(
            crawl_type="detail",
            video_ids=["1"],
            fetch_comments=False,
        ),
    )
    keyword = create_keywords(
        db,
        owner_id=owner.id,
        values=["应用入口词"],
        track_id=None,
    )[0][0]
    db.commit()
    db.expire_all()
    persisted_task = db.get(CrawlTask, task.id)
    persisted_keyword = db.get(DouyinKeyword, keyword.id)
    assert persisted_task is not None
    assert persisted_keyword is not None
    assert persisted_task.track_id == first.id
    assert persisted_keyword.track_id == first.id
    assert (
        db.exec(
            select(func.count())
            .select_from(DouyinTrackTaskLink)
            .where(DouyinTrackTaskLink.task_id == task.id)
        ).one()
        == 1
    )
    assert (
        db.exec(
            select(func.count())
            .select_from(DouyinTrackKeywordLink)
            .where(DouyinTrackKeywordLink.keyword_id == keyword.id)
        ).one()
        == 1
    )


def test_concurrent_default_track_creation_is_idempotent(db: Session) -> None:
    """验证多线程并发获取默认赛道时只会创建一条记录，不会产生重复默认赛道。"""
    owner = _owner(db)

    def resolve_in_fresh_session() -> uuid.UUID:
        """在独立会话中获取（或创建）默认赛道并返回其 id。"""
        with Session(engine) as session:
            track = ensure_default_track(session, owner_id=owner.id)
            session.commit()
            return track.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        track_ids = list(
            executor.map(lambda _index: resolve_in_fresh_session(), range(2))
        )

    assert track_ids[0] == track_ids[1]
    assert (
        db.exec(
            select(func.count())
            .select_from(DouyinTrack)
            .where(DouyinTrack.owner_id == owner.id, DouyinTrack.is_default.is_(True))
        ).one()
        == 1
    )


def test_database_rejects_unbound_task(db: Session) -> None:
    """验证数据库层面拒绝 track_id 为空的任务（非空约束兜底，绕过应用层也写不进去）。"""
    owner = _owner(db)
    task = CrawlTask(
        owner_id=owner.id,
        track_id=None,  # type: ignore[arg-type]
        crawl_type="detail",
        status=CrawlTaskStatus.succeeded.value,
        request_json='{"crawl_type":"detail","video_ids":["1"]}',
    )
    db.add(task)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_detail_source_marker_does_not_match_same_named_keyword(db: Session) -> None:
    """验证 detail 等采集来源标记不会被误当成关键词并改变内容赛道。"""
    owner = _owner(db)
    detail_track = create_track(
        db,
        owner_id=owner.id,
        name="详情赛道",
        description="",
        prompt="",
        keywords=[],
    )
    keyword_track = create_track(
        db,
        owner_id=owner.id,
        name="同名词赛道",
        description="",
        prompt="",
        keywords=[],
    )
    create_keywords(
        db,
        owner_id=owner.id,
        values=["detail"],
        track_id=keyword_track.id,
    )
    task = CrawlTask(
        owner_id=owner.id,
        track_id=detail_track.id,
        crawl_type="detail",
        status=CrawlTaskStatus.succeeded.value,
        request_json='{"crawl_type":"detail","video_ids":["detail-aweme"]}',
        checkpoint_json='{"version":1,"phase":"completed","position":{}}',
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    db.add(
        DouyinAweme(
            task_id=task.id,
            aweme_id="detail-source-marker-aweme",
            title="详情来源作品",
            source_keyword="detail",
        )
    )
    db.commit()

    assert _library_filter(db, owner_id=owner.id, track_id=detail_track.id).count == 1
    assert _library_filter(db, owner_id=owner.id, track_id=keyword_track.id).count == 0


def test_history_content_follows_current_keyword_track(
    db: Session,
) -> None:
    """验证历史任务保留审计赛道，但绑定任务、作品与评论跟随关键词当前赛道。"""
    owner = _owner(db)
    track_a = create_track(
        db,
        owner_id=owner.id,
        name="赛道甲",
        description="",
        prompt="",
        keywords=[],
    )
    track_b = create_track(
        db,
        owner_id=owner.id,
        name="赛道乙",
        description="",
        prompt="",
        keywords=[],
    )
    keyword = create_keywords(
        db,
        owner_id=owner.id,
        values=["归属测试词"],
        track_id=track_a.id,
    )[0][0]
    task = _task(db, owner=owner, track=track_b)
    aweme = DouyinAweme(
        task_id=task.id,
        aweme_id="keyword-track-follow-aweme",
        title="关键词归属作品",
        source_keyword="归属测试词",
    )
    db.add(aweme)
    db.add(
        DouyinComment(
            task_id=task.id,
            aweme_id=aweme.aweme_id,
            comment_id="keyword-track-follow-comment",
            content="跟随关键词赛道的评论",
        )
    )
    db.commit()

    count, created, bound = sync_task(
        db,
        task=task,
        source=DouyinKeywordSyncSource.history,
    )
    db.commit()
    db.refresh(keyword)
    assert (count, created, bound) == (1, 0, 1)
    assert keyword.track_id == track_a.id
    assert db.exec(
        select(DouyinKeywordTaskLink).where(
            DouyinKeywordTaskLink.keyword_id == keyword.id,
            DouyinKeywordTaskLink.task_id == task.id,
        )
    ).one()
    row = next(
        item
        for item in build_keyword_public_rows(db, owner_id=owner.id)
        if item.id == keyword.id
    )
    assert row.task_count == 1
    assert row.success_task_count == 1
    assert row.aweme_count == 1
    assert _library_filter(db, owner_id=owner.id, track_id=track_a.id).count == 1
    assert _library_filter(db, owner_id=owner.id, track_id=track_b.id).count == 0
    assert (
        _comment_filter(db, owner_id=owner.id, task_id=None, track_id=track_a.id).count
        == 1
    )
    assert (
        _comment_filter(db, owner_id=owner.id, task_id=None, track_id=track_b.id).count
        == 0
    )


def test_comment_task_and_track_filters_validate_visibility(db: Session) -> None:
    """验证评论筛选的 task_id/track_id 组合校验：任务不存在或属他人报 404 语义，任务与赛道不匹配报请求错误。"""
    owner = _owner(db)
    track_a = create_track(
        db,
        owner_id=owner.id,
        name="筛选甲",
        description="",
        prompt="",
        keywords=[],
    )
    track_b = create_track(
        db,
        owner_id=owner.id,
        name="筛选乙",
        description="",
        prompt="",
        keywords=[],
    )
    task = _task(db, owner=owner, track=track_a)

    with pytest.raises(ResourceNotFoundError, match="任务不存在或无权访问"):
        _comment_filter(
            db,
            owner_id=owner.id,
            task_id=uuid.uuid4(),
            track_id=None,
        )

    other_owner = _owner(db)
    other_track = ensure_default_track(db, owner_id=other_owner.id)
    other_task = _task(db, owner=other_owner, track=other_track)
    with pytest.raises(ResourceNotFoundError, match="任务不存在或无权访问"):
        _comment_filter(
            db,
            owner_id=owner.id,
            task_id=other_task.id,
            track_id=None,
        )

    with pytest.raises(InvalidRequestError, match="任务不属于所选赛道"):
        _comment_filter(
            db,
            owner_id=owner.id,
            task_id=task.id,
            track_id=track_b.id,
        )


def test_default_protection_rehome_and_user_cascade(db: Session) -> None:
    """验证默认赛道不可删除/停用但可改文案；删除普通赛道时其任务与关键词迁移到默认赛道；删除用户时级联清理其赛道、任务与关键词。"""
    owner = _owner(db)
    fallback = ensure_default_track(db, owner_id=owner.id)
    normal = create_track(
        db,
        owner_id=owner.id,
        name="待删除赛道",
        description="",
        prompt="",
        keywords=["待迁移关键词"],
    )
    task = _task(db, owner=owner, track=normal)
    assign_task_track(db, task=task, track=normal)
    db.commit()

    with pytest.raises(TrackConflictError, match="不能删除"):
        delete_track_record(
            db,
            track_id=fallback.id,
            actor_id=owner.id,
            is_superuser=False,
        )
    updated_default = update_track_record(
        db,
        track_id=fallback.id,
        actor_id=owner.id,
        is_superuser=False,
        name=fallback.name,
        description="允许更新描述",
        prompt="允许更新提示词",
        enabled=True,
    )
    assert updated_default.description == "允许更新描述"
    assert updated_default.prompt == "允许更新提示词"

    with pytest.raises(TrackConflictError, match="不能停用"):
        update_track_record(
            db,
            track_id=fallback.id,
            actor_id=owner.id,
            is_superuser=False,
            name=fallback.name,
            description="允许更新描述",
            prompt="允许更新提示词",
            enabled=False,
        )

    delete_track_record(
        db,
        track_id=normal.id,
        actor_id=owner.id,
        is_superuser=False,
    )
    db.expire_all()
    assert db.get(CrawlTask, task.id).track_id == fallback.id  # type: ignore[union-attr]
    moved_keyword = db.exec(
        select(DouyinKeyword).where(DouyinKeyword.keyword == "待迁移关键词")
    ).one()
    assert moved_keyword.track_id == fallback.id

    owner_id = owner.id
    task_id = task.id
    keyword_id = moved_keyword.id
    db.delete(db.get(User, owner_id))
    db.commit()
    assert db.get(User, owner_id) is None
    assert db.get(CrawlTask, task_id) is None
    assert db.get(DouyinKeyword, keyword_id) is None
    assert (
        db.exec(
            select(func.count())
            .select_from(DouyinTrack)
            .where(DouyinTrack.owner_id == owner_id)
        ).one()
        == 0
    )
