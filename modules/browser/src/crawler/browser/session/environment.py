"""浏览器环境采集：从真实页面读 navigator/screen/connection 读数并推导请求指纹。

抖音公共参数里的浏览器指纹必须与本次会话**真实使用的 User-Agent 同源**：

* 同一份 UA 字符串里能读出的信息（浏览器/内核实名与版本、系统名与版本）一律由
  :func:`derive_browser_family` 用正则派生；
* 浏览器环境独有的读数（``navigator.platform`` / ``hardwareConcurrency`` /
  ``deviceMemory`` / ``navigator.language`` / ``screen`` / ``navigator.connection``）
  由 :class:`BrowserEnvironment` 通过一次 ``page.evaluate`` 采集。

**缺键即不写入**：推不出真实值的字段不进映射；本模块刻意不提供任何默认常量兜底，
避免历史实现里 "MacIntel / Mac OS 10.15.7 / 2560x1440 / Chrome 125.0.0.0"
这类与真实 UA 互相矛盾的伪造指纹重新出现。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from crawler.browser.page.primitives import evaluate_stable
from playwright.async_api import Page

logger = logging.getLogger(__name__)

# 抖音请求指纹的键表（与 DouyinClient.FINGERPRINT_KEYS 集合相等，由门禁 G15 钉死）。
# 两处声明是有意的：browser 与 douyin_client 互不 import 是硬约束，键表只可能各写一份。
DOUYIN_FINGERPRINT_KEYS: tuple[str, ...] = (
    "browser_language",
    "browser_platform",
    "browser_name",
    "browser_version",
    "engine_name",
    "engine_version",
    "os_name",
    "os_version",
    "cpu_core_num",
    "device_memory",
    "screen_width",
    "screen_height",
    "effective_type",
    "round_trip_time",
)

# 一次性采集全部浏览器读数的脚本；缺项（如 Firefox 没有 navigator.deviceMemory、
# 非 Chromium 没有 navigator.connection）由 ``?? null`` 归一为 null，推导时按「缺值」处理。
BROWSER_READINGS_SCRIPT = """() => {
    const connection = navigator.connection || {};
    return {
        user_agent: navigator.userAgent,
        language: navigator.language,
        platform: navigator.platform,
        hardware_concurrency: navigator.hardwareConcurrency,
        device_memory: navigator.deviceMemory ?? null,
        on_line: navigator.onLine,
        screen_width: screen.width,
        screen_height: screen.height,
        effective_type: connection.effectiveType ?? null,
        round_trip_time: connection.rtt ?? null,
    };
}"""

# 读数键 -> 指纹键。只映射 DOUYIN_FINGERPRINT_KEYS 内的键；脚本额外读到的
# ``user_agent`` / ``on_line`` 不产生指纹键（browser_online 属 douyin_client
# 自己维护的稳定参数，不在指纹键表内）。
_READING_SOURCES: tuple[tuple[str, str], ...] = (
    ("browser_language", "language"),
    ("browser_platform", "platform"),
    ("cpu_core_num", "hardware_concurrency"),
    ("device_memory", "device_memory"),
    ("screen_width", "screen_width"),
    ("screen_height", "screen_height"),
    ("effective_type", "effective_type"),
    ("round_trip_time", "round_trip_time"),
)

# 顺序敏感：必须先匹配衍生浏览器（Edg/OPR/FxiOS/CriOS），否则会被它们 UA 中
# 携带的 Chrome/Safari 标记抢先命中。
_BROWSER_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("Edge", "Blink", re.compile(r"\bEdg(?:e|A|iOS)?/([0-9][0-9.]*)")),
    ("Opera", "Blink", re.compile(r"\bOPR/([0-9][0-9.]*)")),
    ("Chrome", "Blink", re.compile(r"\bCriOS/([0-9][0-9.]*)")),
    ("Firefox", "Gecko", re.compile(r"\bFxiOS/([0-9][0-9.]*)")),
    ("Firefox", "Gecko", re.compile(r"\bFirefox/([0-9][0-9.]*)")),
    ("Chrome", "Blink", re.compile(r"\bChrome/([0-9][0-9.]*)")),
    # Safari 的版本号只在 Version/ 里；Chrome 的 "Safari/537.36" 不带 Version/，
    # 因此不会误判。iOS Safari 需要 Mobile/ 段。
    (
        "Safari",
        "WebKit",
        re.compile(r"\bVersion/([0-9][0-9.]*)\s+Mobile/\S+\s+Safari/"),
    ),
    ("Safari", "WebKit", re.compile(r"\bVersion/([0-9][0-9.]*)\s+Safari/")),
)

# WebKit 内核版本真实存在于 UA 的 AppleWebKit/ 标记里；Blink 与 Gecko 的 UA
# 只带冻结的兼容标记（537.36 / 20100101），推不出真实内核版本。
_APPLE_WEBKIT_PATTERN = re.compile(r"\bAppleWebKit/([0-9][0-9.]*)")


def _as_param_string(value: Any) -> str | None:
    """把浏览器读数规范化成公共参数字符串；读不到真实值时返回 None。

    只接受正整数（含等值浮点，如 ``navigator.deviceMemory`` 返回的 8.0）与非空
    字符串；布尔、负数、零、复合对象一律视为缺值，交由调用方省略该键。
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value) if value > 0 else None
    if isinstance(value, float):
        return str(int(value)) if value > 0 and value.is_integer() else None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _derive_os(user_agent: str) -> tuple[str | None, str | None]:
    """从 UA 派生 (系统名, 系统版本)；系统版本推不出时只返回系统名。"""
    match = re.search(r"Windows NT ([0-9.]+)", user_agent)
    if match:
        return "Windows", match.group(1)
    # Android 与 Chrome OS 的 UA 都带 Linux 标记，必须先于 Linux 判断。
    match = re.search(r"Android[ /]([0-9.]+)", user_agent)
    if match:
        return "Android", match.group(1)
    match = re.search(r"(?:iPhone|iPad|iPod|CPU (?:iPhone )?OS) ([0-9_]+)", user_agent)
    if match:
        return "iOS", match.group(1).replace("_", ".")
    match = re.search(r"Mac OS X[ /]([0-9_]+)", user_agent)
    if match:
        return "Mac OS", match.group(1).replace("_", ".")
    match = re.search(r"CrOS [^ ]+ ([0-9.]+)", user_agent)
    if match:
        return "Chrome OS", match.group(1)
    if "Linux" in user_agent:
        # 发行版内核版本不在 UA 里，无法诚实推出。
        return "Linux", None
    return None, None


