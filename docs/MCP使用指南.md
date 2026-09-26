# MCP 使用指南

本指南说明 `crawler-mcp`（MCP 网关）如何把**后端的全部 HTTP 接口**暴露给外部智能体，
以及前端页面使用的接口与 MCP 工具的对应关系。所有结论都可以用仓库里的脚本与契约测试复核。

## 1. 一句话定位

MCP 网关是**同一套能力的第二个入口**：它不复制任何业务逻辑，而是用超级管理员（或指定
服务账号）登录后端，把每次工具调用翻译成一次 HTTP 请求，并把响应原样（或按
content-type 转换后）返回给模型。

```
外部智能体 ──MCP(stdio / streamable-http)──▶ crawler-mcp ──HTTP──▶ crawler-api ──▶ business ──▶ PostgreSQL / MinIO / 浏览器
                                                             ▲
前端页面（React + 生成客户端）────────────────────────────────┘
```

前端与智能体走的是**同一批接口**，因此「前端能做的，MCP 都能做」；反过来，MCP 工具
的参数与返回也与接口逐字段一致（见 §5）。

## 2. 工具总览：两套工具

| 套别 | 数量 | 命名 | 参数口径 | 用途 |
| --- | --- | --- | --- | --- |
| 便捷工具 | 32 | 语义化短名，如 `create_douyin_task`、`list_douyin_tracks` | 经过裁剪与归一化（例如 `targets` 按采集类型解释成关键词/作品/作者） | 给模型最好用的常见动作，描述里带业务语义与安全提示 |
| 接口工具（生成） | 140 | 由 OpenAPI `operationId` 生成，如 `douyin_list_tasks`、`users_read_user_me` | **与接口完全一致**：参数名、类型、枚举、必填性、默认值都来自 OpenAPI | 覆盖全部后端能力，需要精细参数时使用 |

两套工具调用的是同一个接口，结果一致；`list_douyin_tasks` 与 `douyin_list_tasks`
的区别只是参数暴露多少。每个接口工具都带元数据 `meta.api = {method, path}`，
可以直接告诉模型「这个工具对应哪个接口」。

`modules/mcp/src/crawler/mcp/tools_spec.json` 是接口工具的唯一事实来源，由
`scripts/generate_mcp_tools.py` 从后端 OpenAPI 生成；`tests/architecture/test_mcp_coverage.py`
保证「每个接口都有工具」且「参数与接口 schema 一致」。

## 3. 启动与配置

### 3.1 传输方式

| 模式 | 命令 | 适用 |
| --- | --- | --- |
| stdio | `uv run python -m crawler.mcp` | 由本机 MCP 客户端（Claude Desktop、ChatGPT 桌面端等）托管进程 |
| streamable-http | `uv run python -m crawler.mcp --transport streamable-http --host 127.0.0.1 --port 8766 --path /mcp` | 远程/容器化部署；监听通配地址时必须显式给 `--allowed-host` |

### 3.2 环境变量（`.env`）

| 变量 | 含义 | 默认 |
| --- | --- | --- |
| `MCP_API_BASE_URL` | 后端 API 基地址（含 `/api/v1`） | `http://127.0.0.1:8000/api/v1` |
| `MCP_API_USERNAME` / `MCP_API_PASSWORD` | 网关登录用的账号；为空时回退超管 `FIRST_SUPERUSER` | 空 |
| `DOUYIN_MCP_TRANSPORT` | 默认传输方式 | `stdio` |
| `DOUYIN_MCP_HOST` / `DOUYIN_MCP_PORT` / `DOUYIN_MCP_PATH` | HTTP 模式的监听参数 | `127.0.0.1` / `8766` / `/mcp` |

网关**不使用 Cookie 或平台账号**：需要登录态的能力（扫码、互动发送）由后端在执行时用
托管账号完成，MCP 侧只传业务参数。

### 3.3 健康检查

HTTP 模式下 `GET /health` 返回 `{"status": "ok", "service": "Douyin Crawler MCP"}`；
后端可用性用 `GET /api/v1/utils/health-check/`（对应工具 `utils_health_check`）。

## 4. 鉴权与会话

1. 网关首次调用工具时用 `MCP_API_USERNAME/PASSWORD` 调 `/login/access-token` 拿 token 并缓存；
2. 之后每个请求带 `Authorization: Bearer <token>`；
3. 遇到 401/403 会清空 token 重新登录并**重试一次**；
4. token 只在网关进程内存里，不落库、不写日志。

模型侧不需要、也无法读取 token；工具参数里没有任何鉴权字段（`login_access_token`
这个生成工具只在需要自建会话时使用，正常不建议调用）。

## 5. 参数与结果约定

* **参数**：接口工具的参数名 = 接口的路径参数 / 查询参数 / 请求体字段名，类型按
  OpenAPI 映射（`string`→`str`、`integer`→`int`、`boolean`→`bool`、字符串枚举→`Literal`）。
  必填参数没有默认值，选填参数沿用接口默认值。
* **可选参数**：接口未声明默认值的选填字段，在 MCP 侧是「可空可选」（默认 `None`）。
  传 `null` 与不传等价——网关都不会把该字段放进请求体，行为与直接用 HTTP 调用一致。
* **结果**：接口返回 JSON 时，工具返回**同一份 JSON**（字段名与嵌套结构完全一致，
  不做重命名、不做脱敏二次处理——脱敏在业务层完成）。
* **非 JSON 接口**（导出文件、视频文件/预览流、二维码、互动截图）：
  * 图片（二维码、截图）→ 小于 512 KB 时以图片内容块返回，模型可直接「看」；
  * 文本（导出 CSV/SRT/VTT、密码找回 HTML）→ 返回 `{"content_type": ..., "text": ...}`；
  * 二进制（视频文件、预览流）→ 返回元信息信封
    `{"content_type": ..., "size_bytes": ..., "filename": ...}`；
    真正下载请走前端页面或先用预览会话接口拿票据。
