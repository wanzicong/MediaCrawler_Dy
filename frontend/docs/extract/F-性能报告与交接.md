# F · 性能报告与交接

> 来源：`docs/前端项目分析.md` 第 **42000–47767** 行（Claude Code 会话导出，共 75,392 行）。
> 主题：MediaCrawler_Dy_V2 前端（抖音采集运营工作台）性能与卡顿分析 + 最终交付报告 + 交接 prompt。
> 技术栈：React 19 + TypeScript + Vite 7 + Tailwind v4 + TanStack Router / Query。
> 说明：该区间原文被「思考过程」与「工具调用 JSON」按行交错污染，本文件只抽取实质信息，不收录思考推演、工具参数原文、被读取文件原文、重复的《项目开发约定》。
> **第 47660–47766 行的《抖音采集工作台 · 性能与卡顿分析报告》为逐条完整抄录，未合并、未压缩、量化数字全部保留。**

---

## 背景与数据来源

- **[结论]** 47656 — 前端 `refactor/uv-workspace-modules` 分支与 `dev` 分支仅差 5 行（`login.tsx` 4 行 + `tsconfig.json` 1 行），性能结论跨分支通用 | 报告结论对两个分支均成立
- **[结论]** 47554 — 数据来源：**6 组缺陷审查**（212 条原始，去重后 高 22 / 中 48 / 低 60+）+ **Agent A 渲染性能 24 条** + **Agent B 网络/主线程/内存 23 条** | 最终报告的全部素材
- **[结论]** 47565 — 性能问题 = Agent A 24 条 + Agent B 23 条 = **47 条**，去重合并后约 40 条 | 去重口径
- **[结论]** 47571-47579 — 去重映射：轮询无暂停 A#5 ↔ B#5/6/11/19/20；selected 数组 includes A#2/6/18；每行重组件 A#1/9；未 memo A#3/7/8/10-15/19-24；串行循环 B#9/10；全量加载 B#1/2/3/18；无防抖 B#7/8；iframe 重挂载 B#14/15；大列表无虚拟滚动 B#16/17 | 去重依据
- **[结论]** 47656 — 缺陷 212 条 + 性能 47 条合并去重后输出最终报告 | 交付规模
- **[结论]** 47546/47594 — 工作区（dev）与 refactor/uv-workspace-modules 前端代码几乎一致，已确认仅差 5 行 | 无需重跑审查

---

## P0

### 最终报告 · P0 卡死 / 崩溃级（原文 47676-47685，共 4 条）

- **[性能]** `douyin-comments.tsx:987-1010` — 导出评论（>1万条）：`while` 串行 100 次请求 + 主线程拼 5-10MB 字符串 | **卡死 20-50s**
- **[性能]** `douyin-library.tsx:420-447` — 导出字幕（>500 条带字幕）：串行拉取 + 拼接 25-50MB 字符串，主线程阻塞 5-15s | **低端设备 OOM**
- **[性能]** `douyin-interactions.tsx:161-185` — 重试全部可重试项（>500 条）：`do-while` 全量拉取 + `Promise.allSettled` 500 个并发请求 | **前端卡死 + 后端连接池耗尽**
- **[性能]** `douyin-interactions.tsx:652-691` — 打开互动详情（含 50+ 截图事件）：每个截图事件 `useEffect` 内并发 `fetch` + `createObjectURL` | **瞬间 50 个并发请求 + 内存 spike**
- **[结论]** 47685 — P0 根因：前端承担了应由后端完成的批量/流式职责；修复方向均为「改后端流式/批量接口，前端只下载」 | P0 统一修复方向

### 中间报告 · P0（原文 47307-47363，共 3 条；与上方 P0-1/2/3 逐字对应，已在上方出现）

- **[性能]** `routes/_layout/douyin-comments.tsx:987-1010` — P0-1 评论导出：前端全量分页拉取 + 主线程拼接巨大字符串。`exportTxt` 用 `while (items.length < total)` 循环分页拉取全部评论到前端数组，再用 `items.map((field) => txt.Cell(...)).join("\t")` 在主线程拼接成单个字符串；虽有 1000 条确认提示（:979），但确认后仍全量拉取并拼接。触发场景：评论管理页 → 导出筛选结果 → 命中数千~数万条评论。量化影响：**1 万条评论 = 100 次分页请求（串行）+ 主线程拼接 ~5-10MB 字符串，主线程阻塞 2-5s，页面冻结无响应**。建议改为后端流式导出接口（已有 `downloadComments` 走后端 :1168，应统一用后端导出），或用 Web Worker 拼接 + Blob 分片写入 | （已在最终报告 P0-1 出现）
- **[性能]** `routes/_layout/douyin-library.tsx:420-447` — P0-2 字幕导出：前端全量分页拉取 + 主线程拼接巨大字符串。`exportSubtitles` 用 `while (works.length < total)` 全量拉取作品，再 `blocks.join("\n\n")` 拼接所有字幕全文（:447），字幕全文可能每条数 KB。触发场景：视频资源库 → 导出字幕 → 命中数千条带字幕作品。量化影响：**5000 条字幕 = 50 次分页请求 + 拼接 ~20-50MB 字符串，主线程阻塞数秒，大字幕可能触发浏览器 OOM**。建议同 P0-1 改后端流式导出 | （已在最终报告 P0-2 出现）
- **[性能]** `routes/_layout/douyin-interactions.tsx:161-185` — P0-3 互动重试全部：全量分页拉取 + `Promise.allSettled` 无上限并发。`retryAll` 用 `do-while` 全量分页拉取所有互动任务（161-171），再用 `Promise.allSettled(candidates.map(...))` 对所有候选同时发起重试请求（:178-185），无并发上限。触发场景：互动任务页 → 「重试全部可重试项」→ 有数百条失败互动任务。量化影响：**500 条候选 = 5 次分页拉取 + 500 个并发 HTTP 请求瞬间发出，浏览器连接数耗尽（Chrome 上限 6/域名），后端被打满，前端 Promise 堆积内存激增**。建议改为后端批量重试接口（类似 `bulkResumeTasks` 的设计），或前端用并发池（p-limit 模式，上限 5-10） | （已在最终报告 P0-3 出现）
- **[结论]** 47307 — 中间报告 P0 段标题为「🔴 极严重（会导致页面卡死或浏览器崩溃）」；该段只列出 P0-1/P0-2/P0-3 三条，**P0-4（互动证据截图）是最终报告新增的第 4 条** | 说明 P0-4 为最终报告补齐

