"""The only browser attachment primitive used by CDP adapters."""

from playwright.async_api import Browser, BrowserType


async def connect_over_cdp(
    browser_type: BrowserType,
    endpoint: str,
    *,
    timeout_ms: float | None = None,
) -> Browser:
    """Attach to an existing browser without any launch fallback."""
    if timeout_ms is None:
        return await browser_type.connect_over_cdp(endpoint)
    return await browser_type.connect_over_cdp(endpoint, timeout=timeout_ms)
