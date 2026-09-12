"""纯 CDP 的浏览器运行时封装：会话编排、连接、只读页面端口与入站契约。

本包属于 crawler.* 命名空间下的浏览器集成层，仅通过 Chrome DevTools Protocol
连接浏览器，被登录、采集、互动等上层业务模块统一复用。

本模块是 ``crawler.browser.facade`` 的**门面镜像**：符号表与顺序逐字一致，
且每个符号与门面是同一对象（门禁 G5）。上层只允许 import ``crawler.browser``
或 ``crawler.browser.facade`` 两个精确模块名，其余子路径均属内部实现。
"""

from crawler.browser.facade import (
    BrowserAutomationError,
    BrowserAutomationTimeoutError,
    BrowserMode,
    BrowserPage,
    BrowserSessionContext,
    BrowserSessionSpec,
    CDPBrowserSession,
    CDPConnectionError,
    CommentPresence,
    DouyinInteractionExecutor,
    DouyinLogin,
    InteractionApi,
    InteractionApiFactory,
    InteractionExecutionError,
    InteractionExecutionRequest,
    InteractionExecutionResult,
    InteractionStepCallback,
    LoginApi,
    LoginError,
    QRCodeCallback,
    capture_screenshot,
    probe_cdp_pages,
)

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
