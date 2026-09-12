"""抖音浏览器适配器：把 ``douyin_client`` 包装成 browser 门面的入站契约。

本模块是 business 侧**唯一**构造 ``DouyinClient`` 的位置（门禁 G16）：其他
调用点一律通过 ``open_douyin_client`` 或 ``build_interaction_api_factory`` 取用，
不再自己 new 客户端，也不再从会话上取临时兼容属性（``page`` / ``context``）。

三个交付物：

- ``open_douyin_client``：按只读页面端口 ``BrowserPage`` 与 settings 构造客户端。
- ``DouyinLoginApi``：``browser.LoginApi`` 的实现，**不持有**客户端生命周期，
  由调用方负责 ``aclose()``。
- ``DouyinInteractionApi``：``browser.InteractionApi`` 的实现，**拥有**客户端
  生命周期（首用时 lazy 建连、``aclose()`` 负责关闭），并显式拒绝未导航的页面。
"""

from __future__ import annotations

from typing import Any

from crawler.bootstrap.settings import Settings
from crawler.browser.facade import (
    BrowserPage,
    CommentPresence,
    InteractionApi,
    InteractionApiFactory,
    InteractionExecutionError,
)
from crawler.business.douyin.adapters.models import DouyinBrowserApiConfig
from crawler.douyin_client import DataFetchError, DouyinClient


async def _create_client(
    *, page: BrowserPage, timeout: float, verify_ssl: bool
) -> DouyinClient:
    """按显式请求参数构造客户端（本模块唯一出现 ``DouyinClient.create`` 的地方）。"""
    return await DouyinClient.create(
        session=page,
        timeout=timeout,
        verify_ssl=verify_ssl,
    )


async def open_douyin_client(*, page: BrowserPage, settings: Settings) -> DouyinClient:
    """构造 ``DouyinClient``：UA 与 cookie 全部由只读页面端口 ``page`` 提供。

    参数：
        page: 已完成导航的只读页面端口（``BrowserPage`` 的形状覆盖
            ``douyin_client.SessionContext``，因此可直接作为会话注入）。
        settings: 应用配置（提供请求超时与 SSL 校验开关）。

    返回：
        初始化完成的 ``DouyinClient``；调用方负责 ``await client.close()``。
    """
    return await _create_client(
        page=page,
        timeout=settings.DOUYIN_REQUEST_TIMEOUT,
        verify_ssl=settings.DOUYIN_REQUEST_SSL_VERIFY,
    )


class DouyinLoginApi:
    """``browser.LoginApi`` 实现：登录态校验与 cookie 同步。

    不持有客户端生命周期——客户端由调用方构造并负责关闭，适配器只做委托，
    避免同一客户端被两处 ``close()``。
    """

    def __init__(self, *, client: DouyinClient) -> None:
        """包装一个已构造完成的抖音客户端。

        参数：
            client: 由 ``open_douyin_client`` 构造的客户端实例。
        """
        self._client = client

    async def verify_login(self, *, require_self_profile: bool = False) -> bool:
        """校验登录态；任何失败都返回 ``False``，不向调用方抛异常。"""
        try:
            return await self._client.pong(require_self_profile=require_self_profile)
        except Exception:
            return False

    async def get_self_profile(self) -> dict[str, Any]:
        """读取本人资料接口的原始响应（用于识别账号身份）。

        接口故障向上抛出，由调用方决定「复用已持久化身份」等降级策略；
        返回类型比 ``LoginApi`` 契约更窄（协议允许 ``None``），便于直接消费。
        """
        return await self._client.user_api.get_self_profile()

    async def refresh_cookies(self) -> None:
        """从浏览器会话重新采集 cookie 并同步进客户端请求头。"""
        await self._client.update_cookies()

    async def aclose(self) -> None:
        """关闭底层 HTTP 连接（不关闭浏览器页面）。"""
        await self._client.close()