def derive_browser_family(user_agent: str) -> dict[str, str]:
    """从同一份 UA 正则派生浏览器/内核/系统字段；推不出的键不写入。

    参数：
        user_agent: 本次会话真实使用的 ``navigator.userAgent`` 字符串。

    返回：
        仅含推得出真实值的键（``browser_name`` / ``browser_version`` /
        ``engine_name`` / ``engine_version`` / ``os_name`` / ``os_version``）。
    """
    fields: dict[str, str] = {}
    if not isinstance(user_agent, str):
        return fields
    normalized = user_agent.strip()
    if not normalized:
        return fields
    for name, engine, pattern in _BROWSER_PATTERNS:
        match = pattern.search(normalized)
        if match is None:
            continue
        fields["browser_name"] = name
        fields["browser_version"] = match.group(1)
        fields["engine_name"] = engine
        if engine == "WebKit":
            webkit = _APPLE_WEBKIT_PATTERN.search(normalized)
            if webkit:
                fields["engine_version"] = webkit.group(1)
        break
    os_name, os_version = _derive_os(normalized)
    if os_name:
        fields["os_name"] = os_name
    if os_version:
        fields["os_version"] = os_version
    return fields


class BrowserEnvironment:
    """从真实页面采集浏览器读数并产出抖音请求指纹键映射。

    只读页面，不持有会话生命周期；每次采集都是一次 ``page.evaluate``，
    缓存策略由调用方（``BrowserSessionContext``）负责。
    """

    def __init__(self, page: Page) -> None:
        """初始化采集器。

        参数：
            page: 已完成导航的 Playwright 页面；cookie/UA 与请求保持同源。
        """
        self._page = page

    async def read_user_agent(self) -> str:
        """返回当前页面的真实 ``navigator.userAgent``；取不到时返回空字符串。"""
        readings = await self.read_readings()
        user_agent = readings.get("user_agent")
        return user_agent if isinstance(user_agent, str) else ""

    async def read_local_storage(self) -> dict[str, Any]:
        """返回当前页面的 ``window.localStorage`` 快照；取不到时返回 {}。

        页面未导航（about:blank）或处于跨源上下文时浏览器会直接拒绝访问，
        此处按「读不到」处理，绝不向上抛异常。
        """
        try:
            raw: object = await evaluate_stable(self._page, "() => window.localStorage")
        except Exception:
            logger.debug("读取页面 localStorage 失败", exc_info=True)
            return {}
        return dict(raw) if isinstance(raw, Mapping) else {}

    async def read_readings(self) -> dict[str, Any]:
        """一次性采集 navigator/screen/connection 原始读数；失败时返回 {}。"""
        try:
            raw: object = await evaluate_stable(self._page, BROWSER_READINGS_SCRIPT)
        except Exception:
            logger.debug("采集浏览器环境读数失败", exc_info=True)
            return {}
        return dict(raw) if isinstance(raw, Mapping) else {}

    async def read_fingerprint(
        self, *, user_agent: str | None = None
    ) -> dict[str, str]:
        """产出抖音请求指纹键映射；推不出真实值的键一律不写入。

        参数：
            user_agent: 与请求头同源的 UA；为 None 时用本页面读数里的 UA。

        返回：
            键 ⊆ :data:`DOUYIN_FINGERPRINT_KEYS` 的映射；缺键仅记一次 WARNING。
        """
        readings = await self.read_readings()
        resolved_ua = user_agent
        if resolved_ua is None:
            raw_ua = readings.get("user_agent")
            resolved_ua = raw_ua if isinstance(raw_ua, str) else ""
        values: dict[str, str] = derive_browser_family(resolved_ua)
        for fingerprint_key, reading_key in _READING_SOURCES:
            normalized = _as_param_string(readings.get(reading_key))
            if normalized is not None:
                values[fingerprint_key] = normalized
        fingerprint = {
            key: values[key] for key in DOUYIN_FINGERPRINT_KEYS if key in values
        }
        missing = [key for key in DOUYIN_FINGERPRINT_KEYS if key not in fingerprint]
        if missing:
            # 缺键即不写入：只提示一次，绝不回退伪造常量补齐。
            logger.warning(
                "浏览器指纹缺少以下键，将不写入抖音公共参数: %s", ", ".join(missing)
            )
        return fingerprint


__all__ = [
    "BROWSER_READINGS_SCRIPT",
    "DOUYIN_FINGERPRINT_KEYS",
    "BrowserEnvironment",
    "derive_browser_family",
]
