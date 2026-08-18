import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from app.application.douyin.comments.query_service import list_comment_library
from app.application.douyin.keywords.service import (
    build_keyword_public_rows,
    create_keywords,
    sync_task,
)
from app.application.douyin.tasks.persistence import DouyinStorage
from app.application.douyin.tracks.bindings import (
    assign_task_track,
    ensure_default_track,
)
from app.application.douyin.tracks.service import (
    TrackConflictError,
    create_track,
    delete_track_record,
    update_track_record,
)
from app.application.errors import InvalidRequestError, ResourceNotFoundError
from app.domain.douyin.keywords.models import (
    DouyinKeyword,
    DouyinKeywordSyncSource,
    DouyinKeywordTaskLink,
)
from app.domain.douyin.tasks.models import CrawlTask, CrawlTaskCreate, CrawlTaskStatus
from app.domain.douyin.tracks.models import (
    DouyinTrack,
    DouyinTrackKeywordLink,
    DouyinTrackTaskLink,
)
from app.domain.identity.models import User
from app.framework.database import engine


def _owner(db: Session) -> User:
    owner = User(
        email=f"track-binding-{uuid.uuid4().hex}@example.com",
        hashed_password="not-used-in-this-test",
    )
    db.add(owner)
    db.commit()
    db.refresh(owner)
    return owner


def _task(db: Session, *, owner: User, track: DouyinTrack) -> CrawlTask:
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


def test_default_track_is_singleton_and_application_records_are_bound(
    db: Session,
) -> None:
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
    owner = _owner(db)

    def resolve_in_fresh_session() -> uuid.UUID:
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


def test_history_sync_keeps_existing_keyword_track_and_metrics_scoped(
    db: Session,
) -> None:
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
    assert row.task_count == 0
    assert row.success_task_count == 0


def test_comment_task_and_track_filters_validate_visibility(db: Session) -> None:
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
