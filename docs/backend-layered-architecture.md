# 后端多模块架构设计（uv workspace）

## 目标与不可变约束

后端从单项目五层结构升级为 uv workspace 多项目（monorepo）架构：每个业务模块是一个独立的 Python 项目，模块边界由打包元数据物理强制。无论结构如何演进，以下约束不变：

- 已发布的路径、HTTP 方法、请求/响应结构、`operationId` 和状态码保持不变。
- 现有 21 张表的表名、列顺序、类型、可空性、主外键、索引和约束保持不变；结构重构不生成 Alembic 迁移。
- 任务状态机、恢复逻辑、并发策略、媒体处理、账号选择、CDP 浏览器行为和 MCP 工具语义保持不变。
- Cookie、Token、原始账号 ID、脱敏与"仅 CDP、禁止浏览器 launch 回退"等安全约束保持不变。

自动门禁冻结当前基线：OpenAPI 为 76 个路径、112 个 schema；SQLModel metadata 为 21 张表；MCP 工具 32 个；抖音核心路由 30 条。任何基线变化都必须作为独立业务或数据库变更进行审查，不能混入目录迁移。

## 模块结构

仓库根是一个 uv workspace（根 `pyproject.toml` 声明 `members = ["modules/*"]`），六个成员共享 `crawler.*` 命名空间（PEP 420：`src/crawler/` 目录不放 `__init__.py`，各项目只装自己的子包）：

```text
modules/
├── bootstrap/                    # crawler-bootstrap：运行配置与技术原语
│   └── src/crawler/bootstrap/
│       ├── settings.py           # pydantic-settings，路径锚定仓库根 BASE_DIR
│       ├── database.py           # engine 与 session 工厂
│       ├── security.py           # 密码哈希与 JWT
│       └── logging.py            # 敏感传输日志收敛
├── browser/                      # crawler-browser：CDP-only 浏览器运行时
│   └── src/crawler/browser/
│       ├── cdp/                  # 端点发现、connect_over_cdp、端口探测
│       ├── session.py            # CDP 会话、stealth 注入、自动化标签页
│       ├── remote.py             # Docker 远程浏览器槽位管理
│       ├── errors.py             # CDPConnectionError
│       └── resources/stealth.js
├── douyin-client/                # crawler-douyin-client：抖音传输适配
│   └── src/crawler/douyin_client/
│       ├── client.py             # 签名 HTTP 客户端（读数据）
│       ├── signer.py             # a_bogus（execjs → Node 执行 douyin.js）
│       ├── login.py              # 扫码 / Cookie 登录
│       ├── interactions.py       # 页面互动写回（评论/私信）
│       ├── privacy.py            # HMAC 脱敏与昵称打码
│       ├── types.py / errors.py
│       ├── resources/douyin.js
│       └── NON_COMMERCIAL_LICENSE
├── business/                     # crawler-business：业务域全部内容
│   ├── alembic.ini + alembic/    # 数据库迁移（versions/）
│   └── src/crawler/business/
│       ├── model_registry.py     # 显式注册全部表到 SQLModel.metadata
│       ├── errors.py             # 业务通用异常
│       ├── concurrency/          # FairLimiter 按 key 公平轮转限流
│       ├── resources/            # 技术驱动：storage(local/minio)、media(ffmpeg)、http(ranges)
│       ├── common/ system/       # 通用与系统文档模型
│       ├── identity/             # models + service + bootstrap + mail + email-templates
│       ├── items/                # 模板演示切片（models + service）
│       └── douyin/               # 10 个业务子域，domain 与 application 按同名子域合并
│           ├── accounts/  tasks/  tracks/  keywords/  comments/
│           ├── content/   tags/   media/    library/   interactions/
│           # 每个子域固定 models.py + service.py；重读子域加 query_service.py；
│           # content 仅 models（例外登记），comments 以 exports/query_service 代替 service
├── api/                          # crawler-api：HTTP 入站适配
│   └── src/crawler/api/
│       ├── main.py               # FastAPI 应用与 lifespan（组合根）
│       ├── router.py             # api_router 装配
│       ├── deps.py               # SessionDep / CurrentUser
│       ├── routes/               # 纯 HTTP 适配器
│       └── backend_pre_start.py / initial_data.py / tests_pre_start.py
├── mcp/                          # crawler-mcp：MCP 入站网关
│   └── src/crawler/mcp/
│       ├── server.py / runtime.py / __main__.py
│       └── tools/                # 32 个工具，全部代理到 REST API
tests/
├── architecture/                 # 跨模块契约测试（依赖边界 + 分包规范 + 四哈希）
├── business/                     # 业务域测试（douyin/、crud/、scripts/）
├── api/                          # HTTP 路由测试
└── utils/                        # 共享测试工具
```

