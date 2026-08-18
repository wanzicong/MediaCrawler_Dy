# crawler-browser

CDP-only 浏览器运行时模块。系统与 Chrome 之间的唯一通道：只通过 CDP 连接已存在的浏览器，绝不自行启动标准 Playwright 实例。

## 定位

- 分发包名：`crawler-browser`
- 导入路径：`crawler.browser`
- 依赖：`crawler-bootstrap` + playwright + httpx

## 文件职责

| 文件 | 职责 |
|------|------|
| `cdp/endpoint.py` | CDP 端点发现与端口探测 |
| `cdp/connection.py` | `connect_over_cdp` 连接管理 |
| `cdp/network.py` | CDP 网络层辅助 |
| `session.py` | CDP 会话：stealth 反检测注入、自动化标签页生命周期 |
| `remote.py` | Docker 远程浏览器槽位管理（账号槽位池，多实例分配） |
| `errors.py` | `CDPConnectionError`——连接失败即任务失败，禁止回退 |
| `resources/stealth.js` | 反自动化检测注入脚本 |

## 架构约束

- **禁止** `chromium.launch()`、`launch_persistent_context()` 及任何标准模式回退。
- 只依赖 bootstrap；不得 import business/api 层代码。
- CDP 端口等同浏览器完全控制权，只允许回环/内网绑定。

## 质量门禁

```powershell
uv run mypy -p crawler.browser
uv run ruff check modules/browser
```
