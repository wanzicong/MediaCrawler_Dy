"""DIP 入站契约：browser 拥有、由上层适配器实现并注入。

browser 的站点流程（登录、互动）只依赖这里的 Protocol，不依赖任何具体 API
客户端；上层（``crawler.business.douyin.adapters``）把 ``douyin_client`` 包装成
``LoginApi`` / ``InteractionApi`` 后注入。契约全部返回内建类型，business 侧
可以用结构化实现满足它们而无需继承。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal, Protocol, runtime_checkable

from crawler.browser.page.port import BrowserPage

CommentPresence = Literal["present", "unavailable", "inconclusive"]


@runtime_checkable
class LoginApi(Protocol):
    """登录流程所需的会话校验与同步能力（由上层适配器包装 douyin-client 后注入）。"""

    async def verify_login(self, *, require_self_profile: bool = False) -> bool: ...
    async def get_self_profile(self) -> Mapping[str, Any] | None: ...
    async def refresh_cookies(self) -> None: ...


@runtime_checkable
class InteractionApi(Protocol):
    """互动执行所需的抖音读写能力。

    约定：实现方必须把底层 API 异常翻译为本模块可识别的信号，端口自身不抛第三方异常。
    - 登录类失败 → verify_login() 返回 False（不得抛异常）
    - 写操作前置的评论核验失败/不可判定 → verify_target_comment() 返回 "inconclusive"
    - 作者解析时的接口故障 → 实现方抛 InteractionExecutionError("api_unavailable", retryable=True)
    """

    async def verify_login(self, *, require_self_profile: bool = False) -> bool: ...
    async def verify_target_comment(
        self,
        *,
        aweme_id: str,
        comment_id: str,
        parent_comment_id: str | None = None,
    ) -> CommentPresence: ...
    async def resolve_video_author_sec_uid(self, aweme_id: str) -> str | None: ...
    async def refresh_cookies(self) -> None: ...
    async def aclose(self) -> None: ...


InteractionApiFactory = Callable[[BrowserPage], Awaitable[InteractionApi]]

__all__ = [
    "CommentPresence",
    "InteractionApi",
    "InteractionApiFactory",
    "LoginApi",
]
