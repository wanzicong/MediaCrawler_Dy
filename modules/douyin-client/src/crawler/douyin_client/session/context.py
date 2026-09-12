"""``SessionContext``：DouyinClient 依赖的浏览器会话最小能力契约。

douyin_client 拥有本 Protocol，实现方由上层注入（business 经
``crawler.browser`` 门面传入 ``BrowserSessionContext``）；本包**不 import**
任何实现方，靠结构化匹配满足，因此 ``crawler.douyin_client`` 可以完全脱离
浏览器依赖独立导入。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SessionContext(Protocol):
    """DouyinClient 依赖的浏览器会话最小能力；由上层注入，douyin_client 不反向依赖实现方。

    实现方（``crawler.browser.session.context.BrowserSessionContext``）不 import 本
    Protocol，靠结构化匹配满足；4 个方法全部返回内建类型，mypy strict 可结构化校验。
    """

    async def user_agent(self) -> str:
        """返回当前浏览器会话的真实 User-Agent；取不到时返回空字符串。"""
        ...

    async def local_storage(self) -> dict[str, Any]:
        """返回 www.douyin.com 页面的 window.localStorage 快照；取不到时返回 {}，不得抛异常。"""
        ...

    async def cookies(self, urls: Sequence[str]) -> tuple[str, dict[str, str]]:
        """读取指定 URL 的 cookie，返回 (cookie 字符串, 名值字典)。"""
        ...

    async def fingerprint(self) -> Mapping[str, str]:
        """返回与真实浏览器一致的请求指纹参数（键见 DouyinClient.FINGERPRINT_KEYS）。

        缺失的键不写入映射；实现方不得用伪造常量补齐。仅供 DouyinClient 读取，取不到时返回 {}。
        """
        ...


__all__ = ["SessionContext"]