## 依赖方向（DAG）

```text
api ──> business ──> douyin-client ──> browser ──> bootstrap
mcp ───────────────────────────────────────────> bootstrap
```

- `bootstrap` 不依赖任何其他 workspace 模块。
- `browser` 只依赖 bootstrap；`douyin-client` 只依赖 browser/bootstrap，不得直接访问业务表或管理事务。
- `business` 可以使用前三个模块，不得依赖 api/mcp；不导入 FastAPI/Starlette/Playwright，MinIO SDK 只允许出现在 `resources/storage/` 驱动中。
- `api` 只负责协议层：参数、鉴权、调用 business、HTTP 异常/响应映射；不得直接操作 Session 查询/事务（登记的运维脚本除外）。唯一登记的越界例外：`routes/system_docs.py` 自省 `crawler.mcp.server` 的工具元数据。
- `mcp` 是薄网关：所有工具通过 HTTP 调用同一 FastAPI 服务，不复制第二套业务逻辑。

## 分包规范

- business 按业务子域分包：抖音子域挂 `business/douyin/`，通用子域（identity、items、common、system）直挂 `business/`。
- 每个子域固定 `models.py` + `service.py` 两件套；重读场景追加 `query_service.py`；专有编排使用同名模块（如 `tasks/crawler.py`、`tracks/bindings.py`）。
- browser / douyin-client 按职责分文件；资源文件（JS、许可证、邮件模板）随所在模块一起搬移，通过 `Path(__file__)` 相对引用。
- 以上规范由 `tests/architecture/test_module_layout.py` 机器强制，包括命名空间目录无 `__init__.py`、成员单包归属、两件套约定、资源文件存在性和测试 monkeypatch 目标存在性。

## 架构门禁

`tests/architecture/` 提供持续约束：

- OpenAPI 精确 canonical SHA256，防止路径、schema 或描述等契约被结构迁移意外改变。
- SQLModel metadata 语义 SHA256，覆盖迁移相关的表、列、外键、索引和约束。
- 32 个 MCP 工具的名称、描述与输入输出 schema SHA256。
- 30 条抖音核心路由的 method、path、operationId 与注册顺序快照。
- AST 依赖边界检查：按模块 DAG 约束 crawler.* 内部 import 与各层第三方框架（bootstrap/browser/douyin-client 禁 FastAPI，business 禁 FastAPI/Starlette/Playwright，api 禁 MinIO/Playwright 与 SQLModel 新增 import，mcp 禁 SQLModel/FastAPI），并禁止 API 层直接调用 Session 方法。
- 分包规范与 patch 目标存在性检查。

基线只在经过明确评审的业务契约或数据库迁移中更新；纯重构不得更新基线。

## 运行与配置

- `settings.py` 通过 `BASE_DIR = Path(__file__).resolve().parents[5]` 锚定仓库根：`.env`/`.env.local` 加载与 `data/`、`browser_data/` 等相对路径默认值不再依赖进程工作目录；容器中 `BASE_DIR` 解析为 `/app`，语义一致。
- 本地开发：仓库根 `uv sync` 一次安装全部成员；`.\scripts\start-local.ps1` 以仓库根为工作目录启动 uvicorn（`crawler.api.main:app`）与 MCP（`python -m crawler.mcp`）。
- 数据库迁移：在 `modules/business/` 下执行 `alembic upgrade head` / `alembic revision --autogenerate`。
- Docker：`docker/api/Dockerfile` 以仓库根为构建上下文，`uv sync --frozen --no-install-workspace --package crawler-api` 安装依赖后直接从 `modules/*/src` 源码运行（PYTHONPATH 含全部六个 src，因为 api 需要自省 mcp 工具元数据）。
