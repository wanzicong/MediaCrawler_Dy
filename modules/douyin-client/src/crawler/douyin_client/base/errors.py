# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音客户端的异常类型定义：采集、登录与互动执行流程的统一错误层级。"""


class DouyinError(RuntimeError):
    """抖音采集相关错误的基类。"""


class DataFetchError(DouyinError):
    """抖音 API 返回了无效或被拒绝的响应时抛出。"""


class LoginError(DouyinError):
    """所选的登录流程未能完成时抛出。"""


class InteractionExecutionError(DouyinError):
    """互动执行失败错误，携带错误码与处置标记。

    属性：
        code: 机器可读的错误码。
        retryable: 是否可安全重试。
        ambiguous: 结果是否不明确（可能已发出，需人工核对）。
        affects_account_health: 是否影响账号健康状态。
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        ambiguous: bool = False,
        affects_account_health: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.ambiguous = ambiguous
        self.affects_account_health = affects_account_health
