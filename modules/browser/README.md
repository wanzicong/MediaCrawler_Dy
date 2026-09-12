# crawler-browser

CDP-only 浏览器运行时模块。系统与 Chrome 之间的唯一通道：**只通过
Chrome DevTools Protocol（CDP）连接已存在的浏览器**，绝不自行启动标准 Playwright
实例（禁止 `chromium.launch()` / `launch_persistent_context()`）。

- 分发包名：`crawler-browser`
- 导入路径：`crawler.browser`（对外符号统一从包门面导出；`crawler.browser.facade`
  是逐名同一的等价入口）
- 依赖：`crawler-bootstrap` + playwright
- 架构位置：依赖方向 `business → crawler.browser → bootstrap`；只允许依赖 bootstrap，
  禁止反向 import business / api / mcp；也禁止 import `crawler.douyin_client`
  （纯 API 层零浏览器依赖，二者互不 import）。

## 公共 API

所有对外符号从包门面导出（22 项）：

```python
from crawler.browser import (
    CDPBrowserSession,           # 会话门面（异步上下文管理器）
    BrowserSessionSpec,          # 会话连接参数（冻结 dataclass）
    BrowserSessionContext,       # 会话能力适配器（结构化满足 douyin_client.SessionContext）
    BrowserMode,                 # 模式枚举：local / remote（原 DouyinBrowserMode）
    CDPConnectionError,          # CDP 端点不可达/停止响应
    BrowserAutomationError,      # = PlaywrightError（保持上层捕获兼容）
    BrowserAutomationTimeoutError,  # = PlaywrightTimeoutError
    LoginError,                  # 抖音登录流程失败
    InteractionExecutionError,   # 互动执行失败（携带 code/retryable/ambiguous）
    BrowserPage,                 # 只读页面能力端口（上层唯一可用的浏览器面）
    LoginApi, InteractionApi, InteractionApiFactory, CommentPresence,  # 入站契约
    capture_screenshot, probe_cdp_pages,                              # 站点无关能力
    DouyinLogin, QRCodeCallback,                                      # 抖音登录
    DouyinInteractionExecutor, InteractionExecutionRequest,
    InteractionExecutionResult, InteractionStepCallback,               # 抖音互动写回
)
```

### CDPBrowserSession

统一入口：负责启动 Playwright、按模式连上浏览器、注入 stealth 反检测脚本、获取页面。
内部只做编排，连接、代启动与页面策略分别由 `connection/`、`session/` 下的组件承担。

```python
session = CDPBrowserSession(
    config,                       # crawler.bootstrap.settings.Settings
    *,
    browser_mode=None,            # "local"/"remote" 或浏览器模式枚举；缺省取 config
    remote_host=None,             # 覆盖 DOUYIN_REMOTE_CDP_HOST
    remote_port=None,             # 覆盖 DOUYIN_REMOTE_CDP_PORT
    user_data_dir=None,           # 本地模式用户数据目录（缺省取配置）
    debug_port=None,              # CDP 调试端口（缺省取配置）
    reuse_existing_page=False,    # 无标记时复用上下文既有页面
    close_page_on_exit=True,      # 退出时关闭本会话拥有的页面
    page_marker=None,             # 页面标记，按 window.name 复用专属自动化页
)

# business 路径推荐：直接用账号解析结果构造
session = CDPBrowserSession.from_spec(config, spec, page_marker=...)
```

原生 Playwright 对象**不再对外暴露**（历史上的 `session.page` / `session.context`
临时属性已在 S5b 删除）。上层可用的浏览器面只有两个：

```python
async with session:
    await session.open("https://www.douyin.com")   # 等同 page.goto，超时抛
                                                   # BrowserAutomationTimeoutError
    page = session.browser_page                    # BrowserPage：只读能力端口
    ua = await page.user_agent()
    ctx = session.session_context()                # BrowserSessionContext：会话读数
```

`page_handle`（`PlaywrightPageHandle`）是 browser **内部专用**的写操作入口
（`goto` / `set_cookies` / `wait_for_selector` …），business/api/mcp 源码中禁止出现
该名字；覆盖 `tests/browser/**` 与 `crawler.browser` 包内的直测。

启动成功后常用属性：`browser`、`browser_mode`、`debug_port`、`owns_page`、
`unrelated_page_count`（标记模式下隔离的用户页数量）。

模式语义：

| 模式 | 行为 |
|---|---|
| `remote` | 连接配置的远程 CDP（如 Docker 中的 Chrome）。内部经 `/json/version` 发现并把容器内 ws 地址重写为外部可访问地址 |
| `local` + `DOUYIN_CDP_CONNECT_EXISTING=true` | 只附加本机已开启 CDP 的浏览器；端口不可用直接抛 `CDPConnectionError` |
| `local`（默认） | 端口已有 CDP 则附加；否则代找浏览器、扫空闲端口并拉起一个开启 CDP 的进程（`managed=true`，退出按配置自动关闭） |

## 目录结构

