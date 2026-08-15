import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, SessionDep
from app.application.items import service as item_service
from app.domain.common.models import Message
from app.domain.items.models import (
    ItemCreate,
    ItemPublic,
    ItemsPublic,
    ItemUpdate,
)

router = APIRouter(prefix="/items", tags=["items"])


@router.get("/", response_model=ItemsPublic)
def read_items(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
) -> Any:
    """
    Retrieve items.
    """

    return item_service.list_items(
        session=session,
        actor=current_user,
        skip=skip,
        limit=limit,
    )


@router.get("/{id}", response_model=ItemPublic)
def read_item(session: SessionDep, current_user: CurrentUser, id: uuid.UUID) -> Any:
    """
    Get item by ID.
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
    """
    Create new item.
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
    """
    Update an item.
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
    """
    Delete an item.
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
