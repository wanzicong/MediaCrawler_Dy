"""Read-side use cases for the Douyin comment catalog."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlmodel import Session, col, func, select

from app.application.douyin.tasks.query_service import require_task_access
from app.application.errors import (
    InvalidRequestError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from app.domain.douyin.comments.models import (
    DouyinComment,
    DouyinCommentLibraryItemPublic,
    DouyinCommentLibraryPublic,
    DouyinCommentLibrarySummaryPublic,
    DouyinCommentsPublic,
)
from app.domain.douyin.content.models import (
    DouyinAweme,
    DouyinUserAction,
    DouyinUserActionsPublic,
)
from app.domain.douyin.tasks.models import CrawlTask, CrawlTaskStatus
from app.domain.douyin.tracks.models import DouyinTrack


def _filters(
    *,
    owner_id: uuid.UUID | None,
    comment_content: str | None,
    search: str | None,
    task_id: uuid.UUID | None,
    track_id: uuid.UUID | None,
    aweme_id: str | None,
    video_creator: str | None,
    source_keyword: str | None,
    comment_type: str,
    has_pictures: str,
    min_likes: int | None,
    max_likes: int | None,
    published_from: int | None,
    published_to: int | None,
) -> list[Any]:
    filters: list[Any] = []
    if owner_id is not None:
        filters.append(CrawlTask.owner_id == owner_id)
    if task_id:
        filters.append(DouyinComment.task_id == task_id)
    if track_id:
        filters.append(CrawlTask.track_id == track_id)
    if aweme_id and aweme_id.strip():
        filters.append(col(DouyinComment.aweme_id).ilike(f"%{aweme_id.strip()}%"))
    if comment_content and comment_content.strip():
        filters.append(col(DouyinComment.content).ilike(f"%{comment_content.strip()}%"))
    if search and search.strip():
        term = f"%{search.strip()}%"
        filters.append(
            col(DouyinComment.content).ilike(term)
            | col(DouyinComment.nickname).ilike(term)
            | col(DouyinComment.comment_id).ilike(term)
            | col(DouyinAweme.title).ilike(term)
            | col(DouyinAweme.aweme_id).ilike(term)
        )
    if video_creator and video_creator.strip():
        filters.append(col(DouyinAweme.nickname).ilike(f"%{video_creator.strip()}%"))
    if source_keyword and source_keyword.strip():
        filters.append(
            col(DouyinAweme.source_keyword).ilike(f"%{source_keyword.strip()}%")
        )
    top_level = col(DouyinComment.parent_comment_id).in_(["", "0"])
    if comment_type == "top_level":
        filters.append(top_level)
    elif comment_type == "reply":
        filters.append(~top_level)
    if has_pictures == "yes":
        filters.append(DouyinComment.pictures != "")
    elif has_pictures == "no":
        filters.append(DouyinComment.pictures == "")
    if min_likes is not None:
        filters.append(col(DouyinComment.like_count) >= min_likes)
    if max_likes is not None:
        filters.append(col(DouyinComment.like_count) <= max_likes)
    if published_from is not None:
        filters.append(col(DouyinComment.create_time) >= published_from)
    if published_to is not None:
        filters.append(col(DouyinComment.create_time) <= published_to)
    return filters


def _count(session: Session, filters: list[Any]) -> int:
    return session.exec(
        select(func.count())
        .select_from(DouyinComment)
        .join(
            DouyinAweme,
            (col(DouyinAweme.task_id) == col(DouyinComment.task_id))
            & (col(DouyinAweme.aweme_id) == col(DouyinComment.aweme_id)),
        )
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinComment.task_id))
        .where(*filters)
    ).one()


def list_comment_library(
    session: Session,
    *,
    owner_id: uuid.UUID | None,
    comment_content: str | None,
    search: str | None,
    task_id: uuid.UUID | None,
    track_id: uuid.UUID | None,
    aweme_id: str | None,
    video_creator: str | None,
    source_keyword: str | None,
    comment_type: Literal["all", "top_level", "reply"],
    has_pictures: Literal["all", "yes", "no"],
    min_likes: int | None,
    max_likes: int | None,
    published_from: int | None,
    published_to: int | None,
    sort_by: Literal["published_at", "like_count", "sub_comment_count", "fetched_at"],
    sort_order: Literal["asc", "desc"],
    skip: int,
    limit: int,
) -> DouyinCommentLibraryPublic:
    selected_task: CrawlTask | None = None
    if task_id is not None:
        try:
            selected_task = require_task_access(
                session,
                task_id=task_id,
                owner_id=owner_id,
            )
        except (ResourceNotFoundError, PermissionDeniedError) as exc:
            # Catalog filters use not-found semantics so another tenant cannot
            # probe whether an arbitrary task UUID exists.
            raise ResourceNotFoundError("任务不存在或无权访问") from exc
    if track_id is not None:
        track = session.get(DouyinTrack, track_id)
        if track is None or (owner_id is not None and track.owner_id != owner_id):
            raise ResourceNotFoundError("赛道不存在或无权访问")
        if selected_task is not None and selected_task.track_id != track_id:
            raise InvalidRequestError("任务不属于所选赛道，请调整筛选条件")
    filters = _filters(
        owner_id=owner_id,
        comment_content=comment_content,
        search=search,
        task_id=task_id,
        track_id=track_id,
        aweme_id=aweme_id,
        video_creator=video_creator,
        source_keyword=source_keyword,
        comment_type=comment_type,
        has_pictures=has_pictures,
        min_likes=min_likes,
        max_likes=max_likes,
        published_from=published_from,
        published_to=published_to,
    )
    count = _count(session, filters)
    top_level_filter = col(DouyinComment.parent_comment_id).in_(["", "0"])
    top_level_count = _count(session, [*filters, top_level_filter])
    picture_count = _count(session, [*filters, DouyinComment.pictures != ""])
    total_like_count = session.exec(
        select(func.coalesce(func.sum(DouyinComment.like_count), 0))
        .select_from(DouyinComment)
        .join(
            DouyinAweme,
            (col(DouyinAweme.task_id) == col(DouyinComment.task_id))
            & (col(DouyinAweme.aweme_id) == col(DouyinComment.aweme_id)),
        )
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinComment.task_id))
        .where(*filters)
    ).one()
    sort_column = {
        "published_at": DouyinComment.create_time,
        "like_count": DouyinComment.like_count,
        "sub_comment_count": DouyinComment.sub_comment_count,
        "fetched_at": DouyinComment.fetched_at,
    }[sort_by]
    order_expression = (
        col(sort_column).asc() if sort_order == "asc" else col(sort_column).desc()
    ).nulls_last()
    rows = session.exec(
        select(DouyinComment, DouyinAweme, CrawlTask)
        .join(
            DouyinAweme,
            (col(DouyinAweme.task_id) == col(DouyinComment.task_id))
            & (col(DouyinAweme.aweme_id) == col(DouyinComment.aweme_id)),
        )
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinComment.task_id))
        .where(*filters)
        .order_by(order_expression, col(DouyinComment.fetched_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return DouyinCommentLibraryPublic(
        data=[
            DouyinCommentLibraryItemPublic(
                comment=comment,
                aweme=aweme,
                task_status=CrawlTaskStatus(task.status),
                task_created_at=task.created_at,
            )
            for comment, aweme, task in rows
        ],
        count=count,
        summary=DouyinCommentLibrarySummaryPublic(
            matched_count=count,
            top_level_count=top_level_count,
            reply_count=count - top_level_count,
            picture_count=picture_count,
            total_like_count=int(total_like_count),
        ),
    )


def list_task_comments(
    session: Session,
    *,
    task_id: uuid.UUID,
    aweme_id: str | None,
    sort_by: Literal["published_at", "like_count", "fetched_at"],
    sort_order: Literal["asc", "desc"],
    skip: int,
    limit: int,
) -> DouyinCommentsPublic:
    filters = [DouyinComment.task_id == task_id]
    if aweme_id:
        filters.append(DouyinComment.aweme_id == aweme_id)
    count = session.exec(
        select(func.count()).select_from(DouyinComment).where(*filters)
    ).one()
    sort_column = {
        "published_at": DouyinComment.create_time,
        "like_count": DouyinComment.like_count,
        "fetched_at": DouyinComment.fetched_at,
    }[sort_by]
    order_expression = (
        col(sort_column).asc() if sort_order == "asc" else col(sort_column).desc()
    ).nulls_last()
    data = session.exec(
        select(DouyinComment)
        .where(*filters)
        .order_by(order_expression, col(DouyinComment.fetched_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return DouyinCommentsPublic(data=data, count=count)


def list_task_actions(
    session: Session,
    *,
    task_id: uuid.UUID,
    skip: int,
    limit: int,
) -> DouyinUserActionsPublic:
    count = session.exec(
        select(func.count())
        .select_from(DouyinUserAction)
        .where(DouyinUserAction.task_id == task_id)
    ).one()
    data = session.exec(
        select(DouyinUserAction)
        .where(DouyinUserAction.task_id == task_id)
        .order_by(col(DouyinUserAction.observed_at).desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return DouyinUserActionsPublic(data=data, count=count)


__all__ = ["list_comment_library", "list_task_actions", "list_task_comments"]