* **错误**：接口返回 4xx/5xx 时，工具调用失败并带上接口的 `detail` 文案
  （例如 `任务状态不允许取消`），与前端看到的提示一致。

## 6. 安全与合规约束

| 约束 | 说明 |
| --- | --- |
| 敏感字段不回显 | Cookie、Token、平台原始账号 ID 不落库、不写日志、不出现在响应里；MCP 侧不额外拼接 |
| 互动发送必须人工确认 | 便捷工具只提供 `prepare_douyin_interaction`（创建草稿），发送/取消在 Web 页面由人二次确认。**接口工具里存在 `douyin_interactions_confirm_interaction` 等发送类工具**，仅供受控场景使用，调用前请确认已获得操作授权 |
| 采集合规 | 只允许对自有账号与公开内容做合规采集；不要用它做大规模抓取或平台违规操作 |
| 数据隔离 | 非超管账号只能看到自己 `owner_id` 下的数据；越权访问按 404 处理 |

## 7. 前端如何使用这些接口

前端是 React + Vite，所有请求都通过**自动生成的 TypeScript 客户端**
（`frontend/src/client/`，由 `bun run generate-client` 从同一个 OpenAPI 生成）。
典型调用链：

```ts
// 1) 页面里取数据（TanStack Query + 生成客户端）
const query = useQuery({
  queryKey: ["douyin-tasks", trackId],
  queryFn: () => DouyinService.listTasks({ trackId, limit: 50 }),
})

// 2) 触发动作（mutation → 生成客户端方法）
const promote = useMutation({
  mutationFn: (body: DouyinFollowingsPromoteRequest) =>
    DouyinService.promoteMineFollowings({ requestBody: body }),
})
```

`DouyinService.listTasks` 对应的就是 `GET /api/v1/douyin/tasks`，
因此它和 MCP 工具 `douyin_list_tasks` 是**同一个接口**：

| 层次 | 名称 | 参数 | 返回 |
| --- | --- | --- | --- |
| 前端 | `DouyinService.listTasks({...})` | camelCase 包装（`trackId`） | 生成类型 `DouyinTasksPublic` |
| HTTP | `GET /api/v1/douyin/tasks?track_id=…` | snake_case 查询参数 | 同一份 JSON |
| MCP | `douyin_list_tasks(track_id=…, limit=…)` | snake_case、与接口一致 | 同一份 JSON |

三个名字、一套语义：**MCP 工具名 = 接口 operationId 的蛇形形式**，
前端方法名 = 同一 operationId 去掉服务前缀后的驼峰形式，所以对照表里三者永远同排。

### 7.1 完整对照表（接口 ↔ MCP 工具 ↔ 前端）

下表由 `scripts/generate_mcp_guide.py` 生成（数据来自 OpenAPI 与前端源码），
「调用位置」列出直接调用该 SDK 方法的页面/组件，便于排查前端行为。

<!-- BEGIN GENERATED INVENTORY -->

