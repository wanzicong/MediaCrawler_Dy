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
    await task_manager.startup()
    await interaction_manager.startup()
    yield
    await interaction_manager.shutdown()
    await task_manager.shutdown()


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)

# Set all CORS enabled origins
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)
