"""浏览器集成层异常族的统一出口：包内一律 ``from crawler.browser.errors import X``。"""

from crawler.browser.errors.family import (
    BrowserAutomationError,
    BrowserAutomationTimeoutError,
    CDPConnectionError,
    InteractionExecutionError,
    LoginError,
)

__all__ = [
    "BrowserAutomationError",
    "BrowserAutomationTimeoutError",
    "CDPConnectionError",
    "InteractionExecutionError",
    "LoginError",
]
