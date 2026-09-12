"""抖音 HTTP API 客户端门面：签名、传输、响应解析与隐私映射。

本包是**零浏览器依赖的纯 API 层**：浏览器侧能力一律经入站契约
:class:`SessionContext` 注入，包内不 import `crawler.browser` 与 `playwright`。
对外符号统一从此包导出；内部实现位于 errors/http/parsing/privacy/signing/session
子目录。适配实现仍受随附的 ``NON_COMMERCIAL_LICENSE``（非商业许可）约束。
"""

from crawler.douyin_client.errors.family import (
    DataFetchError as DataFetchError,
)
from crawler.douyin_client.errors.family import (
    DouyinError as DouyinError,
)
from crawler.douyin_client.http.client import (
    DouyinClient as DouyinClient,
)
from crawler.douyin_client.http.redaction import (
    REDACTED as REDACTED,
)
from crawler.douyin_client.http.redaction import (
    is_sensitive_key as is_sensitive_key,
)
from crawler.douyin_client.http.redaction import (
    redact_headers as redact_headers,
)
from crawler.douyin_client.http.request_log import (
    CommentCallback as CommentCallback,
)
from crawler.douyin_client.http.request_log import (
    DouyinRequestLogEntry as DouyinRequestLogEntry,
)
from crawler.douyin_client.http.request_log import (
    IntervalProvider as IntervalProvider,
)
from crawler.douyin_client.http.request_log import (
    RequestLogCallback as RequestLogCallback,
)
from crawler.douyin_client.parsing.links import (
    parse_creator_info as parse_creator_info,
)
from crawler.douyin_client.parsing.links import (
    parse_video_info as parse_video_info,
)
from crawler.douyin_client.parsing.types import (
    CreatorUrlInfo as CreatorUrlInfo,
)
from crawler.douyin_client.parsing.types import (
    PublishTimeType as PublishTimeType,
)
from crawler.douyin_client.parsing.types import (
    SearchChannelType as SearchChannelType,
)
from crawler.douyin_client.parsing.types import (
    SearchSortType as SearchSortType,
)
from crawler.douyin_client.parsing.types import (
    VideoUrlInfo as VideoUrlInfo,
)
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
from crawler.douyin_client.session.context import (
    SessionContext as SessionContext,
)

__all__ = [
    # 异常
    "DouyinError",
    "DataFetchError",
    # 类型与链接解析
    "SearchChannelType",
    "SearchSortType",
    "PublishTimeType",
    "VideoUrlInfo",
    "CreatorUrlInfo",
    "parse_video_info",
    "parse_creator_info",
    # HTTP 客户端与可观测记录
    "DouyinClient",
    "DouyinRequestLogEntry",
    "RequestLogCallback",
    "CommentCallback",
    "IntervalProvider",
    # 会话契约
    "SessionContext",
    # 隐私脱敏
    "anonymize_user_id",
    "anonymize_account_id",
    "mask_nickname",
    "map_aweme",
    "map_comment",
    "REDACTED",
    "redact_headers",
    "is_sensitive_key",
]
