"""抖音赛道（track）归属绑定的测试：覆盖默认赛道单例与并发幂等、任务/关键词归属绑定、评论筛选的归属校验、默认赛道保护、删除迁移与用户级联删除。"""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from crawler.bootstrap.database import engine
from crawler.business.douyin.comments.models import DouyinComment
from crawler.business.douyin.comments.query_service import list_comment_library
from crawler.business.douyin.content.models import DouyinAweme, DouyinUserAction
from crawler.business.douyin.creators.models import DouyinCreator, DouyinCreatorTaskLink
from crawler.business.douyin.interactions.models import DouyinInteraction
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
from crawler.business.douyin.media.models import DouyinMediaAsset
from crawler.business.douyin.request_logs.models import DouyinRequestLog
from crawler.business.douyin.tags.models import DouyinAwemeTag, DouyinTag
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskShard,
    CrawlTaskShardStatus,
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
    reset_track_record,
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


def test_default_track_lookup_preserves_disabled_state(db: Session) -> None:
    """冻结默认赛道后再次惰性解析不得把它自动重新启用。"""
    owner = _owner(db)
    track = ensure_default_track(db, owner_id=owner.id)
    track.enabled = False
    db.add(track)
    db.commit()

    resolved = ensure_default_track(db, owner_id=owner.id)

    assert resolved.id == track.id
    assert resolved.enabled is False
    resolved.enabled = True
    db.add(resolved)
    db.commit()


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


def test_default_protection_force_delete_and_user_cascade(db: Session) -> None:
    """验证默认赛道保护、普通赛道强制清理以及用户级联删除。"""
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
    assert db.get(DouyinTrack, normal.id) is None
    assert db.get(CrawlTask, task.id) is None
    assert (
        db.exec(
            select(DouyinKeyword).where(DouyinKeyword.keyword == "待迁移关键词")
        ).first()
        is None
    )

    retained_keyword = create_keywords(
        db,
        owner_id=owner.id,
        values=["用户级联关键词"],
        track_id=fallback.id,
    )[0][0]
    retained_task = _task(db, owner=owner, track=fallback)
    owner_id = owner.id
    task_id = retained_task.id
    keyword_id = retained_keyword.id
    stored_owner = db.get(User, owner_id)
    assert stored_owner is not None
    db.delete(stored_owner)
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


def test_reset_track_keeps_configuration_and_removes_business_data(db: Session) -> None:
    """重置保留赛道配置，同时删除关键词、任务、作品和评论。"""
    owner = _owner(db)
    track = create_track(
        db,
        owner_id=owner.id,
        name="待重置赛道",
        description="配置保留",
        prompt="分析提示词",
        keywords=["待清空关键词"],
    )
    task = _task(db, owner=owner, track=track)
    creator = DouyinCreator(
        owner_id=owner.id,
        track_id=track.id,
        sec_uid="reset-creator-sec-uid",
        creator_hash="reset-creator-hash",
        nickname="待清空达人",
    )
    db.add(creator)
    db.flush()
    db.add(DouyinCreatorTaskLink(creator_id=creator.id, task_id=task.id))
    aweme = DouyinAweme(
        task_id=task.id,
        aweme_id="track-reset-aweme",
        title="待清空作品",
        source_keyword="待清空关键词",
    )
    db.add(aweme)
    db.add(
        DouyinComment(
            task_id=task.id,
            aweme_id=aweme.aweme_id,
            comment_id="track-reset-comment",
            content="待清空评论",
        )
    )
    db.commit()
    aweme_row_id = aweme.id
    creator_id = creator.id

    result = reset_track_record(
        db,
        track_id=track.id,
        actor_id=owner.id,
        is_superuser=False,
    )

    db.expire_all()
    retained_track = db.get(DouyinTrack, track.id)
    assert retained_track is not None
    assert retained_track.description == "配置保留"
    assert retained_track.prompt == "分析提示词"
    assert result.track_count == 0
    assert result.keyword_count == 1
    assert result.creator_count == 1
    assert result.task_count == 1
    assert result.aweme_count == 1
    assert result.comment_count == 1
    assert db.get(CrawlTask, task.id) is None
    assert db.get(DouyinAweme, aweme_row_id) is None
    assert db.get(DouyinCreator, creator_id) is None
    assert (
        db.exec(
            select(DouyinKeyword).where(DouyinKeyword.keyword == "待清空关键词")
        ).first()
        is None
    )


