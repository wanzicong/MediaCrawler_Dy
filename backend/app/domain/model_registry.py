"""Single import point that registers every SQLModel table.

Alembic, application bootstrap, and tests must import this module before
reading ``SQLModel.metadata``.  Import order follows foreign-key dependencies.
"""

from sqlmodel import SQLModel

from app.domain.douyin.accounts import models as account_models  # noqa: F401
from app.domain.douyin.comments import models as comment_models  # noqa: F401
from app.domain.douyin.content import models as content_models  # noqa: F401
from app.domain.douyin.interactions import models as interaction_models  # noqa: F401
from app.domain.douyin.keywords import models as keyword_models  # noqa: F401
from app.domain.douyin.media import models as media_models  # noqa: F401
from app.domain.douyin.tags import models as tag_models  # noqa: F401
from app.domain.douyin.tasks import models as task_models  # noqa: F401
from app.domain.douyin.tracks import models as track_models  # noqa: F401
from app.domain.identity import models as identity_models  # noqa: F401
from app.domain.items import models as item_models  # noqa: F401

metadata = SQLModel.metadata

__all__ = ["metadata"]
