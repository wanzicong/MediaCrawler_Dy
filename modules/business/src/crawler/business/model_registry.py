"""Single import point that registers every SQLModel table.

Alembic, application bootstrap, and tests must import this module before
reading ``SQLModel.metadata``.  Import order follows foreign-key dependencies.
"""

from crawler.business.douyin.accounts import models as account_models  # noqa: F401
from crawler.business.douyin.comments import models as comment_models  # noqa: F401
from crawler.business.douyin.content import models as content_models  # noqa: F401
from crawler.business.douyin.interactions import (
    models as interaction_models,  # noqa: F401
)
from crawler.business.douyin.keywords import models as keyword_models  # noqa: F401
from crawler.business.douyin.media import models as media_models  # noqa: F401
from crawler.business.douyin.tags import models as tag_models  # noqa: F401
from crawler.business.douyin.tasks import models as task_models  # noqa: F401
from crawler.business.douyin.tracks import models as track_models  # noqa: F401
from crawler.business.identity import models as identity_models  # noqa: F401
from crawler.business.items import models as item_models  # noqa: F401
from sqlmodel import SQLModel

metadata = SQLModel.metadata

__all__ = ["metadata"]
