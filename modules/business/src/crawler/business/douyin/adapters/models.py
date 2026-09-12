"""抖音浏览器适配层的配置模型与契约别名。

只承载「构造 ``DouyinClient`` 所需的冻结配置」，不含任何业务状态：配置在
适配器构造时一次性拍定，运行期不再变化，因此用冻结 dataclass 表达。
"""

from __future__ import annotations

from dataclasses import dataclass

from crawler.browser.facade import InteractionApiFactory


@dataclass(frozen=True)
class DouyinBrowserApiConfig:
    """适配器构造 ``DouyinClient`` 时使用的请求配置。

    属性：
        timeout: 抖音接口单次请求超时时间（秒）。
        verify_ssl: 请求抖音接口时是否校验 SSL 证书。
    """

    timeout: float
    verify_ssl: bool


__all__ = [
    "DouyinBrowserApiConfig",
    # 门面契约在本子域的类型入口，便于调用方从同一处取「工厂」与「实现」。
    "InteractionApiFactory",
]
