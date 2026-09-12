# 目标架构冻结规格（browser / douyin-client 重构）

> 本文是最终冻结规格，不是讨论稿。凡本文出现的路径、符号名、签名、门禁条目均为**唯一事实**，
> 实施时不得自行改名、改路径、改签名；如需偏离，必须先修改本文并重新评审。
>
> 主体取自「A-最小改动面」方案（评审排名第一），并嫁接 B 系方案的 7 项做法，
> 修掉三份评审指出的全部 fatal flaw。

## 0. 拍板结论（争议点一次性决定）

| 争议点 | 决定 | 理由 |
| --- | --- | --- |
| 门面出口 | 保留 `crawler.browser` 与 `crawler.browser.facade` **两个等价入口**，二者的 `__all__` 顺序一致且逐名同一对象 | 保住房 business 现有 3 处 import，0 改动；同时用「门面同一性」门禁把镜像入口钉死。比 B 的根单入口少一轮 churn |
| 深路径门禁 | 上层（business/api/mcp）只允许 `crawler.browser` 与 `crawler.browser.facade` 两个**精确模块名**，其余 `crawler.browser.<sub>` 一律违规 | 一条前缀判定即可 AST 表达，覆盖 A 的双入口白名单所缺的「子路径」约束 |
| business 是否还能拿到 Playwright 对象 | **不能**。新增只读端口 `BrowserPage`；`CDPBrowserSession.page` / `.context` 在 S5 删除，只留 `browser_page: BrowserPage`（公开）与 `page_handle: PlaywrightPageHandle`（browser 内部专用） | 修掉 A 的致命伤 2（方向 #3 只做到 import 级）；goto/set_cookies 只存在于不出门面的 handle 上 |
| 导航错误契约 | **不引入 `NavigationResult`**。`open()` 保持与 `page.goto()` 同语义：超时抛 `BrowserAutomationTimeoutError`，连接失败抛 `CDPConnectionError` | 修掉 B 系评审指出的「返回值改造超出已确认方向 + `BrowserAutomationTimeoutError` 变成永不触发的悬空符号」；business 的 `except` 与 `_page_navigation_warning` 原样保留 |
| 指纹契约形态 | `SessionContext` 用**内建返回类型**的原语方法（`str` / `dict` / `tuple` / `Mapping[str,str]`），不用 frozen dataclass 结构化协议 | 三条评审一致认定：dataclass 属性不变型会让跨模块结构化满足在 mypy strict 下失败。键名漂移用「两侧键表相等」门禁兜底，不用结构类型兜底 |
| 指纹键表重复 | 允许两处声明（browser 侧 `DOUYIN_FINGERPRINT_KEYS`、douyin_client 侧 `DouyinClient.FINGERPRINT_KEYS`），由门禁断言集合相等 | 两模块互不 import 是硬约束，键表只可能各写一份；用测试把漂移变成红灯比用 dict 魔法键强 |
| 缺键处理 | **缺键即不写入**，绝不回退伪造常量（禁止再出现 `MacIntel`/`Mac OS`/`2560`/`Chrome 125` 字面量） | 修掉 B 的致命伤 2（「回落现有常量」把 P0 缺陷装了回去） |
| 5xx 重试位置 | 判定放在 `request()` 内（`if response.status_code in _RETRYABLE_STATUSES: raise _RetryableStatus`），重签循环放在 `get()`/`post()`；`request()` 原有 TransportError 三次重试**原样保留** | 结构上保证 403/429 不可能进入重试分支（修掉 B 的致命伤 1）；`test_request_retries_transient_remote_protocol_error` 直调 `request()` 的语义不破 |
| `DataFetchError` 签名 | **不改**（不加 `http_status`） | B 加 `http_status` 正是为了做重试判定，而判定放 `request()` 内就不需要它；不改签名 → 零调用方 churn |
| P0b 范围 | 只脱敏 `request_headers`（`Cookie`/`Set-Cookie`/`Authorization`/`Proxy-Authorization`/`X-CSRF-Token`/`X-XSRF-Token`）；`url`/`query_params`/`request_body` 不动 | 修掉 B 的致命伤 4；严格限定在用户口径「仅请求头」，落库内容零变化 |
| `DouyinBrowserMode` 命名 | 重命名为 `BrowserMode`，**不留别名** | 全仓存在两个同名 `DouyinBrowserMode`（browser 一个、business ORM 一个），是真实命名陷阱；引用方只有 browser 内部与 2 个测试 |
| `InteractionBrowserConnection` | **删除**，统一用 `BrowserSessionSpec` | 字段完全重复；business 已在逐字段搬运（`interactions/service.py:1212`） |
| executor 的 `account=` 旧入参与槽位 JSON 解析 | **删除**（连同 `_LegacyAccountId` / `_LegacyInteractionAccount` / `_legacy_remote_slots`） | 生产路径只用 `connection=`/`spec=`；business 的 `resolve_account_browser` 是唯一真源。也避免把 ORM 形状复制进集成层 |
| 目标评论翻页核验归属 | 下沉为 `CommentsApi.find_comment(...) -> CommentPresence`（douyin_client 纯 API 层），browser 侧只做文案翻译 | 三条评审一致认定的「最佳可测试性动作」；原逻辑（50 页 / 1000 条 / cursor 重复 / has_more 类型判定）本就是纯 API 关注点 |
| 适配器落点 | 新增 business 子域 `douyin/adapters/{models.py,service.py}`，并把 `DOUYIN_SUBDOMAINS` 由 10 项扩为 11 项 | 与既有 `models/service 成对` 约定一致；`browser_adapters.py` 挂 douyin 根目录属无约定裸文件 |
| `DouyinClient` 构造点 | 只允许 `douyin/adapters/service.py`（门禁：`DouyinClient(` / `DouyinClient.create(` 的 CallExpr） | `tasks/crawler.py` 需要完整 5 个场景 API，通过适配器的工厂函数 `open_douyin_client()` 取用，而不是自建 |
| 门禁「模块根无裸 .py」范围 | **只覆盖 browser 与 douyin-client 两个成员** | 修掉三份评审共同指出的致命伤：bootstrap/api/mcp/business 模块根今天存在裸 .py 且不在本次范围，全仓落地必然永红 |
| 绿灯节奏 | 允许 `crawler.browser.runtime.{cookies,dom,session}` 三个**临时转发 shim**（S2 建、S6 删） | 让 S1–S5 每个步骤边界都保持 `import` 图完整（`tests/conftest.py` 顶层 import `crawler.api.main`，任何断链会让 pytest 整体 collection error） |
| `tests/browser/` | 新增顶层测试目录（含 `__init__.py`），浏览器内部单测全部迁入 | 新门禁禁止 `tests/business/**`、`tests/api/**` import `crawler.browser.<sub>`，内部单测必须有合法落点 |

---

## 1. 目标目录树

### 1.1 `modules/browser/src/crawler/browser/`（站点无关内核 + 抖音站点层）

