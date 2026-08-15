# 后端分层重构设计

## 目标与不可变约束

本次重构只调整代码的组织方式和依赖边界，不改变任务行为、API 契约、数据库语义或前端调用方式。重构全过程遵守以下约束：

- 已发布的路径、HTTP 方法、请求/响应结构、`operationId` 和状态码保持不变。
- 现有 21 张表的表名、列顺序、类型、可空性、主外键、索引和约束保持不变，因此本次结构重构不生成 Alembic 迁移。
- 任务状态机、恢复逻辑、并发策略、媒体处理、账号选择、CDP 浏览器行为和 MCP 工具语义保持不变。
- `items` 虽然属于模板演示功能，但仍存在公开 API、前端路由、生成客户端和测试；在没有单独的下线需求与兼容方案前继续保留，不在本次重构中删除。
- Cookie、Token、原始账号 ID、脱敏与“仅 CDP、禁止浏览器 launch 回退”等安全约束保持不变。

自动门禁冻结了当前基线：OpenAPI 为 76 个路径、112 个 schema；SQLModel metadata 为 21 张表。任何基线变化都必须作为独立业务或数据库变更进行审查，不能混入目录迁移。

## 最终五层结构

```text
backend/app/
├── bootstrap/                 # 应用配置；main.py 是运行时组合根
├── framework/                 # 横向技术能力，不包含业务词汇
│   ├── database.py
│   ├── security.py
│   ├── logging.py
│   ├── browser/cdp/           # CDP 发现、连接、端口探测
│   ├── concurrency/           # 按 key 公平轮转限流
│   ├── storage/               # 本地文件与 MinIO driver
│   ├── http/ranges.py         # 单 Range 解析与文件分块
│   └── media/ffmpeg.py        # 通用 FFmpeg 子进程执行
├── integrations/              # 外部平台和协议适配
│   └── douyin/
│       ├── client.py
│       ├── signer.py
│       ├── browser.py
│       ├── remote_browser.py
│       ├── login.py
│       └── privacy.py
├── domain/                    # 业务模型、值对象与纯业务规则
│   ├── identity/
│   ├── items/                 # 暂保留的模板业务切片
│   └── douyin/
│       ├── accounts/
│       ├── tasks/
│       ├── content/
│       ├── library/
│       ├── comments/
│       ├── interactions/
│       ├── keywords/
│       ├── tracks/
│       ├── tags/
│       └── media/
├── application/               # 用例、事务、后台 Manager 与任务编排
│   ├── identity/
│   ├── items/
│   └── douyin/
│       ├── accounts/
│       ├── tasks/
│       ├── comments/
│       ├── interactions/
│       ├── keywords/
│       ├── tracks/
│       ├── tags/
│       └── media/
├── api/                       # HTTP 入站接口、鉴权依赖和协议转换
│   ├── deps.py
│   └── routes/                # douyin_tasks/media/catalog 等纯适配器
└── mcp_server/                # 与 API 平行的 MCP 入站接口
```

### `framework`：技术底座

只提供配置、数据库连接、密码学、日志、对象存储、HTTP、FFmpeg 和调度等通用能力。它不能导入 `api`、`domain`、`integrations` 或 `mcp_server`，也不能出现抖音任务、作品、评论、账号等业务状态机。

数据库引擎和 session 工厂属于 `framework`；“创建首个管理员”属于 `application.identity` 的启动用例。MinIO 文件读写属于 `framework.storage`；媒体资产状态变化和 `douyin/{task_id}/...` 对象 key 规则属于 `application.douyin.media`。CDP 的发现、WebSocket 地址重写和唯一的 `connect_over_cdp` 入口属于 `framework.browser.cdp`；stealth、Profile、页面 marker 与抖音中文错误翻译仍属于 integration。

### `integrations`：外部平台适配

承载抖音签名、HTTP 客户端、CDP 连接、远程浏览器、登录和页面操作等外部协议细节。该层可以使用 `framework`，但不能导入 `api`、`domain` 或 `mcp_server`，不得直接持久化 SQLModel 实体。

集成层通过中立 DTO 或函数返回平台数据；账号选择、任务恢复、入库和媒体状态机由 `application` 协调，并使用 `domain` 模型表达状态。这样平台页面变化不会迫使 HTTP 路由和数据库规则一起变化。

### `domain`：业务模型与规则

按业务切片组织持久化模型、值对象、Schema 和不依赖外部系统的规则。每个切片内部可继续按 `models`、`schemas`、`policy` 拆分，不为追求目录数量而制造空抽象。

