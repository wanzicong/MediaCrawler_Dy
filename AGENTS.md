# 项目开发约定

## 技术栈

- 官方 Full Stack FastAPI Template 0.10.0
- 后端：Python、FastAPI、SQLModel、PostgreSQL、Alembic、Pytest
- 前端：React、TypeScript、Vite、Tailwind、自动生成 OpenAPI 客户端
- 浏览器：Playwright 仅用于 `connect_over_cdp`，禁止标准 launch 回退

## 目录边界

- 运行配置与装配：`backend/app/bootstrap/`
- 通用技术能力：`backend/app/framework/`，按数据库、安全、日志、存储、HTTP、浏览器和并发职责切分，不得包含抖音业务语义。
- 外部平台适配：`backend/app/integrations/douyin/`，负责抖音请求、签名、登录、CDP 和页面协议，不得直接访问业务表或管理事务。
- 业务模型与纯规则：`backend/app/domain/`，按 identity、items 及 douyin 子域切分。
- 用例、事务、任务编排与后台 Manager：`backend/app/application/`。
- HTTP 入站接口：`backend/app/api/`，只负责参数、鉴权、调用 application 和 HTTP 异常/响应映射。
- MCP 入站接口：`backend/app/mcp_server/`，只通过项目 HTTP API 复用业务能力，不建立第二套业务逻辑。
- `backend/app/models.py`、`backend/app/services/`、`backend/app/douyin/` 和 `backend/app/core/` 是迁移期兼容入口；新实现与新 import 必须使用 canonical 分层路径。
- 数据库迁移：`backend/app/alembic/versions/`
- 后端测试：`backend/tests/douyin/`

依赖方向固定为：`api/mcp -> application -> domain`，`application -> integrations/framework`，`integrations -> framework`。禁止反向依赖；`main.py` 是运行时组合根，`bootstrap/settings.py` 提供全局配置。API 路由禁止直接使用 SQLAlchemy/SQLModel 查询、MinIO、Playwright、文件路径判断或事务操作。

## 必须遵守

- Cookie、Token 和原始账号 ID 不得写入数据库、日志或 API 响应。
- 所有爬取参数必须是任务级对象，禁止修改模块级全局配置。
- 禁止 `chromium.launch()`、`launch_persistent_context()` 以及 CDP 失败后的标准模式回退。
- 创作者/评论用户信息必须通过现有脱敏映射后落库。
- 修改模型时必须同步增加 Alembic 迁移。
- 抖音适配代码必须保留非商业许可证和版权来源。
- 纯目录重构不得修改 OpenAPI、MCP 工具、表结构、Alembic head、任务状态机、存储 key/路径和错误语义。
- 移动旧模块时必须让旧路径与 canonical 路径指向同一模块/单例，避免 monkeypatch 与后台 Manager 分叉。

## 质量门禁

后端变更至少执行：

```bash
uv run ruff check app tests
uv run mypy app
uv run python -m compileall -q app
uv run pytest
uv run alembic check
```

涉及服务行为时还需执行数据库迁移、启动后端并验证健康检查、鉴权和对应业务 API。
结构重构还必须运行 `backend/tests/architecture/` 中的 OpenAPI、SQLModel metadata、MCP 与依赖方向契约测试。
