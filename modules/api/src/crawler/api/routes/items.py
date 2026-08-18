"""示例 Item 资源路由：提供通用的增删改查接口模板（框架自带示例资源）。"""

import uuid
from typing import Any

from crawler.api.deps import CurrentUser, SessionDep
from crawler.business.common.models import Message
from crawler.business.items import service as item_service
from crawler.business.items.models import (
    ItemCreate,
    ItemPublic,
    ItemsPublic,
    ItemUpdate,
)
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/items", tags=["items"])


@router.get("/", response_model=ItemsPublic)
def read_items(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
) -> Any:
    """查询 Item 列表（超级管理员可见全部，普通用户仅可见自己的）。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        skip: 分页偏移量。
        limit: 每页数量。

    返回：
        Item 分页结果。
    """

    return item_service.list_items(
        session=session,
        actor=current_user,
        skip=skip,
        limit=limit,
    )


@router.get("/{id}", response_model=ItemPublic)
def read_item(session: SessionDep, current_user: CurrentUser, id: uuid.UUID) -> Any:
    """按 ID 获取单个 Item。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        id: 目标 Item 的 ID。

    返回：
        Item 详情。

    异常：
        HTTPException: Item 不存在（404）或无权访问（403）。
    """
    try:
        return item_service.get_item(
            session=session,
            actor=current_user,
            item_id=id,
        )
    except item_service.ItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Item not found") from exc
    except item_service.ItemPermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail="Not enough permissions") from exc


@router.post("/", response_model=ItemPublic)
def create_item(
    *, session: SessionDep, current_user: CurrentUser, item_in: ItemCreate
) -> Any:
    """创建新 Item，归属当前用户。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        item_in: Item 创建参数。

    返回：
        创建成功的 Item。
    """
    return item_service.create_item(
        session=session,
        item_in=item_in,
        owner_id=current_user.id,
    )


@router.put("/{id}", response_model=ItemPublic)
def update_item(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    item_in: ItemUpdate,
) -> Any:
    """更新指定 Item。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        id: 目标 Item 的 ID。
        item_in: Item 更新参数。

    返回：
        更新后的 Item。

    异常：
        HTTPException: Item 不存在（404）或无权操作（403）。
    """
    try:
        return item_service.update_item(
            session=session,
            actor=current_user,
            item_id=id,
            item_in=item_in,
        )
    except item_service.ItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Item not found") from exc
    except item_service.ItemPermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail="Not enough permissions") from exc


@router.delete("/{id}")
def delete_item(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    """删除指定 Item。

    参数：
        session: 数据库会话依赖。
        current_user: 当前登录用户。
        id: 目标 Item 的 ID。

    返回：
        删除结果消息。

    异常：
        HTTPException: Item 不存在（404）或无权操作（403）。
    """
    try:
        item_service.delete_item(
            session=session,
            actor=current_user,
            item_id=id,
        )
    except item_service.ItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Item not found") from exc
    except item_service.ItemPermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail="Not enough permissions") from exc
    return Message(message="Item deleted successfully")
