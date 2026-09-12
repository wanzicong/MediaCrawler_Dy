"""抖音 API 客户端的异常族（包内统一从 ``crawler.douyin_client.errors`` 导入）。"""

from crawler.douyin_client.errors.family import (
    DataFetchError as DataFetchError,
)
from crawler.douyin_client.errors.family import (
    DouyinError as DouyinError,
)

__all__ = [
    "DataFetchError",
    "DouyinError",
]
