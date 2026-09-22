"""抖音内容分类路由：两级分类树维护、视频/达人批量归类与筛选。

分类是用户自建的运营标签体系（最多两级），归类的对象是平台作品号与达人名单 ID，
因此归类结果跨任务有效。所有接口都按当前登录用户隔离，超管也不能读取他人分类。
"""

import uuid
from typing import Any

from crawler.api.deps import CurrentUser, SessionDep
from crawler.business.douyin.categories.models import (
    DouyinCategoriesPublic,
    DouyinCategoryAssignRequest,
    DouyinCategoryAssignResult,
    DouyinCategoryCreate,
    DouyinCategoryPublic,
    DouyinCategoryUpdate,
)
from crawler.business.douyin.categories.service import (
    assign_items,
    create_category,
    delete_category,
    list_categories,
    update_category,
)
from crawler.business.errors import (
    ConflictError,
    InvalidRequestError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from fastapi import APIRouter, HTTPException, Response, status

router = APIRouter(prefix="/categories", tags=["douyin-categories"])


def _raise_http_error(exc: Exception) -> None:
    """把业务层统一异常映射为对应的 HTTP 状态码（404/403/422/409）。"""
    if isinstance(exc, ResourceNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PermissionDeniedError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, ConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, InvalidRequestError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.get("", response_model=DouyinCategoriesPublic)
def list_categories_route(
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """列出当前用户的全部内容分类（扁平列表，前端按 parent_id 组树）。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。

    返回：
        分类列表（含直接归类的视频数/达人数）与总数。
    """
    return list_categories(session, owner_id=current_user.id)


@router.post(
    "", response_model=DouyinCategoryPublic, status_code=status.HTTP_201_CREATED
)
def create_category_route(
    session: SessionDep,
    current_user: CurrentUser,
    request: DouyinCategoryCreate,
) -> Any:
    """新建内容分类；parent_id 为空表示一级大类，最多两级。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        request: 分类创建参数（名称、父分类、描述、排序）。

    返回：
        新建的分类。

    异常：
        HTTPException: 404 父分类不存在、409 同级同名、422 层级超限。
    """
    try:
        return create_category(session, owner_id=current_user.id, request=request)
    except (
        ResourceNotFoundError,
        PermissionDeniedError,
        ConflictError,
        InvalidRequestError,
    ) as exc:
        _raise_http_error(exc)


@router.patch("/{category_id}", response_model=DouyinCategoryPublic)
def update_category_route(
    session: SessionDep,
    current_user: CurrentUser,
    category_id: uuid.UUID,
    request: DouyinCategoryUpdate,
) -> Any:
    """重命名分类、调整层级或排序。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        category_id: 目标分类 ID。
        request: 待更新字段（全部可选）。

    返回：
        更新后的分类。

    异常：
        HTTPException: 404 分类不存在、409 同级同名、422 层级非法。
    """
    try:
        return update_category(
            session,
            owner_id=current_user.id,
            category_id=category_id,
            name=request.name,
            parent_id=request.parent_id,
            description=request.description,
            sort_order=request.sort_order,
        )
    except (
        ResourceNotFoundError,
        PermissionDeniedError,
        ConflictError,
        InvalidRequestError,
    ) as exc:
        _raise_http_error(exc)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category_route(
    session: SessionDep,
    current_user: CurrentUser,
    category_id: uuid.UUID,
) -> Response:
    """删除分类；其子分类与归类关系一并删除，视频/达人本身不受影响。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        category_id: 目标分类 ID。

    返回：
        空响应体（204）。

    异常：
        HTTPException: 404 分类不存在或无权访问。
    """
    try:
        delete_category(session, owner_id=current_user.id, category_id=category_id)
    except (ResourceNotFoundError, PermissionDeniedError) as exc:
        _raise_http_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{category_id}/items", response_model=DouyinCategoryAssignResult)
def assign_category_items_route(
    session: SessionDep,
    current_user: CurrentUser,
    category_id: uuid.UUID,
    request: DouyinCategoryAssignRequest,
) -> Any:
    """把视频/达人加入指定分类（已在那里的幂等跳过）。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        category_id: 目标分类 ID。
        request: 待归类的平台作品号与达人 ID 列表。

    返回：
        本次新增归类数量。

    异常：
        HTTPException: 404 分类不存在或无权访问。
    """
    try:
        return assign_items(
            session,
            owner_id=current_user.id,
            category_id=category_id,
            aweme_ids=request.aweme_ids,
            creator_ids=request.creator_ids,
            attach=True,
        )
    except (ResourceNotFoundError, PermissionDeniedError) as exc:
        _raise_http_error(exc)


@router.delete("/{category_id}/items", response_model=DouyinCategoryAssignResult)
def unassign_category_items_route(
    session: SessionDep,
    current_user: CurrentUser,
    category_id: uuid.UUID,
    request: DouyinCategoryAssignRequest,
) -> Any:
    """把视频/达人移出指定分类。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        category_id: 目标分类 ID。
        request: 待移出的平台作品号与达人 ID 列表。

    返回：
        本次移除归类数量。

    异常：
        HTTPException: 404 分类不存在或无权访问。
    """
    try:
        return assign_items(
            session,
            owner_id=current_user.id,
            category_id=category_id,
            aweme_ids=request.aweme_ids,
            creator_ids=request.creator_ids,
            attach=False,
        )
    except (ResourceNotFoundError, PermissionDeniedError) as exc:
        _raise_http_error(exc)


__all__ = ["router"]
