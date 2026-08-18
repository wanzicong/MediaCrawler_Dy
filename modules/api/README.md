# crawler-api

HTTP 入站适配模块。纯协议层：只做参数校验、JWT 鉴权、调用 business、HTTP 异常/响应映射，不含任何业务逻辑。

## 定位

- 分发包名：`crawler-api`
- 导入路径：`crawler.api`
- 依赖：`crawler-business`（连带传递全链）+ fastapi[standard] + sentry-sdk

## 文件职责

| 文件 | 职责 |
|------|------|
| `main.py` | FastAPI 应用装配与 lifespan（运行时组合根） |
| `router.py` | `api_router` 装配 |
| `deps.py` | `SessionDep` / `CurrentUser` 等依赖注入（登记的 SQL 使用例外之一） |
| `backend_pre_start.py` | 启动前等待数据库就绪 |
| `initial_data.py` | 首个超级用户初始化 |
| `tests_pre_start.py` | 测试前置初始化 |

## 路由清单（`routes/`，15 个模块）

| 分组 | 路由 | 说明 |
|------|------|------|
| 抖音核心 | `douyin.py` | 30 条核心路由的装配（注册顺序受契约测试保护） |
| 抖音子域 | `douyin_tasks.py` `douyin_tracks.py` `douyin_keywords.py` `douyin_accounts.py` `douyin_catalog.py` `douyin_interactions.py` `douyin_media.py` `douyin_tags.py` | 任务/赛道/关键词/账号/资源库/互动/媒体/标签 |
| 模板 | `login.py` `users.py` `items.py` `utils.py` `private.py` `system_docs.py` | 登录/用户/演示/工具/私有/系统文档 |

唯一登记的越界例外：`routes/system_docs.py` 自省 `crawler.mcp.server` 的工具元数据。

## 架构约束

- 路由禁止直接使用 SQLAlchemy/SQLModel 查询（登记的四个脚本除外）、MinIO、Playwright、文件路径判断或事务操作。
- OpenAPI 契约（76 paths / 112 schemas）受哈希基线保护，变更必须作为独立业务变更评审。

## 运行

```powershell
uv run fastapi run modules/api/src/crawler/api/main.py
```

## 质量门禁

```powershell
uv run mypy -p crawler.api
uv run ruff check modules/api
```