### 抖音 · 账号与浏览器

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/douyin/accounts` | `douyin_accounts_list_accounts` | skip、limit | `listAccounts` · `src/components/Douyin/BatchCommentDialog.tsx`、`src/components/Douyin/CreateTaskDialog.tsx` 等 11 处 |
| `POST /api/v1/douyin/accounts` | `douyin_accounts_add_account` | **name**、browser_mode（local/remote）、slot、weight、priority、concurrency_limit …共 8 个 | `addAccount` · `src/routes/_layout/douyin-accounts.tsx` |
| `GET /api/v1/douyin/accounts/browser-slots` | `douyin_accounts_list_browser_slots` | — | `listBrowserSlots` · `src/components/Douyin/CreateTaskDialog.tsx`、`src/components/Douyin/InteractionLiveMonitor.tsx` 等 4 处 |
| `DELETE /api/v1/douyin/accounts/by-id/{account_id}` | `douyin_accounts_delete_account` | **account_id** | `deleteAccount` · `src/routes/_layout/douyin-accounts.tsx` |
| `PATCH /api/v1/douyin/accounts/by-id/{account_id}` | `douyin_accounts_edit_account` | **account_id**、name、slot、weight、priority、concurrency_limit …共 9 个 | `editAccount` · `src/routes/_layout/douyin-accounts.tsx` |
| `GET /api/v1/douyin/accounts/by-id/{account_id}/local-browsers` | `douyin_accounts_list_account_local_browsers` | **account_id** | `listAccountLocalBrowsers` · `src/routes/_layout/douyin-accounts.tsx` |
| `PUT /api/v1/douyin/accounts/by-id/{account_id}/local-browsers` | `douyin_accounts_bind_account_local_browsers_route` | **account_id**、slot_names | `bindAccountLocalBrowsersRoute` · `src/routes/_layout/douyin-accounts.tsx` |
| `POST /api/v1/douyin/accounts/by-id/{account_id}/login` | `douyin_accounts_start_account_login` | **account_id** | `startAccountLogin` · `src/routes/_layout/douyin-accounts.tsx`、`src/routes/_layout/douyin-browsers.tsx` |
| `POST /api/v1/douyin/accounts/by-id/{account_id}/verify` | `douyin_accounts_verify_account_login` | **account_id** | `verifyAccountLogin` · `src/routes/_layout/douyin-accounts.tsx` |
| `GET /api/v1/douyin/accounts/local-browsers` | `douyin_accounts_list_local_browsers_route` | — | `listLocalBrowsersRoute` · `src/routes/_layout/douyin-accounts.tsx`、`src/routes/_layout/douyin-browsers.tsx` |
| `POST /api/v1/douyin/accounts/local-browsers` | `douyin_accounts_create_local_browser_route` | label | `createLocalBrowserRoute` · `src/routes/_layout/douyin-browsers.tsx` |
| `DELETE /api/v1/douyin/accounts/local-browsers/{browser_id}` | `douyin_accounts_delete_local_browser_route` | **browser_id** | `deleteLocalBrowserRoute` · `src/routes/_layout/douyin-browsers.tsx` |
| `PATCH /api/v1/douyin/accounts/local-browsers/{browser_id}` | `douyin_accounts_update_local_browser_route` | **browser_id**、label、enabled | `updateLocalBrowserRoute` · `src/routes/_layout/douyin-browsers.tsx` |
| `GET /api/v1/douyin/accounts/pools` | `douyin_accounts_list_pools` | — | `listPools` · `src/components/Douyin/BatchCommentDialog.tsx`、`src/components/Douyin/CreateTaskDialog.tsx` 等 5 处 |
| `POST /api/v1/douyin/accounts/pools` | `douyin_accounts_add_pool` | **name**、description、strategy（least_loaded/round_robin/weighted_round_robin）、max_parallel_accounts、account_ids | `addPool` · `src/routes/_layout/douyin-accounts.tsx` |
| `DELETE /api/v1/douyin/accounts/pools/{pool_id}` | `douyin_accounts_delete_pool` | **pool_id** | `deletePool` · `src/routes/_layout/douyin-accounts.tsx` |
| `PATCH /api/v1/douyin/accounts/pools/{pool_id}` | `douyin_accounts_edit_pool` | **pool_id**、name、description、strategy（least_loaded/round_robin/weighted_round_robin）、max_parallel_accounts、account_ids …共 7 个 | `editPool` · （生成客户端，未见直接调用） |

### 抖音 · 采集任务

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/douyin/tasks` | `douyin_list_tasks` | skip、limit、track_id、source_type（keyword/creator/mixed/task）、source_id | `listTasks` · `src/components/Douyin/OnboardingChecklist.tsx`、`src/hooks/useSmartPolling.ts` 等 9 处 |
| `POST /api/v1/douyin/tasks` | `douyin_create_task` | track_id、crawl_type（search/detail/creator/creator_from_aweme/creator_from_comment/creator_profile）、login_type（qrcode/cookie）、browser_mode（local/remote）、cookies、keywords …共 31 个 | `createTask` · `src/components/Douyin/CreateTaskDialog.tsx` |
| `POST /api/v1/douyin/tasks/bulk-delete` | `douyin_bulk_delete_tasks` | **ids** | `bulkDeleteTasks` · `src/routes/_layout/douyin.tsx` |
| `POST /api/v1/douyin/tasks/bulk-resume` | `douyin_bulk_resume_tasks` | **ids**、task_interval_seconds、account_id | `bulkResumeTasks` · `src/routes/_layout/douyin.tsx` |
| `DELETE /api/v1/douyin/tasks/{task_id}` | `douyin_delete_task` | **task_id** | `deleteTask` · `src/routes/_layout/douyin.tsx` |
| `GET /api/v1/douyin/tasks/{task_id}` | `douyin_get_task` | **task_id** | `getTask` · `src/components/Douyin/InteractionComposerDialog.tsx`、`src/routes/_layout/douyin-library.tsx` 等 3 处 |
| `GET /api/v1/douyin/tasks/{task_id}/actions` | `douyin_list_actions` | **task_id**、skip、limit | `listActions` · `src/components/Douyin/TaskResults.tsx` |
| `GET /api/v1/douyin/tasks/{task_id}/awemes` | `douyin_list_awemes` | **task_id**、sort_by（published_at/liked_count/comment_count/collected_count/fetched_at）、sort_order（asc/desc）、skip、limit | `listAwemes` · `src/components/Douyin/TaskResults.tsx` |
| `POST /api/v1/douyin/tasks/{task_id}/awemes/{aweme_id}/comments/recrawl` | `douyin_recrawl_aweme_comments` | **task_id**、**aweme_id**、browser_mode（local/remote）、cookies、fetch_sub_comments、max_comments_per_aweme …共 10 个 | `recrawlAwemeComments` · `src/components/Douyin/AwemeActions.tsx`、`src/routes/_layout/douyin-library.tsx` |
| `POST /api/v1/douyin/tasks/{task_id}/awemes/{aweme_id}/creator/crawl` | `douyin_crawl_aweme_creator` | **task_id**、**aweme_id**、browser_mode（local/remote）、cookies、max_awemes、fetch_comments …共 13 个 | `crawlAwemeCreator` · （生成客户端，未见直接调用） |
| `GET /api/v1/douyin/tasks/{task_id}/awemes/{aweme_id}/online-preview` | `douyin_preview_online_media` | **task_id**、**aweme_id** | `previewOnlineMedia` · （生成客户端，未见直接调用） |
| `POST /api/v1/douyin/tasks/{task_id}/awemes/{aweme_id}/online-preview-session` | `douyin_create_online_preview_session` | **task_id**、**aweme_id** | `createOnlinePreviewSession` · （生成客户端，未见直接调用） |
| `POST /api/v1/douyin/tasks/{task_id}/cancel` | `douyin_cancel_task` | **task_id** | `cancelTask` · `src/routes/_layout/douyin_.$taskId.tsx` |
| `GET /api/v1/douyin/tasks/{task_id}/comments` | `douyin_list_comments` | **task_id**、aweme_id、sort_by（published_at/like_count/fetched_at）、sort_order（asc/desc）、skip、limit | `listComments` · `src/components/Douyin/AwemeActions.tsx`、`src/components/Douyin/TaskResults.tsx` 等 3 处 |
| `POST /api/v1/douyin/tasks/{task_id}/exports/comments` | `douyin_export_comments` | **task_id**、**aweme_ids** | `exportComments` · （生成客户端，未见直接调用） |
| `POST /api/v1/douyin/tasks/{task_id}/exports/subtitles` | `douyin_export_subtitles` | **task_id**、**aweme_ids**、format（txt/srt/vtt） | `exportSubtitles` · （生成客户端，未见直接调用） |
| `GET /api/v1/douyin/tasks/{task_id}/media` | `douyin_list_media` | **task_id**、skip、limit | `listMedia` · `src/components/Douyin/MediaPipelinePanel.tsx` |
| `GET /api/v1/douyin/tasks/{task_id}/media-summary` | `douyin_get_media_summary` | **task_id** | `getMediaSummary` · `src/components/Douyin/MediaPipelinePanel.tsx`、`src/components/Douyin/TaskExecutionProgress.tsx` |
| `POST /api/v1/douyin/tasks/{task_id}/media/migrate-to-minio` | `douyin_migrate_media_to_minio` | **task_id**、asset_ids | `migrateMediaToMinio` · `src/components/Douyin/MediaMigrationDialog.tsx` |
| `POST /api/v1/douyin/tasks/{task_id}/media/process` | `douyin_process_media` | **task_id**、media_storage（local/minio）、translate_subtitles、subtitle_only、force_retranslate、transcription_language …共 7 个 | `processMedia` · `src/components/Douyin/ProcessMediaDialog.tsx` |
| `POST /api/v1/douyin/tasks/{task_id}/media/retry` | `douyin_retry_media` | **task_id**、asset_ids、retry_downloads、retry_subtitles、force_retranslate | `retryMedia` · `src/components/Douyin/MediaPipelinePanel.tsx`、`src/components/Douyin/UnifiedWorksPanel.tsx` 等 3 处 |
| `GET /api/v1/douyin/tasks/{task_id}/media/{asset_id}/file` | `douyin_download_media_file` | **task_id**、**asset_id** | `downloadMediaFile` · （生成客户端，未见直接调用） |
| `GET /api/v1/douyin/tasks/{task_id}/media/{asset_id}/preview` | `douyin_preview_media_file` | **task_id**、**asset_id** | `previewMediaFile` · （生成客户端，未见直接调用） |
| `POST /api/v1/douyin/tasks/{task_id}/media/{asset_id}/preview-session` | `douyin_create_media_preview_session` | **task_id**、**asset_id** | `createMediaPreviewSession` · （生成客户端，未见直接调用） |
| `POST /api/v1/douyin/tasks/{task_id}/media/{asset_id}/retranslate` | `douyin_retranslate_media` | **task_id**、**asset_id** | `retranslateMedia` · `src/components/Douyin/MediaPipelinePanel.tsx`、`src/components/Douyin/UnifiedWorksPanel.tsx` 等 3 处 |
| `GET /api/v1/douyin/tasks/{task_id}/qrcode` | `douyin_get_qrcode` | **task_id** | `getQrcode` · （生成客户端，未见直接调用） |
| `POST /api/v1/douyin/tasks/{task_id}/restart` | `douyin_restart_task` | **task_id** | `restartTask` · `src/routes/_layout/douyin.tsx` |
| `POST /api/v1/douyin/tasks/{task_id}/resume` | `douyin_resume_task` | **task_id**、resume_crawl、resume_media、cookies、account_id、task_interval_seconds | `resumeTask` · `src/components/Douyin/ResumeTaskDialog.tsx` |
| `GET /api/v1/douyin/tasks/{task_id}/shards` | `douyin_list_task_shards` | **task_id** | `listTaskShards` · `src/routes/_layout/douyin_.$taskId.tsx` |
| `GET /api/v1/douyin/tasks/{task_id}/works` | `douyin_list_works` | **task_id**、search、tag_id、download_status、subtitle_status、storage_backend …共 10 个 | `listWorks` · `src/components/Douyin/UnifiedWorksPanel.tsx`、`src/routes/_layout/douyin_.$taskId.feed.tsx` |
| `GET /api/v1/douyin/tasks/{task_id}/works/{aweme_id}` | `douyin_get_work` | **task_id**、**aweme_id** | `getWork` · （生成客户端，未见直接调用） |

