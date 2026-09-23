"""把 page+context 适配成 ``douyin_client.SessionContext`` 能力（含指纹缓存）。

``BrowserSessionContext`` 是 browser 侧对「浏览器会话能力」的唯一适配器：
4 个原语方法全部返回内建类型（``str`` / ``dict`` / ``tuple`` / ``Mapping``），
因此不需要 import ``crawler.douyin_client`` 就能结构化满足其 ``SessionContext``
Protocol（browser 不得依赖 douyin_client，见门禁 G2）。

指纹同一会话内幂等：首次采集后缓存，``close()`` 后置空并拒绝服务。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qs, urlsplit

from crawler.browser.errors import CDPConnectionError
from crawler.browser.session.cookies import browser_cookies
from crawler.browser.session.environment import BrowserEnvironment
from playwright.async_api import BrowserContext, Page


class BrowserSessionContext:
    """把 Playwright 的 page+context 适配成上层可用的只读会话能力。

    不持有会话生命周期（页面/浏览器的关闭仍由 ``CDPBrowserSession`` 负责），
    只负责「怎么把页面上的真实读数读出来」并对指纹做一次会话内缓存。
    """

    def __init__(self, *, page: Page, context: BrowserContext) -> None:
        """初始化适配器。

        参数：
            page: 会话当前使用的 Playwright 页面。
            context: 页面所属的浏览器上下文（cookie 读取的唯一来源）。
        """
        self._page = page
        self._environment = BrowserEnvironment(page)
        self._context = context
        self._fingerprint: dict[str, str] | None = None
        # 真实 webid：抖音 SDK 只暴露 setter，读不到当前值，只能从页面自己发出的
        # 请求里观测（每个签名请求都带 webid=...）。这里挂一次监听并缓存观测结果，
        # 保证我们后续请求用到的 webid 与浏览器完全一致（原先每次随机生成）。
        self._webid: str = ""
        page.on("request", self._observe_request)
        self._closed = False

    def _observe_request(self, request: Any) -> None:
        """从抖音页面自身请求里观测真实 webid；已观测到就不再更新。"""
        if self._webid:
            return
        try:
            url = request.url
        except Exception:  # noqa: BLE001 - 监听回调绝不能影响页面
            return
        if "/aweme/v1/web/" not in url:
            return
        try:
            values = parse_qs(urlsplit(url).query).get("webid") or []
        except Exception:  # noqa: BLE001 - 同上
            return
        if values and values[0]:
            self._webid = str(values[0])

    async def webid(self) -> str:
        """返回观测到的真实 webid；尚未观测到时返回空字符串。

        等待策略由调用方决定（客户端在拿不到时会回落到自身的生成逻辑），
        这里只做「读缓存」，避免在只读原语里引入额外等待。
        """
        self._require_open()
        return self._webid

    async def user_agent(self) -> str:
        """返回当前浏览器会话的真实 User-Agent；取不到时返回空字符串。"""
        self._require_open()
        return await self._environment.read_user_agent()

    async def local_storage(self) -> dict[str, Any]:
        """返回当前页面的 window.localStorage 快照；取不到时返回 {}，不抛异常。"""
        self._require_open()
        return await self._environment.read_local_storage()

    async def cookies(self, urls: Sequence[str]) -> tuple[str, dict[str, str]]:
        """读取指定 URL 的 cookie，返回 (cookie 字符串, 名值字典)。"""
        self._require_open()
        return await browser_cookies(self._context, list(urls))

    async def fingerprint(self) -> Mapping[str, str]:
        """返回与真实浏览器一致的请求指纹参数（键见 DOUYIN_FINGERPRINT_KEYS）。

        缺失的键不写入映射，绝不用伪造常量补齐；首次采集后缓存，同一会话内幂等。
        """
        self._require_open()
        if self._fingerprint is None:
            self._fingerprint = await self._environment.read_fingerprint()
        return dict(self._fingerprint)

    async def evaluate(self, expression: str, argument: Any = None) -> Any:
        """在页面上下文执行 JS 表达式，返回可 JSON 序列化的结果。

        用途：抖音部分接口（如「喜欢列表」）要求请求带上页面内安全 SDK
        生成的签名，直连 HTTP 拿不到；此时改由页面内 ``fetch`` 发出，
        SDK 会自行补签名。表达式由调用方提供，本类不做任何站点语义处理。

        参数：
            expression: 在页面里求值的 JS 表达式（通常是 async 箭头函数）。
            argument: 传给表达式的单个可序列化参数。

        返回：
            表达式的返回值；页面不可用或求值失败时抛 CDPConnectionError。
        """
        self._require_open()
        try:
            return await self._page.evaluate(expression, argument)
        except CDPConnectionError:
            raise
        except Exception as exc:  # noqa: BLE001 - 统一收敛为浏览器错误
            raise CDPConnectionError(f"页面上下文执行失败: {exc}") from exc

    def close(self) -> None:
        """标记会话上下文已失效：缓存清空，其后任何读取都抛 CDPConnectionError。"""
        self._closed = True
        self._fingerprint = None

    def _require_open(self) -> None:
        """会话已关闭时拒绝服务，避免读到上个页面的残留读数。"""
        if self._closed:
            raise CDPConnectionError("浏览器会话已关闭，无法再读取会话上下文")


__all__ = ["BrowserSessionContext"]
