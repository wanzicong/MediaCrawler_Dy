"""自动化标签页的获取策略：复用既有页面或按标记新建专属页面。

属于本地/远程会话共用的纯决策逻辑，不启动浏览器也不持有会话生命周期，
只负责回答"取哪个页面、是否归本会话所有、隔离了多少无关页面"。
"""

from playwright.async_api import BrowserContext, Page

# 页面标记写入脚本：把 marker 写到 window.name，供下次会话按名复用。
_MARKER_JS = "marker => { window.name = marker; }"


class PageAcquisitionPolicy:
    """在给定浏览器上下文中按标记/复用策略获取一个自动化页面。

    页面标记模式下只复用 ``window.name`` 与标记匹配的既有页面，绝不劫持用户
    手工打开的页面；无匹配时新建专属页面并写入标记。
    """

    def __init__(
        self,
        *,
        page_marker: str | None = None,
        reuse_existing_page: bool = False,
    ) -> None:
        """初始化获取策略。

        参数：
            page_marker: 页面标记；设置后按 window.name 匹配并复用同名页面。
            reuse_existing_page: 为 True 且无标记时，直接复用上下文中的既有页面。
        """
        self.page_marker = page_marker
        self.reuse_existing_page = reuse_existing_page
        self.page: Page | None = None
        self.owns_page = False
        self.unrelated_page_count = 0

    async def acquire(self, context: BrowserContext) -> None:
        """按策略从上下文中取页或新建页，并把结果写入本策略实例。"""
        reusable_pages = [page for page in context.pages if not page.is_closed()]
        if self.page_marker:
            marked_pages: list[Page] = []
            for candidate in reusable_pages:
                try:
                    marker = await candidate.evaluate("() => window.name")
                except Exception:
                    # 页面可能已关闭或处于不可评估状态，跳过该候选。
                    continue
                if marker == self.page_marker:
                    marked_pages.append(candidate)
            self.unrelated_page_count = len(reusable_pages) - len(marked_pages)
            if marked_pages:
                self.page = marked_pages[-1]
                self.owns_page = False
                return
            self.page = await context.new_page()
            await self.page.evaluate(_MARKER_JS, self.page_marker)
            self.owns_page = True
            return
        if self.reuse_existing_page and reusable_pages:
            self.page = reusable_pages[-1]
            self.owns_page = False
            return
        self.page = await context.new_page()
        self.owns_page = True
