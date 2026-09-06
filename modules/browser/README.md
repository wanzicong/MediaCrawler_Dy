# crawler-browser

CDP-only 浏览器运行时模块。系统与 Chrome 之间的唯一通道：**只通过
Chrome DevTools Protocol（CDP）连接已存在的浏览器**，绝不自行启动标准 Playwright
实例（禁止 `chromium.launch()` / `launch_persistent_context()`）。

- 分发包名：`crawler-browser`
- 导入路径：`crawler.browser`（对外符号统一从包门面导出）
- 依赖：`crawler-bootstrap` + playwright + httpx
- 架构位置：依赖方向 `business → douyin-client → browser → bootstrap`；只允许依赖
  bootstrap，禁止反向 import business / api / mcp。

## 公共 API

所有对外符号从包门面导出：

```python
from crawler.browser import (
    CDPBrowserSession,           # 会话门面（异步上下文管理器）
    DouyinBrowserMode,           # 模式枚举：local / remote
    CDPConnectionError,          # CDP 端点不可达/停止响应
    BrowserAutomationError,      # = PlaywrightError（保持上层捕获兼容）
    BrowserAutomationTimeoutError,  # = PlaywrightTimeoutError
)
```

### CDPBrowserSession

统一入口：负责启动 Playwright、按模式连上浏览器、注入 stealth 反检测脚本、获取页面。
内部只做编排，本地启动 / 连接 / 页面策略分别由 `runtime/` 下的组件承担。

```python
session = CDPBrowserSession(
    config,                       # crawler.bootstrap.settings.Settings
    *,
    browser_mode=None,            # "local"/"remote" 或领域枚举；缺省取 config
    remote_host=None,             # 覆盖 DOUYIN_REMOTE_CDP_HOST
    remote_port=None,             # 覆盖 DOUYIN_REMOTE_CDP_PORT
    user_data_dir=None,           # 本地模式用户数据目录（缺省取配置）
    debug_port=None,              # CDP 调试端口（缺省取配置）
    reuse_existing_page=False,    # 无标记时复用上下文既有页面
    close_page_on_exit=True,      # 退出时关闭本会话拥有的页面
    page_marker=None,             # 页面标记，按 window.name 复用专属自动化页
)

async with session:
    page = session.page           # Playwright Page
    context = session.context     # BrowserContext
```

启动成功后常用属性：`page`、`context`、`browser`、`browser_mode`、`debug_port`、
`owns_page`、`unrelated_page_count`（标记模式下隔离的用户页数量）。

模式语义：

| 模式 | 行为 |
|---|---|
| `remote` | 连接配置的远程 CDP（如 Docker 中的 Chrome）。内部经 `/json/version` 发现并把容器内 ws 地址重写为外部可访问地址 |
| `local` + `DOUYIN_CDP_CONNECT_EXISTING=true` | 只附加本机已开启 CDP 的浏览器；端口不可用直接抛 `CDPConnectionError` |
| `local`（默认） | 端口已有 CDP 则附加；否则代找浏览器、扫空闲端口并拉起一个开启 CDP 的进程（`managed=true`，退出按配置自动关闭） |

## 目录结构

```
src/crawler/browser/
├── __init__.py              # 公共门面：re-export，不写逻辑
├── base/                    # 横切支撑
│   ├── errors.py            # 异常唯一出处：CDPConnectionError + playwright 别名
│   └── modes.py             # DouyinBrowserMode 枚举 + 兼容解析
├── runtime/                 # 运行时会话编排（唯一持有 Playwright 生命周期）
│   ├── session.py           # CDPBrowserSession：start()/close()/页面归属编排
│   ├── launcher.py          # LocalChromeLauncher：找浏览器/起子进程/等就绪/空闲端口
│   ├── connect.py           # LocalCdpConnector：端口探测/本地发现/CDP 附加
│   └── pages.py             # PageAcquisitionPolicy：页面标记/复用/归属决策
├── remote/
│   └── manager.py           # RemoteBrowserManager：远程 CDP 端点发现与连接
└── resources/stealth.js     # 反自动化检测注入脚本
```

约定：**一个文件一个类**（`base/errors.py` 的异常族是唯一例外）；包根目录下只有
门面 `__init__.py` 和职责子目录，没有游离的 `.py`。业务层只应从包门面导入，不应
深入内部子包路径。

## 用法示例

### 1. 本地模式（自动附加或代启动）

```python
from crawler.browser import CDPBrowserSession

async with CDPBrowserSession(config) as session:
    page = session.page
    await page.goto("https://www.douyin.com")
```

### 2. 远程模式（连接 Docker 中的 douyin-browser）

```python
from crawler.browser import CDPBrowserSession, DouyinBrowserMode

async with CDPBrowserSession(
    config, browser_mode=DouyinBrowserMode.remote
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
- 只依赖 bootstrap；不得 import business/api/mcp 层代码。
- CDP 端口等同浏览器完全控制权：本地代启动只允许回环地址；远程只连可信端点。
- 包内仅 `base/`、`runtime/`、`remote/` 三个子包；运行时会话层是唯一持有
  Playwright 生命周期的一层。

## 质量门禁

```powershell
uv run mypy -p crawler.browser
uv run ruff check modules/browser
uv run pytest tests/business/douyin/test_browser_session.py tests/business/douyin/test_remote_browser.py
```
