"""浏览器集成层的异常类型定义（全模块唯一出处）。

``BrowserAutomationError`` 与 ``BrowserAutomationTimeoutError`` 是对 Playwright
原生异常的别名：应用编排层捕获这些由集成层拥有的名字，而其运行时身份仍是
Playwright 自身的异常类。
"""

from typing import TypeAlias

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


class CDPConnectionError(RuntimeError):
    """CDP 浏览器端点不可达或停止响应时抛出的异常。"""


BrowserAutomationError: TypeAlias = PlaywrightError
BrowserAutomationTimeoutError: TypeAlias = PlaywrightTimeoutError

__all__ = [
    "BrowserAutomationError",
    "BrowserAutomationTimeoutError",
    "CDPConnectionError",
]
