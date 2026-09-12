"""浏览器集成层的异常类型定义（全模块唯一出处）。

``BrowserAutomationError`` 与 ``BrowserAutomationTimeoutError`` 是对 Playwright
原生异常的别名：应用编排层捕获这些由集成层拥有的名字，而其运行时身份仍是
Playwright 自身的异常类。

``LoginError`` / ``InteractionExecutionError`` 属于抖音站点层的异常，已在 S4
随 ``login/`` 与 ``interactions/`` 一起从 ``crawler.douyin_client`` 迁入本模块，
基类由 ``DouyinError`` 改为 ``RuntimeError``（全仓零处 ``except DouyinError``，
见裁决 R3），因此 ``browser/*`` 一律从这里取异常类型，不反向 import
``crawler.douyin_client``（裁决 R10.1）。
"""

from typing import TypeAlias

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


class CDPConnectionError(RuntimeError):
    """CDP 浏览器端点不可达或停止响应时抛出的异常。"""


class LoginError(RuntimeError):
    """所选的登录流程未能完成时抛出。"""


class InteractionExecutionError(RuntimeError):
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


BrowserAutomationError: TypeAlias = PlaywrightError
BrowserAutomationTimeoutError: TypeAlias = PlaywrightTimeoutError

__all__ = [
    "BrowserAutomationError",
    "BrowserAutomationTimeoutError",
    "CDPConnectionError",
    "InteractionExecutionError",
    "LoginError",
]
