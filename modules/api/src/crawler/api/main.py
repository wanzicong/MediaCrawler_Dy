"""FastAPI 应用入口：创建 app 实例、配置生命周期、Sentry、CORS 并挂载 API 路由。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sentry_sdk
from crawler.api.router import api_router
from crawler.bootstrap.logging import configure_sensitive_transport_logging
from crawler.bootstrap.settings import settings
from crawler.business.douyin.interactions.service import interaction_manager
from crawler.business.douyin.tasks.service import task_manager
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

configure_sensitive_transport_logging()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """应用生命周期管理：启动时拉起任务管理与互动管理后台服务，关闭时反向优雅停止。

    参数：
        _: FastAPI 应用实例（未使用）。
    """
    if settings.TESTING:
        # 测试库会复制用户数据，其中可能包含中断或运行中的任务。测试服务不得恢复
        # 这些任务，否则会触发真实浏览器、下载或互动操作。
        yield
        return

    await task_manager.startup()
    await interaction_manager.startup()
    yield
    await interaction_manager.shutdown()
    await task_manager.shutdown()


def custom_generate_unique_id(route: APIRoute) -> str:
    """为 OpenAPI 生成稳定的 operationId：取路由首个 tag 与路由名拼接。

    参数：
        route: FastAPI 路由对象。

    返回：
        形如「tag-路由名」的唯一 ID。
    """
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)

# 注册所有启用 CORS 的来源
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)
