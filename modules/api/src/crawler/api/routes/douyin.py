"""抖音总路由：聚合 catalog、media、tasks 三个纯 HTTP 适配子路由，并对外再导出路由函数与服务单例。"""

from crawler.api.routes.douyin_catalog import (
    crawl_aweme_creator,
    export_comment_selection,
    export_comments,
    export_subtitles,
    get_work,
    list_actions,
    list_awemes,
    list_comment_library,
    list_comments,
    list_library_creators,
    list_library_works,
    list_source_options,
    list_works,
    recrawl_aweme_comments,
)
from crawler.api.routes.douyin_catalog import (
    early_router as catalog_early_router,
)
from crawler.api.routes.douyin_catalog import (
    late_router as catalog_late_router,
)
from crawler.api.routes.douyin_media import (
    create_media_preview_session,
    download_media_file,
    get_media_summary,
    list_media,
    list_media_tasks,
    migrate_library_media_to_minio,
    migrate_media_to_minio,
    preview_media_file,
    process_media,
    retranslate_media,
    retry_media,
)
from crawler.api.routes.douyin_media import (
    library_router as media_library_router,
)
from crawler.api.routes.douyin_media import (
    router as media_router,
)
from crawler.api.routes.douyin_request_logs import router as request_log_router
from crawler.api.routes.douyin_tasks import (
    cancel_task,
    create_task,
    get_qrcode,
    get_task,
    list_task_shards,
    list_tasks,
    resume_task,
)
from crawler.api.routes.douyin_tasks import (
    creation_router as task_creation_router,
)
from crawler.api.routes.douyin_tasks import (
    delivery_router as task_delivery_router,
)
from crawler.api.routes.douyin_tasks import (
    management_router as task_management_router,
)
from crawler.business.douyin.media.migration import media_migration_manager
from crawler.business.douyin.media.pipeline import media_manager
from crawler.business.douyin.media.storage import media_storage
from crawler.business.douyin.tasks.service import task_manager
from fastapi import APIRouter

router = APIRouter(prefix="/douyin", tags=["douyin"])

# 保持重构前的注册顺序不变，保证生成的客户端与接口文档稳定
router.include_router(task_creation_router)
router.include_router(catalog_early_router)
router.include_router(media_library_router)
router.include_router(task_management_router)
router.include_router(media_router)
router.include_router(task_delivery_router)
router.include_router(catalog_late_router)
router.include_router(request_log_router)

__all__ = [
    "cancel_task",
    "crawl_aweme_creator",
    "create_media_preview_session",
    "create_task",
    "download_media_file",
    "export_comment_selection",
    "export_comments",
    "export_subtitles",
    "get_media_summary",
    "get_qrcode",
    "get_task",
    "get_work",
    "list_actions",
    "list_awemes",
    "list_comment_library",
    "list_comments",
    "list_library_creators",
    "list_library_works",
    "list_source_options",
    "list_media",
    "list_media_tasks",
    "list_task_shards",
    "list_tasks",
    "list_works",
    "media_manager",
    "media_migration_manager",
    "media_storage",
    "migrate_library_media_to_minio",
    "migrate_media_to_minio",
    "preview_media_file",
    "process_media",
    "recrawl_aweme_comments",
    "resume_task",
    "retranslate_media",
    "retry_media",
    "router",
    "task_manager",
]