```
__init__.py                        门面镜像：仅 `from crawler.browser.facade import (...)`，__all__ 与 facade 逐字一致
facade/
  __init__.py                      唯一对外符号表（22 项），上层只从这里取符号
  protocols.py                     DIP 入站契约：CommentPresence / LoginApi / InteractionApi / InteractionApiFactory
  capabilities.py                  站点无关公共能力：probe_cdp_pages / capture_screenshot（实现原样保留）
  spec.py                          BrowserSessionSpec（冻结 dataclass，连接参数，字节不动）
errors/
  __init__.py                      再导出：包内统一 `from crawler.browser.errors import X`
  family.py                        异常族：BrowserAutomationError / BrowserAutomationTimeoutError（Playwright 别名）、
                                   CDPConnectionError、LoginError、InteractionExecutionError（自 douyin_client 迁入，
                                   基类由 DouyinError 改为 RuntimeError）
connection/
  __init__.py                      包说明：CDP 端点探测、本机拉起与远程接入
  connector.py                     LocalCdpConnector（原 runtime/connect.py 逐行搬移）
  launcher.py                      LocalChromeLauncher（原 runtime/launcher.py 逐行搬移）
  remote.py                        RemoteBrowserManager（原 remote/manager.py 逐行搬移）
session/
  __init__.py                      包说明：会话建立、治理与浏览器环境采集
  manager.py                       CDPBrowserSession（原 runtime/session.py）+ from_spec / open / session_context /
                                   browser_page / page_handle；page/context 属性仅临时保留至 S5
  mode.py                          BrowserMode（原 DouyinBrowserMode 改名）+ coerce_browser_mode（原 base/modes.py）
  policy.py                        PageAcquisitionPolicy（原 runtime/pages.py）
  cookies.py                       convert_cookies / browser_cookies / parse_cookie_string（原 runtime/cookies.py）
  context.py                       BrowserSessionContext：把 page+context 适配成 SessionContext 能力（含 fingerprint 缓存）
  environment.py                   BrowserEnvironment：从真实页面采集 navigator/screen/connection 读数，
                                   从真实 UA 正则推导 browser/os/engine，产出抖音请求指纹键映射
page/
  __init__.py                      包说明：站点无关页面基元与只读端口
  port.py                          BrowserPage（只读能力端口 Protocol，上层唯一可用的浏览器面）
  handle.py                        PlaywrightPageHandle：BrowserPage 的唯一实现，内部附带 goto/set_cookies/
                                   wait_for_selector/clear_domain_cookies/reload/current_url（不出门面）
  primitives.py                    原 runtime/dom.py 的 9 个基元（find_visible/click_control_center/evaluate_stable/...）
interactions/
  __init__.py                      包说明：抖音互动写操作编排
  models.py                        InteractionExecutionRequest / InteractionExecutionResult / InteractionStepCallback
  selectors.py                     抖音互动 DOM 选择器、文案与就绪脚本常量（原样搬移）
  reporting.py                     report_step()：唯一步骤上报函数（合并原 executor._trace 与 SubmitFlow._report）
  navigation.py                    INDEX_URL / VIDEO_URL_TEMPLATE / CREATOR_URL_TEMPLATE + open_index / open_video /
                                   open_creator_profile（原 executor._open_video 等）
  panel.py                         open_comment_panel() / activate_comment_control()（原 executor 同名私有方法）
  verification.py                  lookup_target_comment()：调 InteractionApi.verify_target_comment 并把
                                   CommentPresence 翻译成 InteractionExecutionError 四种分支
  comment_locator.py               CommentLocator（原样搬移 + 方法全部去下划线）
  page_controller.py               PageController（原样搬移 + 方法全部去下划线）
  submit_flow.py                   SubmitFlow（原样搬移 + 去下划线，_report 改为 reporting.report_step）
  response_inspector.py            ResponseInspector（原样搬移 + 去下划线）
  executor.py                      DouyinInteractionExecutor：只剩 __init__(settings) + execute(*, spec, request,
                                   api_factory, step_callback) 与三条流程编排（目标 ≤ 300 行，硬上限见门禁）
login/
  __init__.py                      包说明：抖音登录流程
  flow.py                          DouyinLogin（原 login/login.py）+ from_session() 类方法；verify/refresh 走注入的 LoginApi
resources/
  stealth.js                       反检测脚本（路径不变；读取方在 session/ 第 2 层，parents[1] 仍解析正确）
```

### 1.2 `modules/douyin-client/src/crawler/douyin_client/`（纯 API：签名 + httpx + 解析 + 脱敏）

```
__init__.py                        唯一对外符号表（23 项）
errors/
  __init__.py                      再导出
  family.py                        DouyinError / DataFetchError（LoginError 与 InteractionExecutionError 已迁往 browser）
privacy/
  __init__.py                      再导出
  masking.py                       anonymize_user_id / anonymize_account_id / mask_nickname
  mapping.py                       map_aweme / map_comment / _as_int / _note_images / _comment_images
signing/
  __init__.py                      再导出
  web_id.py                        get_web_id
  a_bogus.py                       get_a_bogus / _signer（execjs + resources/douyin.js，parents[1] 深度不变）
parsing/
  __init__.py                      再导出
  types.py                         SearchChannelType / SearchSortType / PublishTimeType / VideoUrlInfo / CreatorUrlInfo
  links.py                         parse_video_info / parse_creator_info
session/
  __init__.py                      再导出 SessionContext
  context.py                       SessionContext Protocol（入站 DIP：douyin_client 拥有，browser 结构化满足，business 注入）
http/
  __init__.py                      包说明
  client.py                        DouyinClient：session= 注入、指纹全外置（P0a）、get/post 5xx 重签重试（P0c）
  request_log.py                   DouyinRequestLogEntry（P0b：__post_init__ 构造即脱敏请求头）+ RequestLogCallback /
                                   CommentCallback / IntervalProvider / _interval_seconds
  redaction.py                     脱敏唯一真源：SENSITIVE_HEADER_NAMES / SENSITIVE_KEY_MARKERS / REDACTED /
                                   redact_headers / redact_mapping（business 侧改为复用）
  scenarios/
    __init__.py                    再导出五个场景客户端
    aweme.py                       AwemeApi（+ get_video 保持不变）
    comments.py                    CommentsApi（+ find_comment(...) -> CommentPresence，自 executor 迁入）
    resolver.py                    ShortUrlApi（本次不动 5xx 重试，只把 failure_detail 调用改为公开名）
    search.py                      SearchApi
    user.py                        UserApi
resources/
  douyin.js                        execjs 签名脚本（路径不变）
```

### 1.3 `modules/business/src/crawler/business/douyin/adapters/`（新增子域）

```
__init__.py                        子域门面
models.py                          DouyinBrowserApiConfig（timeout / verify_ssl 冻结配置）+ InteractionApiFactory 别名
service.py                         唯一装配点：
                                     - open_douyin_client(*, page, settings) -> DouyinClient
                                     - DouyinLoginApi（实现 browser.LoginApi）
                                     - DouyinInteractionApi（实现 browser.InteractionApi）
                                     - build_interaction_api_factory(settings) -> InteractionApiFactory
```

---

## 2. browser 门面导出清单（`crawler.browser.__all__` == `crawler.browser.facade.__all__`，22 项）

| # | 符号 | 种类 | 位置 |
| --- | --- | --- | --- |
| 1 | `BrowserAutomationError` | TypeAlias（`playwright.async_api.Error`） | `errors/family.py` |
| 2 | `BrowserAutomationTimeoutError` | TypeAlias（`playwright.async_api.TimeoutError`） | `errors/family.py` |
| 3 | `CDPConnectionError` | 异常类（RuntimeError 子类） | `errors/family.py` |
| 4 | `LoginError` | 异常类（RuntimeError 子类，自 douyin_client 迁入） | `errors/family.py` |
| 5 | `InteractionExecutionError` | 异常类（RuntimeError 子类，保留 code/retryable/ambiguous/affects_account_health） | `errors/family.py` |
| 6 | `BrowserMode` | Enum（str；local/remote；原 `DouyinBrowserMode` 改名） | `session/mode.py` |
| 7 | `BrowserSessionSpec` | 冻结 dataclass | `facade/spec.py` |
| 8 | `CDPBrowserSession` | 类（会话编排入口） | `session/manager.py` |
| 9 | `BrowserSessionContext` | 类（会话能力适配器，结构化满足 `douyin_client.SessionContext`） | `session/context.py` |
| 10 | `capture_screenshot` | async 函数（真实实现，供 handle 与直测使用） | `facade/capabilities.py` |
| 11 | `probe_cdp_pages` | 同步函数 | `facade/capabilities.py` |
| 12 | `BrowserPage` | Protocol（只读页面能力端口，business 唯一可用浏览器面） | `page/port.py` |
| 13 | `LoginApi` | Protocol（browser 拥有的登录契约） | `facade/protocols.py` |
| 14 | `InteractionApi` | Protocol（browser 拥有的互动读接口契约） | `facade/protocols.py` |
| 15 | `InteractionApiFactory` | TypeAlias | `facade/protocols.py` |
| 16 | `CommentPresence` | Literal 别名 | `facade/protocols.py` |
| 17 | `InteractionStepCallback` | TypeAlias（首个参数为 `BrowserPage`） | `interactions/models.py` |
| 18 | `QRCodeCallback` | TypeAlias | `login/flow.py` |
| 19 | `InteractionExecutionRequest` | 冻结 dataclass | `interactions/models.py` |
| 20 | `InteractionExecutionResult` | 冻结 dataclass | `interactions/models.py` |
| 21 | `DouyinInteractionExecutor` | 类 | `interactions/executor.py` |
| 22 | `DouyinLogin` | 类 | `login/flow.py` |

**相对现状的变化**：新增 4 项（`BrowserMode`、`BrowserPage`、`LoginApi`、`InteractionApi`+`InteractionApiFactory`+`CommentPresence`+`LoginError`+`InteractionExecutionError`+`InteractionExecution*`+`DouyinLogin`+`DouyinInteractionExecutor` 中的 browser 新增部分 —— 即净增 14 项）；移除 12 项（9 个 dom 基元 + 3 个 cookie 工具，改由 `crawler.browser.page.primitives` / `session.cookies` 内部路径提供）。

> 事实校正（三份评审共同指出原方案计数有误）：现状 `crawler.browser.__all__` **恰好 20 项**、`facade.__all__` **8 项**。本次是 `20 → 22`，不是「32 → 20」。