### 抖音 · 下载与字幕任务

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/douyin/media-tasks` | `douyin_list_media_tasks` | skip、limit、track_id | `listMediaTasks` · `src/components/Douyin/MediaTaskManagement.tsx` |
| `POST /api/v1/douyin/media-tasks/process` | `douyin_process_media_tasks` | media_storage（local/minio）、translate_subtitles、subtitle_only、force_retranslate、transcription_language、cookies …共 7 个 | `processMediaTasks` · `src/components/Douyin/BatchProcessMediaDialog.tsx` |

### 抖音 · 视频资源库

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/douyin/library/creators` | `douyin_list_library_creators` | task_id、track_id、category_id、search、limit、download_status（all/missing/queued/downloading/downloaded/failed） | `listLibraryCreators` · `src/routes/_layout/douyin-library.tsx` |
| `POST /api/v1/douyin/library/media/migrate-to-minio` | `douyin_migrate_library_media_to_minio` | search、task_id、track_id、creator_hash、tag_id、subtitle_status（all/pending/running/completed/failed） | `migrateLibraryMediaToMinio` · `src/routes/_layout/douyin-library.tsx` |
| `GET /api/v1/douyin/library/works` | `douyin_list_library_works` | search、task_id、track_id、source_type（keyword/creator/mixed/task）、source_id、group_by（work/task） …共 16 个 | `listLibraryWorks` · `src/routes/_layout/douyin-creators_.$creatorId.tsx`、`src/routes/_layout/douyin-library.feed.tsx` 等 4 处 |

