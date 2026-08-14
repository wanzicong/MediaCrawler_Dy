import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.douyin.storage import task_public_values
from app.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskPublic,
    DouyinBulkDeleteRequest,
    DouyinCrawlType,
    DouyinKeywordBatchMode,
    DouyinKeywordsPublic,
    DouyinKeywordTaskBatchResult,
    DouyinTrack,
    DouyinTrackCreate,
    DouyinTrackDetailPublic,
    DouyinTrackKeywordAdd,
    DouyinTrackKeywordLink,
    DouyinTracksPublic,
    DouyinTrackTaskLink,
    DouyinTrackTaskRequest,
    DouyinTrackUpdate,
    MediaProcessingMode,
    Message,
    get_datetime_utc,
)
from app.services.douyin_keywords import build_keyword_public_rows
from app.services.douyin_tasks import task_manager
from app.services.douyin_tracks import (
    add_track_keywords,
    build_track_public_rows,
    create_track,
    normalize_track_name,
    track_keywords,
)

router = APIRouter(prefix="/douyin/tracks", tags=["douyin-tracks"])


def _get_track(
    session: SessionDep, current_user: CurrentUser, track_id: uuid.UUID
) -> DouyinTrack:
    item = session.get(DouyinTrack, track_id)
    if item is None or (
        item.owner_id != current_user.id and not current_user.is_superuser
    ):
        raise HTTPException(status_code=404, detail="赛道不存在")
    return item


def _detail(session: SessionDep, track: DouyinTrack) -> DouyinTrackDetailPublic:
    summary = next(
        item
        for item in build_track_public_rows(
            session, owner_id=track.owner_id, track_id=track.id
        )
        if item.id == track.id
    )
    return DouyinTrackDetailPublic(**summary.model_dump(), prompt=track.prompt)


