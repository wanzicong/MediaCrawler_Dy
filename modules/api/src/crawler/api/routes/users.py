import uuid
from typing import Any

from crawler.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)
from crawler.business.common.models import Message
from crawler.business.identity import service as identity_service
from crawler.business.identity.models import (
    UpdatePassword,
    UserCreate,
    UserPublic,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UsersPublic,
)
def read_users(session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
    """
    Retrieve users.
    """

    return identity_service.list_users(session=session, skip=skip, limit=limit)


@router.post(
    "/", dependencies=[Depends(get_current_active_superuser)], response_model=UserPublic
)
def create_user(*, session: SessionDep, user_in: UserCreate) -> Any:
    """
    Create new user.
    """
    try:
        return identity_service.create_managed_user(session=session, user_in=user_in)
    except identity_service.EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        ) from exc


@router.patch("/me", response_model=UserPublic)
def update_user_me(
    *, session: SessionDep, user_in: UserUpdateMe, current_user: CurrentUser
) -> Any:
    """
    Update own user.
    """

    try:
        return identity_service.update_current_user(
            session=session,
            current_user=current_user,
            user_in=user_in,
        )
    except identity_service.EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409, detail="User with this email already exists"
        ) from exc


@router.patch("/me/password", response_model=Message)
def update_password_me(
    *, session: SessionDep, body: UpdatePassword, current_user: CurrentUser
) -> Any:
    """
    Update own password.
    """
    try:
        identity_service.update_current_password(
            session=session,
            current_user=current_user,
            body=body,
        )
    except identity_service.IncorrectPasswordError as exc:
        raise HTTPException(status_code=400, detail="Incorrect password") from exc
    except identity_service.PasswordReuseError as exc:
        raise HTTPException(
            status_code=400, detail="New password cannot be the same as the current one"
        ) from exc
    return Message(message="Password updated successfully")


@router.get("/me", response_model=UserPublic)
def read_user_me(current_user: CurrentUser) -> Any:
    """
    Get current user.
    """
    return current_user


@router.delete("/me", response_model=Message)
def delete_user_me(session: SessionDep, current_user: CurrentUser) -> Any:
    """
    Delete own user.
    """
    try:
        identity_service.delete_current_user(
            session=session,
            current_user=current_user,
        )
    except identity_service.SelfDeletionForbiddenError as exc:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        ) from exc
    return Message(message="User deleted successfully")


@router.post("/signup", response_model=UserPublic)
def register_user(session: SessionDep, user_in: UserRegister) -> Any:
    """
    Create new user without the need to be logged in.
    """
    try:
        return identity_service.register_user(session=session, user_in=user_in)
    except identity_service.EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system",
        ) from exc


@router.get("/{user_id}", response_model=UserPublic)
def read_user_by_id(
    user_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    """
    Get a specific user by id.
    """
    try:
        return identity_service.get_visible_user(
            session=session,
            current_user=current_user,
            user_id=user_id,
        )
    except identity_service.InsufficientPrivilegesError as exc:
        raise HTTPException(
            status_code=403,
            detail="The user doesn't have enough privileges",
        ) from exc
    except identity_service.UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="User not found") from exc


@router.patch(
    "/{user_id}",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UserPublic,
)
def update_user(
    *,
    session: SessionDep,
    user_id: uuid.UUID,
    user_in: UserUpdate,
) -> Any:
    """
    Update a user.
    """

    try:
        return identity_service.update_managed_user(
            session=session,
            user_id=user_id,
            user_in=user_in,
        )
    except identity_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="The user with this id does not exist in the system",
        ) from exc
    except identity_service.EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409, detail="User with this email already exists"
        ) from exc


@router.delete("/{user_id}", dependencies=[Depends(get_current_active_superuser)])
def delete_user(
    session: SessionDep, current_user: CurrentUser, user_id: uuid.UUID
) -> Message:
    """
    Delete a user.
    """
    try:
        identity_service.delete_managed_user(
            session=session,
            current_user=current_user,
            user_id=user_id,
        )
    except identity_service.UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="User not found") from exc
    except identity_service.SelfDeletionForbiddenError as exc:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        ) from exc
    return Message(message="User deleted successfully")