### 抖音 · 达人名单

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/douyin/creators/` | `douyin_creators_list_creators` | search、track_id、category_id、status（unprocessed/active/crawled/failed）、enabled、profile_status（synced/pending/failed） …共 10 个 | `listCreators` · `src/components/Douyin/AwemeActions.tsx`、`src/components/Douyin/CreateTaskDialog.tsx` 等 4 处 |
| `POST /api/v1/douyin/creators/batch-tasks` | `douyin_creators_create_creator_tasks` | **creator_ids**、track_id、mode、login_type（qrcode/cookie）、browser_mode（local/remote）、cookies …共 26 个 | `createCreatorTasks` · （生成客户端，未见直接调用） |
| `POST /api/v1/douyin/creators/bulk` | `douyin_creators_bulk_create_creators` | **creators**、track_id、notes、enabled | `bulkCreateCreators` · `src/components/Douyin/CreateTaskDialog.tsx`、`src/routes/_layout/douyin-creators.tsx` |
| `POST /api/v1/douyin/creators/bulk-delete` | `douyin_creators_bulk_delete_creators` | **ids** | `bulkDeleteCreators` · `src/routes/_layout/douyin-creators.tsx`、`src/routes/_layout/douyin-mine.tsx` |
| `DELETE /api/v1/douyin/creators/by-id/{creator_id}` | `douyin_creators_delete_creator` | **creator_id** | `deleteCreator` · `src/routes/_layout/douyin-creators.tsx`、`src/routes/_layout/douyin-mine.tsx` |
| `GET /api/v1/douyin/creators/by-id/{creator_id}` | `douyin_creators_get_creator` | **creator_id** | `getCreator` · `src/routes/_layout/douyin-creators_.$creatorId.tsx` |
| `PATCH /api/v1/douyin/creators/by-id/{creator_id}` | `douyin_creators_edit_creator` | **creator_id**、nickname、track_id、enabled、notes、sec_uid | `editCreator` · `src/components/Douyin/CreatorCard.tsx`、`src/routes/_layout/douyin-creators.tsx` 等 4 处 |
| `GET /api/v1/douyin/creators/by-id/{creator_id}/tasks` | `douyin_creators_list_creator_tasks` | **creator_id** | `listCreatorTasks` · `src/routes/_layout/douyin-creators_.$creatorId.tsx` |
| `POST /api/v1/douyin/creators/profiles/sync` | `douyin_creators_sync_creator_profiles` | creator_ids、account_id、limit、only_missing | `syncCreatorProfiles` · `src/routes/_layout/douyin-creators.tsx`、`src/routes/_layout/douyin-creators_.$creatorId.tsx` |
| `POST /api/v1/douyin/creators/sync/awemes` | `douyin_creators_sync_creators_from_awemes` | — | `syncCreatorsFromAwemes` · `src/routes/_layout/douyin-creators.tsx` |
| `POST /api/v1/douyin/creators/sync/history` | `douyin_creators_sync_historical_creators` | — | `syncHistoricalCreators` · `src/routes/_layout/douyin-creators.tsx` |
| `POST /api/v1/douyin/creators/sync/tasks/{task_id}` | `douyin_creators_sync_creators_from_task` | **task_id** | `syncCreatorsFromTask` · （生成客户端，未见直接调用） |

### 抖音 · 关键词

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/douyin/keywords/` | `douyin_keywords_list_keywords` | search、track_id、category、status（unprocessed/active/crawled/failed）、enabled、sort_by（keyword/status/task_count/aweme_count/last_crawled_at/created_at） …共 9 个 | `listKeywords` · `src/components/Douyin/OnboardingChecklist.tsx`、`src/routes/_layout/douyin-keywords.tsx` 等 3 处 |
| `POST /api/v1/douyin/keywords/batch-tasks` | `douyin_keywords_create_keyword_tasks` | **keyword_ids**、track_id、mode（combined/separate）、login_type（qrcode/cookie）、browser_mode（local/remote）、start_page …共 25 个 | `createKeywordTasks` · `src/routes/_layout/douyin-keywords.tsx` |
| `POST /api/v1/douyin/keywords/bulk` | `douyin_keywords_bulk_create_keywords` | **keywords**、track_id、notes、category、enabled | `bulkCreateKeywords` · `src/routes/_layout/douyin-keywords.tsx` |
| `POST /api/v1/douyin/keywords/bulk-delete` | `douyin_keywords_bulk_delete_keywords` | **ids** | `bulkDeleteKeywords` · `src/routes/_layout/douyin-keywords.tsx`、`src/routes/_layout/douyin-tracks_.$trackId.tsx` |
| `DELETE /api/v1/douyin/keywords/by-id/{keyword_id}` | `douyin_keywords_delete_keyword` | **keyword_id** | `deleteKeyword` · `src/routes/_layout/douyin-keywords.tsx` |
| `PATCH /api/v1/douyin/keywords/by-id/{keyword_id}` | `douyin_keywords_edit_keyword` | **keyword_id**、keyword、track_id、enabled、category、notes | `editKeyword` · `src/routes/_layout/douyin-keywords.tsx`、`src/routes/_layout/douyin-tracks_.$trackId.tsx` |
| `GET /api/v1/douyin/keywords/by-id/{keyword_id}/tasks` | `douyin_keywords_list_keyword_tasks` | **keyword_id** | `listKeywordTasks` · `src/routes/_layout/douyin-keywords.tsx` |
| `POST /api/v1/douyin/keywords/sync/history` | `douyin_keywords_sync_historical_keywords` | — | `syncHistoricalKeywords` · `src/routes/_layout/douyin-keywords.tsx` |
| `POST /api/v1/douyin/keywords/sync/tasks/{task_id}` | `douyin_keywords_sync_keywords_from_task` | **task_id** | `syncKeywordsFromTask` · `src/routes/_layout/douyin.tsx` |

