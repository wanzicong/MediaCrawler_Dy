# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音 API 客户端的异常族。

本模块只承载纯 API 层自有的异常：``DouyinError`` 与签名不变的 ``DataFetchError``。
浏览器/登录/互动执行类异常（``LoginError`` / ``InteractionExecutionError``）的终态归属是
``crawler.browser.errors``（browser 站点层），纯 API 层不再保留副本。
"""


class DouyinError(RuntimeError):
    """抖音采集相关错误的基类。"""


class DataFetchError(DouyinError):
    """抖音 API 返回了无效或被拒绝的响应时抛出。"""


__all__ = [
    "DataFetchError",
    "DouyinError",
]
