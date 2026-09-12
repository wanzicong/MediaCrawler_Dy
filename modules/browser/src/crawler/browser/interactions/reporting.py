"""互动流程的唯一步骤上报出口（合并原 executor ``_trace`` 与 SubmitFlow ``_report``）。

页面级协作者内部持有的是 Playwright 原生页面，而步骤回调只允许暴露只读端口
``BrowserPage``：本模块是这两者之间**唯一**的转换点，因此裸 Playwright 对象
不可能经回调流到上层。
"""

from __future__ import annotations

from crawler.browser.interactions.models import InteractionStepCallback
from crawler.browser.page.handle import PlaywrightPageHandle
from crawler.browser.page.port import BrowserPage
from playwright.async_api import Page

# 上报目标：内部协作类传 Playwright 页面，浏览器会话句柄本身就是 BrowserPage。
ReportTarget = Page | BrowserPage


def as_browser_page(page: ReportTarget) -> BrowserPage:
    """把内部持有的页面适配成回调可见的只读端口。

    传入 ``PlaywrightPageHandle`` 时原样返回（复用会话级指纹缓存）；传入裸
    Playwright 页面（含私信流程中新打开的标签页）时，就地包一层句柄——句柄
    只暴露只读能力，写操作仍留在 browser 内部。
    """
    if not isinstance(page, Page):
        # 非 Playwright 页面即已是只读端口（PlaywrightPageHandle 也走此分支）。
        return page
    return PlaywrightPageHandle(page=page, context=page.context)


async def report_step(
    callback: InteractionStepCallback | None,
    page: ReportTarget,
    step: str,
    detail: str,
) -> None:
    """若提供了步骤回调，则上报一个执行步骤（回调首个参数为 ``BrowserPage``）。"""
    if callback is None:
        return
    await callback(as_browser_page(page), step, detail)


__all__ = ["ReportTarget", "as_browser_page", "report_step"]