### 抖音 · 赛道

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/douyin/tracks` | `douyin_tracks_list_tracks` | search、enabled、skip、limit | `listTracks` · `src/components/Douyin/OnboardingChecklist.tsx`、`src/components/Douyin/TrackSelect.tsx` 等 3 处 |
| `POST /api/v1/douyin/tracks` | `douyin_tracks_add_track` | **name**、description、prompt、keywords、default_task_config、reply_templates …共 7 个 | `addTrack` · `src/routes/_layout/douyin-tracks.tsx` |
| `POST /api/v1/douyin/tracks/bulk-delete` | `douyin_tracks_bulk_delete_tracks` | **ids** | `bulkDeleteTracks` · （生成客户端，未见直接调用） |
| `DELETE /api/v1/douyin/tracks/{track_id}` | `douyin_tracks_delete_track` | **track_id** | `deleteTrack` · `src/routes/_layout/douyin-tracks.tsx` |
| `GET /api/v1/douyin/tracks/{track_id}` | `douyin_tracks_get_track` | **track_id** | `getTrack` · `src/components/Douyin/BatchProcessMediaDialog.tsx`、`src/components/Douyin/InteractionComposerDialog.tsx` 等 6 处 |
| `PATCH /api/v1/douyin/tracks/{track_id}` | `douyin_tracks_edit_track` | **track_id**、name、description、prompt、enabled、default_task_config …共 8 个 | `editTrack` · `src/routes/_layout/douyin-tracks.tsx`、`src/routes/_layout/douyin-tracks_.$trackId.tsx` |
| `GET /api/v1/douyin/tracks/{track_id}/creators` | `douyin_tracks_list_track_creators` | **track_id** | `listTrackCreators` · `src/routes/_layout/douyin-tracks.tsx`、`src/routes/_layout/douyin-tracks_.$trackId.tsx` |
| `POST /api/v1/douyin/tracks/{track_id}/creators` | `douyin_tracks_append_track_creators` | **track_id**、**creators** | `appendTrackCreators` · `src/routes/_layout/douyin-tracks_.$trackId.tsx` |
| `DELETE /api/v1/douyin/tracks/{track_id}/creators/{creator_id}` | `douyin_tracks_remove_track_creator` | **track_id**、**creator_id** | `removeTrackCreator` · `src/routes/_layout/douyin-tracks_.$trackId.tsx` |
| `GET /api/v1/douyin/tracks/{track_id}/keywords` | `douyin_tracks_list_track_keywords` | **track_id** | `listTrackKeywords` · `src/routes/_layout/douyin-tracks.tsx`、`src/routes/_layout/douyin-tracks_.$trackId.tsx` |
| `POST /api/v1/douyin/tracks/{track_id}/keywords` | `douyin_tracks_append_track_keywords` | **track_id**、**keywords** | `appendTrackKeywords` · `src/routes/_layout/douyin-tracks.tsx`、`src/routes/_layout/douyin-tracks_.$trackId.tsx` |
| `DELETE /api/v1/douyin/tracks/{track_id}/keywords/{keyword_id}` | `douyin_tracks_remove_track_keyword` | **track_id**、**keyword_id** | `removeTrackKeyword` · `src/routes/_layout/douyin-tracks_.$trackId.tsx` |
| `POST /api/v1/douyin/tracks/{track_id}/reset` | `douyin_tracks_reset_track` | **track_id** | `resetTrack` · `src/routes/_layout/douyin-tracks_.$trackId.tsx` |
| `POST /api/v1/douyin/tracks/{track_id}/tasks` | `douyin_tracks_create_track_tasks` | **track_id**、mode（combined/separate）、start_page、max_awemes、fetch_comments、fetch_sub_comments …共 27 个 | `createTrackTasks` · `src/routes/_layout/douyin-tracks.tsx` |

### 抖音 · 内容分类

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/douyin/categories` | `douyin_list_categories_route` | — | `douyinListCategoriesRoute` · （生成客户端，未见直接调用） |
| `POST /api/v1/douyin/categories` | `douyin_create_category_route` | **name**、parent_id、description、sort_order | `douyinCreateCategoryRoute` · （生成客户端，未见直接调用） |
| `DELETE /api/v1/douyin/categories/{category_id}` | `douyin_delete_category_route` | **category_id** | `douyinDeleteCategoryRoute` · （生成客户端，未见直接调用） |
| `PATCH /api/v1/douyin/categories/{category_id}` | `douyin_update_category_route` | **category_id**、name、parent_id、description、sort_order | `douyinUpdateCategoryRoute` · （生成客户端，未见直接调用） |
| `DELETE /api/v1/douyin/categories/{category_id}/items` | `douyin_unassign_category_items_route` | **category_id**、aweme_ids、creator_ids | `douyinUnassignCategoryItemsRoute` · （生成客户端，未见直接调用） |
| `POST /api/v1/douyin/categories/{category_id}/items` | `douyin_assign_category_items_route` | **category_id**、aweme_ids、creator_ids | `douyinAssignCategoryItemsRoute` · （生成客户端，未见直接调用） |

