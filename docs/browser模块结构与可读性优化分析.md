# crawler-browser 模块结构与可读性优化分析

> 分析日期：2026-09-06 · 状态：**已按方案 B 实施**（目录重构完成，单测/mypy/ruff 绿；仅 MCP 契约测试为既有环境漂移失败，与本次改动无关）
> 范围：`modules/browser`（重构前 819 行 / 7 个 py 文件 + `resources/stealth.js`）
> 核心诉求：**结构清晰、代码可读性高；包根目录下不要有游离的 `.py` 文件；职责单一；一个 Python 文件一个类。**

## 1. 现状速览

```
modules/browser/
├── pyproject.toml            # 分发包 crawler-browser
├── README.md
└── src/crawler/browser/
    ├── __init__.py           # 仅 docstring，什么都不导出
    ├── errors.py             # 5 行：只定义 CDPConnectionError        ← 游离根级文件
    ├── session.py            # 386 行 —— CDPBrowserSession 全能类      ← 游离根级文件
    ├── remote.py             # 89 行 —— RemoteBrowserManager           ← 游离根级文件
    ├── cdp/
    │   ├── __init__.py       # 聚合 re-export
    │   ├── connection.py     # 24 行：connect_over_cdp 薄透传
    │   ├── endpoint.py       # 167 行：/json/version 发现 + ws 地址重写
    │   └── network.py        # 68 行：TCP 探测 + 空闲端口扫描
    └── resources/stealth.js
```

**外部 API 面（全部消费方共用）**，均来自 `crawler.browser.session`：
`CDPBrowserSession`、`BrowserAutomationError`、`BrowserAutomationTimeoutError`、`DouyinBrowserMode`。

**消费方**：`crawler.business.douyin.tasks.crawler`、`crawler.business.douyin.accounts.service`、`crawler.douyin_client.interactions`。
`remote.py` 只被 `session.py` 使用；`cdp/*` 只被 `session.py` / `remote.py` 内部使用。

## 2. 不可破坏的仓库硬约束

由架构测试锁定（`tests/architecture/test_module_layout.py`、`test_dependency_boundaries.py`）：

1. `crawler` 是 PEP 420 命名空间包，`modules/*/src/crawler/` 下**不得有** `__init__.py`。
2. 每个 workspace 成员在 `src/crawler` 下**恰好拥有一个子包**——browser 只能是 `crawler/browser`，不能在顶层另起包名（`browser` 内部的再分子目录不受此限）。
3. 依赖 DAG：`bootstrap ← browser ← douyin-client ← business ← api`；browser 只依赖 bootstrap / playwright / httpx，禁止反向上游 import。
4. 每个 `monkeypatch`/`patch` 目标字符串必须能解析到真实符号。当前测试把 `crawler.browser.session.httpx`、`crawler.browser.session.socket.create_connection`、`session._acquire_page` / `_websocket_url` / `_probe` / `_connect` 都钉死（见 `tests/business/douyin/test_browser_session.py`）——搬目录必须同步更新这些字符串。

## 3. 诊断

### P0 · 包根目录平铺游离文件，职责归属失衡（核心诉求的落点）

打开 `crawler/browser/` 看到：3 个功能各异的平铺文件（`session.py` 386 行 / `remote.py` 89 行 / `errors.py` 5 行）+ 唯一一个子目录 `cdp/`。**最复杂、最有逻辑的代码平铺在根上，反而只有零碎协议原语进了子目录**——目录一眼看不出边界、看不出谁属于谁。期望形态：包根只留 `__init__.py` 门面，每个职责一个目录，每个类一个文件。

### P0 · `session.py` 是 386 行的全能类（违反"职责单一 / 一个文件一个类"）

`CDPBrowserSession` 一个文件一个类里塞了 6 组正交职责，约 18 个状态字段：

