"""对外能力门面：外部系统（business/api/mcp）统一从这里导入浏览器能力。

browser 模块对外的能力面收敛到本子包：会话编排入口 ``CDPBrowserSession`` 与会话
能力适配器 ``BrowserSessionContext``、会话连接参数 ``BrowserSessionSpec``、站点无关
的 CDP 健康探测与页面截图、只读页面端口 ``BrowserPage``、入站 Protocol 契约
（``LoginApi`` / ``InteractionApi`` / ``InteractionApiFactory`` / ``CommentPresence``），
浏览器集成层的中立异常与模式枚举，以及抖音站点层的登录/互动编排
（``DouyinLogin`` / ``DouyinInteractionExecutor`` 及其请求、结果与回调类型）。
外部调用方只依赖本门面，不再深入到 ``connection`` / ``session`` / ``page`` /
``errors`` / ``interactions`` / ``login`` 等内部实现。
"""

from crawler.browser.errors import (
    BrowserAutomationError,
    BrowserAutomationTimeoutError,
    CDPConnectionError,
    InteractionExecutionError,
    LoginError,
)
from crawler.browser.facade.capabilities import capture_screenshot, probe_cdp_pages
from crawler.browser.facade.protocols import (
    CommentPresence,
    InteractionApi,
    InteractionApiFactory,
    LoginApi,
)
from crawler.browser.facade.spec import BrowserSessionSpec
from crawler.browser.interactions.executor import DouyinInteractionExecutor
from crawler.browser.interactions.models import (
    InteractionExecutionRequest,
    InteractionExecutionResult,
    InteractionStepCallback,
)
from crawler.browser.login.flow import DouyinLogin, QRCodeCallback
from crawler.browser.page.port import BrowserPage
from crawler.browser.session.context import BrowserSessionContext
from crawler.browser.session.manager import CDPBrowserSession
from crawler.browser.session.mode import BrowserMode

__all__ = [
    "BrowserAutomationError",
    "BrowserAutomationTimeoutError",
    "CDPConnectionError",
    "LoginError",
    "InteractionExecutionError",
    "BrowserMode",
    "BrowserSessionSpec",
    "CDPBrowserSession",
    "BrowserSessionContext",
    "capture_screenshot",
    "probe_cdp_pages",
    "BrowserPage",
    "LoginApi",
    "InteractionApi",
    "InteractionApiFactory",
    "CommentPresence",
    "InteractionStepCallback",
    "QRCodeCallback",
    "InteractionExecutionRequest",
    "InteractionExecutionResult",
    "DouyinInteractionExecutor",
    "DouyinLogin",
]