**不在门面内、仅供 browser 内部与 `tests/browser/` 直测的符号**：`PlaywrightPageHandle`、`CommentLocator`、`PageController`、`SubmitFlow`、`ResponseInspector`、`interactions.selectors` 常量、`LocalCdpConnector`、`LocalChromeLauncher`、`RemoteBrowserManager`、`PageAcquisitionPolicy`、`BrowserEnvironment`、`page.primitives` 的 9 个基元、`session.cookies` 的 3 个工具、`describe_browser_error`（如需）。

---

## 3. douyin-client 对外保留清单（`crawler.douyin_client.__all__`，23 项）

| # | 符号 | 种类 | 位置 |
| --- | --- | --- | --- |
| 1 | `DouyinError` | 异常基类 | `errors/family.py` |
| 2 | `DataFetchError` | 异常类（签名不变：`DataFetchError(message)`） | `errors/family.py` |
| 3 | `SearchChannelType` | Enum | `parsing/types.py` |
| 4 | `SearchSortType` | Enum | `parsing/types.py` |
| 5 | `PublishTimeType` | Enum | `parsing/types.py` |
| 6 | `VideoUrlInfo` | pydantic BaseModel | `parsing/types.py` |
| 7 | `CreatorUrlInfo` | pydantic BaseModel | `parsing/types.py` |
| 8 | `parse_video_info` | 函数 | `parsing/links.py` |
| 9 | `parse_creator_info` | 函数 | `parsing/links.py` |
| 10 | `DouyinClient` | 类 | `http/client.py` |
| 11 | `DouyinRequestLogEntry` | dataclass（`__post_init__` 构造即脱敏） | `http/request_log.py` |
| 12 | `RequestLogCallback` | TypeAlias | `http/request_log.py` |
| 13 | `CommentCallback` | TypeAlias（本次纳入 `__all__`） | `http/request_log.py` |
| 14 | `IntervalProvider` | TypeAlias（本次纳入 `__all__`） | `http/request_log.py` |
| 15 | `SessionContext` | Protocol（本次新增公开） | `session/context.py` |
| 16 | `anonymize_user_id` | 函数 | `privacy/masking.py` |
| 17 | `anonymize_account_id` | 函数 | `privacy/masking.py` |
| 18 | `mask_nickname` | 函数 | `privacy/masking.py` |
| 19 | `map_aweme` | 函数 | `privacy/mapping.py` |
| 20 | `map_comment` | 函数 | `privacy/mapping.py` |
| 21 | `REDACTED` | 常量 `"[REDACTED]"` | `http/redaction.py` |
| 22 | `redact_headers` | 函数 | `http/redaction.py` |
| 23 | `redact_mapping` | 函数 | `http/redaction.py` |

**移出（迁往 `crawler.browser`）**：`LoginError`、`InteractionExecutionError`、`DouyinLogin`、`DouyinInteractionExecutor`、`InteractionExecutionRequest`、`InteractionExecutionResult`、`InteractionBrowserConnection`（并入 `BrowserSessionSpec`）。
**同时删除的打包级依赖**：`modules/douyin-client/pyproject.toml` 的 `crawler-browser`、`playwright`（`crawler-bootstrap` 只出现在 `[tool.uv.sources]`，一并删除该条），description 改为 `"Douyin HTTP API client: signing, transport, response parsing, privacy mapping."`。

---

## 4. Protocol 与新增/变更签名（可直接落地）

