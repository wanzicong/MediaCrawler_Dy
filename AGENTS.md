# 项目开发约定

## 技术栈

- 官方 Full Stack FastAPI Template 0.10.0
- 后端：Python、FastAPI、SQLModel、PostgreSQL、Alembic、Pytest
- 包管理：uv workspace 多项目（monorepo），统一 `crawler.*` 命名空间（PEP 420）
- 前端：React、TypeScript、Vite、Tailwind、自动生成 OpenAPI 客户端
- 浏览器：Playwright 仅用于 `connect_over_cdp`，禁止标准 launch 回退

## 模块边界（uv workspace）

每个 `modules/*` 目录是一个独立的 Python 项目（独立 pyproject.toml、src 布局、独立分发包），依赖方向由打包元数据和架构测试双重强制：

- `modules/bootstrap/`（crawler-bootstrap）：运行配置、数据库引擎、安全与日志原语。不得依赖任何其他 workspace 模块。
- `modules/browser/`（crawler-browser）：CDP-only 浏览器运行时（端点发现、会话、远程槽位、stealth 注入），只依赖 bootstrap。
- `modules/douyin-client/`（crawler-douyin-client）：抖音传输适配（HTTP 客户端、a_bogus 签名、登录、互动写回、脱敏），只依赖 browser/bootstrap，不得直接访问业务表或管理事务。
- `modules/business/`（crawler-business）：业务域全部内容——按子域合并的 models.py + service.py（`douyin/<子域>/` 与 `identity/`、`items/`、`common/`、`system/`）、用例编排与后台 Manager、存储/媒体/HTTP 资源驱动（`resources/`）、并发原语（`concurrency/`）、Alembic 迁移（`alembic/`）。
- `modules/api/`（crawler-api）：HTTP 入站适配，只负责参数、鉴权、调用 business 和 HTTP 异常/响应映射。唯一登记的越界例外：`routes/system_docs.py` 自省 `crawler.mcp.server` 的工具元数据。
- `modules/mcp/`（crawler-mcp）：MCP 入站网关，只通过项目 HTTP API 复用业务能力，不得建立第二套业务逻辑。

依赖方向固定为：`api -> business -> douyin-client -> browser -> bootstrap`，`mcp -> bootstrap`。禁止反向依赖；`crawler/api/main.py` 是运行时组合根，`crawler/bootstrap/settings.py` 提供全局配置。API 路由禁止直接使用 SQLAlchemy/SQLModel 查询（登记的运维脚本除外）、MinIO、Playwright、文件路径判断或事务操作。MinIO SDK 只允许出现在 `business/resources/storage/` 驱动中。

## 测试布局

- `tests/architecture/`：跨模块契约测试（依赖边界、分包规范、OpenAPI/SQLModel metadata/MCP 工具/路由顺序四哈希）。
- `tests/business/`：业务域测试（`douyin/`、`crud/`、`scripts/`）。
- `tests/api/`：HTTP 路由测试。
- `tests/utils/`：共享测试工具。

## 必须遵守

- Cookie、Token 和原始账号 ID 不得写入数据库、日志或 API 响应。
- 所有爬取参数必须是任务级对象，禁止修改模块级全局配置。
- 禁止 `chromium.launch()`、`launch_persistent_context()` 以及 CDP 失败后的标准模式回退。
- 创作者/评论用户信息必须通过现有脱敏映射后落库。
- 修改模型时必须同步增加 Alembic 迁移（`modules/business/alembic/versions/`）。
- 抖音适配代码必须保留非商业许可证和版权来源（`modules/douyin-client/src/crawler/douyin_client/NON_COMMERCIAL_LICENSE`）。
- 纯目录重构不得修改 OpenAPI、MCP 工具、表结构、Alembic head、任务状态机、存储 key/路径和错误语义。

## 质量门禁

后端变更在仓库根目录至少执行：

```bash
uv run ruff check modules tests
uv run ruff format modules tests --check
uv run mypy -p crawler.bootstrap -p crawler.browser -p crawler.douyin_client -p crawler.business -p crawler.api -p crawler.mcp
uv run python -m compileall -q modules tests
uv run pytest
(cd modules/business && uv run alembic check)
```

涉及服务行为时还需执行数据库迁移、启动后端并验证健康检查、鉴权和对应业务 API。
结构重构还必须运行 `tests/architecture/` 中的 OpenAPI、SQLModel metadata、MCP 与依赖方向契约测试。
