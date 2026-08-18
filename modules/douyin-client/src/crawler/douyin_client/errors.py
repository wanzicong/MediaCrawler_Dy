# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音客户端的异常类型定义：采集与登录流程的统一错误层级。"""


class DouyinError(RuntimeError):
    """抖音采集相关错误的基类。"""


class DataFetchError(DouyinError):
    """抖音 API 返回了无效或被拒绝的响应时抛出。"""


class LoginError(DouyinError):
    """所选的登录流程未能完成时抛出。"""
