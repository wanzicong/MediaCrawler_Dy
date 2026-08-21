"""抖音赛道路由：赛道的增删改查、批量删除、关键词挂载/移除与批量创建采集任务。"""

import uuid
from typing import Any, NoReturn

from crawler.api.deps import CurrentUser, SessionDep
from crawler.business.common.models import Message
from crawler.business.douyin.creators.models import (
    DouyinCreatorsPublic,
    DouyinTrackCreatorAdd,
)
from crawler.business.douyin.keywords.models import (
    DouyinBulkDeleteRequest,
    DouyinKeywordsPublic,
    DouyinKeywordTaskBatchResult,
)
from crawler.business.douyin.tracks import query_service, service
from crawler.business.douyin.tracks.models import (
    DouyinTrackCreate,
    DouyinTrackDetailPublic,
    DouyinTrackKeywordAdd,
    DouyinTracksPublic,
    DouyinTrackTaskRequest,
    DouyinTrackUpdate,
)
from fastapi import APIRouter, HTTPException, Query, status

router = APIRouter(prefix="/douyin/tracks", tags=["douyin-tracks"])


def _raise_http_error(exc: service.TrackServiceError) -> NoReturn:
    """把赛道业务异常映射为对应的 HTTP 状态码（404/403/409/422，兜底 500）。"""
    if isinstance(exc, service.TrackNotFoundError):
        status_code = 404
    elif isinstance(exc, service.TrackPermissionDeniedError):
        status_code = 403
    elif isinstance(exc, service.TrackConflictError):
        status_code = 409
    elif isinstance(exc, service.TrackValidationError):
        status_code = 422
    else:
        status_code = 500
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("", response_model=DouyinTracksPublic)
def list_tracks(
    session: SessionDep,
    current_user: CurrentUser,
    search: str | None = Query(default=None, max_length=100),
    enabled: bool | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> Any:
    """分页查询当前用户的赛道列表，支持名称搜索与启用状态过滤。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        search: 按赛道名搜索。
        enabled: 按是否启用过滤。
        skip: 分页偏移量。
        limit: 每页数量。

    返回：
        赛道分页结果。
    """
    return query_service.list_tracks(
        session,
        owner_id=current_user.id,
        search=search,
        enabled=enabled,
        skip=skip,
        limit=limit,
    )


@router.get("/{track_id}", response_model=DouyinTrackDetailPublic)
def get_track(
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> DouyinTrackDetailPublic:
    """获取指定赛道的详情（含关键词挂载情况）。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        track_id: 目标赛道 ID。

    返回：
        赛道详情。
    """
    try:
        return query_service.get_track_detail(
            session,
            track_id=track_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)


@router.post(
    "", response_model=DouyinTrackDetailPublic, status_code=status.HTTP_201_CREATED
)
def add_track(
    request: DouyinTrackCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """创建赛道，可同时挂载一批关键词。

    参数：
        request: 赛道创建参数（名称、描述、提示词、关键词列表）。
        session: 数据库会话依赖。
        current_user: 当前登录用户。

    返回：
        创建成功的赛道详情。
    """
    try:
        return service.create_track_record(
            session,
            owner_id=current_user.id,
            name=request.name,
            description=request.description,
            prompt=request.prompt,
            keywords=request.keywords,
            default_task_config=request.default_task_config,
            reply_templates=request.reply_templates,
            keyword_categories=request.keyword_categories,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)


@router.patch("/{track_id}", response_model=DouyinTrackDetailPublic)
def edit_track(
    request: DouyinTrackUpdate,
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> Any:
    """更新指定赛道的名称、描述、提示词与启用状态。

    参数：
        request: 赛道更新参数。
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        track_id: 目标赛道 ID。

    返回：
        更新后的赛道详情。
    """
    try:
        return service.update_track_record(
            session,
            track_id=track_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
            name=request.name,
            description=request.description,
            prompt=request.prompt,
            enabled=request.enabled,
            default_task_config=request.default_task_config,
            reply_templates=request.reply_templates,
            keyword_categories=request.keyword_categories,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)


@router.delete("/{track_id}")
def delete_track(
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> Message:
    """删除指定赛道（关键词、任务与采集结果保留）。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        track_id: 目标赛道 ID。

    返回：
        删除结果消息。
    """
    try:
        service.delete_track_record(
            session,
            track_id=track_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)
    return Message(message="赛道已删除；关键词、任务和采集结果均已保留")


@router.post("/bulk-delete", response_model=Message)
def bulk_delete_tracks(
    request: DouyinBulkDeleteRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    """批量删除赛道（历史任务与作品保留）。

    参数：
        request: 批量删除请求（赛道 ID 列表）。
        session: 数据库会话依赖。
        current_user: 当前登录用户。

    返回：
        删除数量消息。
    """
    try:
        count = service.delete_track_batch(
            session,
            owner_id=current_user.id,
            track_ids=request.ids,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)
    return Message(message=f"已删除 {count} 个赛道；历史任务和作品均已保留")


@router.get("/{track_id}/keywords", response_model=DouyinKeywordsPublic)
def list_track_keywords(
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> Any:
    """查询指定赛道挂载的关键词列表。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        track_id: 目标赛道 ID。

    返回：
        赛道下的关键词列表。
    """
    try:
        return query_service.list_track_keywords(
            session,
            track_id=track_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)


@router.post("/{track_id}/keywords", response_model=DouyinKeywordsPublic)
def append_track_keywords(
    request: DouyinTrackKeywordAdd,
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> Any:
    """向指定赛道追加挂载一批关键词。

    参数：
        request: 关键词追加请求。
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        track_id: 目标赛道 ID。

    返回：
        追加后的赛道关键词列表。
    """
    try:
        return service.append_track_keyword_records(
            session,
            track_id=track_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
            keywords=request.keywords,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)


@router.delete("/{track_id}/keywords/{keyword_id}")
def remove_track_keyword(
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
    keyword_id: uuid.UUID,
) -> Message:
    """把指定关键词从赛道移除（关键词本身与历史任务不受影响）。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        track_id: 目标赛道 ID。
        keyword_id: 待移除的关键词 ID。

    返回：
        移除结果消息。
    """
    try:
        service.remove_track_keyword_record(
            session,
            track_id=track_id,
            keyword_id=keyword_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)
    return Message(message="关键词已从赛道移除，关键词本身及历史任务不受影响")


@router.get("/{track_id}/creators", response_model=DouyinCreatorsPublic)
def list_track_creators(
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> Any:
    """查询指定赛道挂载的达人名单。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        track_id: 目标赛道 ID。

    返回：
        赛道下的达人列表。
    """
    try:
        return query_service.list_track_creators(
            session,
            track_id=track_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)


@router.post("/{track_id}/creators", response_model=DouyinCreatorsPublic)
def append_track_creators(
    request: DouyinTrackCreatorAdd,
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> Any:
    """向指定赛道追加挂载一批达人（主页链接或 sec_user_id）。

    参数：
        request: 达人追加请求。
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        track_id: 目标赛道 ID。

    返回：
        追加后的赛道达人列表。
    """
    try:
        return service.append_track_creator_records(
            session,
            track_id=track_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
            creators=request.creators,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)


@router.delete("/{track_id}/creators/{creator_id}")
def remove_track_creator(
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
    creator_id: uuid.UUID,
) -> Message:
    """把指定达人从赛道移除（达人本身与历史任务不受影响）。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        track_id: 目标赛道 ID。
        creator_id: 待移除的达人 ID。

    返回：
        移除结果消息。
    """
    try:
        service.remove_track_creator_record(
            session,
            track_id=track_id,
            creator_id=creator_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)
    return Message(message="达人已从赛道移除，达人本身及历史任务不受影响")


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
    """按赛道下挂载的关键词批量创建采集任务（异步受理）。

    参数：
        request: 批量任务请求（采集参数）。
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        track_id: 目标赛道 ID。

    返回：
        批量任务创建结果。
    """
    try:
        return await service.create_track_crawl_tasks(
            session,
            track_id=track_id,
            actor_id=current_user.id,
            is_superuser=current_user.is_superuser,
            request=request,
        )
    except service.TrackServiceError as exc:
        _raise_http_error(exc)
