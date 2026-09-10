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
from crawler.browser.facade.capabilities import capture_screenshot, probe_cdp_pages
from crawler.browser.facade.spec import BrowserSessionSpec
from crawler.browser.runtime.cookies import (
    browser_cookies,
    convert_cookies,
    parse_cookie_string,
)
from crawler.browser.runtime.dom import (
    auto_dismiss_dialogs,
    click_control_center,
    editor_is_empty,
    evaluate_stable,
    find_text_control,
    find_visible,
    scroll_container_to_bottom,
    visible_page_message,
    wait_editor_empty,
)
from crawler.browser.runtime.session import CDPBrowserSession

__all__ = [
    "BrowserAutomationError",
    "BrowserAutomationTimeoutError",
    "BrowserSessionSpec",
    "CDPBrowserSession",
    "CDPConnectionError",
    "DouyinBrowserMode",
    # 对外能力门面（外部系统建议从 crawler.browser.facade 导入）
    "capture_screenshot",
    "probe_cdp_pages",
    # 通用页面基元
    "auto_dismiss_dialogs",
    "click_control_center",
    "editor_is_empty",
    "evaluate_stable",
    "find_text_control",
    "find_visible",
    "scroll_container_to_bottom",
    "visible_page_message",
    "wait_editor_empty",
    # cookie 工具
    "browser_cookies",
    "convert_cookies",
    "parse_cookie_string",
]
