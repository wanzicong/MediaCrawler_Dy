"""上层唯一可用的浏览器面：只读页面能力端口 ``BrowserPage``。

端口只暴露「读」的能力（UA、localStorage、cookie、指纹、截图），不暴露任何
Playwright 类型：导航（``goto``）与 cookie 写入只存在于不出门面的
``crawler.browser.page.handle.PlaywrightPageHandle`` 上，上层无法绕过会话编排
直接驱动页面。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BrowserPage(Protocol):
    """browser 提供给上层的只读页面能力端口（上层唯一可用的浏览器面）。"""

    async def user_agent(self) -> str: ...
    async def local_storage(self) -> dict[str, Any]: ...
    async def cookies(self, urls: Sequence[str]) -> tuple[str, dict[str, str]]: ...
    async def fingerprint(self) -> Mapping[str, str]: ...
    async def capture_screenshot(self, *, quality: int, timeout: float) -> bytes: ...


__all__ = ["BrowserPage"]