@router.get("", response_model=DouyinTracksPublic)
def list_tracks(
    session: SessionDep,
    current_user: CurrentUser,
    search: str | None = Query(default=None, max_length=100),
    enabled: bool | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> Any:
    rows = build_track_public_rows(session, owner_id=current_user.id, search=search)
    if enabled is not None:
        rows = [item for item in rows if item.enabled == enabled]
    return DouyinTracksPublic(data=rows[skip : skip + limit], count=len(rows))


@router.get("/{track_id}", response_model=DouyinTrackDetailPublic)
def get_track(
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> DouyinTrackDetailPublic:
    return _detail(session, _get_track(session, current_user, track_id))


@router.post(
    "", response_model=DouyinTrackDetailPublic, status_code=status.HTTP_201_CREATED
)
def add_track(
    request: DouyinTrackCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    track = create_track(
        session,
        owner_id=current_user.id,
        name=request.name,
        description=request.description,
        prompt=request.prompt,
        keywords=request.keywords,
    )
    session.commit()
    session.refresh(track)
    return _detail(session, track)


@router.patch("/{track_id}", response_model=DouyinTrackDetailPublic)
def edit_track(
    request: DouyinTrackUpdate,
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> Any:
    track = _get_track(session, current_user, track_id)
    if request.name is not None:
        name, normalized = normalize_track_name(request.name)
        conflict = session.exec(
            select(DouyinTrack).where(
                DouyinTrack.owner_id == track.owner_id,
                DouyinTrack.normalized_name == normalized,
                DouyinTrack.id != track.id,
            )
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail="同名赛道已存在")
        track.name, track.normalized_name = name, normalized
    if request.description is not None:
        track.description = request.description.strip()
    if request.prompt is not None:
        track.prompt = request.prompt.strip()
    if request.enabled is not None:
        track.enabled = request.enabled
    track.updated_at = get_datetime_utc()
    session.add(track)
    session.commit()
    return _detail(session, track)


@router.delete("/{track_id}")
def delete_track(
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> Message:
    session.delete(_get_track(session, current_user, track_id))
    session.commit()
    return Message(message="赛道已删除；关键词、任务和采集结果均已保留")


@router.post("/bulk-delete", response_model=Message)
def bulk_delete_tracks(
    request: DouyinBulkDeleteRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    rows = session.exec(
        select(DouyinTrack).where(
            DouyinTrack.owner_id == current_user.id,
            col(DouyinTrack.id).in_(request.ids),
        )
    ).all()
    for row in rows:
        session.delete(row)
    session.commit()
    return Message(message=f"已删除 {len(rows)} 个赛道；历史任务和作品均已保留")


@router.get("/{track_id}/keywords", response_model=DouyinKeywordsPublic)
def list_track_keywords(
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> Any:
    track = _get_track(session, current_user, track_id)
    ids = {item.id for item in track_keywords(session, track_id=track.id)}
    rows = [
        item
        for item in build_keyword_public_rows(session, owner_id=track.owner_id)
        if item.id in ids
    ]
    return DouyinKeywordsPublic(data=rows, count=len(rows))


@router.post("/{track_id}/keywords", response_model=DouyinKeywordsPublic)
def append_track_keywords(
    request: DouyinTrackKeywordAdd,
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> Any:
    track = _get_track(session, current_user, track_id)
    add_track_keywords(
        session, track=track, owner_id=track.owner_id, values=request.keywords
    )
    session.commit()
    return list_track_keywords(session, current_user, track_id)


@router.delete("/{track_id}/keywords/{keyword_id}")
def remove_track_keyword(
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
    keyword_id: uuid.UUID,
) -> Message:
    track = _get_track(session, current_user, track_id)
    link = session.exec(
        select(DouyinTrackKeywordLink).where(
            DouyinTrackKeywordLink.track_id == track_id,
            DouyinTrackKeywordLink.keyword_id == keyword_id,
        )
    ).first()
    if link is None:
        raise HTTPException(status_code=404, detail="赛道关键词关联不存在")
    session.delete(link)
    track.updated_at = get_datetime_utc()
    session.add(track)
    session.commit()
    return Message(message="关键词已从赛道移除，关键词本身及历史任务不受影响")


@router.post(
    "/{track_id}/tasks",
    response_model=DouyinKeywordTaskBatchResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_track_tasks(
    request: DouyinTrackTaskRequest,
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> Any:
    track = _get_track(session, current_user, track_id)
    if track.owner_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="不能为其他用户的赛道创建采集任务",
        )
    if not track.enabled:
        raise HTTPException(status_code=409, detail="赛道已停用")
    available = track_keywords(session, track_id=track.id)
    by_id = {item.id: item for item in available}
    selected_ids = list(dict.fromkeys(request.keyword_ids)) or [
        item.id for item in available if item.enabled
    ]
    if not selected_ids:
        raise HTTPException(status_code=422, detail="赛道没有可运行的关键词")
    if any(item_id not in by_id for item_id in selected_ids):
        raise HTTPException(status_code=404, detail="部分关键词不属于该赛道")
    selected = [by_id[item_id] for item_id in selected_ids]
    if any(not item.enabled for item in selected):
        raise HTTPException(status_code=409, detail="选中的关键词包含已停用项目")
    values = [item.keyword for item in selected]
    groups = (
        [[value] for value in values]
        if request.mode == DouyinKeywordBatchMode.separate
        else [values[index : index + 20] for index in range(0, len(values), 20)]
    )
    if request.mode == DouyinKeywordBatchMode.separate and len(groups) > 20:
        raise HTTPException(status_code=422, detail="独立任务模式一次最多创建 20 个任务")
    tasks: list[CrawlTask] = []
    for group in groups:
        task_request = CrawlTaskCreate(
            crawl_type=DouyinCrawlType.search,
            keywords=group,
            max_awemes=request.max_awemes,
            fetch_comments=request.fetch_comments,
            fetch_sub_comments=request.fetch_sub_comments,
            max_comments_per_aweme=request.max_comments_per_aweme,
            request_delay_level=request.request_delay_level,
            publish_time=request.publish_time,
            media_processing_mode=(
                MediaProcessingMode.immediate
                if request.download_media
                else MediaProcessingMode.none
            ),
            download_media=request.download_media,
            translate_subtitles=request.translate_subtitles,
            account_id=request.account_id,
            account_pool_id=request.account_pool_id,
            account_strategy=request.account_strategy,
        )
        try:
            task = await task_manager.create(
                owner_id=current_user.id, request=task_request
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        tasks.append(task)
        session.add(DouyinTrackTaskLink(track_id=track.id, task_id=task.id))
    track.updated_at = get_datetime_utc()
    session.add(track)
    session.commit()
    return DouyinKeywordTaskBatchResult(
        data=[CrawlTaskPublic(**task_public_values(task)) for task in tasks],
        count=len(tasks),
    )