---

## P1

### 最终报告 · P1 高频轮询必现卡顿（原文 47687-47697，共 7 条）

- **[性能]** `UnifiedWorksPanel.tsx:694-942` — **每行挂载 ≈13 个 hook 实例**（AwemeActions 含 useQuery + 2 useMutation + 2 个 InteractionComposerDialog 各 4 useQuery + CommentsDialog + VideoPreviewDialog）。20 行 ≈ **260 个 observer** | 卡顿场景：`worksQuery` 每 2s 轮询新引用触发整组件重渲染，260 实例全部重执行 hook 逻辑，任务运行中打开「作品数据」tab **持续卡顿**
- **[性能]** `UnifiedWorksPanel.tsx:646,794,829` + `douyin-creators.tsx:375` + `CreateTaskDialog.tsx:466` — `selected` 用 `string[]` + `.includes()` 每行 O(n)。creators 页 200 行 × 选中 50 = **10000 次数组扫描/每 10s** | 任何勾选 + 轮询重渲染时，列表滚动/勾选明显掉帧
- **[性能]** `Sidebar/Main.tsx:33` — `useRouterState()` **无 select**，全量订阅 router state | 资源库页切任何筛选（URL search 变化）→ 整个侧边栏所有菜单项无差别重渲染
- **[性能]** `InteractionLiveMonitor.tsx:68,74` — detail **1s** + slots **2s** 双高频轮询，事件列表 `events.map` 全量渲染 | 打开实时监控后每秒 1 次重渲染 × N 个事件 DOM diff，低端设备掉帧
- **[性能]** `UnifiedWorksPanel.tsx:224-262` — render 体 **8 处未 memo** 派生计算（pageIds/selectedWorks/selectedAssets/lastMediaActivity 含 `new Date()` 比较…），仅 failedAssets memo 了 | 每 2s 轮询全部重算，`lastMediaActivity` 每行 new Date 两次
- **[性能]** `douyin-library.tsx:284-299` — render 体 **8 次遍历**（pageAwemeIds/selectedRows/allPageSelected/pageLocal/pageMinio/pageUndownloaded/hasPlayableRows） | 每 5s 轮询 32 行 × 8 次 = 256 次操作
- **[性能]** `main.tsx:39-46` — **QueryClient 无 defaultOptions**：全局 `staleTime=0` + `refetchIntervalInBackground=true` | 每次路由切换/refocus 触发 5-15 个 query 重新请求；切后台仍轮询。**一行修复可缓解 10+ 问题**

### 中间编号清单 · 🔴 严重（高频轮询场景下必现卡顿）第 1-6 条（原文 42340-45368）