| 职责 | 现位置 |
|---|---|
| 模式解析 + 历史枚举兼容 | `__init__` |
| 启动编排（remote / attach / launch 三路分支） | `start` |
| 子进程拉起 Chrome + 等待端口就绪 | `_launch_local_browser` |
| 页面复用 / 标记 / 归属策略 | `_acquire_page` |
| 浏览器可执行文件搜索 | `_find_browser` |
| 连接 / ws 发现 / 端口探测 | `_connect` … `_available_port` |
| 资源清理与归属判断 | `close` |

中文 docstring 质量不错，问题在：(a) `start()` 的 `if/elif` 分支森林 + 边执行边改写状态（`debug_port` / `managed` / `process` 中途变化）；(b) 私有方法只是命名上拆分，读者仍要在约 400 行上下文里跟踪 `owns_page` / `managed` / `page_marker` / `unrelated_page_count` 等局部状态。按"一个文件一个类"，这 6 组职责应拆成各自的类文件，`session.py` 只留编排。

### P0 · `cdp` 子包是一层无价值的"半抽象"

- `connection.py` 24 行，是 `playwright.connect_over_cdp` 的**纯透传**；真正的错误包装散落在 `session.py` 与 `remote.py` 两处，文案各写一遍。
- `endpoint.py` 与 `network.py` 的边界名不副实：前者是 /json/version 轮询 + ws 地址重写，后者是 TCP 探测 + 空闲端口扫描；README 职责表已写反。
- 这些"平台无关层"原语各自**只有一个真正调用方**（轮询+重写→remote；端口探测/空闲端口→本地启动/连接路径）。既然没有第二方复用，单独成包就是假分层——按"一个文件一个类"，应直接并入唯一调用方的类，做成私有方法。

### P1 · 测试注入在前景造成噪音（过度依赖注入）

发现函数普遍吃 6~9 个注入参数（`client_factory / error_factory / clock / sleep / socket_factory / connection_factory`）。现有测试证明真正需要的挂点只有 `httpx.AsyncClient` 与 `socket.create_connection` 两处——不必为每个原语都开工厂口子。

### P1 · 公共 API 出口不统一，历史兼容 hack 堆在类文件顶部

- 包 `__init__.py` 什么都不导出，真正做聚合的是 `cdp/__init__.py`；外部被迫 `from crawler.browser.session import ...`。自然形态是 `from crawler.browser import CDPBrowserSession, DouyinBrowserMode`。
- `PlaywrightError` 别名 `BrowserAutomationError` 的兼容逻辑、保留历史 ORM 枚举对象的兼容逻辑，都塞在入口类顶部；`errors.py` 只有 5 行却形同虚设。
- **跨层同名枚举的认知税**：`crawler.browser.session.DouyinBrowserMode`（中立枚举）与 `crawler.business.douyin.accounts.models.DouyinBrowserMode`（ORM 枚举）同名两套，靠 `.value` 字符串桥接（测试被迫写成 `BrowserModuleMode` 区分）。DAG 允许 business import browser，理论上可让 ORM 列直接复用同一枚举、消灭桥接；但会动 SQLModel 列定义与枚举类身份，属跨模块高风险改动，须单独评估。

### P2 · README 与实现漂移

职责表 2 处写反（`endpoint.py` / `network.py`）；`remote.py` 描述成"Docker 槽位池/多实例分配"，但代码只是"连一台远程 Chrome"。

## 4. 目标目录结构与编码约定

### 4.1 编码约定（落到结构里的原则）

1. **包根只有门面 + 目录**：`crawler/browser/` 下只允许 `__init__.py` 和职责子目录，没有任何游离 `.py`。
2. **一个文件一个类（全模块强制，无例外目录）**：每个承担职责的「对象」独占一个文件，**文件名 = 类名**（snake_case），读者靠文件列表即可导航。
3. **类内部不再"方法即职责"**：拆出来的类各自只有一种任务；`start()`/`close()` 这类编排只留在门面类。
4. **不做无复用方的人工分层**：协议原语并入**唯一调用方**的类私有方法；多处需要同一原语时以最轻形式内联，接受少量重复，换取结构单一。
5. **异常集中、枚举单一出处**：`base/errors.py` 集中所有异常类型（异常是类型声明、无行为，属此约定唯一例外，一个模块放异常族）；`base/modes.py` 唯一持有 `DouyinBrowserMode`。
6. **门面导出**：外部一律 `from crawler.browser import CDPBrowserSession, ...`，内部用包内完整路径。
7. **不做反向依赖、不做纯透传**：browser 只依赖 bootstrap；无逻辑的转发文件直接删除。

