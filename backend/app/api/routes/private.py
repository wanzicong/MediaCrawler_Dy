from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import SessionDep
from app.application.identity.service import create_private_user
from app.domain.identity.models import UserPublic

router = APIRouter(tags=["private"], prefix="/private")


class PrivateUserCreate(BaseModel):
    email: str
    password: str
    full_name: str
    is_verified: bool = False


@router.post("/users/", response_model=UserPublic)
def create_user(user_in: PrivateUserCreate, session: SessionDep) -> Any:
    """
    Create a new user.
    """

    return create_private_user(
        session=session,
        email=user_in.email,
        password=user_in.password,
        full_name=user_in.full_name,
    )
