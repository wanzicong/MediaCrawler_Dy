# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音请求的公共辅助类型。

集中 ``DouyinRequestLogEntry`` / ``RequestLogCallback`` 等记录类型与请求间隔解析；
``http/client.py`` 从本模块导入，保持客户端聚焦请求本身。
cookie 序列化/解析工具已下沉到浏览器模块，本层只经 ``SessionContext.cookies()`` 消费。
请求头在记录**构造时**即脱敏，规则来自 ``crawler.douyin_client.http.redaction``。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from crawler.douyin_client.http.redaction import redact_headers

if TYPE_CHECKING:
    from crawler.douyin_client.http.client import DouyinClient

# 评论批次回调：参数为 aweme_id 与本批评论原始字典列表
CommentCallback = Callable[[str, list[dict[str, Any]]], Awaitable[None]]
# 请求间隔（秒）：可为固定数值，或返回数值的可调用对象
IntervalProvider = float | Callable[[], float]


@dataclass
class DouyinRequestLogEntry:
    """一次抖音接口调用的可观测记录。

    ``request_headers`` 在构造时即按敏感键标记集脱敏，Cookie、Authorization 等
    值不会以明文进入本对象（见 ``__post_init__``）。
    ``url`` / ``query_params`` / ``request_body`` 仍携带签名后的原始值；响应侧仅在
    失败时短暂携带返回快照；上层落库前必须继续脱敏并限长。
    """

    method: str  # HTTP 方法
    path: str  # 请求路径（不含查询串）
    url: str  # 完整请求地址
    query_params: dict[str, Any]  # 签名后的完整查询参数
    request_headers: dict[str, str]  # 实际发送的全部请求头（构造时已脱敏）
    request_body: dict[str, Any] | None  # POST 表单数据（签名后），GET 为 None
    response_status: int | None  # 响应状态码；网络异常时为 None
    duration_ms: int  # 请求耗时（毫秒）
    error: str | None  # 异常类型名；成功时为 None
    failure_detail: dict[str, Any] | None = None  # 失败响应快照；成功时为 None

    def __post_init__(self) -> None:
        """构造时立即脱敏请求头，移除 Cookie、Authorization 等敏感值。

        这里是凭据离开 ``DouyinClient`` 的唯一出口，脱敏在此完成而非依赖上层，
        使任何消费方（含直接持有 entry 的调用方）都无法拿到明文凭据。
        """
        self.request_headers = redact_headers(self.request_headers)


# 抖音请求日志回调：由上层应用注册，每次抖音接口调用完成后触发
RequestLogCallback = Callable[["DouyinClient", DouyinRequestLogEntry], Awaitable[None]]


def _interval_seconds(interval: IntervalProvider) -> float:
    """将固定值或可调用形式的间隔配置统一解析为秒数。"""
    return interval() if callable(interval) else interval