### 4.2 目标目录结构（已定：拆除 `cdp/`）

```
src/crawler/browser/
├── __init__.py              # 门面：re-export，不写逻辑
├── base/                    # 横切支撑（不依赖 Playwright）
│   ├── __init__.py          #   仅聚合导出
│   ├── errors.py            #   [异常族] CDPConnectionError / BrowserAutomationError / Timeout
│   └── modes.py             #   [enum] DouyinBrowserMode + 兼容解析
├── runtime/                 # 运行时会话层 —— 唯一持有 Playwright 生命周期，逐类成文件
│   ├── __init__.py          #   仅聚合导出
│   ├── session.py           #   [class] CDPBrowserSession —— 仅编排 start()/close()/页面归属
│   ├── launcher.py          #   [class] LocalChromeLauncher —— 找浏览器 / 起子进程 / 等就绪 / 空闲端口
│   ├── connect.py           #   [class] LocalCdpConnector —— 探测 / 本地 /json/version 发现 / connect_over_cdp
│   └── pages.py             #   [class] PageAcquisitionPolicy —— marker/reuse/owns 纯策略
└── remote/                  # 远程 CDP 浏览器接入 —— 逐类成文件
    ├── __init__.py          #   仅聚合导出
    └── manager.py           #   [class] RemoteBrowserManager（原 remote.py，自持轮询与 ws 重写）
```

原 `cdp/*` 归位方式（协议原语 → 唯一调用方的类私有方法）：

| 原 cdp 内容 | 归入 |
|---|---|
| `connect_over_cdp` 纯透传 | 直接删除；附加逻辑由 `LocalCdpConnector.connect()` / `RemoteBrowserManager.connect()` 各自承担并包装错误 |
| `find_available_port`（空闲端口扫描） | `LocalChromeLauncher`（本地代为启动时才需要） |
| `probe_tcp_port`（TCP 端口探测） | `LocalChromeLauncher`（等进程就绪）+ `LocalCdpConnector`（attach 前探测）各自内联私有方法 |
| 本地 `/json/version` 轮询 + ws 拼写 | `LocalCdpConnector` 私有方法（无 host 重写） |
| 远程 `/json/version` 轮询 + authority 重写 | `RemoteBrowserManager` 私有方法 |

> 本地与远程各持一份轮询/重写私有实现——二者重试模型与是否重写本就不同，重复量很小且语义各自清晰，这正是选 B 时接受的代价。

### 4.3 「文件 ↔ 内容」映射（实施后的导航索引）

| 文件 | 类 / 内容 | 来源 |
|---|---|---|
| `browser/__init__.py` | —（门面 re-export） | 新 |
| `browser/base/errors.py` | `CDPConnectionError`；`BrowserAutomationError/Timeout` alias | `errors.py` + `session.py:41-44` |
| `browser/base/modes.py` | `DouyinBrowserMode` + 兼容解析 | `session.py:47-59` / `__init__` 解析 |
| `browser/runtime/session.py` | `CDPBrowserSession`（仅编排） | `session.py` 瘦身 |
| `browser/runtime/launcher.py` | `LocalChromeLauncher` | `_launch_local_browser` + `_find_browser` + `find_available_port` |
| `browser/runtime/connect.py` | `LocalCdpConnector` | `_connect` / `_websocket_url` / `_probe` + 本地轮询原语 |
| `browser/runtime/pages.py` | `PageAcquisitionPolicy` | `_acquire_page` |
| `browser/remote/manager.py` | `RemoteBrowserManager` | `remote.py` + `discover_remote`/`rewrite` 原语 |