### 抖音 · 我的（关注/点赞/收藏）

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/douyin/my/awemes` | `douyin_get_mine_awemes` | **account_id**、kind（liked/collected）、search、sort_by（fetched_at/liked_count/published_at）、sort_order（asc/desc）、skip …共 7 个 | `douyinGetMineAwemes` · （生成客户端，未见直接调用） |
| `GET /api/v1/douyin/my/followings` | `douyin_get_mine_followings` | **account_id**、search、sort_by（fetched_at/follower_count/nickname/profile_synced_at/aweme_total_count）、sort_order（asc/desc）、skip、limit | `douyinGetMineFollowings` · （生成客户端，未见直接调用） |
| `POST /api/v1/douyin/my/followings/profile-sync` | `douyin_sync_mine_followings_profiles` | **account_id**、following_ids、track_id、notes、limit、only_missing | `douyinSyncMineFollowingsProfiles` · （生成客户端，未见直接调用） |
| `POST /api/v1/douyin/my/followings/to-creators` | `douyin_promote_mine_followings` | **account_id**、track_id、notes、following_ids、search、limit | `douyinPromoteMineFollowings` · （生成客户端，未见直接调用） |
| `GET /api/v1/douyin/my/summary` | `douyin_get_mine_summary` | **account_id** | `douyinGetMineSummary` · （生成客户端，未见直接调用） |

### 抖音 · 互动

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/douyin/interactions` | `douyin_interactions_list_interactions` | task_id、track_id、aweme_id、interaction_type（video_comment/comment_reply/creator_message）、status（pending_confirmation/queued/running/succeeded/failed/blocked）、source_type（keyword/creator/mixed/task） …共 9 个 | `listInteractions` · `src/components/Douyin/TaskInteractionsPanel.tsx`、`src/routes/_layout/douyin-interactions.tsx` 等 3 处 |
| `POST /api/v1/douyin/interactions` | `douyin_interactions_prepare_interaction` | **task_id**、**aweme_id**、**account_id**、**interaction_type**（video_comment/comment_reply/creator_message）、target_comment_id、**content** | `prepareInteraction` · `src/components/Douyin/InteractionComposerDialog.tsx` |
| `POST /api/v1/douyin/interactions/batch-comments` | `douyin_interactions_create_batch_comments` | **targets**、**comments**、mode（one_per_video/all_per_video）、account_id、account_pool_id、account_strategy（least_loaded/round_robin/weighted_round_robin） …共 9 个 | `createBatchComments` · `src/components/Douyin/BatchCommentDialog.tsx` |
| `POST /api/v1/douyin/interactions/preflight` | `douyin_interactions_preflight_interaction` | **task_id**、**aweme_id**、**account_id**、**interaction_type**（video_comment/comment_reply/creator_message）、target_comment_id、**content** | `preflightInteraction` · `src/components/Douyin/InteractionComposerDialog.tsx` |
| `GET /api/v1/douyin/interactions/quota` | `douyin_interactions_list_interaction_quota` | — | `listInteractionQuota` · `src/components/Douyin/InteractionComposerDialog.tsx` |
| `GET /api/v1/douyin/interactions/{interaction_id}` | `douyin_interactions_get_interaction` | **interaction_id** | `getInteraction` · `src/components/Douyin/InteractionLiveMonitor.tsx`、`src/routes/_layout/douyin-interactions.tsx` |
| `POST /api/v1/douyin/interactions/{interaction_id}/cancel` | `douyin_interactions_cancel_interaction` | **interaction_id** | `cancelInteraction` · `src/components/Douyin/TaskInteractionsPanel.tsx`、`src/routes/_layout/douyin-interactions.tsx` |
| `POST /api/v1/douyin/interactions/{interaction_id}/confirm` | `douyin_interactions_confirm_interaction` | **interaction_id** | `confirmInteraction` · `src/components/Douyin/InteractionComposerDialog.tsx`、`src/components/Douyin/TaskInteractionsPanel.tsx` 等 3 处 |
| `GET /api/v1/douyin/interactions/{interaction_id}/events/{event_id}/screenshot` | `douyin_interactions_get_interaction_event_screenshot` | **interaction_id**、**event_id** | `getInteractionEventScreenshot` · （生成客户端，未见直接调用） |
| `POST /api/v1/douyin/interactions/{interaction_id}/retry` | `douyin_interactions_retry_interaction` | **interaction_id**、confirm_not_sent | `retryInteraction` · `src/components/Douyin/TaskInteractionsPanel.tsx`、`src/routes/_layout/douyin-interactions.tsx` |

### 抖音 · 评论管理

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/douyin/comments` | `douyin_list_comment_library` | comment_content、search、task_id、track_id、aweme_id、video_creator …共 19 个 | `listCommentLibrary` · `src/routes/_layout/douyin-comments.tsx`、`src/routes/_layout/douyin-library_.video.$awemeId.tsx` |
| `POST /api/v1/douyin/comments/export` | `douyin_export_comment_selection` | **comment_ids** | `exportCommentSelection` · （生成客户端，未见直接调用） |

### 抖音 · 标签

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/douyin/tags/` | `douyin_tags_list_tags` | search、task_id、track_id、sort_by（name/aweme_count/task_count/last_seen_at）、sort_order（asc/desc）、skip …共 7 个 | `listTags` · `src/components/Douyin/UnifiedWorksPanel.tsx`、`src/routes/_layout/douyin-library.tsx` 等 3 处 |
| `POST /api/v1/douyin/tags/sync` | `douyin_tags_sync_tags` | — | `syncTags` · `src/routes/_layout/douyin-tags.tsx` |

### 抖音 · 请求日志

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/douyin/request-logs` | `douyin_list_request_logs` | task_id、method、path、response_status、created_from、created_to …共 8 个 | `douyinListRequestLogs` · （生成客户端，未见直接调用） |

### 抖音 · 界面文案

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/douyin/ui-labels` | `douyin_ui_get_ui_labels` | — | `getUiLabels` · `src/hooks/useAccountStatusLabels.ts` |

### 抖音 · 来源筛选

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/douyin/source-options` | `douyin_list_source_options` | track_id | `listSourceOptions` · `src/components/Douyin/SourceSelect.tsx` |

### 用户与账号

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/users/` | `users_read_users` | skip、limit | `readUsers` · `src/routes/_layout/admin.tsx` |
| `POST /api/v1/users/` | `users_create_user` | **email**、is_active、is_superuser、full_name、**password** | `createUser` · `src/components/Admin/AddUser.tsx` |
| `DELETE /api/v1/users/me` | `users_delete_user_me` | — | `deleteUserMe` · `src/components/UserSettings/DeleteConfirmation.tsx` |
| `GET /api/v1/users/me` | `users_read_user_me` | — | `readUserMe` · `src/routes/_layout/admin.tsx`、`src/routes/_layout/developer-tools.tsx` |
| `PATCH /api/v1/users/me` | `users_update_user_me` | full_name、email | `updateUserMe` · `src/components/UserSettings/UserInformation.tsx` |
| `PATCH /api/v1/users/me/password` | `users_update_password_me` | **current_password**、**new_password** | `updatePasswordMe` · `src/components/UserSettings/ChangePassword.tsx` |
| `POST /api/v1/users/signup` | `users_register_user` | **email**、**password**、full_name | `registerUser` · `src/hooks/useAuth.ts` |
| `DELETE /api/v1/users/{user_id}` | `users_delete_user` | **user_id** | `deleteUser` · `src/components/Admin/DeleteUser.tsx` |
| `GET /api/v1/users/{user_id}` | `users_read_user_by_id` | **user_id** | `readUserById` · （生成客户端，未见直接调用） |
| `PATCH /api/v1/users/{user_id}` | `users_update_user` | **user_id**、email、is_active、is_superuser、full_name、password | `updateUser` · `src/components/Admin/EditUser.tsx` |

