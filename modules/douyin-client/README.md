# crawler-douyin-client

抖音传输适配模块。抖音平台的"协议层"：所有与抖音服务器/页面交互的细节封装于此，对上层只暴露干净的客户端接口。

## 定位

- 分发包名：`crawler-douyin-client`
- 导入路径：`crawler.douyin_client`
- 依赖：`crawler-browser`（CDP 会话）+ httpx + PyExecJS + playwright + pydantic

## 文件职责

| 文件 | 职责 |
|------|------|
| `client.py` | 签名 HTTP 客户端：搜索、作品详情、评论、用户主页等读接口 |
| `signer.py` | `a_bogus` 请求签名（PyExecJS → Node 执行 `resources/douyin.js`） |
| `login.py` | 扫码登录 / Cookie 登录流程 |
| `interactions.py` | 页面互动写回：评论发表/回复、私信等经 CDP 页面的操作 |
| `privacy.py` | HMAC 脱敏与昵称打码（创作者/评论用户信息落库前必经此层） |
| `types.py` | 传输层类型定义 |
| `errors.py` | `DouyinError` / `DataFetchError` / `LoginError` |
| `resources/douyin.js` | 签名算法（沿用 MediaCrawler，见 `NON_COMMERCIAL_LICENSE`） |

## 架构约束

- 不得直接访问业务表、不得管理数据库事务。
- Cookie、Token、原始账号 ID 不出此层（不写库、不进日志）。
- 抖音适配代码受非商业学习许可证约束，仅限学习研究用途。

## 质量门禁

```powershell
uv run mypy -p crawler.douyin_client
uv run ruff check modules/douyin-client
```
