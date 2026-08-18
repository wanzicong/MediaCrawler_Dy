from typing import Any

from crawler.api.deps import SessionDep
from crawler.business.identity.models import UserPublic
from crawler.business.identity.service import create_private_user
from fastapi import APIRouter
from pydantic import BaseModel

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
