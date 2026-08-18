# crawler-bootstrap

运行配置与技术原语模块。整个系统的"地基"：只提供无业务语义的基础能力，位于依赖 DAG 最底层。

## 定位

- 分发包名：`crawler-bootstrap`
- 导入路径：`crawler.bootstrap`
- 依赖：仅第三方（pydantic、sqlmodel、pyjwt、pwdlib），**不依赖任何其他 workspace 模块**

## 文件职责

| 文件 | 职责 |
|------|------|
| `settings.py` | pydantic-settings 全局配置（数据库、JWT、CORS、邮件、Whisper、MinIO、MCP 等）；`BASE_DIR` 锚定仓库根，`.env`/`.env.local` 加载与相对路径解析不依赖进程工作目录 |
| `database.py` | SQLModel/SQLAlchemy engine 与 Session 工厂 |
| `security.py` | 密码哈希（pwdlib）与 JWT 签发/校验 |
| `logging.py` | 日志配置，敏感传输字段（Cookie、Token）收敛 |

## 架构约束

- 禁止 import 任何 `crawler.*` 兄弟模块（反向依赖）。
- 禁止导入 FastAPI / Playwright 等上层框架。
- 配置字段变更需同步检查 `.env` 模板与 compose 文件。

## 质量门禁

```powershell
uv run mypy -p crawler.bootstrap
uv run ruff check modules/bootstrap
```
