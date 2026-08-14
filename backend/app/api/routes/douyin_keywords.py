import uuid
from typing import Any, Literal

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
    DouyinKeyword,
    DouyinKeywordBatchMode,
    DouyinKeywordBatchTaskRequest,
    DouyinKeywordBulkCreateRequest,
    DouyinKeywordBulkCreateResult,
    DouyinKeywordPublic,
    DouyinKeywordsPublic,
    DouyinKeywordStatus,
    DouyinKeywordSyncResult,
    DouyinKeywordSyncSource,
    DouyinKeywordTaskBatchResult,
    DouyinKeywordUpdate,
    Message,
)
from app.services.douyin_keywords import (
    build_keyword_public_rows,
    create_keywords,
    keyword_tasks,
    sync_history,
    sync_task,
    update_keyword,
)
from app.services.douyin_tasks import task_manager

router = APIRouter(prefix="/douyin/keywords", tags=["douyin-keywords"])


def _get_keyword(
    session: SessionDep, current_user: CurrentUser, keyword_id: uuid.UUID
) -> DouyinKeyword:
    item = session.get(DouyinKeyword, keyword_id)
    if not item:
        raise HTTPException(status_code=404, detail="关键词不存在")
    if item.owner_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return item


def _get_task(
    session: SessionDep, current_user: CurrentUser, task_id: uuid.UUID
) -> CrawlTask:
    task = session.get(CrawlTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="抖音任务不存在")
    if task.owner_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return task


