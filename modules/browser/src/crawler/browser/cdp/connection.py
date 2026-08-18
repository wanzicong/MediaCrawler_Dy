"""CDP 适配层唯一使用的浏览器附加（attach）原语。"""

from playwright.async_api import Browser, BrowserType


async def connect_over_cdp(
    browser_type: BrowserType,
    endpoint: str,
    *,
    timeout_ms: float | None = None,
) -> Browser:
    """附加到一个已存在的浏览器，不提供任何启动（launch）回退。

    参数：
        browser_type: Playwright 的浏览器类型（通常为 chromium）。
        endpoint: CDP 端点地址（WebSocket 或 http 形式）。
        timeout_ms: 连接超时时间（毫秒）；为 None 时使用 Playwright 默认超时。

    返回：
        通过 CDP 附加成功的 Browser 对象。
    """
    if timeout_ms is None:
        return await browser_type.connect_over_cdp(endpoint)
    return await browser_type.connect_over_cdp(endpoint, timeout=timeout_ms)