- **[性能]** `components/Douyin/UnifiedWorksPanel.tsx:694-942` — 第 1 条（最严重）：每行挂载重组件 + useQuery 实例。每行挂载 `<WorkQuickActions>`（内含 `AwemeActions`：1 个 useQuery + 2 个 useMutation + useCustomToast + useNavigate + 2 个 `InteractionComposerDialog`，每个 Dialog 含 4 个 useQuery）、`<CommentsDialog>`（含 1 个 useQuery）、`<VideoPreviewDialog>`（含 useEffect + useState）；一页 20 行 = **20 × (约 13 个 hook 实例) ≈ 260 个 observer/状态实例** | `worksQuery` 有 `refetchInterval: active ? 2_000 : 5_000`（Line 141），每 2s 轮询新引用触发整组件重渲染，20 行子组件全部重执行 hook 逻辑，任务运行中打开「作品数据」标签页持续卡顿。建议 React.memo 包裹行组件 + 稳定 props，或改单实例 + 选中行 id 驱动（已在最终报告 P1-1 出现）
- **[性能]** `components/Douyin/UnifiedWorksPanel.tsx:646, 794, 829` — 第 2 条：`selected` 用 `string[]` + `.includes()`，单行 O(selected.length)；配合 Line 226 `pageIds.every((id) => selected.includes(id))`、Line 227-229 `rows.filter((row) => selected.includes(...))`，全页复杂度 **O(行数 × selected.length)** | 每 2s 轮询重渲染时 20 行 × 已选数量次 includes，选中半页（10 条）时每 2s 做 200 次数组扫描。建议改 `Set<string>`（`douyinSets.ts:114` 已是正确做法），或 `useMemo(() => new Set(selected), [selected])` 后用 `.has()`（已在最终报告 P1-2 出现）
- **[性能]** `components/Douyin/UnifiedWorksPanel.tsx:224-262, 304, 564, 571` — 第 3 条：render 体大量未 memo 派生计算 + 每次 render 重建数组。直接执行 `pageIds = rows.map(...)`（224）、`allPageSelected`（225-226）、`selectedWorks = rows.filter(...)`（227-229）、`selectedAssets = rows.filter(...).map(...)`（238-240）、`lastMediaActivity = rows.reduce(...)` 含 `new Date()` 比较（256-262）、`rows.some(...)`（304）、`selectedAssets.some(...)`（564）、`selectedAssets.map(...)`（571）；仅 `failedAssets` 用了 useMemo（241） | `worksQuery` 每 2s 轮询更新 `rows` 引用，8 处计算全部重算，`lastMediaActivity` 每行 `new Date()` 两次。建议全部 `useMemo` 包裹依赖 `[rows, selected]`，`lastMediaActivity` 用时间戳数字比较代替 `new Date()` 对象比较（已在最终报告 P1-5 出现）
- **[性能]** `components/Sidebar/Main.tsx:33` — 第 4 条：`useRouterState()` 无 `select` 全量订阅。未传 `select`，全量订阅 router state；任何 search param 变化（如 `douyin-tracks` 的 `run`、`douyin-library` 的 8 个 search 参数）都会触发整个侧边栏重渲染 | 侧边栏常驻，资源库页切换任何筛选时所有 `SidebarGroup`/`SidebarMenuItem` 无差别重渲染。建议改为 `useRouterState({ select: (state) => state.location.pathname })`，只订阅 pathname（对比 `HorizontalNavigation.tsx:13` 的正确做法）（已在最终报告 P1-3 出现）
- **[性能]** `components/Douyin/InteractionLiveMonitor.tsx:61-75` — 第 5 条：轮询频率叠加。`detail` 轮询 `refetchInterval: open ? 1_000 : false`（Line 68），`slots` 轮询 `refetchInterval: open ? 2_000 : false`（Line 74），打开监控时**每秒至少 1 次请求，峰值 2 次/秒** | 互动任务页/任务详情页点击「实时监控」打开 Sheet 后持续每秒刷新，iframe 重载 + 事件列表重渲染叠加，低端设备明显掉帧。建议合并为单一轮询（或 detail 改 2s），iframe 用 `key` 稳定化避免重载，事件列表做增量 diff 而非全量重渲染（已在最终报告 P1-4 出现）
- **[性能]** `routes/_layout/douyin-creators.tsx:375` — 第 6 条：每行 `selected.includes` + 200 行规模。`selected={selected.includes(creator.id)}`，`pageLimit = 200`（Line 75），`creatorsQuery` 有 `refetchInterval: 10_000`（Line 122），`overviewQuery` 有 `refetchInterval: 15_000`（Line 133）；**200 行 × 每行 O(selected.length) 次 includes** | 达人列表每 10s 轮询重渲染 200 行，选中 50 位达人时每 10s 做 10000 次数组扫描，滚动 + 勾选明显卡顿。建议 `selected` 改 `Set<string>`，`selected.includes` → `selectedSet.has`（已在最终报告 P1-2 出现）

### 中间性能审查报告 · 🟠 高严重度（明显卡顿/网络风暴）P1-1 ~ P1-10（原文 47370-47532）

