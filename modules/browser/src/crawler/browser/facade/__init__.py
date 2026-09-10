"""对外能力门面：外部系统（business 层）统一从这里导入浏览器能力。

browser 模块对外的能力面收敛到本子包：会话编排入口 ``CDPBrowserSession``、
会话连接参数 ``BrowserSessionSpec``、站点无关的 CDP 健康探测与页面截图，
以及浏览器集成层的中立异常与模式枚举。外部调用方只依赖本门面，
不再深入到 ``runtime`` / ``base`` 等内部实现。
"""

from crawler.browser.base.errors import (
    BrowserAutomationError,
    BrowserAutomationTimeoutError,
    CDPConnectionError,
)
from crawler.browser.base.modes import DouyinBrowserMode
from crawler.browser.facade.capabilities import capture_screenshot, probe_cdp_pages
from crawler.browser.facade.spec import BrowserSessionSpec
from crawler.browser.runtime.session import CDPBrowserSession

__all__ = [
    "BrowserAutomationError",
    "BrowserAutomationTimeoutError",
    "BrowserSessionSpec",
    "CDPBrowserSession",
    "CDPConnectionError",
    "DouyinBrowserMode",
    "capture_screenshot",
    "probe_cdp_pages",
]
