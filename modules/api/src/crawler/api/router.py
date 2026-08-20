"""API 总路由：汇总所有子路由模块；private 调试路由仅在 local 环境挂载。"""

from crawler.api.routes import (
    douyin,
    douyin_accounts,
    douyin_creators,
    douyin_interactions,
    douyin_keywords,
    douyin_tags,
    douyin_tracks,
    items,
    login,
    private,
    system_docs,
    users,
    utils,
)
from crawler.bootstrap.settings import settings
from fastapi import APIRouter

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)
api_router.include_router(douyin_accounts.router)
api_router.include_router(douyin_interactions.router)
api_router.include_router(douyin_creators.router)
api_router.include_router(douyin_keywords.router)
api_router.include_router(douyin_tags.router)
api_router.include_router(douyin_tracks.router)
api_router.include_router(douyin.router)
api_router.include_router(system_docs.router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