- **[性能]** `main.tsx:39-46` — P1-1 全局无 staleTime，每次挂载/打开 Dialog 都重新请求。`QueryClient` 未设 `defaultOptions.queries.staleTime`，默认 staleTime=0；全项目仅 8 处显式设置 staleTime（TrackSelect/4SourceSelect/library/comments 的 tasks 查询），其余数十个查询每次组件挂载都重新请求。触发：打开任意 Dialog（InteractionComposerDialog 的 accounts/task/track 查询 :100-115）、切 Tab 后切回、路由返回再进入。量化：每次打开评论回复 Dialog 触发 **3-4 个重复请求**（accounts/task/track/quota），无缓存复用。建议 `new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, refetchIntervalInBackground: false } } })` | （已在最终报告 P1-7 + 横切根因 G1 出现）
- **[性能]** `routes/_layout/douyin.tsx:127` — P1-2 任务列表页固定 3s 轮询，无终态判断，无 inBackground。`refetchInterval: 3_000` 固定 3s，不判断是否有进行中任务，无 `refetchIntervalInBackground: false`；即使所有任务都已成功/失败仍每 3s 请求一次，多标签页叠加放大 | 单标签页 **20 次/分钟**；5 个标签页 **100 次/分钟**持续打到后端。建议改函数式 refetchInterval，有活动任务时 3s 否则 false，加 `refetchIntervalInBackground: false`（已在最终报告 P2-3 / P2-4 出现）
- **[性能]** `components/Douyin/MediaTaskManagement.tsx:122` — P1-3 媒体任务管理固定 3s 轮询，无终态判断。同 P1-2，`refetchInterval: 3_000` 固定轮询，无终态判断、无 inBackground | 无活动任务时仍持续轮询。建议同 P1-2（已在最终报告 P2-3 出现）
- **[性能]** `components/Douyin/UnifiedWorksPanel.tsx:378-382`（onChange）+ `:122`（search 进 queryKey） — P1-4 作品面板搜索无防抖，每次按键触发网络请求。搜索框 `onChange` 直接 `setSearch(event.target.value)`，`search` 进入 `worksQuery` 的 queryKey（:122），每次按键都触发 `listWorks` 网络请求。触发：任务详情 → 作品数据 tab → 输入「搞笑猫咪」（6 个字）。量化：**6 次按键 = 6 次 HTTP 请求**（每次取消上一次但仍发起新的），输入快时后端被搜索请求轰炸。建议 `useDeferredValue` 或 `300ms debounce` 后再 setSearch | （已在最终报告 P2-1 出现）
- **[性能]** `routes/_layout/douyin-creators.tsx:288`（onChange）+ `:110`（search 进 queryKey） — P1-5 达人列表搜索无防抖，每次按键触发网络请求。`creatorsQuery` 的 queryKey 包含 `search`（:110），onChange 直接 setSearch（:288），每次按键触发 `listCreators` 请求 | 量化影响同 P1-4。建议同 P1-4（已在最终报告 P2-1 出现）
- **[性能]** `components/Douyin/UnifiedWorksPanel.tsx:196-213` — P1-6 批量补采评论：串行 await 循环。`recrawlComments` 用 `for...of await` 串行，且循环内可能额外调用 `getTask`（:337）获取任务详情（虽有 taskCache 但首次仍请求）。触发：任务详情 → 选中 20 个视频 → 批量补采评论。量化：**20 个视频 = 20 次顺序请求，每次 ~1-3s，总耗时 20-60s**，用户等待期间无进度反馈。建议改后端批量接口，或前端并发池上限 5 | （已在最终报告 P2-2 出现）
- **[性能]** `routes/_layout/douyin-library.tsx:333-356` — P1-7 库页面批量补采评论：串行 await 循环 5 次（含额外 find/filter getTask 请求）。`recrawlComments` 用 `for...of await` 串行 | 量化：**N 个视频 = N~2N 次顺序请求**。建议同 P1-6（已在最终报告 P2-2 出现）
- **[性能]** `components/Douyin/InteractionLiveMonitor.tsx:68`（detail 1s）+ `:74`（slots 2s） — P1-8 互动实时监控两次 1s/2s 轮询，无 inBackground。`refetchInterval: open ? 1_000 : false`，打开监控时每 1s 请求互动详情 + 每 2s 请求浏览器槽位，无 `refetchIntervalInBackground: false`，切到其他标签页仍持续轮询。触发：打开评论实时监控 Sheet 并保持。量化：**60 次/分钟（detail）+ 30 次/分钟（slots）= 90 次/分钟**，切后台仍持续。建议加 `refetchIntervalInBackground: false`；互动进入终态后停止 detail 轮询 | （已在最终报告 P1-4 / P2-4 出现）
- **[性能]** `routes/_layout/douyin-interactions.tsx:103-108` — P1-9 互动任务列表终态后仍 5s 轮询。`refetchInterval` 有活动任务时 2s，无活动任务时仍 5s（:103-108），无 inBackground。触发：互动任务页保持打开、所有任务已完成 | 量化：**12 次/分钟**持续请求。建议无活动任务时返回 false（已在最终报告 P2-3 出现）
- **[性能]** `components/Douyin/UnifiedWorksPanel.tsx:141`（worksQuery）+ `:157`（summaryQuery）、`components/Douyin/MediaPipelinePanel.tsx:67`、`components/Douyin/TaskInteractionsPanel.tsx:43-48`、`components/Douyin/TaskExecutionProgress.tsx:68` — P1-10 作品面板/媒体管道终态后仍 1s、2s 轮询。多处 `refetchInterval: active ? 2_000 : 5_000` 或 `2_000 : 10_000`，任务终态后仍以 5s/10s 持续 | 终态后持续产生无意义请求。建议终态后返回 false（已在最终报告 P2-3 / P2-4 出现）

---

## P2

### 最终报告 · P2 明显劣化 / 网络风暴（原文 47699-47712，共 10 条）

- **[性能]** `UnifiedWorksPanel:378`、`creators:288`、`tracks:208`、`keywords:283`、`library:579`、`comments`、`tags:113` — **6 处搜索无防抖**，onChange 直接 setState 且进 queryKey | 输入「美食推荐」8 字 → 8 次请求，快速输入每秒 5-10 次
- **[性能]** `UnifiedWorksPanel:196-213`、`library:333-356` — `recrawlComments` **串行 for await** | 选 30 作品 → 60 次顺序请求，耗时 60-120s
- **[性能]** `douyin.tsx:127`、`MediaTaskManagement:122` — 固定 3s 轮询**无终态判断** | 全部任务已成功仍每分钟 20 次请求
- **[性能]** 10+ 页面（index/accounts/keywords/tracks/creators/library/browsers…） — 固定轮询 + **无 refetchIntervalInBackground** | 切后台仍轮询，10+ 页面后台每分钟数十次请求
- **[性能]** `InteractionLiveMonitor:177`、`douyin-browsers:206` — iframe `key={viewer_url}` 强制**重挂载** | viewer_url 变化时 2-5s 白屏 + 重新加载整个浏览器页面
- **[性能]** `interactions:539`、`InteractionLiveMonitor:279` — 互动事件/监控步骤**全量渲染无虚拟滚动** | 100+ 事件全量 DOM，配合 1s 轮询每秒全量 diff
- **[BUG]** `UnifiedWorksPanel:155`、`MediaPipelinePanel:65`、`TaskExecutionProgress:66` — 相同 queryKey `["douyin-media-summary",taskId]` **不同 refetchInterval 冲突** | 轮询频率不可预测（2s 或 10s），组件间互相干扰
- **[性能]** `creators:124-134` — `overviewQuery` 拉 **limit:500** 条完整创作者仅算 4 个指标 | 每次加载额外 200-500KB，每 15s 轮询刷新
- **[性能]** `douyin-tracks_.$trackId:243-269,402` — 关键词列表 filter/map/every/some **6 处未 memo** + 3 个 query 同时 10s 轮询 | 数百关键词每 10s 全量重算，搜索每次按键全量重算
- **[交互]** `MediaPipelinePanel:209-210` — 全局 `isPending` 传所有行，**单行操作禁用全部按钮** | 任一行重试时其他行全 disabled，批量体验差