class DouyinInteractionApi:
    """``browser.InteractionApi`` 实现：互动执行所需的抖音读写能力。

    生命周期归本类所有：首次 API 调用时才构造 ``DouyinClient``（此时页面必然
    已导航完成），``aclose()`` 负责关闭它，避免 httpx 连接泄漏。
    """

    def __init__(self, *, page: BrowserPage, config: DouyinBrowserApiConfig) -> None:
        """记录页面端口与请求配置，此时**不**建连。

        参数：
            page: 互动执行专用标签页的只读端口。
            config: 构造客户端所需的冻结请求配置。
        """
        self._page = page
        self._config = config
        self._client: DouyinClient | None = None

    async def _client_or_open(self) -> DouyinClient:
        """返回客户端；首次调用时先断言页面已导航，再 lazy 建连。

        异常：
            InteractionExecutionError: 页面尚未完成导航（建连会拿到空 cookie/UA
                并把「登录有效」静默判成「未登录」）；该错误可安全重试。
        """
        if self._client is None:
            await self._assert_page_navigated()
            self._client = await _create_client(
                page=self._page,
                timeout=self._config.timeout,
                verify_ssl=self._config.verify_ssl,
            )
        return self._client

    async def _assert_page_navigated(self) -> None:
        """断言首次 API 调用之前页面已完成导航。

        页面未导航时，``DouyinClient`` 从页面读到的 cookie 是空的（UA 也可能
        为空），登录校验会**静默**判为未登录并让互动以 ``login_required`` 失败。
        这里把该失败模式变成显式且可重试的错误。
        """
        user_agent = await self._page.user_agent()
        cookie_string, _ = await self._page.cookies(DouyinClient.cookie_urls)
        if not user_agent.strip() or not cookie_string.strip():
            raise InteractionExecutionError(
                "browser_unavailable",
                "抖音页面尚未完成导航，已中止互动以避免误判登录状态",
                retryable=True,
            )

    async def verify_login(self, *, require_self_profile: bool = False) -> bool:
        """校验登录态；接口故障返回 ``False``，不抛异常。

        例外：页面未导航时 ``_client_or_open()`` 会抛 ``InteractionExecutionError``，
        这属于调用方的时序错误而非登录失败，必须显式暴露。
        """
        client = await self._client_or_open()
        try:
            return await client.pong(require_self_profile=require_self_profile)
        except Exception:
            return False

    async def verify_target_comment(
        self,
        *,
        aweme_id: str,
        comment_id: str,
        parent_comment_id: str | None = None,
    ) -> CommentPresence:
        """翻页核验目标评论是否仍存在；接口故障一律兜成 ``"inconclusive"``。"""
        client = await self._client_or_open()
        try:
            return await client.comments_api.find_comment(
                aweme_id=aweme_id,
                comment_id=comment_id,
                parent_comment_id=parent_comment_id,
            )
        except DataFetchError:
            return "inconclusive"

    async def resolve_video_author_sec_uid(self, aweme_id: str) -> str | None:
        """解析作品作者的 sec_uid。

        返回 ``None`` 表示「作品确实解析不出作者」（作者缺失或没有可用标识）；
        作品详情**接口本身故障**时抛 ``InteractionExecutionError``，两种情形
        刻意不压成同一个 ``None``，以便上层区分「换目标」与「稍后重试」。

        异常：
            InteractionExecutionError: 作品详情接口不可用（可重试）。
        """
        client = await self._client_or_open()
        try:
            detail = await client.aweme_api.get_video(aweme_id)
        except DataFetchError as exc:
            raise InteractionExecutionError(
                "api_unavailable",
                "作品详情接口暂时不可用，无法解析私信目标作者",
                retryable=True,
            ) from exc
        author = detail.get("author")
        if not isinstance(author, dict):
            return None
        sec_uid = str(author.get("sec_uid") or author.get("sec_user_id") or "").strip()
        return sec_uid or None

    async def refresh_cookies(self) -> None:
        """从浏览器会话重新采集 cookie 并同步进客户端请求头。"""
        client = await self._client_or_open()
        await client.update_cookies()

    async def aclose(self) -> None:
        """关闭底层 HTTP 连接；未建连时为空操作，可重复调用。

        必须 ``await self._client.close()``：否则 httpx 连接池泄漏。
        """
        client = self._client
        self._client = None
        if client is not None:
            await client.close()


def build_interaction_api_factory(settings: Settings) -> InteractionApiFactory:
    """按 settings 生成 ``InteractionApiFactory``（browser 的互动执行器入参）。

    工厂本身无状态：每次被调用都返回一个**新的** ``DouyinInteractionApi``
    （即新的客户端与新的生命周期），由 executor 的 ``finally`` 负责关闭。
    """
    config = DouyinBrowserApiConfig(
        timeout=settings.DOUYIN_REQUEST_TIMEOUT,
        verify_ssl=settings.DOUYIN_REQUEST_SSL_VERIFY,
    )

    async def factory(page: BrowserPage) -> InteractionApi:
        """为一次互动执行构造独立的 API 适配器（lazy 建连）。"""
        return DouyinInteractionApi(page=page, config=config)

    return factory


__all__ = [
    "DouyinInteractionApi",
    "DouyinLoginApi",
    "build_interaction_api_factory",
    "open_douyin_client",
]