### 4.4 已定决策（不再摇摆）

- `base/` 独立成目录；`cdp/` 拆除，协议原语并入唯一调用方（选 B）。
- 消费方统一改走门面：`from crawler.browser import CDPBrowserSession, DouyinBrowserMode, CDPConnectionError`。
- 只删不造：`connection.py` 纯透传删除，错误包装落在 `LocalCdpConnector` / `RemoteBrowserManager` 各自方法里。

## 5. 分阶段实施计划

### 第 1 步 · 目录落地 + 门面化（骨架，可独立成 commit）
1. 建 `base/`、`runtime/`、`remote/`；`errors.py`→`base/errors.py`、`session.py`→`runtime/session.py`、`remote.py`→`remote/manager.py`（**此步类内逻辑暂不变**，仅换路径）。
2. 拆除 `cdp/`：`connection.py` 删除；`endpoint.py`/`network.py` 内容**暂内联**为 `runtime/session.py`、`remote/manager.py` 内模块级私有函数（第 2 步抽取类时随类归位为方法）。
3. 包根 `__init__.py` 门面 re-export。
4. **同步更新**（否则全红）：消费方 3 处、测试 import 与 `monkeypatch` 字符串前缀、stealth.js 相对引用（`parents[1] / "resources"`）、README 职责表与目录图。

### 第 2 步 · 按"一个文件一个类"拆出 runtime 四类（核心瘦身；可与第 1 步同一 PR）
1. `runtime/pages.py` — `PageAcquisitionPolicy`（纯逻辑、不触 playwright，先拆、最易测）。
2. `runtime/launcher.py` — `LocalChromeLauncher`（吸收空闲端口扫描/等就绪探测为私有方法）。
3. `runtime/connect.py` — `LocalCdpConnector`（吸收端口探测/本地轮询/`connect_over_cdp` 为方法）。
4. `runtime/session.py` 瘦身为纯编排（`start()` 按 mode 选择策略对象 → `close()` 按归属清理）。
5. `DouyinBrowserMode` + 解析/兼容 → `base/modes.py`；Playwright alias → `base/errors.py`；`remote/manager.py` 把第 1 步内联的轮询/重写提为私有方法。
6. 核对架构测试 patch 解析与 `test_browser_session.py` 断言（方法行为不变，仅路径/宿主变化）。

### 第 3 步 · 清理（可选，低收益）
1. 收敛仍偏测试注入的参数为真实依赖默认值（`httpx.AsyncClient` 与 `socket.create_connection` 两个挂点已足够）。
2. 若 runtime 与 remote 的轮询确实出现明显重复且难读，再做一次定向去重评估（仅在有收益处合并）。

### 第 4 步 ·（单独评估）
跨层统一 `DouyinBrowserMode` 单一出处：收益大但动 ORM 列定义，另开会话专项。

## 6. 迁移影响与风险清单

| 风险 | 应对 |
|---|---|
| 架构测试与单测钉死 `crawler.browser.session.*` 私有方法及模块内 `httpx`/`socket` | `runtime/session.py` 同名同法保留；搬移时同步改 import 与 patch 字符串；`test_monkeypatch_target_exists` 兜底 |
| 3 个消费方深层导入 | 第 1 步一次切到门面，改齐 |
| `resources/stealth.js` 相对定位 | 收敛为 `parents[1] / "resources"`，随搬移一起改 |
| `base/` 只承载 errors + modes 两个小文件 | 已定独立；异常族 + 枚举语义清晰，属支撑模块 |
| runtime 与 remote 出现重复轮询/探测原语（选 B 的固有代价） | 已在 §4.2 注明；仅在有明显可读性收益时定向去重（第 3 步） |
| 跨层枚举统一动 SQLModel 列定义 | 独立专项（第 4 步），先验序列化影响 |