### 登录与密码

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `POST /api/v1/login/access-token` | `login_login_access_token` | — | `loginAccessToken` · `src/hooks/useAuth.ts` |
| `POST /api/v1/login/test-token` | `login_test_token` | — | `testToken` · （生成客户端，未见直接调用） |
| `POST /api/v1/password-recovery-html-content/{email}` | `login_recover_password_html_content` | **email** | `recoverPasswordHtmlContent` · （生成客户端，未见直接调用） |
| `POST /api/v1/password-recovery/{email}` | `login_recover_password` | **email** | `recoverPassword` · `src/routes/recover-password.tsx` |
| `POST /api/v1/reset-password/` | `login_reset_password` | **token**、**new_password** | `resetPassword` · `src/routes/reset-password.tsx` |

### 示例 Items

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/items/` | `items_read_items` | skip、limit | `readItems` · `src/routes/_layout/items.tsx` |
| `POST /api/v1/items/` | `items_create_item` | **title**、description | `createItem` · `src/components/Items/AddItem.tsx` |
| `DELETE /api/v1/items/{id}` | `items_delete_item` | **id** | `deleteItem` · `src/components/Items/DeleteItem.tsx` |
| `GET /api/v1/items/{id}` | `items_read_item` | **id** | `readItem` · （生成客户端，未见直接调用） |
| `PUT /api/v1/items/{id}` | `items_update_item` | **id**、title、description | `updateItem` · `src/components/Items/EditItem.tsx` |

### 系统管理

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/system/integrations/` | `system_integrations_get_integration_docs` | — | `getIntegrationDocs` · `src/routes/_layout/developer-tools.tsx` |

### 运维工具

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `GET /api/v1/utils/health-check/` | `utils_health_check` | — | `healthCheck` · `src/routes/_layout.tsx` |
| `POST /api/v1/utils/test-email/` | `utils_test_email` | **email_to** | `testEmail` · （生成客户端，未见直接调用） |

### 本地私有路由

| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |
| --- | --- | --- | --- |
| `POST /api/v1/private/users/` | `private_create_user` | **email**、**password**、**full_name**、is_verified | `createUser` · `src/components/Admin/AddUser.tsx` |

合计 **140** 个接口 / 工具（另有 32 个参数经过裁剪的便捷工具，见指南正文「两套工具」一节）。

<!-- END GENERATED INVENTORY -->

## 8. 常用场景（自然语言 → 工具）

| 你想做的事 | 建议工具序列 |
| --- | --- |
| 看某赛道的采集任务与产出 | `list_douyin_tracks` → `douyin_list_tasks` / `list_douyin_tasks` → `list_douyin_works` |
| 抓一批关键词 | `douyin_keywords_bulk_create_keywords`（建词）→ `douyin_keywords_create_keyword_tasks`（每个词一个任务）→ `douyin_get_task` 轮询 |
| 抓某达人的作品 | `douyin_creators_bulk_create_creators`（加名单）→ `douyin_creators_create_creator_tasks` → `douyin_get_task` |
| 由一条评论找评论者并采集其作品 | `douyin_create_task`（`crawl_type=creator_from_comment` + `comment_targets=[{aweme_id, comment_id}]`；任务执行时实时反查评论者，原始账号标识不落库） |
| 给任务补视频与字幕 | `douyin_process_media`（单任务，可指定存储/语言）或 `douyin_process_media_tasks`（多任务同配置）→ `douyin_get_media_summary` 看进度 |
| 看字幕正文 / 重做字幕 | `douyin_list_media`（含字幕正文）→ `douyin_retranslate_media`（单条） / `douyin_retry_media`（失败项） |
| 素材入库与迁移 | `list_douyin_works` → `douyin_migrate_media_to_minio` 或 `douyin_migrate_library_media_to_minio` |
| 账号登录与体检 | `douyin_accounts_start_account_login`（出二维码）→ `douyin_get_qrcode`（看图，需人工扫码）→ `douyin_accounts_verify_account_login` |
| 互动（评论/私信） | `prepare_douyin_interaction` 建草稿 → **在 Web 页面确认发送**（接口工具里的 confirm 仅供受控场景） |
| 我的关注/点赞/收藏 | `douyin_get_mine_summary` → `douyin_get_mine_followings` / `douyin_get_mine_awemes` → `douyin_promote_mine_followings`（进达人名单）→ `douyin_sync_mine_followings_profiles`（清洗主页信息） |

## 9. 如何再生成与校验

```bash
# 1) 刷新后端 OpenAPI 快照
uv run python -c "import crawler.api.main, json, pathlib; \
  pathlib.Path('frontend/openapi.json').write_text(json.dumps(crawler.api.main.app.openapi()), encoding='utf-8')"

# 2) 重新生成 MCP 工具规格（新增/修改接口后必须执行）
uv run python scripts/generate_mcp_tools.py

# 3) 刷新本指南的对照表
uv run python scripts/generate_mcp_guide.py

# 4) 校验覆盖率与契约（会同时校验 OpenAPI / MCP 工具 / 路由顺序的哈希基线）
uv run pytest tests/architecture -q
```

改动接口后如果契约测试报「工具数/哈希不一致」，按提示更新
`tests/architecture/test_behavior_contracts.py` 里的 `EXPECTED_MCP_TOOLS` 与
`EXPECTED_MCP_TOOLS_SHA256`，并在注释里说明本次变更。
