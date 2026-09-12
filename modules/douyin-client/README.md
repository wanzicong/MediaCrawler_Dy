# crawler-douyin-client

抖音 HTTP API 客户端模块。抖音平台的"协议层"：签名、传输、响应解析与隐私映射封装于此，
对上层只暴露干净的纯 API 接口。**零浏览器依赖**——不 import `crawler.browser` /
`crawler.bootstrap`，也不 import playwright。

- 分发包名：`crawler-douyin-client`
- 导入路径：`crawler.douyin_client`（对外符号统一从包门面导出）
- 依赖：httpx + PyExecJS + pydantic
- 架构位置：依赖方向 `business → douyin-client`。浏览器侧能力（UA / localStorage /
  cookie / 请求指纹）一律经入站契约 `SessionContext` 注入，实现方在 `crawler.browser`。

## 公共 API

所有对外符号从包门面导出（23 项）：

```python
from crawler.douyin_client import (
    DouyinClient,                  # 签名 HTTP 客户端（会话能力经 session= 注入）
    SessionContext,                # 入站契约：user_agent/local_storage/cookies/fingerprint
    DouyinError, DataFetchError,   # 异常族（登录/互动异常已迁往 crawler.browser）
    SearchChannelType, SearchSortType, PublishTimeType,                  # 枚举
    VideoUrlInfo, CreatorUrlInfo, parse_video_info, parse_creator_info,  # 链接解析
    DouyinRequestLogEntry, RequestLogCallback, CommentCallback, IntervalProvider,
    REDACTED, redact_headers, is_sensitive_key,                          # 请求头脱敏
    anonymize_user_id, anonymize_account_id, mask_nickname,
    map_aweme, map_comment,                                              # 隐私脱敏
)
```

`signing` 的 `get_web_id` / `get_a_bogus` 保持包内私有，不从门面导出。

登录流程（`DouyinLogin`）、互动写回编排（`DouyinInteractionExecutor`）与
`LoginError` / `InteractionExecutionError` 已迁往 `crawler.browser`，不再属于本包。

## 目录结构

```
src/crawler/douyin_client/
├── __init__.py              # 公共门面：re-export，不写逻辑
├── errors/
│   ├── __init__.py
│   └── family.py            # DouyinError / DataFetchError
├── parsing/
│   ├── __init__.py
│   ├── types.py             # 枚举 + 链接 DTO
│   └── links.py             # parse_video_info / parse_creator_info
├── signing/
│   ├── __init__.py
│   ├── web_id.py            # get_web_id
│   └── a_bogus.py           # get_a_bogus（Node 执行 resources/douyin.js）
├── privacy/
│   ├── __init__.py
│   ├── masking.py           # HMAC 脱敏与昵称打码
│   └── mapping.py           # map_aweme / map_comment
├── session/
│   ├── __init__.py
│   └── context.py           # SessionContext：本包拥有、browser 结构化满足的入站契约
├── http/
│   ├── __init__.py
│   ├── client.py            # DouyinClient：主机会话 + 签名传输引擎 + 场景客户端容器
│   ├── request_log.py       # DouyinRequestLogEntry / 回调类型
│   ├── redaction.py         # 请求头脱敏唯一真源（SENSITIVE_KEY_MARKERS / redact_headers）
│   └── scenarios/           # 读接口按业务场景拆分（组合挂在 client.<场景>_api 上）
│       ├── search.py        # SearchApi：综合搜索
│       ├── aweme.py         # AwemeApi：作品详情、用户发布列表
│       ├── comments.py      # CommentsApi：一级/子评论分页、整批抓取、find_comment
│       ├── user.py          # UserApi：本人/他用户资料、点赞、收藏
│       └── resolver.py      # ShortUrlApi：v.douyin.com 短链解析
└── resources/douyin.js      # 签名算法（沿用 MediaCrawler，见 NON_COMMERCIAL_LICENSE）
```

约定：**一个文件一个类**；包根目录下只有门面 `__init__.py` 和职责子目录，没有游离的
`.py`。业务层只应从包门面导入，不应深入内部子包路径（`crawler.douyin_client.http.*` 等
仅供本模块内部与测试使用）。

`DouyinClient` 是「主机会话 + 签名传输」，搜索/作品/评论/用户/短链等读接口按业务
场景拆分到 `http/scenarios/`，经组合属性访问、方法名保持不变：`client.search_api.search(...)`、
`client.aweme_api.get_video(...)`、`client.comments_api.get_all_comments(...)`、
`client.user_api.get_self_profile(...)`、`client.resolver_api.resolve_short_url(...)`。
登录态探测 `pong`/cookie 同步 `update_cookies`/通用 `get`/`post` 仍留在 `DouyinClient`，
二者不接受任何浏览器对象（S5b 已删除历史兼容入参 `browser_context`）。

## 会话能力注入（零浏览器依赖的关键）

`DouyinClient` 不持有任何浏览器对象，构造与工厂只接收 `session: SessionContext`：

```python
client = await DouyinClient.create(
    session=page,      # 任何结构化满足 SessionContext 的对象（如 browser 的 BrowserPage）
    timeout=10.0,
    verify_ssl=True,
)
```

请求指纹（`DouyinClient.FINGERPRINT_KEYS` 共 14 项）逐键取自
`await session.fingerprint()`：**缺键即不写入，绝不回退伪造常量**，因此源码中不存在
任何硬编码指纹字面量。

## 架构约束

- 不得直接访问业务表、不得管理数据库事务。
- Cookie、Token、原始账号 ID 不出此层（不写库、不进日志）；原始 sec_uid 等仅保留在
  本地内存用于页面跳转，不落盘、不上报。
- 请求日志在构造时即脱敏请求头（`redact_headers`），脱敏标记集唯一真源在
  `http/redaction.py`。
- 抖音适配代码受非商业学习许可证约束，仅限学习研究用途。

## 质量门禁

```powershell
uv run mypy -p crawler.douyin_client
uv run ruff check modules/douyin-client
uv run pytest tests/business/douyin/test_client.py tests/business/douyin/test_privacy.py tests/business/douyin/test_request_logs.py --confcutdir tests/business/douyin
```

登录与互动执行相关的用例已随代码迁往 browser 站点层：
`tests/browser/sites/douyin/test_login_flow.py`、`tests/browser/sites/douyin/test_interaction_executor.py`。
