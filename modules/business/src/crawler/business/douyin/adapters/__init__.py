"""抖音浏览器适配层：business 与 browser / douyin_client 之间的唯一装配点。

本子域把「browser 门面定义的入站契约」（``LoginApi`` / ``InteractionApi`` /
``InteractionApiFactory``）与「douyin_client 的 HTTP 客户端」缝合成 business
可直接注入的对象，业务调用点不再自行构造 ``DouyinClient``、也不再触碰
``CDPBrowserSession`` 的临时兼容属性。
"""

from crawler.business.douyin.adapters.models import DouyinBrowserApiConfig
from crawler.business.douyin.adapters.service import (
    DouyinInteractionApi,
    DouyinLoginApi,
    build_interaction_api_factory,
    open_douyin_client,
)

__all__ = [
    "DouyinBrowserApiConfig",
    "DouyinInteractionApi",
    "DouyinLoginApi",
    "build_interaction_api_factory",
    "open_douyin_client",
]
