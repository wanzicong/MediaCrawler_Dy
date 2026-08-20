"""所有 SQLModel 数据表的统一注册入口。

Alembic 迁移、应用启动流程与测试在读取 ``SQLModel.metadata`` 之前，
都必须先导入本模块。导入顺序遵循外键依赖关系。
"""

from crawler.business.douyin.accounts import models as account_models  # noqa: F401
from crawler.business.douyin.comments import models as comment_models  # noqa: F401
from crawler.business.douyin.content import models as content_models  # noqa: F401
from crawler.business.douyin.creators import models as creator_models  # noqa: F401
from crawler.business.douyin.interactions import (
    models as interaction_models,  # noqa: F401
)
from crawler.business.douyin.keywords import models as keyword_models  # noqa: F401
from crawler.business.douyin.media import models as media_models  # noqa: F401
from crawler.business.douyin.request_logs import (
    models as request_log_models,  # noqa: F401
)
from crawler.business.douyin.tags import models as tag_models  # noqa: F401
from crawler.business.douyin.tasks import models as task_models  # noqa: F401
from crawler.business.douyin.tracks import models as track_models  # noqa: F401
from crawler.business.identity import models as identity_models  # noqa: F401
from crawler.business.items import models as item_models  # noqa: F401
from sqlmodel import SQLModel

# 全量表注册完成后的共享 metadata，供 Alembic autogenerate 与应用启动建表使用
metadata = SQLModel.metadata

__all__ = ["metadata"]
