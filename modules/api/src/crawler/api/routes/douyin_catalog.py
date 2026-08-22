"""抖音评论库与统一内容目录的 HTTP 适配层：评论库查询/导出、作品库查询、任务下作品/评论/行为列表及派生采集任务。"""

from __future__ import annotations

import os
import uuid
from typing import Any, Literal

from crawler.api.deps import CurrentUser, SessionDep
from crawler.business.douyin.comments.exports import (
    build_comment_selection_export,
    build_comments_export,
    build_subtitles_export,
)
from crawler.business.douyin.comments.models import (
    DouyinAwemeCommentCrawlRequest,
    DouyinCommentExportRequest,
    DouyinCommentLibraryPublic,
    DouyinCommentSelectionExportRequest,
    DouyinCommentsPublic,
)
from crawler.business.douyin.comments.query_service import (
    list_comment_library as query_comment_library,
)
from crawler.business.douyin.comments.query_service import (
    list_task_actions as query_task_actions,
)
from crawler.business.douyin.comments.query_service import (
    list_task_comments as query_task_comments,
)
from crawler.business.douyin.content.models import (
    DouyinAwemeCreatorCrawlRequest,
    DouyinAwemesPublic,
    DouyinCreatorOptionsPublic,
    DouyinUserActionsPublic,
)
from crawler.business.douyin.library.models import DouyinWorkPublic, DouyinWorksPublic
from crawler.business.douyin.library.service import (
    create_aweme_comment_recrawl_task,
    create_aweme_creator_crawl_task,
    get_aweme_for_user,
    require_task_access,
)
from crawler.business.douyin.library.service import (
    get_task_work as query_task_work,
)
from crawler.business.douyin.library.service import (
    list_library_creators as query_library_creators,
)
from crawler.business.douyin.library.service import (
    list_library_works as query_library_works,
)
from crawler.business.douyin.library.service import (
    list_task_awemes as query_task_awemes,
)
from crawler.business.douyin.library.service import (
    list_task_works as query_task_works,
)
from crawler.business.douyin.media.models import (
    DouyinSubtitleExportRequest,
    MediaDownloadStatus,
)
from crawler.business.douyin.tasks.models import (
    CrawlTaskPublic,
    DouyinSourceOptionsPublic,
    DouyinSourceType,
)
from crawler.business.douyin.tasks.source_attribution import (
    list_source_options as query_source_options,
)
from crawler.business.errors import (
    InvalidRequestError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

early_router = APIRouter()
late_router = APIRouter()


def _owner_id(current_user: CurrentUser) -> uuid.UUID | None:
    """返回数据归属过滤用的 owner_id；超级管理员返回 None 表示不过滤（可见全部）。"""
    return None if current_user.is_superuser else current_user.id


def _raise_http_error(exc: Exception) -> None:
    """把业务层统一异常映射为对应的 HTTP 状态码（404/403/422），其余异常原样抛出。"""
    if isinstance(exc, ResourceNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PermissionDeniedError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, InvalidRequestError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


def _require_task(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
) -> None:
    """校验当前用户对该任务有访问权限，无权限时抛出对应的 HTTP 异常。"""
    try:
        require_task_access(
            session,
            task_id=task_id,
            owner_id=_owner_id(current_user),
        )
    except (ResourceNotFoundError, PermissionDeniedError, InvalidRequestError) as exc:
        _raise_http_error(exc)


def _get_aweme(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    aweme_id: str,
) -> Any:
    """按权限获取任务下的指定 aweme（视频）记录，失败时抛出对应的 HTTP 异常。"""
    try:
        return get_aweme_for_user(
            session,
            task_id=task_id,
            aweme_id=aweme_id,
            owner_id=_owner_id(current_user),
        )
    except (
        ResourceNotFoundError,
        PermissionDeniedError,
        InvalidRequestError,
    ) as exc:
        _raise_http_error(exc)


@early_router.get("/comments", response_model=DouyinCommentLibraryPublic)
def list_comment_library(
    session: SessionDep,
    current_user: CurrentUser,
    comment_content: str | None = Query(default=None, max_length=200),
    search: str | None = Query(default=None, max_length=200),
    task_id: uuid.UUID | None = None,
    track_id: uuid.UUID | None = None,
    aweme_id: str | None = Query(default=None, max_length=128),
    video_creator: str | None = Query(default=None, max_length=255),
    source_keyword: str | None = Query(default=None, max_length=200),
    source_type: DouyinSourceType | None = None,
    source_id: uuid.UUID | None = None,
    comment_type: Literal["all", "top_level", "reply"] = "all",
    has_pictures: Literal["all", "yes", "no"] = "all",
    min_likes: int | None = Query(default=None, ge=0),
    max_likes: int | None = Query(default=None, ge=0),
    published_from: int | None = Query(default=None, ge=0),
    published_to: int | None = Query(default=None, ge=0),
    sort_by: Literal[
        "published_at", "like_count", "sub_comment_count", "fetched_at"
    ] = "published_at",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> Any:
    """查询跨任务的评论库，支持内容/关键词/创作者/点赞数/时间等多维过滤与排序。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        comment_content: 按评论内容模糊匹配。
        search: 通用搜索关键词。
        task_id: 限定来源任务。
        track_id: 限定来源赛道。
        aweme_id: 限定来源视频。
        video_creator: 按视频创作者过滤。
        source_keyword: 按来源采集关键词过滤。
        comment_type: 评论类型（all/top_level/reply）。
        has_pictures: 是否带图（all/yes/no）。
        min_likes: 最小点赞数。
        max_likes: 最大点赞数。
        published_from: 评论发布时间下界（时间戳）。
        published_to: 评论发布时间上界（时间戳）。
        sort_by: 排序字段。
        sort_order: 排序方向。
        skip: 分页偏移量。
        limit: 每页数量。

    返回：
        评论库分页结果。

    异常：
        HTTPException: 过滤区间不合法（422）或底层权限/资源错误（404/403/422）。
    """
    if min_likes is not None and max_likes is not None and min_likes > max_likes:
        raise HTTPException(status_code=422, detail="最小点赞数不能大于最大点赞数")
    if (
        published_from is not None
        and published_to is not None
        and published_from > published_to
    ):
        raise HTTPException(status_code=422, detail="评论开始时间不能晚于结束时间")
    try:
        return query_comment_library(
            session,
            owner_id=_owner_id(current_user),
            comment_content=comment_content,
            search=search,
            task_id=task_id,
            track_id=track_id,
            aweme_id=aweme_id,
            video_creator=video_creator,
            source_keyword=source_keyword,
            source_type=source_type,
            source_id=source_id,
            comment_type=comment_type,
            has_pictures=has_pictures,
            min_likes=min_likes,
            max_likes=max_likes,
            published_from=published_from,
            published_to=published_to,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=skip,
            limit=limit,
        )
    except (
        ResourceNotFoundError,
        PermissionDeniedError,
        InvalidRequestError,
    ) as exc:
        _raise_http_error(exc)


@early_router.post("/comments/export", response_class=FileResponse)
def export_comment_selection(
    request: DouyinCommentSelectionExportRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> FileResponse:
    """按选中的评论 ID 集合导出评论文本文件；无匹配评论时删除临时文件并返回 404。

    参数：
        request: 导出请求（评论 ID 列表）。
        session: 数据库会话依赖。
        current_user: 当前登录用户。

    返回：
        评论导出文件响应（发送后后台删除临时文件）。

    异常：
        HTTPException: 没有可导出的评论（404）。
    """
    path, filename, exported_count = build_comment_selection_export(
        session,
        owner_id=_owner_id(current_user),
        comment_ids=request.comment_ids,
    )
    if exported_count == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail="没有找到可导出的评论")
    return FileResponse(
        path,
        filename=filename,
        media_type="text/plain; charset=utf-8",
        background=BackgroundTask(os.unlink, path),
        headers={"Cache-Control": "private, no-store"},
    )


@early_router.get("/library/creators", response_model=DouyinCreatorOptionsPublic)
def list_library_creators(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID | None = None,
    track_id: uuid.UUID | None = None,
) -> Any:
    """查询作品库中已下载作品的创作者选项列表（用于筛选下拉框）。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 限定来源任务。
        track_id: 限定来源赛道。

    返回：
        创作者选项列表。
    """
    try:
        return query_library_creators(
            session,
            owner_id=_owner_id(current_user),
            task_id=task_id,
            track_id=track_id,
            downloaded_status=MediaDownloadStatus.downloaded.value,
        )
    except (
        ResourceNotFoundError,
        PermissionDeniedError,
        InvalidRequestError,
    ) as exc:
        _raise_http_error(exc)


@early_router.get("/source-options", response_model=DouyinSourceOptionsPublic)
def list_source_options(
    session: SessionDep,
    current_user: CurrentUser,
    track_id: uuid.UUID,
) -> Any:
    """查询指定赛道下的关键词/作者来源选项；未指定赛道时不返回全量来源。"""
    try:
        return query_source_options(
            session,
            owner_id=_owner_id(current_user),
            track_id=track_id,
        )
    except (ResourceNotFoundError, PermissionDeniedError, InvalidRequestError) as exc:
        _raise_http_error(exc)


@early_router.get("/library/works", response_model=DouyinWorksPublic)
def list_library_works(
    session: SessionDep,
    current_user: CurrentUser,
    search: str | None = Query(default=None, max_length=200),
    task_id: uuid.UUID | None = None,
    track_id: uuid.UUID | None = None,
    source_type: DouyinSourceType | None = None,
    source_id: uuid.UUID | None = None,
    creator_hash: str | None = Query(default=None, max_length=64),
    tag_id: uuid.UUID | None = None,
    download_status: Literal[
        "all", "missing", "queued", "downloading", "downloaded", "failed"
    ] = "downloaded",
    subtitle_status: Literal[
        "all", "pending", "running", "completed", "failed"
    ] = "all",
    storage_backend: Literal["all", "local", "minio"] = "all",
    sort_by: Literal[
        "published_at",
        "liked_count",
        "comment_count",
        "collected_count",
        "persisted_comment_count",
        "downloaded_at",
        "file_size",
        "fetched_at",
    ] = "downloaded_at",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=24, ge=1, le=100),
) -> Any:
    """查询统一作品库，支持搜索、创作者、标签、下载/字幕状态、存储后端过滤与排序。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        search: 搜索关键词。
        task_id: 限定来源任务。
        track_id: 限定来源赛道。
        source_type/source_id: 限定赛道内的关键词或作者来源。
        creator_hash: 按创作者哈希过滤。
        tag_id: 按标签过滤。
        download_status: 媒体下载状态过滤；missing 表示尚未创建下载记录。
        subtitle_status: 字幕处理状态过滤。
        storage_backend: 存储后端过滤（local/minio）。
        sort_by: 排序字段。
        sort_order: 排序方向。
        skip: 分页偏移量。
        limit: 每页数量。

    返回：
        作品库分页结果。
    """
    try:
        return query_library_works(
            session,
            owner_id=_owner_id(current_user),
            search=search,
            task_id=task_id,
            track_id=track_id,
            source_type=source_type,
            source_id=source_id,
            creator_hash=creator_hash,
            tag_id=tag_id,
            download_status=download_status,
            subtitle_status=subtitle_status,
            storage_backend=storage_backend,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=skip,
            limit=limit,
        )
    except (
        ResourceNotFoundError,
        PermissionDeniedError,
        InvalidRequestError,
    ) as exc:
        _raise_http_error(exc)


@late_router.get("/tasks/{task_id}/works", response_model=DouyinWorksPublic)
def list_works(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    search: str | None = Query(default=None, max_length=200),
    tag_id: uuid.UUID | None = None,
    download_status: str | None = Query(default=None, max_length=32),
    subtitle_status: str | None = Query(default=None, max_length=32),
    storage_backend: str | None = Query(default=None, max_length=32),
    sort_by: Literal[
        "published_at",
        "liked_count",
        "comment_count",
        "collected_count",
        "persisted_comment_count",
        "fetched_at",
    ] = "published_at",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> Any:
    """查询指定任务下的作品列表，支持搜索、标签、下载/字幕状态与存储后端过滤。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。
        search: 搜索关键词。
        tag_id: 按标签过滤。
        download_status: 媒体下载状态过滤。
        subtitle_status: 字幕处理状态过滤。
        storage_backend: 存储后端过滤。
        sort_by: 排序字段。
        sort_order: 排序方向。
        skip: 分页偏移量。
        limit: 每页数量。

    返回：
        作品分页结果。
    """
    _require_task(session, current_user, task_id)
    return query_task_works(
        session,
        task_id=task_id,
        search=search,
        tag_id=tag_id,
        download_status=download_status,
        subtitle_status=subtitle_status,
        storage_backend=storage_backend,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )


@late_router.get("/tasks/{task_id}/works/{aweme_id}", response_model=DouyinWorkPublic)
def get_work(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    aweme_id: str,
) -> Any:
    """获取指定任务下单个作品（aweme）的详情。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。
        aweme_id: 抖音视频 ID。

    返回：
        作品详情。
    """
    aweme = _get_aweme(session, current_user, task_id, aweme_id)
    return query_task_work(session, task_id=task_id, aweme=aweme)


@late_router.get("/tasks/{task_id}/awemes", response_model=DouyinAwemesPublic)
def list_awemes(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    sort_by: Literal[
        "published_at", "liked_count", "comment_count", "collected_count", "fetched_at"
    ] = "published_at",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> Any:
    """查询指定任务下的 aweme（视频）列表。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。
        sort_by: 排序字段。
        sort_order: 排序方向。
        skip: 分页偏移量。
        limit: 每页数量。

    返回：
        aweme 分页结果。
    """
    _require_task(session, current_user, task_id)
    return query_task_awemes(
        session,
        task_id=task_id,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )


@late_router.post(
    "/tasks/{task_id}/awemes/{aweme_id}/comments/recrawl",
    response_model=CrawlTaskPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def recrawl_aweme_comments(
    request: DouyinAwemeCommentCrawlRequest,
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    aweme_id: str,
) -> Any:
    """针对任务下某个 aweme 创建评论重采任务（新任务归属当前用户）。

    参数：
        request: 评论重采参数。
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 来源任务 ID。
        aweme_id: 目标视频 ID。

    返回：
        新创建的采集任务。

    异常：
        HTTPException: 资源不存在（404）、无权访问（403）或参数不合法（422）。
    """
    try:
        return await create_aweme_comment_recrawl_task(
            session,
            source_task_id=task_id,
            aweme_id=aweme_id,
            source_owner_id=_owner_id(current_user),
            new_task_owner_id=current_user.id,
            request=request,
        )
    except (ResourceNotFoundError, PermissionDeniedError, InvalidRequestError) as exc:
        _raise_http_error(exc)


@late_router.post(
    "/tasks/{task_id}/awemes/{aweme_id}/creator/crawl",
    response_model=CrawlTaskPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
async def crawl_aweme_creator(
    request: DouyinAwemeCreatorCrawlRequest,
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    aweme_id: str,
) -> Any:
    """针对任务下某个 aweme 的创作者创建主页作品采集任务（新任务归属当前用户）。

    参数：
        request: 创作者采集参数。
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 来源任务 ID。
        aweme_id: 目标视频 ID。

    返回：
        新创建的采集任务。

    异常：
        HTTPException: 资源不存在（404）、无权访问（403）或参数不合法（422）。
    """
    try:
        return await create_aweme_creator_crawl_task(
            session,
            source_task_id=task_id,
            aweme_id=aweme_id,
            source_owner_id=_owner_id(current_user),
            new_task_owner_id=current_user.id,
            request=request,
        )
    except (ResourceNotFoundError, PermissionDeniedError, InvalidRequestError) as exc:
        _raise_http_error(exc)


@late_router.get("/tasks/{task_id}/comments", response_model=DouyinCommentsPublic)
def list_comments(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    aweme_id: str | None = None,
    sort_by: Literal["published_at", "like_count", "fetched_at"] = "published_at",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> Any:
    """查询指定任务下的评论列表，可按 aweme 过滤。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。
        aweme_id: 可选，限定单个视频的评论。
        sort_by: 排序字段。
        sort_order: 排序方向。
        skip: 分页偏移量。
        limit: 每页数量。

    返回：
        评论分页结果。
    """
    _require_task(session, current_user, task_id)
    return query_task_comments(
        session,
        task_id=task_id,
        aweme_id=aweme_id,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )


@late_router.post("/tasks/{task_id}/exports/comments", response_class=FileResponse)
def export_comments(
    request: DouyinCommentExportRequest,
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
) -> FileResponse:
    """导出指定任务下（可按 aweme 列表限定）的评论为文本文件。

    参数：
        request: 导出请求（aweme ID 列表）。
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。

    返回：
        评论导出文件响应（发送后后台删除临时文件）。
    """
    _require_task(session, current_user, task_id)
    path, filename = build_comments_export(
        session, task_id=task_id, aweme_ids=request.aweme_ids
    )
    return FileResponse(
        path,
        filename=filename,
        media_type="text/plain; charset=utf-8",
        background=BackgroundTask(os.unlink, path),
        headers={"Cache-Control": "private, no-store"},
    )


@late_router.post("/tasks/{task_id}/exports/subtitles", response_class=FileResponse)
def export_subtitles(
    request: DouyinSubtitleExportRequest,
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
) -> FileResponse:
    """导出指定任务下作品的字幕文件，支持多种导出格式。

    参数：
        request: 字幕导出请求（aweme ID 列表与格式）。
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。

    返回：
        字幕导出文件响应（发送后后台删除临时文件）。
    """
    _require_task(session, current_user, task_id)
    path, filename, media_type = build_subtitles_export(
        session,
        task_id=task_id,
        aweme_ids=request.aweme_ids,
        export_format=request.format.value,
    )
    return FileResponse(
        path,
        filename=filename,
        media_type=media_type,
        background=BackgroundTask(os.unlink, path),
        headers={"Cache-Control": "private, no-store"},
    )


@late_router.get("/tasks/{task_id}/actions", response_model=DouyinUserActionsPublic)
def list_actions(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> Any:
    """查询指定任务下采集到的用户行为（点赞/收藏等）列表。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        task_id: 目标任务 ID。
        skip: 分页偏移量。
        limit: 每页数量。

    返回：
        用户行为分页结果。
    """
    _require_task(session, current_user, task_id)
    return query_task_actions(session, task_id=task_id, skip=skip, limit=limit)


# 兼容聚合路由：供此前直接 import 本模块的调用方使用
router = APIRouter()
router.include_router(early_router)
router.include_router(late_router)

__all__ = ["early_router", "late_router", "router"]