### 中间编号清单 · 🟠 中等（轮询时可感知卡顿）第 7-18 条（原文 45372-47423）

- **[性能]** `routes/_layout/douyin-library.tsx:284-299` — 第 7 条：render 体 8 次未 memo 遍历。`pageAwemeIds = rows.map(...)`、`selectedRows = rows.filter(...)`、`allPageSelected`、`somePageSelected`、`pageLocal = rows.filter(...).length`、`pageMinio = rows.filter(...).length`、`pageUndownloaded = rows.filter(...).length`、`hasPlayableRows = rows.some(...)` —— **8 次遍历**全在 render 体。`worksQuery` 有 `refetchInterval: 5_000`（Line 264），`pageSize = 32`（Line 84）| 资源库页每 5s 轮询，32 行 × 8 次遍历 = 256 次操作，且 `selectedAwemeSet` 已 memo（280-283）但上述计算未复用。建议合并为单次 `useMemo` 遍历，一次 reduce 产出所有聚合值（已在最终报告 P1-6 出现）
- **[性能]** `routes/_layout/douyin-tracks_.$trackId.tsx:243-269, 402` — 第 8 条：长列表未 memo 计算。`filteredKeywords`、`visibleKeywords`、`visibleKeywordIds = visibleKeywords.map(...)`、`allVisibleKeywordsSelected`、`someVisibleKeywordsSelected`、`visibleCreators` 全在 render 体；3 个 query 都有 `refetchInterval: 10_000`（Line 124, 130, 136）；Line 402 按钮标签内还有 `keywords.filter((item) => item.task_count === 0).length` 每次渲染重算 | 赛道详情页关键词可达数百条，每 10s 轮询重算全部 filter + map + every + some，关键词 tab 切换/搜索输入时每次按键都全量重算。建议 `visibleKeywords`/`visibleKeywordIds`/`allVisibleKeywordsSelected` 用 `useMemo` 包裹依赖 `[keywords, search, keywordFilter, selectedKeywordIds]`（已在最终报告 P2-9 出现）
- **[性能]** `components/Douyin/TaskResults.tsx:126-130` — 第 9 条：每行挂载重组件或 useQuery 实例。每行挂载 `<AwemeActions>`，其内部含 1 个 useQuery（`comments`，`enabled: commentsOpen`）、2 个 useMutation、useCustomToast、useNavigate、2 个 `<InteractionComposerDialog>`（每个 4 个 useQuery）。**20 行 = 20 × (约 11 个 hook 实例)**。`awemes` 有 `refetchInterval: active ? 3_000 : false`（Line 42），每 3s 轮询，20 行 AwemeActions 全部重新执行 | 持续重执行 hook 逻辑。建议同问题 1，memo 化行组件或改为单实例 + 选中行驱动（已在最终报告 P3-1 出现）
- **[性能]** `routes/_layout/douyin-accounts.tsx:188-191` — 第 10 条：render 体 filter + 轮询。`ready = accounts.filter(...).length`、`busy = accounts.filter(...).length`、`availableSlots = browserSlots.filter(...).length` 在 render 体；`accountsQuery` 和 `slotsQuery` 都有 `refetchInterval: 5_000`（Line 94, 105）| 账号池页每 5s 轮询，3 次 filter 重算。建议 `useMemo` 包裹
- **[性能]** `components/Douyin/MediaTaskManagement.tsx:125-140` — 第 11 条：render 体 reduce + 轮询。`counts = tasks.reduce(...)` 在 render 体（未 memo），query 有 `refetchInterval: 3_000`（Line 122）；`filtered` 已正确 memo（141）| 媒体任务管理每 3s 轮询，100 条任务 reduce 重算。建议 `useMemo` 包裹 `counts`
- **[性能]** `components/Douyin/MediaPipelinePanel.tsx:103-108` — 第 12 条：未 memo 的派生计算。`failedAssets = assets.filter(...).map(...)` 在 render 体，`mediaQuery` 有 `refetchInterval: 2_000/5_000`（Line 46-62）| 媒体管线面板每 2s 轮询，100 条资产 filter + map 重算。建议 `useMemo` 包裹
- **[性能]** `routes/_layout/douyin.tsx:130-134, 156-159` — 第 13 条：未 memo 的派生计算。`attentionCount = tasks.filter(...).length`（130-134）、`selectableTasks = filteredTasks.filter(isDeletableTask)`（156）、`allSelectableTasksSelected`（157-159）在 render 体；`useQuery` 有 `refetchInterval: 3_000`（Line 127）；`filteredTasks` 已正确 memo（135）| 任务列表页每 3s 轮询，100 条任务 3 次 filter/every 重算。建议 `useMemo` 包裹
- **[性能]** `routes/_layout/index.tsx:50-65` — 第 14 条：未 memo 的派生计算。`activeCount`、`attentionCount`、`total`（reduce）、`readyAccounts` 4 次 filter/reduce 在 render 体；`tasks` 有 `refetchInterval: 5_000`（Line 41）| 首页每 5s 轮询，100 条任务 4 次遍历重算。建议 `useMemo` 合并
- **[性能]** `routes/_layout/douyin-tracks.tsx:166-169` — 第 15 条：未 memo 的派生计算。`active`、`keywordCount`、`works`、`comments` 4 次 filter/reduce 在 render 体；`tracksQuery` 有 `refetchInterval: 10_000`（Line 113）| 赛道管理页每 10s 轮询，4 次遍历重算。建议 `useMemo` 合并
- **[性能]** `routes/_layout/douyin-request-logs.tsx:87-92` — 第 16 条：每次 render 重建对象/数组/Map。`taskMap = new Map((tasks.data?.data ?? []).map(...))` 在 render 体，每次渲染重建 Map（200 个任务时每次 new Map + 200 次 map）| 请求日志页每次筛选/翻页/输入时都重建 Map。建议 `useMemo(() => new Map(...), [tasks.data?.data])`（已在最终报告 P3-2 出现）
- **[性能]** `routes/_layout/douyin-browsers.tsx:28-34` — 第 17 条：useEffect 依赖不稳定。`useEffect(() => { ... }, [selectedName, slots])`，`slots = slotsQuery.data?.data ?? []`（Line 27），`slotsQuery` 有 `refetchInterval: 5_000`（Line 25）；任务 slots 每 5s 新引用，effect 每 5s 执行一次（即使 selectedName 未变）| 浏览器监控页每 5s 轮询触发 effect 重新执行 `slots.some(...)` 扫描。建议 effect 内只依赖 `slots` 的派生值，或 `useMemo` 先算 `selectedStillExists` 再作为依赖（已在最终报告 P3-6 出现）
- **[性能]** `components/Douyin/CreateTaskDialog.tsx:466, 479` — 第 18 条：selected 用数组 + includes。`form.selectedCreatorIds.includes(item.id)` 在创作者列表每行渲染时调用；Line 456 还有 `(creatorsQuery.data?.data ?? []).filter(...)` 在 render 体 | 创建任务对话框选择创作者时列表每行 includes，创作者多时卡顿。建议 `selectedCreatorIds` 改 Set 或 memo 一个 Set 视图（已在最终报告 P1-2 出现）