@router.get("/", response_model=DouyinKeywordsPublic)
def list_keywords(
    session: SessionDep,
    current_user: CurrentUser,
    search: str | None = Query(default=None, max_length=200),
    keyword_status: DouyinKeywordStatus | None = Query(default=None, alias="status"),
    enabled: bool | None = None,
    sort_by: Literal[
        "keyword", "status", "task_count", "aweme_count", "last_crawled_at", "created_at"
    ] = "last_crawled_at",
    sort_order: Literal["asc", "desc"] = "desc",
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    rows = build_keyword_public_rows(
        session, owner_id=current_user.id, search=search
    )
    if keyword_status:
        rows = [item for item in rows if item.status == keyword_status]
    if enabled is not None:
        rows = [item for item in rows if item.enabled == enabled]
    status_order = {
        DouyinKeywordStatus.active: 0,
        DouyinKeywordStatus.failed: 1,
        DouyinKeywordStatus.unprocessed: 2,
        DouyinKeywordStatus.crawled: 3,
    }
    def sort_key(item: DouyinKeywordPublic) -> str | int | float:
        if sort_by == "keyword":
            return item.keyword.casefold()
        if sort_by == "status":
            return status_order[item.status]
        if sort_by == "task_count":
            return item.task_count
        if sort_by == "aweme_count":
            return item.aweme_count
        if sort_by == "created_at":
            return item.created_at.timestamp()
        return item.last_crawled_at.timestamp() if item.last_crawled_at else 0

    rows.sort(key=sort_key, reverse=sort_order == "desc")
    return DouyinKeywordsPublic(data=rows[skip : skip + limit], count=len(rows))


@router.post(
    "/bulk", response_model=DouyinKeywordBulkCreateResult, status_code=status.HTTP_201_CREATED
)
def bulk_create_keywords(
    request: DouyinKeywordBulkCreateRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    items, created, existing = create_keywords(
        session,
        owner_id=current_user.id,
        values=request.keywords,
        notes=request.notes,
        enabled=request.enabled,
    )
    session.commit()
    rows = build_keyword_public_rows(session, owner_id=current_user.id)
    by_id = {item.id: item for item in rows}
    return DouyinKeywordBulkCreateResult(
        data=[by_id[item.id] for item in items],
        created_count=created,
        existing_count=existing,
    )


@router.patch("/by-id/{keyword_id}", response_model=DouyinKeywordPublic)
def edit_keyword(
    request: DouyinKeywordUpdate,
    session: SessionDep,
    current_user: CurrentUser,
    keyword_id: uuid.UUID,
) -> Any:
    item = update_keyword(
        session,
        item=_get_keyword(session, current_user, keyword_id),
        keyword=request.keyword,
        enabled=request.enabled,
        notes=request.notes,
    )
    owner_id = item.owner_id
    session.commit()
    return next(
        row
        for row in build_keyword_public_rows(session, owner_id=owner_id)
        if row.id == keyword_id
    )


@router.delete("/by-id/{keyword_id}")
def delete_keyword(
    session: SessionDep,
    current_user: CurrentUser,
    keyword_id: uuid.UUID,
) -> Message:
    session.delete(_get_keyword(session, current_user, keyword_id))
    session.commit()
    return Message(message="关键词已删除；关联任务和爬取结果均已保留")


@router.post("/bulk-delete", response_model=Message)
def bulk_delete_keywords(
    request: DouyinBulkDeleteRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    rows = session.exec(
        select(DouyinKeyword).where(
            DouyinKeyword.owner_id == current_user.id,
            col(DouyinKeyword.id).in_(request.ids),
        )
    ).all()
    for row in rows:
        session.delete(row)
    session.commit()
    return Message(message=f"已删除 {len(rows)} 个关键词；历史任务和作品均已保留")


@router.get("/by-id/{keyword_id}/tasks", response_model=list[CrawlTaskPublic])
def list_keyword_tasks(
    session: SessionDep,
    current_user: CurrentUser,
    keyword_id: uuid.UUID,
) -> Any:
    item = _get_keyword(session, current_user, keyword_id)
    return [
        CrawlTaskPublic(**task_public_values(task))
        for task in keyword_tasks(session, keyword_id=item.id)
    ]


@router.post("/sync/tasks/{task_id}", response_model=DouyinKeywordSyncResult)
def sync_keywords_from_task(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
) -> Any:
    task = _get_task(session, current_user, task_id)
    keyword_count, created, bound = sync_task(
        session, task=task, source=DouyinKeywordSyncSource.manual
    )
    if not keyword_count:
        raise HTTPException(status_code=422, detail="该任务没有可同步的搜索关键词")
    session.commit()
    return DouyinKeywordSyncResult(
        task_count=1,
        keyword_count=keyword_count,
        created_count=created,
        binding_count=bound,
    )


@router.post("/sync/history", response_model=DouyinKeywordSyncResult)
def sync_historical_keywords(
    session: SessionDep, current_user: CurrentUser
) -> Any:
    task_count, keyword_count, created, bound = sync_history(
        session, owner_id=current_user.id
    )
    session.commit()
    return DouyinKeywordSyncResult(
        task_count=task_count,
        keyword_count=keyword_count,
        created_count=created,
        binding_count=bound,
    )


@router.post(
    "/batch-tasks",
    response_model=DouyinKeywordTaskBatchResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_keyword_tasks(
    request: DouyinKeywordBatchTaskRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    unique_ids = list(dict.fromkeys(request.keyword_ids))
    keywords = session.exec(
        select(DouyinKeyword).where(
            DouyinKeyword.owner_id == current_user.id,
            col(DouyinKeyword.id).in_(unique_ids),
        )
    ).all()
    by_id = {item.id: item for item in keywords}
    if len(by_id) != len(unique_ids):
        raise HTTPException(status_code=404, detail="部分关键词不存在或无权访问")
    disabled = [by_id[item_id].keyword for item_id in unique_ids if not by_id[item_id].enabled]
    if disabled:
        raise HTTPException(status_code=409, detail="选中的关键词包含已停用项目")
    values = [by_id[item_id].keyword for item_id in unique_ids]
    if request.mode == DouyinKeywordBatchMode.separate:
        if len(values) > 20:
            raise HTTPException(status_code=422, detail="独立任务模式一次最多创建 20 个任务")
        groups = [[value] for value in values]
    else:
        groups = [values[index : index + 20] for index in range(0, len(values), 20)]

    tasks: list[CrawlTask] = []
    for group in groups:
        task_request = CrawlTaskCreate(
            crawl_type=DouyinCrawlType.search,
            login_type=request.login_type,
            browser_mode=request.browser_mode,
            keywords=group,
            start_page=request.start_page,
            max_awemes=request.max_awemes,
            fetch_comments=request.fetch_comments,
            fetch_sub_comments=request.fetch_sub_comments,
            max_comments_per_aweme=request.max_comments_per_aweme,
            concurrency=request.concurrency,
            request_delay_level=request.request_delay_level,
            request_interval_seconds=request.request_interval_seconds,
            publish_time=request.publish_time,
            media_processing_mode=request.media_processing_mode,
            media_storage=request.media_storage,
            download_media=request.download_media,
            translate_subtitles=request.translate_subtitles,
            transcription_language=request.transcription_language,
            account_id=request.account_id,
            account_pool_id=request.account_pool_id,
            account_strategy=request.account_strategy,
        )
        try:
            tasks.append(
                await task_manager.create(owner_id=current_user.id, request=task_request)
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DouyinKeywordTaskBatchResult(
        data=[CrawlTaskPublic(**task_public_values(task)) for task in tasks],
        count=len(tasks),
    )