def test_reset_track_preserves_and_rehomes_shared_task(db: Session) -> None:
    """共享任务仅清理目标赛道作品级数据，并安全改写剩余任务来源。"""
    owner = _owner(db)
    target = create_track(
        db,
        owner_id=owner.id,
        name="共享任务原赛道",
        description="",
        prompt="",
        keywords=["原赛道词"],
    )
    external = create_track(
        db,
        owner_id=owner.id,
        name="共享任务新赛道",
        description="",
        prompt="",
        keywords=["新赛道词"],
    )
    target_keyword = db.exec(
        select(DouyinKeyword).where(
            DouyinKeyword.owner_id == owner.id,
            DouyinKeyword.keyword == "原赛道词",
        )
    ).one()
    external_keyword = db.exec(
        select(DouyinKeyword).where(
            DouyinKeyword.owner_id == owner.id,
            DouyinKeyword.keyword == "新赛道词",
        )
    ).one()
    task = _task(db, owner=owner, track=target)
    db.add(
        DouyinKeywordTaskLink(
            keyword_id=target_keyword.id,
            task_id=task.id,
            source=DouyinKeywordSyncSource.automatic.value,
        )
    )
    db.add(
        DouyinKeywordTaskLink(
            keyword_id=external_keyword.id,
            task_id=task.id,
            source=DouyinKeywordSyncSource.automatic.value,
        )
    )
    task.request_json = json.dumps(
        {
            "crawl_type": "search",
            "keywords": ["原赛道词", "新赛道词"],
            "track_id": str(target.id),
        },
        ensure_ascii=False,
    )
    task.status = CrawlTaskStatus.running.value
    task.checkpoint_json = json.dumps(
        {
            "version": 1,
            "phase": "crawl",
            "crawl_type": "search",
            "position": {"target_index": 1},
        }
    )
    db.add(task)
    shard = CrawlTaskShard(
        task_id=task.id,
        shard_index=0,
        status=CrawlTaskShardStatus.running.value,
        request_json=task.request_json,
    )
    db.add(shard)
    target_aweme = DouyinAweme(
        task_id=task.id,
        aweme_id="shared-target-aweme",
        title="只属于待重置赛道",
        source_keyword="原赛道词",
    )
    external_aweme = DouyinAweme(
        task_id=task.id,
        aweme_id="shared-external-aweme",
        title="属于保留赛道",
        source_keyword="新赛道词",
    )
    db.add(target_aweme)
    db.add(external_aweme)
    target_only_tag = DouyinTag(
        owner_id=owner.id,
        name="#待清理标签",
        normalized_name="待清理标签",
    )
    shared_tag = DouyinTag(
        owner_id=owner.id,
        name="#共享标签",
        normalized_name="共享标签",
    )
    db.add(target_only_tag)
    db.add(shared_tag)
    db.flush()
    db.add(
        DouyinAwemeTag(
            aweme_record_id=target_aweme.id,
            tag_id=target_only_tag.id,
        )
    )
    request_log = DouyinRequestLog(
        owner_id=owner.id,
        task_id=task.id,
        method="GET",
        path="/aweme/v1/web/search/item/",
        url="https://www.douyin.com/aweme/v1/web/search/item/",
    )
    db.add(request_log)
    db.add(
        DouyinAwemeTag(
            aweme_record_id=target_aweme.id,
            tag_id=shared_tag.id,
        )
    )
    db.add(
        DouyinAwemeTag(
            aweme_record_id=external_aweme.id,
            tag_id=shared_tag.id,
        )
    )
    for aweme, suffix in ((target_aweme, "target"), (external_aweme, "external")):
        db.add(
            DouyinComment(
                task_id=task.id,
                aweme_id=aweme.aweme_id,
                comment_id=f"shared-{suffix}-comment",
                content=suffix,
            )
        )
        db.add(
            DouyinMediaAsset(
                task_id=task.id,
                aweme_id=aweme.aweme_id,
                source_url=f"https://example.com/{suffix}.mp4",
            )
        )
        db.add(
            DouyinUserAction(
                task_id=task.id,
                account_hash="shared-account",
                aweme_id=aweme.aweme_id,
                action_type=f"like-{suffix}",
            )
        )
        db.add(
            DouyinInteraction(
                owner_id=owner.id,
                task_id=task.id,
                aweme_id=aweme.aweme_id,
                account_name="测试账号",
                interaction_type="video_comment",
                content_encrypted="encrypted",
                content_preview=suffix,
                content_hash=f"hash-{suffix}",
                idempotency_key=f"key-{uuid.uuid4().hex}",
                status="succeeded",
            )
        )
    db.commit()
    target_keyword_id = target_keyword.id
    external_keyword_id = external_keyword.id
    task_id = task.id
    shard_id = shard.id
    target_only_tag_id = target_only_tag.id
    shared_tag_id = shared_tag.id
    request_log_id = request_log.id

    result = reset_track_record(
        db,
        track_id=target.id,
        actor_id=owner.id,
        is_superuser=False,
    )

    db.expire_all()
    retained_task = db.get(CrawlTask, task_id)
    assert retained_task is not None
    assert retained_task.track_id == external.id
    assert retained_task.status == CrawlTaskStatus.cancelled.value
    assert retained_task.finished_at is not None
    retained_request = json.loads(retained_task.request_json)
    assert retained_request["keywords"] == ["新赛道词"]
    assert retained_request["track_id"] == str(external.id)
    assert json.loads(retained_task.checkpoint_json)["position"] == {}
    assert retained_task.aweme_count == 1
    assert retained_task.comment_count == 1
    assert retained_task.action_count == 1
    assert db.get(CrawlTaskShard, shard_id) is None
    assert result.task_count == 0
    assert result.aweme_count == 1
    assert result.comment_count == 1
    assert result.interaction_count == 1
    assert db.get(DouyinKeyword, target_keyword_id) is None
    assert db.get(DouyinKeyword, external_keyword_id) is not None
    assert db.get(DouyinTag, target_only_tag_id) is None
    assert db.get(DouyinTag, shared_tag_id) is not None
    assert db.get(DouyinRequestLog, request_log_id) is None
    assert (
        db.exec(
            select(DouyinAweme).where(DouyinAweme.aweme_id == "shared-target-aweme")
        ).first()
        is None
    )
    assert (
        db.exec(
            select(DouyinAweme).where(DouyinAweme.aweme_id == "shared-external-aweme")
        ).first()
        is not None
    )
    for model in (DouyinComment, DouyinMediaAsset, DouyinInteraction, DouyinUserAction):
        assert (
            db.exec(
                select(model).where(
                    model.task_id == task_id,
                    model.aweme_id == "shared-target-aweme",
                )
            ).first()
            is None
        )
        assert (
            db.exec(
                select(model).where(
                    model.task_id == task_id,
                    model.aweme_id == "shared-external-aweme",
                )
            ).first()
            is not None
        )