```
src/crawler/browser/
├── __init__.py              # 门面镜像：只 from crawler.browser.facade import (...)
├── facade/                  # 唯一对外符号表（22 项）
│   ├── __init__.py
│   ├── protocols.py         # 入站契约：LoginApi / InteractionApi / InteractionApiFactory /
│   │                        #   CommentPresence
│   ├── capabilities.py      # 站点无关能力：probe_cdp_pages / capture_screenshot
│   └── spec.py              # BrowserSessionSpec（冻结 dataclass）
├── errors/
│   ├── __init__.py
│   └── family.py            # CDPConnectionError / LoginError / InteractionExecutionError
│                            #   + playwright 异常别名
├── connection/              # CDP 端点探测、本机拉起与远程接入
│   ├── connector.py         # LocalCdpConnector：端口探测/本地发现/CDP 附加
│   ├── launcher.py          # LocalChromeLauncher：找浏览器/起子进程/等就绪/空闲端口
│   └── remote.py            # RemoteBrowserManager：远程 CDP 端点发现与连接
├── session/                 # 会话建立、治理与浏览器环境采集
│   ├── manager.py           # CDPBrowserSession：start()/close()/open()/页面归属编排
│   ├── mode.py              # BrowserMode 枚举 + coerce_browser_mode
│   ├── policy.py            # PageAcquisitionPolicy：页面标记/复用/归属决策
│   ├── cookies.py           # convert_cookies / browser_cookies / parse_cookie_string
│   ├── context.py           # BrowserSessionContext：page+context → SessionContext 能力
│   └── environment.py       # BrowserEnvironment：真实页面读数 + UA 推导请求指纹
├── page/                    # 站点无关页面基元与只读端口
│   ├── port.py              # BrowserPage（只读能力端口 Protocol）
│   ├── handle.py            # PlaywrightPageHandle（BrowserPage 唯一实现，含写操作）
│   └── primitives.py        # 9 个 DOM 基元（find_visible / click_control_center / ...）
├── interactions/            # 抖音互动写操作编排（executor 只做编排，≤ 300 行）
│   ├── models.py selectors.py reporting.py navigation.py panel.py
│   ├── verification.py comment_locator.py page_controller.py
│   └── submit_flow.py response_inspector.py executor.py
├── login/
│   └── flow.py              # DouyinLogin：扫码登录 / Cookie 登录（+ from_session()）
└── resources/stealth.js     # 反自动化检测注入脚本
```

约定：**一个文件一个类**（`errors/family.py` 的异常族是唯一例外）；包根目录下只有
门面 `__init__.py` 和职责子目录，没有游离的 `.py`。业务层只应从包门面导入，不应
深入内部子包路径（`crawler.browser.<子包>` 一律违规，由架构门禁断言）。

## 用法示例

### 1. 本地模式（自动附加或代启动）

```python
from crawler.browser import CDPBrowserSession

async with CDPBrowserSession(config) as session:
    await session.open("https://www.douyin.com")
    page = session.browser_page
```

### 2. 远程模式（连接 Docker 中的 douyin-browser）

```python
from crawler.browser import BrowserMode, CDPBrowserSession

async with CDPBrowserSession(
    config, browser_mode=BrowserMode.remote
) as session:
    ...
```

### 3. 按账号独立 profile + 专属自动化标签页

多账号场景通常本地模式：每账号独立 `user_data_dir` 与派生 `debug_port`；再以
`page_marker` 标记自动化页，确保不与用户手工页面互相劫持：

```python
async with CDPBrowserSession(
    config,
    user_data_dir=account_profile_dir,
    debug_port=derived_port,
    page_marker=f"mediacrawler:{task_id}",
    close_page_on_exit=False,
) as session:
    assert session.owns_page          # 标记页由本会话拥有/复用
    isolated = session.unrelated_page_count   # 被隔离的用户手工页数量
    ...
```

## 关键配置项

读取自 `crawler.bootstrap.settings.Settings`（.env）：

| 配置 | 含义 |
|---|---|
| `DOUYIN_BROWSER_MODE` | `local` / `remote` |
| `DOUYIN_CDP_HOST` / `DOUYIN_CDP_PORT` | 本地 CDP 地址与调试端口 |
| `DOUYIN_CDP_CONNECT_EXISTING` | 本地是否只附加既有浏览器（不代启动） |
| `DOUYIN_CDP_CONNECT_TIMEOUT` | 等待浏览器就绪/连接的超时（秒） |
| `DOUYIN_CDP_BROWSER_PATH` | Chrome/Edge 可执行文件路径；缺省自动搜索常见路径 |
| `DOUYIN_CDP_USER_DATA_DIR` | 本地浏览器用户数据目录 |
| `DOUYIN_CDP_HEADLESS` | 代启动时是否无头 |
| `DOUYIN_CDP_AUTO_CLOSE` | 退出时是否自动关闭由会话托管的浏览器进程 |
| `DOUYIN_REMOTE_CDP_HOST` / `DOUYIN_REMOTE_CDP_PORT` | 远程 CDP 地址 |

## 架构约束

- **禁止** `chromium.launch()`、`launch_persistent_context()` 及任何标准模式回退。
- 只依赖 bootstrap；不得 import business/api/mcp 层代码，也不得 import `crawler.douyin_client`。
- CDP 端口等同浏览器完全控制权：本地代启动只允许回环地址；远程只连可信端点。
- 包内子包集合冻结为 `facade` / `errors` / `connection` / `session` / `page` /
  `interactions` / `login`；`session/manager.py` 必须留在模块**第 2 层**，否则
  `parents[1] / "resources" / "stealth.js"` 会解析到 `crawler/browser` 之外而静默失效。

## 质量门禁

```powershell
uv run mypy -p crawler.browser
uv run ruff check modules/browser
uv run pytest tests/browser tests/architecture -q
```
