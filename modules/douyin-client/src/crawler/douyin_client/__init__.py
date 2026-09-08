"""抖音底层传输与签名适配层（公共门面）。

对外符号统一从此包导出；内部实现位于 base/http/login/interactions 子目录。
适配实现仍受随附的 ``NON_COMMERCIAL_LICENSE``（非商业许可）约束。
"""

from crawler.douyin_client.base.errors import (
    DataFetchError,
    DouyinError,
    InteractionExecutionError,
    LoginError,
)
from crawler.douyin_client.base.privacy import (
    anonymize_account_id,
    anonymize_user_id,
    map_aweme,
    map_comment,
    mask_nickname,
)
from crawler.douyin_client.base.types import (
    CreatorUrlInfo,
    PublishTimeType,
    SearchChannelType,
    SearchSortType,
    VideoUrlInfo,
    parse_creator_info,
    parse_video_info,
)
from crawler.douyin_client.http.client import DouyinClient
from crawler.douyin_client.http.request_log import (
    DouyinRequestLogEntry,
    RequestLogCallback,
)
from crawler.douyin_client.interactions.executor import DouyinInteractionExecutor
from crawler.douyin_client.interactions.models import (
    InteractionBrowserConnection,
    InteractionExecutionRequest,
    InteractionExecutionResult,
)
from crawler.douyin_client.login.login import DouyinLogin

__all__ = [
    # 异常
    "DataFetchError",
    "DouyinError",
    "LoginError",
    "InteractionExecutionError",
    # 类型与链接解析
    "SearchChannelType",
    "SearchSortType",
    "PublishTimeType",
    "VideoUrlInfo",
    "CreatorUrlInfo",
    "parse_video_info",
    "parse_creator_info",
    # HTTP 客户端
    "DouyinClient",
    "DouyinRequestLogEntry",
    "RequestLogCallback",
    # 登录
    "DouyinLogin",
    # 隐私脱敏
    "anonymize_user_id",
    "anonymize_account_id",
    "mask_nickname",
    "map_aweme",
    "map_comment",
    # 互动
    "DouyinInteractionExecutor",
    "InteractionBrowserConnection",
    "InteractionExecutionRequest",
    "InteractionExecutionResult",
]
