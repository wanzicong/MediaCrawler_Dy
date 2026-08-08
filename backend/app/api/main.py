from fastapi import APIRouter

from app.api.routes import douyin, douyin_accounts, items, login, private, users, utils
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)
api_router.include_router(douyin_accounts.router)
api_router.include_router(douyin.router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
