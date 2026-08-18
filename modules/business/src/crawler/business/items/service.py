"""Item 的事务性用例服务。

HTTP 层将所有查询、鉴权决策与事务都委托给本模块处理。
这里的异常刻意不携带任何 HTTP 语义，因此同一批用例也可被 MCP、
定时任务或其他入口适配器直接调用。
"""

import uuid

from crawler.business.identity.models import User
from crawler.business.items.models import Item, ItemCreate, ItemsPublic, ItemUpdate
from sqlmodel import Session, col, func, select


class ItemServiceError(Exception):
    """Item 用例中预期内失败的基类异常。"""


class ItemNotFoundError(ItemServiceError):
    """请求的 Item 不存在。"""


class ItemPermissionDeniedError(ItemServiceError):
    """操作者无权访问请求的 Item。"""


def list_items(
    *,
    session: Session,
    actor: User,
    skip: int = 0,
    limit: int = 100,
) -> ItemsPublic:
    """按既有的「超级管理员可见全部 / 普通用户仅见自有」规则分页列出 Item。

    参数：
        session: 数据库会话。
        actor: 当前操作者。
        skip: 分页偏移量。
        limit: 每页条数上限。

    返回：
        含当前页数据与总数的 ItemsPublic。
    """

    if actor.is_superuser:
        count_statement = select(func.count()).select_from(Item)
        statement = (
            select(Item).order_by(col(Item.created_at).desc()).offset(skip).limit(limit)
        )
    else:
        count_statement = (
            select(func.count()).select_from(Item).where(Item.owner_id == actor.id)
        )
        statement = (
            select(Item)
            .where(Item.owner_id == actor.id)
            .order_by(col(Item.created_at).desc())
            .offset(skip)
            .limit(limit)
        )

    count = session.exec(count_statement).one()
    items = list(session.exec(statement).all())
    return ItemsPublic(data=items, count=count)


def get_item(*, session: Session, actor: User, item_id: uuid.UUID) -> Item:
    """按可见性规则获取单个 Item。

    异常：
        ItemNotFoundError: Item 不存在。
        ItemPermissionDeniedError: 操作者无权访问该 Item。
    """

    item = session.get(Item, item_id)
    if item is None:
        raise ItemNotFoundError
    _ensure_item_access(item=item, actor=actor)
    return item


def create_item(*, session: Session, item_in: ItemCreate, owner_id: uuid.UUID) -> Item:
    """创建 Item 并归属到指定用户。

    参数：
        session: 数据库会话。
        item_in: 创建入参。
        owner_id: 归属用户的 ID。

    返回：
        创建完成并刷新后的 Item 实体。
    """
    db_item = Item.model_validate(item_in, update={"owner_id": owner_id})
    session.add(db_item)
    session.commit()
    session.refresh(db_item)
    return db_item


def update_item(
    *,
    session: Session,
    actor: User,
    item_id: uuid.UUID,
    item_in: ItemUpdate,
) -> Item:
    """按可见性规则更新 Item，仅入参中显式设置的字段会生效。"""

    item = get_item(session=session, actor=actor, item_id=item_id)
    item.sqlmodel_update(item_in.model_dump(exclude_unset=True))
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def delete_item(*, session: Session, actor: User, item_id: uuid.UUID) -> None:
    """按可见性规则删除 Item。"""

    item = get_item(session=session, actor=actor, item_id=item_id)
    session.delete(item)
    session.commit()


def _ensure_item_access(*, item: Item, actor: User) -> None:
    """校验操作者对 Item 的访问权限：超级管理员或 Item 所有者方可访问。"""
    if not actor.is_superuser and item.owner_id != actor.id:
        raise ItemPermissionDeniedError


__all__ = [
    "ItemNotFoundError",
    "ItemPermissionDeniedError",
    "ItemServiceError",
    "create_item",
    "delete_item",
    "get_item",
    "list_items",
    "update_item",
]