---

## P3

### 最终报告 · P3 资源浪费 / 潜在风险（原文 47714-47723，共 6 条）

- **[性能]** `TaskResults.tsx:126-130` — 每行挂载 AwemeActions（≈11 hook 实例），20 行 = 220 实例，3s 轮询重执行
- **[性能]** `Douyin-request-logs.tsx:87-92` — `taskMap = new Map(...)` 每次 render 重建（200 任务）
- **[性能]** `vite.config.ts` — 无 `manualChunks`，第三方打成一个 ~500KB+ vendor chunk，首屏慢
- **[优化]** `package.json:45` — `react-icons` 死依赖（全项目未引入），拖慢 install
- **[性能]** `useCopyToClipboard:21`、`feed:89` — setTimeout 未在 unmount 清理（React 19 已兜底，影响极小）
- **[性能]** `douyin-browsers:28-34` — useEffect 依赖轮询数组 `slots`，每 5s 新引用触发 effect 执行

### 中间编号清单 · 🟡 轻微（小列表或低频场景）第 19-24 条（原文 47426-47507）

- **[性能]** `routes/_layout/douyin-comments.tsx:194-197` — 第 19 条：未 memo 的派生计算。`visibleIds = rows.map(...)`、`allVisibleSelected` 在 render 体；`rows` 已 memo（184），但 `visibleIds` 未 memo | 评论管理页翻页/筛选时重算，50 行规模影响小。建议 `useMemo`
- **[性能]** `routes/_layout/douyin-keywords.tsx:99-101, 169-171` — 第 20 条：未 memo 的派生计算。`selectedTrack = tracksQuery.data?.data.find(...)`（99-101）、`pageIds = rows.map(...)`（169）、`allPageSelected`（170-171）在 render 体；`query` 有 `refetchInterval: 5_000`（Line 144）| 关键词管理页每 5s 轮询，50 行 map + every 重算。建议 `useMemo`
- **[性能]** `routes/_layout/douyin-creators.tsx:94-96` — 第 21 条：未 memo 的派生计算。`selectedTrack = tracksQuery.data?.data.find(...)` 在 render 体 | 达人列表每 10s 轮询重算 find。建议 `useMemo`
- **[性能]** `components/Douyin/TaskExecutionProgress.tsx:72-77` — 第 22 条：未 memo 的派生计算。`current`/`completed`/`skipped`/`errors`/`pending` 5 次在 render 体；`summaryQuery` 有 `refetchInterval: 2_000/10_000`（Line 68）| stages 固定 4 个元素，影响极小。建议可忽略或合并为单次 reduce
- **[性能]** `routes/_layout/douyin-tags.tsx:102, 106` — 第 23 条：未 memo 的派生计算。`rows.reduce(...)` 两次在 render 体 | 50 行规模、无轮询，影响小。建议 `useMemo`
- **[性能]** `routes/_layout/douyin-library.tsx:463-473` — 第 24 条：内联对象/数组作为 prop。`feedSearch` 对象字面量在 render 体，每次渲染新引用，传给 `<Link search={feedSearch}>` 多处 | 资源库页每次筛选变化 Link 重渲染。建议 `useMemo` 或移到 Link 内联处

### 其他实质发现（原文 42115、42196-42244）

