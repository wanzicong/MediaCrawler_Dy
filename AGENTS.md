# 项目开发约定

## 技术栈

- 官方 Full Stack FastAPI Template 0.10.0
- 后端：Python、FastAPI、SQLModel、PostgreSQL、Alembic、Pytest
- 前端：React、TypeScript、Vite、Tailwind、自动生成 OpenAPI 客户端
- 浏览器：Playwright 仅用于 `connect_over_cdp`，禁止标准 launch 回退

## 目录边界

- 抖音请求、登录、CDP 与编排：`backend/app/douyin/`
- API 路由：`backend/app/api/routes/douyin.py`
- 持久化模型：`backend/app/models.py`
- 数据库迁移：`backend/app/alembic/versions/`
- 任务生命周期：`backend/app/services/douyin_tasks.py`
- 后端测试：`backend/tests/douyin/`

## 必须遵守

- Cookie、Token 和原始账号 ID 不得写入数据库、日志或 API 响应。
- 所有爬取参数必须是任务级对象，禁止修改模块级全局配置。
- 禁止 `chromium.launch()`、`launch_persistent_context()` 以及 CDP 失败后的标准模式回退。
- 创作者/评论用户信息必须通过现有脱敏映射后落库。
- 修改模型时必须同步增加 Alembic 迁移。
- 抖音适配代码必须保留非商业许可证和版权来源。

## 质量门禁

后端变更至少执行：

```bash
uv run ruff check app tests
uv run mypy app
uv run python -m compileall -q app
uv run pytest
```

涉及服务行为时还需执行数据库迁移、启动后端并验证健康检查、鉴权和对应业务 API。
