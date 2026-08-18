# crawler-business

业务域核心模块。系统的心脏：包含全部表操作（21 张表）与全部资源操作——业务模型、用例编排、后台任务管理、存储/媒体/HTTP 技术驱动、Alembic 数据库迁移。

## 定位

- 分发包名：`crawler-business`
- 导入路径：`crawler.business`
- 依赖：`crawler-bootstrap` + `crawler-browser` + `crawler-douyin-client` + sqlmodel + alembic + minio 等

## 顶层结构

| 位置 | 职责 |
|------|------|
| `model_registry.py` | 显式注册全部 21 张表到 SQLModel.metadata（Alembic 与架构测试的统一事实源） |
| `errors.py` | 业务通用异常 |
| `concurrency/fair_limiter.py` | `FairLimiter`：按 key 公平轮转限流，大任务不阻塞小任务 |
| `resources/storage/` | 存储驱动：`local.py`（本地文件）、`minio.py`（对象存储）——MinIO SDK 唯一允许出现的位置 |
| `resources/media/ffmpeg.py` | FFmpeg 音轨提取（16kHz 单声道压缩音频，供远程字幕） |
| `resources/http/ranges.py` | HTTP Range 流式响应（视频进度条拖动） |
| `alembic/` + `alembic.ini` | 数据库迁移，在本目录执行 `uv run alembic upgrade head` |

## 通用子域

| 子域 | 职责 |
|------|------|
| `identity/` | 用户模型与服务、首次启动引导、邮件发送（email-templates） |
| `items/` | 模板自带的演示切片 |
| `common/` / `system/` | 通用模型与系统文档模型 |

## 抖音业务子域（`douyin/`，10 个）

| 子域 | 职责 |
|------|------|
| `accounts/` | 抖音账号槽位：账号选择、状态管理、CDP 槽位绑定 |
| `tasks/` | 采集任务核心：任务状态机（`service.py`）、断点持久化（`persistence.py`）、爬取编排（`crawler.py`，search/detail/creator/liked/collected 五类）、后台 Manager |
| `tracks/` | 赛道：关键词/任务/内容的一级归属维度，默认赛道保护、删除前数据迁移（`bindings.py`） |
| `keywords/` | 关键词库：按赛道组织、批量建任务 |
| `comments/` | 评论落库（脱敏后）、评论库查询（`query_service.py`）与导出（`exports.py`） |
| `content/` | 作品内容模型（仅 `models.py`，例外登记） |
| `tags/` | 标签体系与历史标签同步 |
| `media/` | 媒体资产：下载队列（`pipeline.py`）、远程字幕、本地↔MinIO 迁移（`migration.py`，SHA-256 校验）、预览会话（`preview.py`）、流式投递（`delivery.py`） |
| `library/` | 资源库：跨任务的作品/评论统一检索 |
| `interactions/` | 互动管理：点赞/收藏关系、评论回复执行、截图存证（`screenshots.py`） |

## 分包规范（架构测试机器强制）

- 每个子域固定 `models.py` + `service.py` 两件套；重读场景追加 `query_service.py`。
- 专有编排使用同名模块（如 `tasks/crawler.py`、`tracks/bindings.py`）。
- 例外登记：`content` 仅 models；`comments` 以 exports/query_service 代替 service。

## 架构约束

- 不得 import FastAPI / Starlette / Playwright；MinIO SDK 只允许出现在 `resources/storage/`。
- 修改模型必须同步生成 Alembic 迁移并跑 `alembic check` 确认零漂移。

## 质量门禁

```powershell
uv run mypy -p crawler.business
uv run ruff check modules/business
Set-Location modules/business; uv run alembic check
```