- **[性能]** `douyin-tracks_.$trackId.tsx` 行内 `onSelectedChange={(checked) => toggleTaskSelection(task.id, checked)}` 内联函数每行新建 | 反模式：内联函数作为 prop；严重度低（TaskMobileCard/TaskCompactRow 非 memo 组件时影响有限）
- **[性能]** `douyin-tracks_.$trackId.tsx:402` — `keywords.filter((item) => item.task_count === 0).length` 在 render 体（按钮标签内），每次渲染重算 | 反模式：未 memo 的派生计算；严重度中（关键词列表可能很长，每 10s 轮询）（已在最终报告 P2-9 出现）
- **[结论]** `douyin-interactions.tsx:104-106` — `query.state.data?.data.some((item) => ["queued","running"].includes(item.status))` 在 refetchInterval 回调里 | 这是 TanStack Query 的标准用法，每次轮询前执行，100 行 some 可接受（判定为**非问题**）
- **[性能]** `TaskResults.tsx:126-130` — 每行挂载 `<AwemeActions>`，内含 useQuery（enabled: commentsOpen）+ useMutation + useCustomToast + useNavigate + 2 个 InteractionComposerDialog；20 行 = 20 × 每行大量 hook 实例 | 反模式：每行挂载重组件 + useQuery 实例；严重度高（已在最终报告 P3-1 出现）
- **[性能]** `AwemeActions.tsx:260-266` — 评论列表每行挂载 `<InteractionComposerDialog>`，内含 4 个 useQuery | 反模式：每行挂载 useQuery 实例；严重度中（**10 条评论 × 4 useQuery = 40 个 observer**）（已在最终报告 P1-1 出现）

### 中间清单统计（原文 47511-47532）

- **[结论]** 47511-47527 — 统计表：🔴 严重（高频轮询必现）**6** 条 ｜ 🟠 中 **12** 条 ｜ 🟡 轻微 **6** 条 ｜ **合计 24 条**
- **[结论]** 47527 — 高频轮询场景下必现的卡顿（6 条）：问题 1、2、3、4、5、6 —— 均涉及 10 秒轮询触发的重渲染，在任务运行中、实时监控打开、达人/作品列表展示时持续发生，用户体感最明显
- **[结论]** 47529-47531 — 最优先修复：问题 1（每行重组件实例化）+ 问题 2（selected 数组 includes）+ 问题 4（Sidebar 无 select）—— 这三条影响范围最广、修复成本最低（memo + Set + select 参数）

---

## 横切根因

- **[架构]** `main.tsx:39` — **G1** QueryClient 无 defaultOptions：加 `defaultOptions:{queries:{staleTime:30_000, refetchIntervalInBackground:false}}` → 同时缓解 P1-7 + P2-4 + 全局 refetch 风暴 | 一行修复影响面最大
- **[架构]** 14 处 — **G2** 轮询无统一封装：封装 `useActivePolling(queryKey, fn, { active, interval })`，终态自动返回 false → 缓解 P2-3 + P2-4 | 统一轮询策略
- **[架构]** 3 处 — **G3** selected 普遍用数组：统一改 `Set<string>` + `.has()` → 缓解 P1-2 | 勾选性能
- **[架构]** 47674 — 反模式出现次数：高频轮询无暂停 **14 处**｜未 memo 派生计算 **18 处**｜串行 await 循环 **5 处**｜前端全量加载 **4 处**｜搜索无防抖 **6 处**｜selected 数组 O(n) **3 处**｜每行挂载重 hook **2 处** | 全局量化
- **[结论]** 47672 — 横切配置缺失（一行修复缓解 10+ 问题）共 3 条

---

## 路线图

### 最终报告 · 修复路线图（按 ROI 排序，原文 47733-47746，共 10 步）

- **[优化]** 步骤 **1** `main.tsx` 加 `defaultOptions`（staleTime + inBackground）— 工作量 **1 行**，缓解 G1 / P1-7 / P2-4 / 全局 refetch 风暴
- **[优化]** 步骤 **2** `Sidebar/Main.tsx` useRouterState 加 `select` — 工作量 **1 行**，缓解 P1-3
- **[优化]** 步骤 **3** `selected` 数组 → Set（3 处）— 工作量 小，缓解 P1-2
- **[优化]** 步骤 **4** 派生计算加 `useMemo`（UnifiedWorksPanel 8 处 + library 8 处 + tracks_.$trackId 6 处 + 其余 5 处）— 工作量 批量小，缓解 P1-5 / P1-6 / P2-9
- **[优化]** 步骤 **5** 行组件 `React.memo` + 稳定 props（UnifiedWorksPanel / TaskResults）— 工作量 中，缓解 P1-1 / P3-1
- **[优化]** 步骤 **6** 搜索防抖 `useDeferredValue`（6 处）— 工作量 批量小，缓解 P2-1
- **[优化]** 步骤 **7** 轮询加终态判断返回 false（10+ 处）或封装 hook — 工作量 批量小，缓解 P2-3 / P2-4
- **[优化]** 步骤 **8** iframe 去 `key` 强制重挂载，改 `src` 更新（2 处）— 工作量 小，缓解 P2-5
- **[架构]** 步骤 **9** **P0 改后端**：导出流式接口 + 批量重试接口 + 截图懒加载 — 工作量 大（后端），缓解 P0-1 / P0-2 / P0-3 / P0-4
- **[优化]** 步骤 **10** vite manualChunks + 移除 react-icons — 工作量 小，缓解 P3-3 / P3-4

### 卡顿场景速查（用户体感，原文 47748-47759，共 8 行）

