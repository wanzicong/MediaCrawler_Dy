"""隐私脱敏与字段映射：标识匿名化、昵称打码与作品/评论结构映射。"""

from crawler.douyin_client.privacy.mapping import (
    map_aweme as map_aweme,
)
from crawler.douyin_client.privacy.mapping import (
    map_comment as map_comment,
)
from crawler.douyin_client.privacy.masking import (
    anonymize_account_id as anonymize_account_id,
)
from crawler.douyin_client.privacy.masking import (
    anonymize_user_id as anonymize_user_id,
)
from crawler.douyin_client.privacy.masking import (
    mask_nickname as mask_nickname,
)

__all__ = [
    "anonymize_account_id",
    "anonymize_user_id",
    "map_aweme",
    "map_comment",
    "mask_nickname",
]
