"""纯 CDP 的浏览器运行时封装：异常、会话门面与浏览器模式。

本包属于 crawler.* 命名空间下的浏览器集成层，仅通过 Chrome DevTools Protocol
连接浏览器，被登录、采集、互动等上层业务模块统一复用。对外只从这里导出符号，
内部代码按职责组织在 base / runtime / remote 子包中。
"""

from crawler.browser.base.errors import (
    BrowserAutomationError,
    BrowserAutomationTimeoutError,
    CDPConnectionError,
)
from crawler.browser.base.modes import DouyinBrowserMode
from crawler.browser.runtime.session import CDPBrowserSession

__all__ = [
    "BrowserAutomationError",
    "BrowserAutomationTimeoutError",
    "CDPBrowserSession",
    "CDPConnectionError",
    "DouyinBrowserMode",
]