- **[性能]** 任务运行中打开作品数据 tab → **持续掉帧**，根因：260 hook 实例 × 2s 轮询，对应 P1-1
- **[性能]** 达人列表勾选 + 滚动 → 掉帧，根因：200 行 × includes O(n)，对应 P1-2
- **[性能]** 资源库切换筛选 → 侧边栏重渲染，根因：useRouterState 无 select，对应 P1-3
- **[性能]** 打开实时监控 → 持续掉帧，根因：1s 轮询 + 事件全量 diff，对应 P1-4
- **[性能]** 导出评论/字幕 → **卡死**，根因：全量加载 + 拼大字符串，对应 P0-1/2
- **[性能]** 重试全部互动 → **卡死**，根因：500 并发请求，对应 P0-3
- **[性能]** 任意页面切后台 → 后台轮询不停，根因：无 inBackground，对应 P2-4
- **[性能]** 搜索框输入 → 请求风暴，根因：无防抖，对应 P2-1

### 最终结论（原文 47763）

- **[结论]** 47763 — 性能问题集中在 **3 个横切根因**（QueryClient 配置缺失 / 轮询无封装 / selected 用数组）和 **4 个 P0 前端越界**（导出/批量重试/截图应改后端）；**步骤 1-2 各一行代码即可缓解最大面积卡顿**；步骤 9（P0 后端化）是唯一需要跨端协作的大改
- **[结论]** 47765 — 提出可直接动手修步骤 1-3（一行 + 小改，立即见效）

---

## 交接

### 交接上下文（本区间内可得：末轮 User 指令 + 47542-47654 的整合决策记录）

> 注：正式交接 prompt 的 Goal/Instructions/Discoveries/Accomplished/Relevant files 位于第 47848-47937 行，**在本次指定区间（42000-47767）之外**，未读取。以下为本区间内的等价上下文。

- **[结论]** 47533-47538（末轮 User）— 用户要求「重新分析下」，主项目 `https://atomgit.com/qq_41251172/MediaCrawler_Dy_V2`，分支 `refactor/uv-workspace-modules`
- **[结论]** 47548-47551 — 「重新分析」动因推测：① 之前 Agent 3 和 Agent B 出过空结果，用户对完整性有疑虑；② 用户想要基于 refactor/uv-workspace-modules（默认分支）的干净分析；③ 用户想要一份整合了所有性能 + 缺陷的完整最终报告
- **[结论]** 47560 — 决策：直接给出整合后的最终报告，不再启动智能体重跑（两分支差异仅 5 行，不影响结论）
- **[结论]** 47583-47590 — 报告结构：1 总览（数据来源、统计）/ 2 P0 卡死崩溃级 / 3 P1 持续卡顿级 / 4 P2 明显劣化级 / 5 P3 资源浪费级 / 6 横切性能根因 / 7 修复优先级路线图
- **[结论]** 47608-47612 — P0 去重后 4 条：评论导出（comments:987）｜字幕导出（library:420）｜批量重试（interactions:161）｜互动证据截图（interactions:652）
- **[结论]** 47614-47620 — P1 去重后条目：UnifiedWorksPanel 260 hook 实例 + 2s 轮询 ｜ selected 数组 includes（UnifiedWorksPanel/creators/CreateTaskDialog）｜Sidebar useRouterState 无 select ｜InteractionLiveMonitor 1s+2s 双高频 ｜render 体未 memo 派生计算（UnifiedWorksPanel 8 处、library 8 处、tracks_.$trackId、accounts、index、tracks、douyin、MediaTaskManagement、MediaPipelinePanel）｜全局 QueryClient 无 defaultOptions
- **[结论]** 47622-47630 — P2 去重后条目：搜索无防抖进 queryKey（UnifiedWorksPanel/creators/tracks/keywords/library/comments/tags）｜串行 await 循环（recrawlComments 两处）｜终态后仍轮询（10+ 处）｜无 refetchIntervalInBackground（10+ 页面）｜iframe key 重挂载（InteractionLiveMonitor/browsers）｜大列表无虚拟滚动（互动事件、监控事件）｜重复 queryKey 不同 refetchInterval 冲突（media-summary）｜达人 overviewQuery 拉 500 条算指标
- **[结论]** 47632-47636 — P3 去重后条目：每行挂载 AwemeActions/Dialog 实例（TaskResults）｜request-logs taskMap 每次 render 重建｜bundle 无 manualChunks + react-icons 死依赖｜setTimeout 未清理（useCopyToClipboard/feed）
- **[结论]** 47638-47643 — 横切根因：main.tsx QueryClient 无 defaultOptions（一行修复缓解 10+ 问题）｜轮询策略无统一封装｜selected 普遍用数组而非 Set｜派生计算普遍未 memo｜行组件普遍未 memo + 挂载重 hook
- **[结论]** 47645-47652 — 修复路线图（按 ROI）：1 一行 main.tsx defaultOptions → 缓解 10+ 轮询问题；2 一行 Sidebar useRouterState 加 select；3 批量小改 selected → Set（3 处）；4 批量小改派生计算加 useMemo（10+ 处）；5 中改行组件 React.memo + 稳定 props；6 中改搜索防抖（6 处）；7 大改 P0 导出改后端流式、批量重试改后端批量接口
- **[结论]** 47549 — 历史遗留：Agent 3 与 Agent B 曾出现空结果，是本轮要求「重新分析」的直接原因
- **[结论]** 47571-47579 — 去重后性能问题约 40 条（原始 47 条），交付口径为「40 条」
- **[结论]** 47660 — 最终交付物标题：《抖音采集工作台 · 性能与卡顿分析报告》（原文 47660-47766）