`domain` 不依赖 HTTP、MCP、application 或具体抖音适配器。类名、表名、字段、约束和枚举语义在结构迁移中保持不变。

### `application`：用例与编排

承载事务边界、查询服务、任务 Manager、恢复状态机、账号选择、媒体流水线和互动审计。它依赖 `domain` 表达业务状态，调用 `integrations` 执行平台操作，并使用 `framework` 的数据库、存储和并发原语。

跨业务切片通过公开 application service 协作；后台单例只在 canonical 模块创建一次，旧路径只能指向同一模块对象。任务级配置始终作为参数传递，不能写回模块级全局配置。

application 不导入 FastAPI/Starlette，也不直接导入 Playwright 或 MinIO SDK。HTTP 状态码由 API 层映射；浏览器异常与对象存储客户端通过 integrations/framework 暴露的中立类型进入用例层，避免传输协议和驱动实现反向污染任务逻辑。

### `api` 与 `mcp_server`：入站接口

二者只负责协议层职责：参数解析、鉴权、调用 application 用例、错误映射和响应序列化。SQL 查询、MinIO、Playwright、文件路径判断和业务状态迁移均下沉到 `application`。

API 路由已不再直接导入 SQLModel/SQLAlchemy、MinIO 或 Playwright，也不直接调用 Session 查询/事务方法；唯一保留的 SQLModel import 是 `api/deps.py` 用来构造请求级 `Session` 依赖。MCP 继续通过同一 FastAPI 服务复用 application 用例，不能复制第二套任务逻辑。

## 依赖方向

```text
api ───────┐
           ├──> application ──> domain
mcp_server ┘          ├───────> integrations ──> framework
                     └────────────────────────> framework

bootstrap/settings <── api / application / integrations / framework
main.py ──> api / application / integrations / framework
```

- `framework` 不反向依赖任何业务或入站层。
- `integrations` 不依赖 `domain`、`application` 和入站层。
- `domain` 不依赖 API/MCP/application/integrations。
- `application` 负责编排 domain、integrations 和 framework，不能依赖 API/MCP。
- API/MCP 不直接调用数据库、对象存储或浏览器，只调用 application 用例。
- 应用启动文件是 composition root，负责装配具体实现；不得把装配代码扩散到领域模块。

## 兼容迁移策略

采用“绞杀者 + 兼容门面”的小步迁移，避免一次性移动造成循环依赖或隐藏行为变化。

1. **冻结基线**：先运行 OpenAPI、SQLModel metadata、任务状态机和现有业务测试。
2. **建立技术底座**：新增 `framework`，把纯技术实现迁入；`app.core.*` 暂时作为只重导出的兼容门面。
3. **隔离平台适配**：迁移无数据库依赖的签名、客户端、CDP 和登录模块；`app.douyin.*` 保留兼容导出和原许可证声明。
4. **迁移 application 服务**：按 accounts、tasks、works、comments、interactions、keywords、tracks、tags、media 逐个切片迁移；`app.services.*` 暂时指向同一个 canonical 模块对象。
5. **拆薄入站接口**：保持原路由前缀、函数名、注册顺序和响应模型，把查询与状态变更逐项移入 application service；MCP 同步复用同一 HTTP API。
6. **拆分模型注册**：领域模型迁移后，由唯一的模型注册模块显式导入所有表，Alembic `target_metadata` 仍指向同一个 `SQLModel.metadata`。
7. **移除门面**：只有在仓库内外调用方均已迁移、完整测试通过后，才用独立变更删除兼容路径。

每一步都必须满足：OpenAPI 哈希不变、metadata 哈希不变、`alembic check` 无新操作、后端完整质量门禁通过。目录移动若导致任何契约哈希变化，应先回退并查明原因，不能直接更新基线来“适配”重构。

## 架构门禁

`backend/tests/architecture/` 提供三类持续约束：

- OpenAPI 精确 canonical SHA256，防止路径、schema 或描述等契约被结构迁移意外改变。
- SQLModel metadata 语义 SHA256，覆盖迁移相关的表、列、外键、索引和约束。
- AST 依赖检查，不引入额外依赖包即可识别绝对/相对导入，约束 `framework`、`integrations`、`domain`、`application`、MCP 网关和 API 基础设施依赖，并禁止 application 直接依赖 FastAPI、Starlette、Playwright 与 MinIO SDK。
- 30 条抖音核心路由的 method、path、operationId 与注册顺序快照。
- 旧路径与 canonical 模块/Manager 单例的对象身份契约，防止 monkeypatch 或后台任务分叉。

基线只在经过明确评审的业务契约或数据库迁移中更新；纯重构不得更新基线。