### 4.1 `crawler/douyin_client/session/context.py` —— douyin_client 拥有、browser 结构化实现

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SessionContext(Protocol):
    """DouyinClient 依赖的浏览器会话最小能力；由上层注入，douyin_client 不反向依赖实现方。

    实现方（crawler.browser.session.context.BrowserSessionContext）不 import 本 Protocol，
    靠结构化匹配满足；4 个方法全部返回内建类型，mypy strict 可结构化校验。
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
```

**契约不变量（实现方必须遵守，由门禁与测试钉住）**
1. 键集合必须等于 `DouyinClient.FINGERPRINT_KEYS`（集合相等，允许缺值不允许缺名）。
2. 值必须来自真实浏览器读数（`navigator` / `screen` / `navigator.userAgent` 推导），**禁止任何硬编码假值**。
3. `fingerprint()` 在同一会话内幂等（首次采集后缓存）。

### 4.2 `crawler/browser/page/port.py` —— browser 拥有、business 消费

```python
@runtime_checkable
class BrowserPage(Protocol):
    """browser 提供给上层的只读页面能力端口（上层唯一可用的浏览器面）。"""

    async def user_agent(self) -> str: ...
    async def local_storage(self) -> dict[str, Any]: ...
    async def cookies(self, urls: Sequence[str]) -> tuple[str, dict[str, str]]: ...
    async def fingerprint(self) -> Mapping[str, str]: ...
    async def capture_screenshot(self, *, quality: int, timeout: float) -> bytes: ...
```

> 形状 ⊇ `SessionContext`（前 4 个方法同名同型），因此适配器可把 `browser.browser_page` 直接作为
> `DouyinClient.create(session=...)` 的入参，并可用 `isinstance(PlaywrightPageHandle, SessionContext)`
> 做运行时断言（门禁 G14）。这是替代「14 个魔法字符串键」的结构性保障。

### 4.3 `crawler/browser/facade/protocols.py` —— browser 拥有、business 实现

```python
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
```

### 4.4 `CDPBrowserSession` 公开签名（`session/manager.py`）

```python
class CDPBrowserSession:
    def __init__(
        self,
        config: Settings,
        *,
        browser_mode: str | object | None = None,
        remote_host: str | None = None,
        remote_port: int | None = None,
        user_data_dir: Path | None = None,
        debug_port: int | None = None,
        reuse_existing_page: bool = False,
        close_page_on_exit: bool = True,
        page_marker: str | None = None,
    ) -> None: ...

    @classmethod
    def from_spec(
        cls,
        config: Settings,
        spec: BrowserSessionSpec,
        *,
        reuse_existing_page: bool = False,
        close_page_on_exit: bool = True,
        page_marker: str | None = None,
    ) -> "CDPBrowserSession": ...          # 新增：business 用 resolve_account_browser() 的结果直接构造

    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def __aenter__(self) -> "CDPBrowserSession": ...
    async def __aexit__(self, *exc: object) -> None: ...

    async def open(
        self, url: str, *, wait_until: str = "domcontentloaded", timeout_ms: int = 30_000
    ) -> None: ...                          # 新增：等同 page.goto，超时抛 BrowserAutomationTimeoutError

    def session_context(self) -> BrowserSessionContext: ...   # 新增；未 start() 或已 close() 抛 CDPConnectionError
    @property
    def browser_page(self) -> BrowserPage: ...               # 新增；公开只读面
    @property
    def page_handle(self) -> PlaywrightPageHandle: ...       # 新增；browser 内部专用（business 禁止出现该名字）
    @property
    def browser_mode(self) -> object: ...                    # 原语义保留（返回调用方传入的暴露对象）
    @property
    def unrelated_page_count(self) -> int: ...               # 原语义保留

    # 临时兼容属性（S5 删除，S2–S4 期间保留，仅供未切割的 business 使用）
    @property
    def page(self) -> Page | None: ...
    @property
    def context(self) -> BrowserContext | None: ...
```

### 4.5 `DouyinClient` 签名变更（`http/client.py`）

```python
class DouyinClient:
    host = "https://www.douyin.com"
    cookie_urls = [...]  # 保持不变：抖音 cookie 作用域唯一真源

    FINGERPRINT_KEYS: tuple[str, ...] = (
        "browser_language", "browser_platform", "browser_name", "browser_version",
        "engine_name", "engine_version", "os_name", "os_version",
        "cpu_core_num", "device_memory", "screen_width", "screen_height",
        "effective_type", "round_trip_time",
    )

    def __init__(
        self, *, session: SessionContext, headers: dict[str, str],
        cookie_dict: dict[str, str], timeout: float, verify_ssl: bool,
    ) -> None: ...

    @classmethod
    async def create(
        cls, *, session: SessionContext, timeout: float, verify_ssl: bool
    ) -> "DouyinClient": ...      # UA 取 session.user_agent()，cookie 取 session.cookies(cls.cookie_urls)

    async def close(self) -> None: ...
    async def request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]: ...
    async def get(self, uri: str, params: dict[str, Any] | None = None,
                  headers: dict[str, str] | None = None) -> dict[str, Any]: ...
    async def post(self, uri: str, data: dict[str, Any],
                   headers: dict[str, str] | None = None,
                   params: dict[str, Any] | None = None) -> dict[str, Any]: ...
    async def pong(self, *, require_self_profile: bool = False) -> bool: ...   # 去掉 browser_context 入参
    async def update_cookies(self) -> None: ...                                # 去掉 browser_context 入参
    async def _process_params(self, uri: str, params: dict[str, Any],
                              headers: dict[str, str]) -> dict[str, Any]: ...
```

### 4.6 `CommentsApi.find_comment`（`http/scenarios/comments.py`）

```python
async def find_comment(
    self, *, aweme_id: str, comment_id: str, parent_comment_id: str | None = None,
    max_pages: int = 50, max_comments: int = 1_000,
) -> str:  # "present" | "unavailable" | "inconclusive"
```

搬移原 `executor._lookup_target_comment`（`modules/douyin-client/.../interactions/executor.py:420-474`）的
全部判定与 `asyncio.sleep(0.2)` 节奏，逐行等价；仅把 `request.target_*` 入参改为关键字参数。
返回值建议实现为 `crawler.browser` 侧同名 Literal `CommentPresence`（browser 侧自带一份，避免 import）。

### 4.7 `DouyinLogin` 与 executor（browser 站点层）

```python
class DouyinLogin:
    @classmethod
    def from_session(
        cls, session: CDPBrowserSession, *, qrcode_path: Path, timeout: float,
        on_qrcode: QRCodeCallback,
    ) -> "DouyinLogin": ...                                  # 内部取 session.page_handle / _context
    async def login_with_cookie(self, cookie_string: str, api: LoginApi) -> None: ...
    async def is_logged_in(self, api: LoginApi, *, require_self_profile: bool = False) -> bool: ...
    async def login_with_qrcode(self, api: LoginApi, *, require_self_profile: bool) -> None: ...


class DouyinInteractionExecutor:
    def __init__(self, settings: Settings) -> None: ...
    async def execute(
        self, *, spec: BrowserSessionSpec, request: InteractionExecutionRequest,
        api_factory: InteractionApiFactory,
        step_callback: InteractionStepCallback | None = None,
    ) -> InteractionExecutionResult: ...
```

`is_logged_in` 的**顺序契约（必须逐字保持）**：非 `require_self_profile` 时先读
`session.local_storage()` 的 `HasUserLogin == "1"`、再读 cookie `LOGIN_STATUS == "1"`，命中即 True；
未命中或 `require_self_profile=True` 时才回调 `api.verify_login(require_self_profile=...)`。
（S3 的 login 流程必须钉住这一点，否则扫码轮询会从每秒一次本地判断退化为每秒一次高风控资料接口调用。）

executor 内的登录校验改为：`if not await api.verify_login(require_self_profile=True): raise InteractionExecutionError("login_required", ...)`。
`api_factory` 的调用时机：**首页导航成功之后**、校验登录之前（保证 cookie/UA 已就绪）。

> **订正（S6 复核，见 OI-2）**：实施走的是 `navigation.open_index(page)`
> （即 `page.goto(INDEX_URL, domcontentloaded, 30s)` 且**吞掉** commit 超时），
> 而非本行原文写的 `await session.open(INDEX_URL)`——后者的语义不同，会把超时抛成
> `BrowserAutomationTimeoutError`。取 `open_index()` 是为了**与迁移前行为逐字一致**（更宽松）。
> 两者都满足「导航完成后才建 client」这条真正的不变量，本步按实现钉住了 `api_factory` 的时序。

### 4.8 business 适配器（`douyin/adapters/service.py`）

```python
async def open_douyin_client(*, page: BrowserPage, settings: Settings) -> DouyinClient:
    """唯一构造 DouyinClient 的位置；UA/cookie 全部经 page 提供。"""

class DouyinLoginApi:            # 实现 browser.LoginApi（不持有生命周期）
    def __init__(self, *, client: DouyinClient) -> None: ...
    async def verify_login(self, *, require_self_profile: bool = False) -> bool: ...  # client.pong(...)
    async def get_self_profile(self) -> Mapping[str, Any] | None: ...                 # client.user_api
    async def refresh_cookies(self) -> None: ...                                      # client.update_cookies()
    async def aclose(self) -> None: ...                                               # client.close()

class DouyinInteractionApi:      # 实现 browser.InteractionApi（拥有生命周期）
    def __init__(self, *, page: BrowserPage, config: DouyinBrowserApiConfig) -> None: ...
    # 首次调用时 lazy 构造：assert page 已完成导航 → fingerprint/cookies/user_agent → DouyinClient.create(session=page)
    async def verify_login(...) -> bool: ...
    async def verify_target_comment(...) -> CommentPresence: ...   # DataFetchError → "inconclusive"
    async def resolve_video_author_sec_uid(...) -> str | None: ...  # DataFetchError → InteractionExecutionError("api_unavailable", retryable=True)
    async def refresh_cookies() -> None: ...
    async def aclose() -> None: ...        # 必须 await self._client.close()

def build_interaction_api_factory(settings: Settings) -> InteractionApiFactory: ...
```

> `DouyinInteractionApi` 的 lazy 时序是新增失败模式：若在导航前被调用，cookie/UA 会是空值并静默判为未登录。
> 实现必须显式断言「首次 API 调用前已导航」并配单测（见 S5 验证）。

---

## 5. 目标 import 规则（AST 可断言条目）

以下条目逐条对应门禁测试，`_violating_crawler_imports` / `_violating_third_party_imports` 沿用现有实现。

| 规则 | 断言内容 | 表达方式 |
| --- | --- | --- |
| **G1** douyin_client 零浏览器 | `FORBIDDEN_CRAWLER_PREFIXES["douyin_client"] += ("crawler.browser", "crawler.bootstrap")`；`FORBIDDEN_PACKAGES["douyin_client"] += {"playwright"}`；断言 `_violating_crawler_imports("douyin_client")` 与 `_violating_third_party_imports("douyin_client")` 均为空 | 现有函数 + 两处常量新增 |
| **G2** browser ⊥ douyin_client | browser 禁 `crawler.douyin_client`（现状已满足，保持） | 现有 |
| **G3** 上层只经 browser 门面 | business/api/mcp 逐文件 AST：`ast.ImportFrom` 且 `node.module` 以 `crawler.browser` 开头时，`node.module ∈ {"crawler.browser", "crawler.browser.facade"}` 且每个 `alias.name ∈ crawler.browser.facade.__all__`；`ast.Import` 的 `alias.name` 以 `crawler.browser.` 开头即违规 | 新函数 `_violating_facade_imports(module, prefix, allowed_modules, facade_attr)`；失败时输出 `(文件, 模块, 符号)` 明细 |
| **G4** douyin_client 只经门面 | business/api/mcp：同上，但 `node.module` 必须精确等于 `crawler.douyin_client`，符号名 ∈ `crawler.douyin_client.__all__` | 同 G3，换参数 |
| **G5** 门面同一性 | `crawler.browser.__all__ == crawler.browser.facade.__all__`（顺序一致），且 `getattr(crawler.browser, n) is getattr(crawler.browser.facade, n)` 对每个名字成立 | 运行时比对 |
| **G6** 模块根只 import 自家门面 | `crawler/browser/__init__.py` 的每个 `ast.ImportFrom` 的 `node.module` 只能等于 `crawler.browser.facade`；`douyin_client/__init__.py` 的 `node.module` 只能以 `crawler.douyin_client.` 开头 | AST 扫描该文件 |
| **G7** 模块根纯净（**仅限 browser 与 douyin-client**） | `MODULE_ROOT.glob("*.py") == ["__init__.py"]`；且根下每一项 ∈ {`__init__.py`, 含 `__init__.py` 的目录, `resources`} | 新测试，参数化 `BARE_PY_GUARDED_MEMBERS = ("browser", "douyin-client")` |
| **G8** 子包名不与包内文件重名 | 对 browser/douyin_client 下每个含 `__init__.py` 的目录 `p`：不存在 `p / f"{p.name}.py"` 且不存在 `p / p.name /` | 递归扫描 |
| **G9** 每个子包含 `__init__.py` | browser/douyin_client 递归，除 `resources/` 外每个目录含 `__init__.py` | 递归扫描 |
| **G10** 子包集合冻结 | browser 直接子包集合 `== {"facade","errors","connection","session","page","interactions","login"}`；douyin_client `== {"errors","privacy","signing","parsing","session","http"}` | 集合并集断言 |
| **G11** 旧路径消失 | browser 下不存在 `base/`、`runtime/`、`remote/`；全仓 `.py` 文本不含 `'crawler.browser.runtime'`、`'crawler.browser.base'`、`'crawler.browser.remote'` | 目录存在性 + 文本扫描（含 `tests/`） |
| **G12** 交互/登录归属 | douyin_client 下不存在 `interactions/`、`login/`；`DouyinInteractionExecutor`/`DouyinLogin`/`InteractionExecutionError`/`LoginError`/`InteractionExecutionRequest`/`InteractionExecutionResult` 只从 `crawler.browser` 或 `crawler.browser.facade` 可取（同一性：`getattr(crawler.browser, n) is getattr(importlib.import_module("crawler.douyin_client"), n, None)` 为 False） | 目录存在性 + 符号可达性 |
| **G13** 测试侧边界 | `tests/business/**`、`tests/api/**` 中不得出现 `crawler.browser.<sub>` 形式的 import（只允许 `crawler.browser` 与 `crawler.browser.facade`）；`crawler.browser.core`/`sites` 在本设计不存在，故该规则与 G3 同形 | AST 扫描 `tests/business`、`tests/api` |
| **G14** 端口与契约结构化一致 | `isinstance(crawler.browser.page.handle.PlaywrightPageHandle, crawler.douyin_client.session.context.SessionContext)` 为 True（两个 Protocol 均 `runtime_checkable`；对类而非实例判定） | 运行时断言（类级方法集检查） |
| **G15** 指纹键表一致 | `set(crawler.browser.session.environment.DOUYIN_FINGERPRINT_KEYS) == set(DouyinClient.FINGERPRINT_KEYS)`，且两处均为 `tuple[str, ...]` | 常量比对 |
| **G16** DouyinClient 构造点唯一 | business 下 `DouyinClient(` / `DouyinClient.create(` 的 `ast.Call` 只能出现在 `douyin/adapters/service.py` | AST Call 扫描 |
| **G17** business 不得触碰内部句柄 | business/api/mcp 源码文本不含 `"page_handle"` | 文本扫描（比属性级 AST 更简单且足够精确） |
| **G18** 打包级零浏览器 | `modules/douyin-client/pyproject.toml` 的 `project.dependencies` 不含 `crawler-browser`、`playwright`；`[tool.uv.sources]` 不含 `crawler-browser`、`crawler-bootstrap` | TOML 解析 |
| **G19** 拆分不回流 | `len(Path("modules/browser/.../interactions/executor.py").read_text().splitlines()) <= 300`；`interactions/` 下不得出现新的 `orchestrator.py` 之类聚合文件 | 行数 + 文件名白名单 |
| **G20** browser 内部不反向依赖站点层（可选加固） | browser 无 core/sites 之分，故本规则不适用；改为 `session/`、`page/`、`connection/`、`errors/` 下不得 import `crawler.browser.interactions` 或 `crawler.browser.login` | AST 扫描 |

---

## 6. 分波次迁移步骤

**依赖图**：`S1 ∥ S2` → `S3 ∥ S4` → `S5` → `S6`。
每一步结束时 `import crawler.api.main` 必须成功（`tests/conftest.py` 顶层 import 它，断链会让 pytest 整体 collection error）。

### S1｜P0b + P0c：douyin_client HTTP 层健壮性修复（原地做，独立可发布）

- **【文件集】**
  - 改 `modules/douyin-client/src/crawler/douyin_client/http/client.py`（仅 P0c）
  - 改 `.../http/request_log.py`（P0b）
  - 新增 `.../http/redaction.py`
  - 改 `modules/business/src/crawler/business/douyin/request_logs/service.py`（`sanitize_mapping` 改为复用 `redact_mapping`）
  - 改 `tests/business/douyin/test_client.py`、`tests/business/douyin/test_request_logs.py`
- **【并行分组】** wave1-A，与 S2 并行（文件集不重叠：S1 只碰 douyin_client/http/* 与 business/.../request_logs/，S2 只碰 browser/** 与 tests/browser/**）
- **【风险】**
  1. P0c 只能加在 `get()`/`post()` 层，`request()` 的 TransportError 三次重试必须原样保留（`test_request_retries_transient_remote_protocol_error` 直调 `request()`）。
  2. `_RetryableStatus` 必须继承 `DataFetchError`，否则破坏既有 `except DataFetchError` 调用方。
  3. P0b 只改 `request_headers`：`DouyinRequestLogEntry` 是非 frozen dataclass（已核实），`__post_init__` 可就地赋值；**不得**改 `url`/`query_params`/`request_body`（`test_request_logs.py` 对这三者有逐字段断言）。
  4. P0a 不在本步（见 S3），本步不得触碰 `_process_params` 的指纹常量。
- **【验证方式】**
  - `uv run pytest tests/business/douyin/test_client.py tests/business/douyin/test_request_logs.py -q`
  - `uv run mypy -p crawler.douyin_client`
  - 新增用例：`test_douyin_client_retries_retryable_5xx_with_resigning`（502→200，断言 2 次 HTTP 调用、`get_a_bogus` 被调 2 次）、`test_douyin_client_does_not_retry_403_429`（各断言只发 1 次且抛 `DataFetchError`）、`test_request_log_entry_redacts_headers_at_construction`

### S2｜browser 内部按职责重组到终态路径 + 门面骨架 + 临时 shim

- **【文件集】**
  - 新增 `browser/{__init__.py, facade/{__init__,protocols,capabilities,spec}.py, errors/{__init__,family}.py, connection/{__init__,connector,launcher,remote}.py, session/{__init__,manager,mode,policy,cookies,context,environment}.py, page/{__init__,port,handle,primitives}.py}`
  - 删除 `browser/base/`、`browser/runtime/{connect,launcher,pages,session}.py`、`browser/remote/`
  - 新增临时 shim `browser/runtime/{__init__,cookies,dom,session}.py`（显式 `as` 再导出，S6 删除）
  - 迁移测试：`tests/business/douyin/{test_browser_cookies,test_browser_dom,test_browser_facade,test_browser_session,test_remote_browser}.py` → `tests/browser/core/{test_session,test_connection_local,test_connection_remote,test_probe,test_page_adapter,test_capture_screenshot,test_primitives,test_cookies}.py`；新增 `tests/browser/__init__.py`、`tests/browser/core/__init__.py`
- **【并行分组】** wave1-B，与 S1 并行
- **【风险】**
  1. `session/manager.py` 必须仍在模块**第 2 层**，否则 `Path(__file__).resolve().parents[1] / "resources" / "stealth.js"`（现 `runtime/session.py:160`）解析到 `crawler/browser/` 之外。这一条是 B 系方案的致命伤，本设计用「目录深度 + G9/G10 子包集合冻结」双重锁死，并在 `test_session.py` 加一条**显式断言 `stealth_path.exists()`**（不能只靠 mock）。
  2. `crawler.browser.__all__` 收敛（移除 9 个 dom 基元 + 3 个 cookie 工具）：只有 4 个测试文件引用，均已在本步文件集内。
  3. `page`/`context` 临时属性必须保留（S5 才删），否则 business 立即 ImportError/AttributeError。
  4. `BrowserMode` 改名会打断 `test_browser_session.py` 的 `from crawler.browser.base.modes import DouyinBrowserMode as NeutralMode` —— 该文件在本步迁移，同步改成 `from crawler.browser.session.mode import BrowserMode`。
- **【验证方式】**
  - `uv run ruff check modules/browser tests/browser && uv run mypy -p crawler.browser`
  - `uv run python -c "import crawler.browser, crawler.browser.facade; print(len(crawler.browser.__all__))"`（应为 22）
  - `uv run pytest tests/browser tests/business/douyin/test_client.py -q`（`test_client.py` 靠 shim 继续可跑）
  - 断言 shim 生效：`uv run python -c "from crawler.browser.runtime.cookies import browser_cookies; from crawler.browser.runtime import dom"`

### S3｜douyin_client 纯化：SessionContext 注入 + P0a 指纹 + base/ 重组

- **【文件集】**
  - 新增 `douyin_client/session/{__init__,context}.py`
  - 重组 `douyin_client/base/` → `errors/{__init__,family}.py`、`privacy/{__init__,masking,mapping}.py`、`signing/{__init__,a_bogus,web_id}.py`、`parsing/{__init__,types,links}.py`；删除 `base/`
  - 改 `douyin_client/http/client.py`（`session=` 注入 + `FINGERPRINT_KEYS` + P0a + `pong`/`update_cookies` 去 browser_context 入参）；`http/request_log.py` 仅改 docstring 中的路径引用
  - 改 `douyin_client/__init__.py`（符号表按 §3）
  - 改 `tests/business/douyin/test_client.py`（假 session 改写）、`test_privacy.py`
  - 改 `modules/business/.../douyin/accounts/service.py`（`:1208` 与 `:1218`）与 `.../tasks/crawler.py`（`:158`）两处 `DouyinClient.create(...)` 调用点 → 传 `session=browser.session_context()`
- **【并行分组】** wave2-A，与 S4 并行（S3 只碰 douyin_client 的 client/errors/privacy/signing/parsing/session 与 `__init__.py`、business 两个调用点；S4 只碰 browser/interactions、browser/login、browser/facade、`douyin_client/http/scenarios/*`）
- **【风险】**
  1. **P0a 是本步头号交付**：删除 14 个硬编码指纹键，改为 `fingerprint = await self.session.fingerprint()` 后逐键写入；缺键**不写入**，源码中不得再出现 `MacIntel`/`Mac OS`/`2560`/`1440`/`Chrome 125` 字面量（门禁与用例双重断言）。
  2. `fingerprint()` 的值必须来自真实浏览器：`browser/session/environment.py` 的采集脚本从 `navigator.language/platform/hardwareConcurrency/deviceMemory`、`screen.width/height`、`navigator.onLine`、`navigator.connection.effectiveType/rtt` 读数；`derive_browser_family(user_agent)` 用正则从**与 header 同一个 UA** 推导 `browser_name/browser_version/engine_name/engine_version/os_name/os_version`（Edg→Edge、Chrome→Blink 等；Windows NT x.y→`Windows`/同值，Mac OS X 10_15_7→`Mac OS`/`10.15.7`，Linux/Android/iPhone OS 同理），解析不出则省略并把缺失键记一次 WARNING。
  3. 键集漂移风险：`DOUYIN_FINGERPRINT_KEYS` 与 `FINGERPRINT_KEYS` 必须集合相等（门禁 G15）。**绝不回退伪造常量**（违反即视为 P0 未修复）。
  4. `pong()` 的快速判定改读 `self.session.local_storage()` / `self.session.cookies(self.cookie_urls)`；`local_storage()` 失败必须返回 `{}` 而不是抛异常（否则 pong 语义变化）。
  5. `test_client.py` 的假 session 必须实现 4 个方法且返回内建类型；该文件不得再 import `crawler.browser.<sub>`（G13）。
  6. business 只改 2 处（不是 4 处）：`accounts/service.py:1208` 与 `tasks/crawler.py:158`；`accounts:1218` 的 `client.pong(context)` 与 `accounts:1221` 的 `user_api` 访问本步不动（`DopyinClient` 实例仍在手，S5 才切到 LoginApi）。
- **【验证方式】**
  - `uv run pytest tests/business/douyin/test_client.py tests/business/douyin/test_privacy.py tests/business/douyin/test_accounts_works_exports.py -q`
  - `uv run mypy -p crawler.douyin_client -p crawler.business`
  - 新用例：`test_douyin_client_fingerprint_params_come_from_session`（假 session 返回固定指纹 → 断言公共参数逐键来自指纹；源码无 `MacIntel` 字面量）、`test_douyin_client_has_no_browser_dependency`（`import crawler.douyin_client` 后 `"playwright" not in sys.modules`）

### S4｜interactions/ 与 login/ 迁入 browser（executor 拆五职责、去假私有、CommentPresence 下沉）

- **【文件集】**
  - 新增 `browser/interactions/{__init__,models,selectors,reporting,navigation,panel,verification,comment_locator,page_controller,submit_flow,response_inspector,executor}.py`（自 `douyin_client/interactions/` 迁入并改写）
  - 新增 `browser/login/{__init__,flow}.py`（自 `douyin_client/login/login.py` 迁入 + `from_session`）
  - 改 `browser/facade/{__init__,protocols}.py`、`browser/__init__.py`（补 16 个站点层符号，`__all__` 收到 22）
  - 改 `douyin_client/http/scenarios/comments.py`（+`find_comment`）、`aweme.py`（确认 `get_video` 公开可用）
  - 新增 `tests/browser/sites/douyin/{__init__,test_login_flow,test_interaction_executor,test_comment_locator,test_submit_flow,test_response_inspector,test_navigation,test_verification}.py`
  - **本步不碰** `douyin_client/__init__.py`、`douyin_client/interactions/`、`douyin_client/login/`（保持原样可用，S5 才删）—— 这是「先建新家、后切割」的关键，避免 red window
- **【并行分组】** wave2-B，与 S3 并行（文件集不重叠）
- **【风险】**
  1. 假私有改名（`CommentLocator._find_comment_target` → `find_comment_target` 等约 30 处）会打断 `tests/business/douyin/test_interaction_executor.py` 的 monkeypatch 目标；该文件在本步迁到 `tests/browser/sites/douyin/`，用「先 sed 机械替换、再人工修 mock 形状」两段式。
  2. mock 形状变化：`client.aweme_api.get_video` → `api.resolve_video_author_sec_uid`；`client.comments_api.*` → `api.verify_target_comment`；`client.pong/update_cookies/close` → `api.verify_login/refresh_cookies/aclose`。假 `InteractionApi` 只需 5 个方法。
  3. executor 构造参数变化：`DouyinInteractionExecutor(settings)` 不变，但 `execute()` 新增必填 `spec=` 与 `api_factory=`、删除 `account=`/`connection=`；本步只改 browser 内部与测试，business 调用点在 S5 改。
  4. `api_factory` 必须在 `open_index()` 之后调用；`finally` 中 `await api.aclose()`。
  5. 原 executor 内 `await client.update_cookies(browser.context)`（`:157`）在 `create` 已采集 cookie 后属冗余 → 改为 `await api.refresh_cookies()`（保留调用，语义等价且不回退行为）。
  6. `browser/interactions/*` 仍 import `page.primitives`（不 import `douyin_client`），确保 G1/G2 成立。
- **【验证方式】**
  - `uv run mypy -p crawler.browser`
  - `uv run pytest tests/browser -q`（含新增 `test_verification.py`：`present`→通过、`unavailable`→`InteractionExecutionError("target_unavailable")`、`inconclusive`→`target_lookup_inconclusive`）
  - `uv run python -c "import crawler.browser; print(len(crawler.browser.__all__))"`（应为 22）
  - 行数断言：`interactions/executor.py` ≤ 300 行（G19）

### S5｜切割：business 全面改走门面 + 删除 douyin_client 浏览器残留与 shim

- **【文件集】**
  - 新增 `business/douyin/adapters/{__init__,models,service}.py`
  - 改 `business/douyin/accounts/service.py`（`CDPBrowserSession(...)` → `from_spec` + `open()`；`:1208` 的 `DouyinClient.create` → `open_douyin_client(page=browser.browser_page, ...)`；`:1218` `client.pong(context)` → LoginApi.verify_login；`:1221` `client.user_api.get_self_profile()` → `api.get_self_profile()`；`:1245` `client.close()` → `api.aclose()`；`:1093/:1186-1190` 的 `assert browser.page` + `page.goto` → `browser.open(...)`）
  - 改 `business/douyin/tasks/crawler.py`（`:144` 起：`from_spec`/`open`；`DouyinClient.create` → `open_douyin_client`；`DouyinLogin(...)` → `DouyinLogin.from_session(browser, ...)`；`client.pong(browser.context, ...)` → `api.verify_login(...)`；`client.update_cookies(...)` → `api.refresh_cookies()`；`except BrowserAutomationTimeoutError` 保留；`LoginError` 改从 `crawler.browser` 导入；`self.media_headers` 仍从 `client.headers` 取 —— client 是 DouyinClient，无需改）
  - 改 `business/douyin/interactions/service.py`（删 `InteractionBrowserConnection`（`:68,:1212`）→ 直接传 `spec=resolve_account_browser(reserved)`；`execute(..., api_factory=build_interaction_api_factory(settings))`；`InteractionExecutionError` 改从 `crawler.browser` 导入）
  - 改 `business/douyin/interactions/screenshots.py`（`record(page: BrowserPage, ...)`，`await page.capture_screenshot(...)`；删除 `capture_screenshot` 导入）
  - 改 `business/douyin/request_logs/service.py`（`DouyinClient` 类型注解：改用适配器工厂返回类型，或保留 `DouyinClient` 导入 —— 二者都在 `crawler.douyin_client.__all__` 内，本步仅确认 import 合规）
  - 删除 `douyin_client/interactions/`、`douyin_client/login/`；改 `douyin_client/__init__.py` 移除已迁符号；改 `modules/douyin-client/pyproject.toml`（去 `crawler-browser`/`playwright`/`crawler-bootstrap`）
  - 删除 `browser/runtime/` 三个 shim；删除 `CDPBrowserSession.page` / `.context` 临时属性
  - 改 `tests/business/douyin/{test_interactions,test_crawler,test_accounts_works_exports}.py`、`tests/architecture/test_module_layout.py`（`DOUYIN_SUBDOMAINS` 增 `adapters`）
- **【并行分组】** solo（不可拆分：适配器是三个调用点的共享依赖，import 翻转必须原子完成，否则新旧 API 会各被一半调用点使用）
- **【风险】**
  1. 全计划单点风险最集中处：5 个 business 文件 + 1 个新子域 + 删除 5 类旧符号 + pyproject。任何一处漏改都是 `ImportError`（不是类型错误）。
  2. `test_accounts_works_exports.py` 的 monkeypatch 目标要从 `account_service.DouyinClient` 迁到 `adapters.service.DouyinClient`（动态 monkeypatch 不被 mypy 覆盖，最容易漏）。
  3. 适配器的 lazy 建 client 时序：必须在 `open()` 之后。已在 `DouyinInteractionApi` 内加显式断言 + 单测。
  4. `media_headers` 来源不变（仍取 `client.headers` 的 user-agent/referer/cookie 三项），切割后需人工核对内容一致。
  5. 删除 shim 与删除 `.page`/`.context` 必须在本步末尾一次完成，且本步结束前跑一次完整 import 冒烟。
- **【验证方式】**
  - `uv run ruff check modules && uv run mypy -p crawler.business -p crawler.douyin_client -p crawler.browser`
  - `uv run python -c "import crawler.business.douyin.tasks.crawler, crawler.business.douyin.accounts.service, crawler.business.douyin.interactions.service"`
  - `uv run python -c "import crawler.douyin_client, sys; assert 'playwright' not in sys.modules"`
  - `uv run pytest tests/business tests/api -q`

### S6｜门禁落地 + 收尾

- **【文件集】**
  - 改 `tests/architecture/test_dependency_boundaries.py`（G1–G4、G15–G17、G19、G20）
  - 改 `tests/architecture/test_module_layout.py`（G5–G13、G18）
  - 无源码改动（如需极少量注释/docstring 修正则一并）
- **【并行分组】** wave3-solo（依赖 S1–S5 全部落地）
- **【风险】**
  1. G7（模块根无裸 .py）**只对 browser 与 douyin-client 生效**；对其他 4 个成员只允许在测试里显式声明「本次不覆盖」并加注释，不得暗中放宽（`BARE_PY_GUARDED_MEMBERS = ("browser", "douyin-client")` 常量名即文档）。
  2. G10/G11 一旦落地即冻结结构，任何漏改在此集中暴露。
  3. `test_behavior_contracts`（OpenAPI 95 路径 / 140 schema、SQLModel 24 表、MCP 32 工具、抖音路由 37 条）必须**零变化**；若变动说明误改了业务行为。
  4. `test_mcp_tool_contract_is_unchanged` 在本次改造开始前就已失败（基线不绿），验收时必须作为已知基线排除。
- **【验证方式】**
  - `uv run pytest tests/architecture -q` 全绿
  - `uv run ruff check modules tests && uv run ruff format modules tests --check`
  - `uv run mypy -p crawler.bootstrap -p crawler.browser -p crawler.douyin_client -p crawler.business -p crawler.api -p crawler.mcp`
  - `uv run python -m compileall -q modules tests`
  - `uv run pytest`（除已知失败 `test_mcp_tool_contract_is_unchanged` 外全绿）

---

## 7. 需要新增/修改的门禁测试

| 测试名 | 断言 | 落在 |
| --- | --- | --- |
| `test_douyin_client_has_no_playwright_dependency` | douyin_client 全部 `.py` 的 AST 无 `playwright*` import | `test_dependency_boundaries.py` |
| `test_douyin_client_never_imports_browser` | 无 `crawler.browser` 前缀 import | 同上 |
| `test_douyin_client_never_imports_bootstrap` | 无 `crawler.bootstrap` 前缀 import（原 executor.py 的用法已随迁移消失） | 同上 |
| `test_browser_never_imports_douyin_client` | 沿用现有断言 | 同上 |
| `test_upper_layers_import_browser_only_through_facade` | G3：模块名 ∈ {`crawler.browser`, `crawler.browser.facade`} 且符号 ∈ facade `__all__`，失败输出 `(文件, 模块, 符号)` | 同上 |
| `test_upper_layers_import_douyin_client_only_through_facade` | G4 | 同上 |
| `test_browser_root_facade_mirrors_the_facade` | G5：`__all__` 顺序一致 + `is` 同一性 | 同上 |
| `test_browser_root_init_only_imports_its_facade` | G6 | 同上 |
| `test_business_only_constructs_douyin_client_in_adapter` | G16：CallExpr 只允许在 `douyin/adapters/service.py` | 同上 |
| `test_business_never_references_internal_page_handle` | G17：源码无 `"page_handle"` | 同上 |
| `test_internal_layers_do_not_import_site_layers` | G20：`session/`、`page/`、`connection/`、`errors/` 不 import `interactions`/`login` | 同上 |
| `test_interaction_executor_stays_a_thin_orchestrator` | G19：`executor.py` ≤ 300 行 | 同上 |
| `test_douyin_client_pyproject_has_no_browser_dependency` | G18：TOML 断言 | `test_module_layout.py` |
| `test_module_roots_have_no_bare_python_modules` | G7，仅 browser/douyin-client | 同上 |
| `test_subpackages_do_not_repeat_their_own_name` | G8 | 同上 |
| `test_every_subpackage_has_init` | G9 | 同上 |
| `test_browser_and_douyin_client_subpackage_sets_are_frozen` | G10 | 同上 |
| `test_legacy_browser_paths_are_gone` | G11（目录 + 全仓文本含 tests） | 同上 |
| `test_interaction_and_login_live_in_browser_only` | G12 | 同上 |
| `test_business_and_api_tests_stay_out_of_browser_internals` | G13 | 同上 |
| `test_browser_page_structurally_satisfies_session_context` | G14：`isinstance(PlaywrightPageHandle, SessionContext)` | `tests/architecture/test_contracts.py`（新增文件，或并入 dependency_boundaries） |
| `test_fingerprint_key_sets_are_identical` | G15 | 同上 |
| `test_douyin_request_log_entry_redacts_headers_at_construction` | 构造 `DouyinRequestLogEntry(request_headers={"Cookie":"a=b","Authorization":"Bearer x","User-Agent":"ua"})` 后 Cookie/Authorization 值为 `[REDACTED]`，User-Agent 原值 | `tests/business/douyin/test_request_logs.py` |
| `test_douyin_client_retries_retryable_5xx_with_resigning` | MockTransport 502→200：2 次 HTTP、2 次 `get_a_bogus` | `tests/business/douyin/test_client.py` |
| `test_douyin_client_does_not_retry_403_429` | 各 1 次调用 + `DataFetchError` | 同上 |
| `test_douyin_client_fingerprint_params_come_from_session` | 参数逐键来自注入指纹；源码无 `MacIntel`/`Mac OS`/`2560` | 同上 |
| `test_browser_session_exposes_stealth_script_path` | `session/manager.py` 的 `parents[1]/resources/stealth.js` 真实存在（非 mock） | `tests/browser/core/test_session.py` |
| `test_interaction_api_adapter_rejects_pre_navigation_calls` | 未导航即调用 `verify_login` → 断言失败（适配器显式断言） | `tests/business/douyin/test_interactions.py` |

**既有门禁必须继续绿**：`test_module_layout.py::test_each_member_owns_exactly_one_subpackage`、`test_resource_files_travel_with_their_module`、`test_monkeypatch_target_exists`（自动覆盖全部改名的 patch 字符串）、`test_behavior_contracts` 四类契约。

---

## 8. 三条 P0 修复（落点与改法）

### P0a 指纹与真实 UA 不一致

- **落点**：`douyin_client/http/client.py`（`_process_params`，现 `:385-424`）+ 新增 `browser/session/environment.py`、`browser/session/context.py`。
- **改法**：
  1. 删除 `params.update({...})` 中 14 个硬编码键（`browser_language` / `browser_platform` / `browser_name` / `browser_version` / `engine_name` / `engine_version` / `os_name` / `os_version` / `cpu_core_num` / `device_memory` / `screen_width` / `screen_height` / `effective_type` / `round_trip_time`）。
  2. 在 `FINGERPRINT_KEYS` 之后改为：
     ```python
     fingerprint = await self.session.fingerprint()
     for key in self.FINGERPRINT_KEYS:
         value = fingerprint.get(key)
         if value:
             params[key] = str(value)
     ```
     **缺键不写入，绝不回退伪造值**；缺失键记一次 `logger.warning`。
  3. `msToken` 仍取 `(await self.session.local_storage()).get("xmst")`；`webid` 仍用 `get_web_id()`；`device_platform/aid/channel/version_code/pc_client_type/cookie_enabled/browser_online/platform` 等稳定参数与 `a_bogus` 逻辑不动。
  4. 数据来源：`BrowserEnvironment` 用一段采集脚本从真实页面读 `navigator.language`/`platform`/`hardwareConcurrency`/`deviceMemory`/`onLine`、`screen.width`/`height`、`navigator.connection.effectiveType`/`rtt`，并用 `derive_browser_family(user_agent)` 正则从**与 headers 同一个 UA**（`session.user_agent()`，即现 `client.py:116` 读到的 `navigator.userAgent`）推导 `browser_name`/`browser_version`/`engine_name`/`engine_version`/`os_name`/`os_version`。`BrowserSessionContext.fingerprint()` 首次采集后缓存。
- **验证**：`test_douyin_client_fingerprint_params_come_from_session` + G15 键表一致门禁 + 源码文本断言。

### P0b 请求日志内存中携带完整 Cookie

- **落点**：`douyin_client/http/request_log.py` + 新增 `douyin_client/http/redaction.py`。
- **改法**：
  ```python
  REDACTED = "[REDACTED]"
  SENSITIVE_HEADER_NAMES = frozenset({
      "cookie", "set-cookie", "authorization", "proxy-authorization",
      "x-csrf-token", "x-xsrf-token",
  })
  def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
      """命中敏感头名（大小写不敏感）即整值替换为 REDACTED，其余原样。"""
  ```
  `DouyinRequestLogEntry` 增加 `__post_init__`：`self.request_headers = redact_headers(self.request_headers)`。
  `http/client.py` 与 `http/scenarios/resolver.py` 保持传入原始 headers（不再依赖调用方自觉）。
  business 的 `request_logs/service.py`：`sanitize_mapping` 改为复用 `redact_mapping`，`_SENSITIVE_KEY_MARKERS` 常量删除（标记集唯一真源在 douyin_client）；`sanitize_failure_detail`/`_sanitize_text` 保留（响应侧自由文本脱敏）。
  `url`/`query_params`/`request_body` **不动**（用户口径为「仅请求头」，且 `test_request_logs.py` 对三者有逐字段断言）。

### P0c 5xx 不重试

- **落点**：`douyin_client/http/client.py`。
- **改法**：
  1. 模块常量：`_RETRYABLE_STATUSES = frozenset({502, 503, 504})`、`_SIGNED_ATTEMPTS = 3`、`_RETRY_BACKOFF_SECONDS = 0.25`；模块私有异常 `class _RetryableStatus(DataFetchError)`（继承 `DataFetchError` 保持既有 `except DataFetchError` 兼容）。
  2. `request()`：拿到 `response` 后、`raise_for_status()` 之前插入
     ```python
     if response.status_code in _RETRYABLE_STATUSES:
         entry.response_status = response.status_code
         entry.error = f"HTTPStatusError:{response.status_code}"
         entry.failure_detail = self._failure_detail_from_response(response)
         raise _RetryableStatus(f"抖音请求返回可重试状态码: {response.status_code}")
     ```
     `_RetryableStatus` 不是 `httpx` 异常，因此不会被既有 `except httpx.HTTPError` 分支吞掉；`finally` 仍照常发日志（每次尝试一条，重试可见）。**原有 `httpx.TransportError` 三次重试逻辑原样保留。**
  3. `get()`/`post()` 改为带签名重试的循环：每次尝试都调用 `await self._process_params(...)` **重新计算 a_bogus 并重读 msToken/webid**，再调 `self.request(...)`；捕获 `_RetryableStatus` 时 `if attempt == _SIGNED_ATTEMPTS: raise`，否则 `await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)`。`post()` 按 `params is None` 决定重签结果放回 `data` 还是 `params`（保持现 `:272-284` 语义）。
  4. **403/429 不重试**：走 `raise_for_status()` → `HTTPStatusError` → 既有 `except httpx.HTTPError` → `DataFetchError`，只发一次请求。
  5. `ShortUrlApi.resolve_short_url` 走裸 httpx，本次不加 5xx 重试（明确的范围外）；仅把其调用的 `_client._failure_detail_from_response` 改为公开名 `failure_detail_from_response`。
- **验证**：`test_douyin_client_retries_retryable_5xx_with_resigning`、`test_douyin_client_does_not_retry_403_429`、既有 `test_request_retries_transient_remote_protocol_error` 保持绿。

---

## 9. 主要风险与回退点

| # | 风险 | 影响 | 缓解 / 回退点 |
| --- | --- | --- | --- |
| 1 | `tests/conftest.py` 顶层 `import crawler.api.main`，任何中间态断链会让 pytest **整体** collection error（不是个别用例失败） | 中间步骤的 `pytest` 验证手段失效 | S2 引入 `crawler.browser.runtime.{cookies,dom,session}` 三个转发 shim，S6 才删；每步结束前跑 `python -c "import crawler.api.main"` 冒烟。这三条 shim 是本设计**唯一**允许的临时结构，删除点写死在 S5/S6 |
| 2 | `browser/session/manager.py` 从第 2 层下沉会静默打断 `stealth.js` 的 `parents[1]` 解析，且单测里 context 是 mock，红灯不响 | 反检测脚本静默失效 = 真实风控回归 | G9/G10 冻结子包集合与深度；`tests/browser/core/test_session.py` 加 `path.exists()` 真实断言 |
| 3 | P0a 改变参与 a_bogus 输入串的 14 个参数值 | 无法离线验证抖音是否接受，可能触发不同风控分支 | 键集不变、只随真实浏览器走值；缺键不伪造；上线后观测一次接口成功率。回退点：`FINGERPRINT_KEYS` 置空即退回「不发送指纹参数」 |
| 4 | P0c 最坏 `3 签名尝试 × 3 传输尝试 = 9` 次 HTTP，单请求耗时上升 | 批量评论/搜索任务整体变慢，可能触及任务级超时（`DOUYIN_INTERACTION_EXECUTION_TIMEOUT_SECONDS`） | 退避取 `0.25/0.5s`；上线后观察任务级超时率。回退点：`_SIGNED_ATTEMPTS = 1` 即退回不重签 |
| 5 | 每次请求多一次 CDP `localStorage` 读取（fingerprint 已缓存） | 单请求延迟小幅上升 | fingerprint 会话内缓存；`BrowserSessionContext` 在 `close()` 后置空并抛 `CDPConnectionError` 兜底 |
| 6 | `InteractionApi.aclose()` 把「谁关 DouyinClient」的责任交给 executor 的 `finally` | 适配器忘记关闭 → httpx 连接泄漏 | 适配器 `aclose` 必须 `await self._client.close()`；加单测钉住 |
| 7 | `LoginError`/`InteractionExecutionError` 脱离 `DouyinError` 继承体系（基类改 `RuntimeError`） | 任何 `except DouyinError` 不再捕获互动/登录失败 | 已全仓核查：只有 `interactions/service.py`（`:1267,:1326,:1364,:1373`）与 `tasks/crawler.py` 引用，且都是精确 `except`；S6 加注释/断言提醒 |
| 8 | 删除 `InteractionBrowserConnection`、`crawler.browser` 顶层 12 个符号、`DouyinBrowserMode` 改名 | 公开名字净变化；仓库外脚本/文档若引用会断 | 仓内引用已全量清点；S6 的 G5/G10/G11 门禁把变化点显式化 |
| 9 | `tests/browser/` 新增顶层测试目录 | 需 `__init__.py`、受 pytest 收集约束 | S2 同时创建 `tests/browser/__init__.py` 与子包 `__init__.py`；与 `tests/architecture` 同构 |
| 10 | 改名类重构的 monkeypatch 字符串（约 30–60 处） | `test_module_layout.test_monkeypatch_target_exists` 参数化全量报错 | 「先 sed 机械替换、再人工修 mock 形状」两段式；该测试是漏改的自动探测器 |
| 11 | `DouyinInteractionApi` 的 lazy 建 client 时序（新增失败模式） | 导航前调用 → 空 cookie/UA → 静默判为未登录 | 适配器内显式断言「首次调用前已导航」+ S5 单测；executor 内调用点固定在 `open_index()` 之后 |
| 12 | `test_mcp_tool_contract_is_unchanged` 基线不绿 | 无法判定 pytest 是否整体绿 | S6 验收明确记为已知基线失败，与本改造无关 |
| 13 | G7 全仓扫描若误扩到 6 个成员 | 门禁永红 | 写死 `BARE_PY_GUARDED_MEMBERS = ("browser", "douyin-client")`，并在测试 docstring 里说明 bootstrap/api/mcp/business 的裸 `.py` 不在本次范围 |

**整体回退**：S1（P0b/P0c）与 S2（browser 重组）文件集不重叠，可各自独立回滚；S3/S4 各自可回滚（S4 是纯新增 + facade 扩展，回滚只需还原 facade/`__init__`）；S5 是唯一不可拆分点，回滚策略=整体 revert 该提交（其前置 S1–S4 可保留）。
