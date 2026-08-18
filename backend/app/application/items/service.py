"""Transactional item use cases.

The HTTP layer delegates every query, authorization decision, and transaction to
this module.  The exceptions deliberately carry no HTTP semantics so the same use
cases can also be called from MCP, jobs, or another inbound adapter.
"""

import uuid

from sqlmodel import Session, col, func, select

from app.domain.identity.models import User
from app.domain.items.models import Item, ItemCreate, ItemsPublic, ItemUpdate


class ItemServiceError(Exception):
    """Base class for expected item use-case failures."""


class ItemNotFoundError(ItemServiceError):
    """The requested item does not exist."""


class ItemPermissionDeniedError(ItemServiceError):
    """The actor is not allowed to access the requested item."""


def list_items(
    *,
    session: Session,
    actor: User,
    skip: int = 0,
    limit: int = 100,
) -> ItemsPublic:
    """List visible items using the existing superuser/owner rules."""

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
    """Return an item after applying the existing visibility rule."""

    item = session.get(Item, item_id)
    if item is None:
        raise ItemNotFoundError
    _ensure_item_access(item=item, actor=actor)
    return item


def create_item(*, session: Session, item_in: ItemCreate, owner_id: uuid.UUID) -> Item:
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
    """Update an item after applying the existing visibility rule."""

    item = get_item(session=session, actor=actor, item_id=item_id)
    item.sqlmodel_update(item_in.model_dump(exclude_unset=True))
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def delete_item(*, session: Session, actor: User, item_id: uuid.UUID) -> None:
    """Delete an item after applying the existing visibility rule."""

    item = get_item(session=session, actor=actor, item_id=item_id)
    session.delete(item)
    session.commit()


def _ensure_item_access(*, item: Item, actor: User) -> None:
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
