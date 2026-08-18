# crawler-mcp

MCP 入站网关模块。把系统能力暴露给外部智能体的薄网关：32 个工具全部经 HTTP 代理到同一 FastAPI 服务，零业务逻辑复制。

## 定位

- 分发包名：`crawler-mcp`
- 导入路径：`crawler.mcp`
- 依赖：`crawler-bootstrap` + mcp + httpx

## 文件职责

| 文件 | 职责 |
|------|------|
| `server.py` | MCP Server 装配与工具注册 |
| `runtime.py` | 运行时（服务端登录 FastAPI 的会话管理） |
| `__main__.py` | 入口：`python -m crawler.mcp`，支持 stdio / streamable-http |

## 工具分组（`tools/`，32 个工具）

| 文件 | 工具能力 |
|------|----------|
| `tasks.py` | 创建/查询/取消/恢复任务、单视频评论重爬、作者作品抓取 |
| `accounts.py` | 账号槽位查询与管理 |
| `catalog.py` | 作品/评论/互动分页读取、资源库检索 |
| `interactions.py` | 互动数据工具 |
| `media.py` | 完成后媒体处理、进度查询、失败重试、重新翻译、迁移 MinIO |

## 鉴权模型

- 端口只监听本机回环（`127.0.0.1:8766`）。
- 服务端用环境变量（`MCP_API_USERNAME`/`MCP_API_PASSWORD`，缺省回退 `FIRST_SUPERUSER`）登录 FastAPI；客户端 JSON 不含任何凭据。

## 运行

```powershell
uv run python -m crawler.mcp                                  # stdio 模式
uv run python -m crawler.mcp --transport streamable-http      # HTTP 模式
```

## 架构约束

- 只依赖 bootstrap；所有业务能力必须经 HTTP 调用 API 获得，禁止建立第二套业务逻辑。
- 工具清单（32 个）受契约测试哈希保护。

## 质量门禁

```powershell
uv run mypy -p crawler.mcp
uv run ruff check modules/mcp
```
