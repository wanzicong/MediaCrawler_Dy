# crawler-douyin-client

抖音传输适配模块。抖音平台的"协议层"：所有与抖音服务器/页面交互的细节封装于此，对上层只暴露干净的客户端接口。

- 分发包名：`crawler-douyin-client`
- 导入路径：`crawler.douyin_client`（对外符号统一从包门面导出）
- 依赖：`crawler-browser`（CDP 会话）+ httpx + PyExecJS + playwright + pydantic
- 架构位置：依赖方向 `business → douyin-client → browser → bootstrap`；只允许依赖
  bootstrap / browser，禁止反向 import business / api / mcp。

## 公共 API

所有对外符号从包门面导出：

```python
from crawler.douyin_client import (
    DouyinClient,                  # 签名 HTTP 客户端
    DouyinLogin,                   # 扫码登录 / Cookie 登录流程
    DouyinInteractionExecutor,     # 页面互动写回：评论/回复/私信编排器
    InteractionExecutionRequest,   # 互动请求 DTO
    InteractionExecutionResult,    # 互动执行结果 DTO
    InteractionBrowserConnection,  # CDP 连接参数 DTO（与 account 入参二选一）
    DouyinError, DataFetchError, LoginError, InteractionExecutionError,  # 异常族
    SearchChannelType, SearchSortType, PublishTimeType,                  # 枚举
    VideoUrlInfo, CreatorUrlInfo, parse_video_info, parse_creator_info,  # 链接解析
    DouyinRequestLogEntry, RequestLogCallback,                           # 请求日志类型
    anonymize_user_id, anonymize_account_id, mask_nickname,
    map_aweme, map_comment,                                              # 隐私脱敏
)
```

`signer` 的 `get_web_id` / `get_a_bogus` 保持包内私有，不从门面导出。

## 目录结构

```
src/crawler/douyin_client/
├── __init__.py              # 公共门面：re-export，不写逻辑
├── base/                    # 无状态传输支撑
│   ├── errors.py            # 异常族：DouyinError/DataFetchError/LoginError/InteractionExecutionError
│   ├── types.py             # 枚举 + 链接 DTO + parse 函数
│   ├── signer.py            # webid + a_bogus（Node 执行 resources/douyin.js）
│   └── privacy.py           # HMAC 脱敏与昵称打码
├── http/
│   ├── client.py            # DouyinClient：主机会话 + 签名传输引擎 + 场景客户端容器
│   ├── request_log.py       # DouyinRequestLogEntry/RequestLogCallback + cookie 转换工具
│   └── scenarios/           # 读接口按业务场景拆分（组合挂在 client.<场景>_api 上）
│       ├── search.py        # SearchApi：综合搜索
│       ├── aweme.py         # AwemeApi：作品详情、用户发布列表
│       ├── comments.py      # CommentsApi：一级/子评论分页、整批抓取
│       ├── user.py          # UserApi：本人/他用户资料、点赞、收藏
│       └── resolver.py      # ShortUrlApi：v.douyin.com 短链解析
├── login/
│   └── login.py             # DouyinLogin：扫码登录 / Cookie 登录
├── interactions/            # 页面互动写回（一个文件一个类）
│   ├── executor.py          # DouyinInteractionExecutor：编排 + CDP 连接解析 + 流程入口
│   ├── models.py            # 互动 DTO + 步骤回调 + 旧版账号 Protocol
│   ├── selectors.py         # 选择器/页面文案/就绪脚本常量（唯一出处）
│   ├── page_controller.py   # PageController：DOM 查询与点击基元
│   ├── comment_locator.py   # CommentLocator：评论目标/私信编辑器定位
│   ├── submit_flow.py       # SubmitFlow：内容填写与提交确认
│   └── response_inspector.py# ResponseInspector：发布请求/响应无状态解析
└── resources/douyin.js      # 签名算法（沿用 MediaCrawler，见 NON_COMMERCIAL_LICENSE）
```

约定：**一个文件一个类**；包根目录下只有门面 `__init__.py` 和职责子目录，没有游离的
`.py`。业务层只应从包门面导入，不应深入内部子包路径（`crawler.douyin_client.http.*` 等
仅供本模块内部与测试使用）。

`DouyinClient` 退化为「主机会话 + 签名传输」，搜索/作品/评论/用户/短链等读接口按业务
场景拆分到 `http/scenarios/`，经组合属性访问、方法名保持不变：`client.search_api.search(...)`、
`client.aweme_api.get_video(...)`、`client.comments_api.get_all_comments(...)`、
`client.user_api.get_self_profile(...)`、`client.resolver_api.resolve_short_url(...)`。
登录态探测 `pong`/cookie 同步 `update_cookies`/通用 `get`/`post` 仍留在 `DouyinClient`。

## interactions/ 协作类职责

`DouyinInteractionExecutor` 原是 1800 行的巨型类，现按职责拆为 5 个协作类 + 常量模块；
executor 只做编排，页面级细节委托给协作类：

| 类 / 模块 | 职责 |
|---|---|
| `DouyinInteractionExecutor` | 编排：账号→CDP 连接解析、评论/回复/私信三条流程入口、页面导航、步骤上报 |
| `PageController` | DOM 基元：找可见元素、按文案找控件、触发点击、判空、探测页面文案 |
| `CommentLocator` | 定位：评论列表激活/滚动、按 id/内容定位目标评论、打开回复框、私信编辑器 |
| `SubmitFlow` | 提交：写入内容、触发发送、等待平台明确确认（成功/失败/风控/歧义分类） |
| `ResponseInspector` | 解析：识别发布请求/响应、平台状态码、错误文案、结果 id（纯静态） |
| `selectors.py` | 上述类共用的选择器与页面文案常量，避免各自维护失同步 |

## 架构约束

- 不得直接访问业务表、不得管理数据库事务。
- Cookie、Token、原始账号 ID 不出此层（不写库、不进日志）；原始 sec_uid 等仅保留在
  本地内存用于页面跳转，不落盘、不上报。
- 互动执行经 CDP 已有浏览器 profile，是用户明确确认后的**写操作**；自动化标签页与
  用户手工标签页互相隔离（见 `crawler.browser` 的 `page_marker`）。
- 抖音适配代码受非商业学习许可证约束，仅限学习研究用途。

## 质量门禁

```powershell
uv run mypy -p crawler.douyin_client
uv run ruff check modules/douyin-client
uv run pytest tests/business/douyin/test_client.py tests/business/douyin/test_login.py tests/business/douyin/test_privacy.py tests/business/douyin/test_interaction_executor.py --confcutdir tests/business/douyin
```
