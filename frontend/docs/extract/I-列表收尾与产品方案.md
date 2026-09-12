# I-列表收尾与产品方案（文档行 68000–75392，文件结尾）

> 本区间是会话最后的收尾段，包含五份交付物：
> 1. **列表缺陷报告（收尾部分）**——`douyin.tsx` / `douyin-library.tsx` / `douyin-request-logs.tsx` / `douyin-tags.tsx` / `douyin-comments.tsx` / `douyin-creators.tsx` / `douyin-browsers.tsx` / `UnifiedWorksPanel.tsx` 的 12 维度逐项判定 + 全局共性问题 + 架构师路线图/结论。
> 2. **《数据列表架构重构 · 实施计划》**（阶段 0/1/2/3/4 + 验证计划 + 工作量估算）。
> 3. **《列表功能增强与优化建议》**（A1–A16 / O1–O20 / 优先级矩阵）。
> 4. **《产品架构师视角 · 前端产品优化分析》**（IA1–IA5 / UJ1–UJ5 / DV1–DV5 / EF1–EF6 / CF1–CF4 / FB1–FB3 / HP1–HP3 / MB1–MB2 / 四象限）。
> 5. **《PRD：媒体流水线自动编排》**（概述 / 场景 S1–S5 / US1–US5 / 信息架构 / 数据模型）。
>
> **导出损坏说明**：第 68000–73350 行为导出工具「逐行交错」污染——同一物理行里两段文本被拼接（例如「请求日志列表」表格与「任务列表」表格按列交错），并混入 `# 项目开发约定` 重复注入与思考块。该区间已按可辨识片段尽量还原，**凡不能确证归属者均就地标注**。PRD 段（75220 起）另有 `-trackId）`、`5>`、`8>`、`Dy_V2`、`同时转9字幕` 等垃圾 token 混入正文，已尽力还原并标注「（原文此处损坏，已尽力还原）」。
> 文本顺序已被交错打乱（如 `# 五、浏览器槽位列表` 出现在 `# 三、评论列表` 之前），下文按列表名归档，不按文档物理顺序。

---

## 列表缺陷报告

### 任务列表 `douyin.tsx`（874 行）

- **[BUG]** `src/routes/_layout/douyin.tsx:123-124` — 分页：`skip:0, limit:100` 硬编码，**无分页器** | 严重缺陷，超 100 条任务完全不可见
- **[BUG]** 任务列表 — 筛选架构：全部筛选态为本地 `useState`（L109-112），未同步 URL | 缺陷，刷新/分享/后退丢失筛选
- **[BUG]** 任务列表 — 排序：无排序，表头不可点击 | 缺陷，用户无法按创建时间/状态排序
- **[BUG]** 任务列表 — 选择/批量：选择态全部本地 `useState`（L109-112），未同步 URL；批量删除有 `confirm`+清选（L270/L199） | 缺陷
- **[结论]** 任务列表 — 视图切换：`usePersistentViewMode` 统一；cards/rows/table 三视图共享 `TaskActions`，功能对等（L125-135） | 通过
- **[BUG]** 任务列表 — 三态完整性：空态/加载态为合并文案，无 `isError` 分支、无重试（L170-179） | 缺陷
- **[BUG]** 任务列表 — 数据刷新：`refetchInterval: 3_000`（L127）无终态停止、无 `refetchIntervalInBackground:false`；有手动刷新（L296）；`invalidate` 正确（L591） | 缺陷，终态仍轮询
- **[BUG]** 任务列表 — 组件复用：手写 `Table`（L242-336），未复用通用 `DataTable` | 缺陷
- **[架构]** 任务列表 — 架构师建议①：**引入服务端分页**，`limit:100` 硬编码是最大隐患，任务持续累积后**第 101 条起完全不可见** | 消除隐性数据丢失
- **[性能]** 任务列表 — 架构师建议②：`taskMap` 用 `useMemo(() => new Map(...), [tasks.data])` 化，避免每次渲染重建 Map | 轮询场景下每次渲染重建
- **[架构]** 任务列表 — 架构师建议③：**补齐核心诉求排序能力**，任务慢请求/错误请求排查依赖排序，列表无任何排序，表头不可点击，应至少支持可点击表头 + 服务端 `sortBy/sortOrder` | 日志排查核心诉求

### 视频资源库 `douyin-library.tsx`（1627 行）

- **[BUG]** `src/routes/_layout/douyin-library.tsx:113,260,333` — 分页：服务端分页 `skip: page*32`，`pageSize=50` 常量；`Pager` 仅上/下一页（L155-158），无页码跳转、无每页大小切换 | 缺陷
- **[BUG]** `src/routes/_layout/douyin-library.tsx:84` — 筛选架构：搜索即时触发 `setSearch`，无防抖（L57-59） | **严重缺陷**
- **[BUG]** `src/routes/_layout/douyin-library.tsx:127,159` — 排序：`validateSearch` 仅「初始化读取」`sortBy/sortOrder`，`setXxx` 不写回 URL（单向同步） | 严重缺陷，交互后分享/后退丢失
- **[BUG]** `src/routes/_layout/douyin-library.tsx:279-280,484,490` — 选择/批量：`selectedAwemeIds: string[]`（L279）+ 派生 `Set`（L280），但 `toggleSelection` 用 `includes`（L484）O(n)；全选仅本页（L490）；批量导出无二次确认（L819） | 缺陷
- **[BUG]** `src/routes/_layout/douyin-library.tsx:174-181` — 视图切换：手写 `localStorage` 未用 `usePersistentViewMode`（L156-215） | 缺陷，与其他页不一致
- **[BUG]** `src/routes/_layout/douyin-library.tsx:111` — 三态完整性：`rows.length ? (...) : ...` 无错误态，`worksQuery.isError` 被忽略；错误态无重试按钮 | **严重缺陷**
- **[性能]** `src/routes/_layout/douyin-library.tsx:264` — 数据刷新：`refetchInterval: 5_000` 无终态停止、无后台停止；有手动刷新（L176/L198） | 缺陷
- **[架构]** `src/routes/_layout/douyin-library.tsx:992-1086` — 组件复用：三套视频行组件独立实现 `VideoCard`/`VideoRow`/`VideoTable`，操作列逻辑重复 | 缺陷
- **[性能]** `src/routes/_layout/douyin-library.tsx:102,106` — `rows.reduce` 两次、每次渲染计算且未 memo；三视图功能不对等 | 缺陷
- **[A11Y]** `src/routes/_layout/douyin-library.tsx:845,923` — 搜索 Input 无 label（仅 placeholder）；`TrackSelect` 有 `ariaLabel`；L131 完全忽略 `worksQuery.isError` | 缺陷
- **[BUG]** `src/routes/_layout/douyin-library.tsx:155` — 响应式：外层为 `overflow-hidden`（非 `overflow-x-auto`），列多时窄屏**直接裁掉右侧操作列**，用户无法查看视频 | 缺陷
- **[结论]** `src/routes/_layout/douyin-library.tsx:206` — 行 key：`asset.id` | 通过
- **[BUG]** 视频资源库 — 架构师建议①：**补齐错误态 + 重试**，`worksQuery.isError` 被完全吞没，网络失败时用户只看到「没有符合筛选条件的作品」 | 属致命体验缺陷
- **[架构]** 视频资源库 — 架构师建议②：**统一视图切换 + URL 双向同步**，改用 `usePersistentViewMode`，筛选变更应 `navigate({ search })` 写回 URL，当前 `validateSearch` 形同虚设 | 修复伪 URL 同步
- **[架构]** 视频资源库 — 架构师建议③：**合并操作列实现**，`VideoTable` 内联操作复用 `WorkActionButtons`，消除三视图行为分叉风险 | 消除三视图功能不对等
- **[优化]** 视频资源库 — 架构师建议④：**L155 改 `overflow-x-auto`**，当前 `overflow-hidden` 在窄屏裁掉操作列 | 窄屏可用性

### 请求日志列表 `douyin-request-logs.tsx`（606 行）

- **[结论]** `src/routes/_layout/douyin-request-logs.tsx:55,77,373-390` — 分页：`PAGE_SIZE = 50` 统一常量；L77 `skip` 状态；L373-390 上/下页 | 通过（缺页码跳转与首末页按钮）
- **[BUG]** `src/routes/_layout/douyin-request-logs.tsx:70-76,229` — 筛选架构：draft 模式良好（L70-76 输入态 + L76 applied 态，L229 点「查询」才 `apply`），但 `applied/skip` 未同步 URL，刷新丢失；筛选无防抖（draft 模式下可接受） | 缺陷
- **[BUG]** `src/routes/_layout/douyin-request-logs.tsx:244-25` — 排序：无排序，表头不可点击；日志按时间倒序为隐式行为，用户无法按耗时/状态排序 | 缺陷，日志排查核心诉求缺失
- **[BUG]** `src/routes/_layout/douyin-request-logs.tsx:109-112` — 选择/批量：无选择/批量；全部本地 `useState` 未同步 URL | 缺陷
- **[结论]** `src/routes/_layout/douyin-request-logs.tsx:79,273` — 视图切换 | 通过
- **[BUG]** `src/routes/_layout/douyin-request-logs.tsx:170-179,360-365` — 三态完整性：空/加载合并文案；**无 `isError` 分支、无重试**（L170-179）；删除走 `confirm`（L360-365） | 严重缺陷
- **[BUG]** `src/routes/_layout/douyin-request-logs.tsx:127,296,591` — 数据刷新：`refetchInterval: 3_000`（L127）无终态停止、无 `refetchIntervalInBackground:false`；有手动刷新（L296）；`invalidate` 正确（L591） | 缺陷
- **[BUG]** `src/routes/_layout/douyin-request-logs.tsx:242-336,315-321,312` — 组件复用：手写 `Table`（L242-336）；`RequestLogPreview` 重试（L315-321）；`StatusBadge` 加载态为**纯文案**（L312）非共享骨架屏 | 缺陷
- **[性能]** `src/routes/_layout/douyin-request-logs.tsx:87` — 性能：`taskMap` 用 `useMemo(() => new Map(...), [tasks.data])`——**每次渲染重建 Map**（应为 `useMemo` 收窄依赖）；`limit:100` 量小影响有限 | 缺陷
- **[A11Y]** `src/routes/_layout/douyin-request-logs.tsx:78/296` — 可访问性：操作/搜索均有 `aria-label` 或 label（L323、L360、L78/296） | 通过
- **[结论]** `src/routes/_layout/douyin-request-logs.tsx:361` — 响应式：`overflow-x-auto`（L361） | 通过
- **[结论]** `src/routes/_layout/douyin-request-logs.tsx:336/347/396` — 行 key：`task.id`（L336/L347/L396） | 通过
- **[架构]** 请求日志 — 架构师建议①：**引入服务端分页**，`limit:100` 硬编码是最大隐患，持续累积后第 101 条起完全不可见 | 消除隐性数据丢失
- **[性能]** 请求日志 — 架构师建议②：`taskMap` 加 `useMemo`，避免每次渲染重建 Map | 轮询场景放大
- **[架构]** 请求日志 — 架构师建议③：**补齐核心诉求排序能力**（按耗时/状态/创建时间，可点击表头 + 服务端排序） | 日志排查

### 标签列表 `douyin-tags.tsx`（249 行）

- **[结论]** `src/routes/_layout/douyin-tags.tsx:34,57-58,21-23` — 分页：`pageSize=50` 常量；L57-58 服务端 `skip/limit`；L21-23 上/下页 | 通过（缺页码跳转）
- **[BUG]** `src/routes/_layout/douyin-tags.tsx` — 筛选状态未同步 URL：`statusFilter/trackId/sourceValue` 切换后**刷新即丢失**，应接入 TanStack Router `validateSearch` | 缺陷
- **[BUG]** `src/routes/_layout/douyin-tags.tsx:222` — 三态完整性：加载态为内联文案，**无 `QueryErrorState`**、错误态缺失 | 缺陷
- **[BUG]** `src/routes/_layout/douyin-tags.tsx:504` — 派生计算：2 次 `reduce` 在 render 体，未 `useMemo` | 缺陷（并入全局共性问题 5）
- **[BUG]** `src/routes/_layout/douyin-tags.tsx` — 搜索无防抖；`overflow-hidden` 应为 `overflow-x-auto` | 缺陷
- **[结论]** `src/routes/_layout/douyin-tags.tsx:242` — `formatDate` 第 4 处重复定义（另见互动 L617 / 账号 L927 / 日志 L601） | 应抽到 `@/utils`

### 评论列表 `douyin-comments.tsx`（1206 行）

- **[BUG]** `src/routes/_layout/douyin-comments.tsx:179-180` — 分页：服务端分页 `skip: page*50`；仅上/下一页（L652-665） | 缺陷，无页码跳转、无每页大小切换
- **[BUG]** `src/routes/_layout/douyin-comments.tsx:129,130,199,321` — 筛选架构：无 URL 同步；draft/filters 双状态需点查询才应用（L129/L130/L199）——合理但状态不持久；搜索 Enter 应用（L321）无防抖 | 缺陷
- **[结论]** `src/routes/_layout/douyin-comments.tsx:177,499-509` — 排序：服务端排序字段齐全 | 通过
- **[BUG]** `src/routes/_layout/douyin-comments.tsx:132,195,229` — 选择/批量：`Set<string>`（L132）；全选本页（L195）；`exportSelected` 批量导出**无二次确认**（L229 直接执行） | 缺陷
- **[结论]** `src/routes/_layout/douyin-comments.tsx:135` — 视图切换：`usePersistentViewMode`（L135）统一；cards/rows 共享 `CommentPreviewCard`，table 用 `CommentRow`，功能基本对等 | 通过
- **[BUG]** `src/routes/_layout/douyin-comments.tsx` — 三态完整性：`comments.isError` **完全未处理**，应加错误提示 + 重试 | 严重缺陷
- **[结论]** `src/routes/_layout/douyin-comments.tsx:251` — 数据刷新：无轮询（评论为静态数据，合理）；有手动刷新（L251） | 通过
- **[BUG]** `src/routes/_layout/douyin-comments.tsx:589,782` — 组件复用：`CommentRow`（L589）与 `CommentPreviewCard`（L782）操作列重复 | 缺陷
- **[BUG]** `src/routes/_layout/douyin-comments.tsx` — 性能：`rows.find` 每次渲染 O(n) | 缺陷
- **[A11Y]** `src/routes/_layout/douyin-comments.tsx:767` — 可访问性：`CommentRow` 外链按钮 `✅ 无 aria-label` | 缺陷
- **[结论]** `src/routes/_layout/douyin-comments.tsx:589` — 响应式：`min-w-[900px]` + `overflow-x-auto`（L589） | 通过
- **[结论]** `src/routes/_layout/douyin-comments.tsx:572,619` — 行 key：`item.comment.id`（L572/L619） | 通过
- **[BUG]** 评论 — 架构师建议①：**补齐错误态 + 重试**，`comments.isError` 完全未处理 | 严重缺陷
- **[架构]** 评论 — 架构师建议②：**筛选状态同步 URL**，评论筛选条件多，应接入 router `searchParams` | 刷新后用户需重新填写
- **[架构]** 评论 — 架构师建议③：**操作列合并**，`CommentRow`（L589）与 `CommentPreviewCard`（L782）操作列重复 | 消除重复

### 达人列表 `douyin-creators.tsx`（1101 行）

- **[BUG]** `src/routes/_layout/douyin-creators.tsx:119,75,399-404` — 分页：`limit:200` 一次性加载（L119/L75），超限**仅文字提示**「仅显示前 200 位」（L399-404），无分页器 | 严重缺陷
- **[BUG]** `src/routes/_layout/douyin-creators.tsx:288` — 筛选架构：无 URL 同步；`search` 即时应用无防抖（L288） | 缺陷
- **[结论]** `src/routes/_layout/douyin-creators.tsx:117,339-345` — 排序：服务端排序字段齐全 | 通过
- **[BUG]** `src/routes/_layout/douyin-creators.tsx:91,270,199` — 选择/批量：`selected: string[]`（L91）Array + `includes` O(n)；**无全选功能**；批量删除 `confirm`+清选（L270/L199） | 严重缺陷
- **[结论]** `src/routes/_layout/douyin-creators.tsx:92,411` — 视图切换：`usePersistentViewMode`（L92）统一；`CreatorCard` 一组件三视图（L411），功能对等 | 通过
- **[BUG]** `src/routes/_layout/douyin-creators.tsx:356-359,390-397` — 三态完整性：错误态为纯文案无重试（L356-359）；空态 + 加载态骨架屏缺失（L390-397） | 缺陷
- **[BUG]** `src/routes/_layout/douyin-creators.tsx:122,133` — 数据刷新：`refetchInterval: 10_000`（L122）/`15_000`（L133）排序无终态停止、无后台停止；**无手动刷新按钮** | 严重缺陷
- **[BUG]** `src/routes/_layout/douyin-creators.tsx:430-433` — 组件复用：无 `Table`，全用 `Card` 模拟 table 视图（L430-433），`thead/tbody` 手写 | 缺陷
- **[性能]** `src/routes/_layout/douyin-creators.tsx:124-134` — 性能：`overviewQuery` 额外加载 **500 条**（L124-134），仅为算指标，与主查询**全部重复浪费**；无虚拟滚动（`limit 200`）；`selected` O(n) | 严重缺陷
- **[A11Y]** `src/routes/_layout/douyin-creators.tsx:446,334,286,504` — 可访问性：Checkbox/排序有 `aria-label`（L446/L334）；搜索框无 `aria-label`（L286）；停用/启用按钮无 `aria-label`（L504） | 缺陷
- **[BUG]** `src/routes/_layout/douyin-creators.tsx:430-433` — 响应式：用 `Card` border 模拟 table，无 `min-width`/`overflow-x-auto`，窄屏行为不可控 | 缺陷
- **[结论]** `src/routes/_layout/douyin-creators.tsx:372` — 行 key：`creator.id`（L372） | 通过
- **[架构]** 达人列表 — 架构师建议①：**引入分页 + 后端聚合接口**，消除 `limit:200`；`overviewQuery` 轮询是双重查询（浪费），应改为固定 5s 服务端分页 + 概览统计接口 | 消除双重查询浪费
- **[架构]** 达人列表 — 架构师建议②：**`selected` 改 `Set<string>` + 补全选**（`string[]`+`includes` → `Set`+`.has()`） | O(n) → O(1)
- **[优化]** 达人列表 — 架构师建议③：**补手动刷新按钮** | 当前无手动刷新
- **[优化]** 达人列表 — 架构师建议④：补错误态/骨架屏 | 三态完整性

### 浏览器槽位列表 `douyin-browsers.tsx`（233 行）

> 该页是 master-detail 槽位选择 + iframe 实时画面，非传统表格，按场景评判。

- **[结论]** `src/routes/_layout/douyin-browsers.tsx` — 分页：槽位数量少（通常 <10），无需分页 | 通过
- **[BUG]** `src/routes/_layout/douyin-browsers.tsx` — 筛选架构：无筛选/搜索；槽位多时无法定位（维度缺失，当前规模可接受） | 缺陷
- **[BUG]** `src/routes/_layout/douyin-browsers.tsx` — 排序：无排序；槽位按后端返回顺序，无法按在线状态/账号排序 | 缺陷（槽位多时加搜索/排序，可选）
- **[结论]** `src/routes/_layout/douyin-browsers.tsx:20` — 选择/批量：单选 `selectedName`，master-detail 模式合理，无批量需求 | 通过
- **[BUG]** `src/routes/_layout/douyin-browsers.tsx` — 视图切换：无视图切换（master-detail 固定）；维度缺失但场景合理 | 缺陷
- **[结论]** `src/routes/_layout/douyin-browsers.tsx:159,121,126` — 三态完整性：L159 `isError` + `QueryErrorState` 重试；L121 `isLoading`；L126 空态 | 通过，齐全
- **[结论]** `src/routes/_layout/douyin-browsers.tsx:255,24` — 数据刷新：L255 5s 轮询（浏览器监控需持续，合理）；L24 `retry:false` | 通过
- **[结论]** `src/routes/_layout/douyin-browsers.tsx:23,199` — 组件复用：列表符合场景；`slotKey`（L23/L199）合理但抽离状态 | 通过
- **[性能]** `src/routes/_layout/douyin-browsers.tsx:36,28-34` — 性能：L36 `slots.find` 每次渲染 O(n)；L28-34 `useEffect` 依赖 `slots`，5s 轮询每次触发 effect 重跑 | 缺陷
- **[A11Y]** `src/routes/_layout/douyin-browsers.tsx:82,89,103` — 可访问性：L82 `nav aria-label` 好；L89 button `aria-pressed`；L103 `role=img + aria-label` | 通过，优秀
- **[结论]** `src/routes/_layout/douyin-browsers.tsx:69,209` — 响应式：L69 `xl:grid-cols-5`；L209 iframe 高度自适应 | 通过
- **[结论]** `src/routes/_layout/douyin-browsers.tsx:88` — 行 key：`key={slotKey(slot)}` = slot.name，稳定 | 通过
- **[性能]** 浏览器槽位 — 架构师建议①：**`slots.find` 计算 memo 化**，用 `useMemo` 依赖含 `[slots, selectedName]`，避免每次渲染空遍历 | 减少重复 O(n)
- **[优化]** 浏览器槽位 — 架构师建议②：**刷新 effect 依赖收窄**，L28-34 仅需 `slots` 变化时校正 `selectedName`，可拆出 `selectedStillExists` 判断，减少 effect 触发 | 5s 轮询下每轮重跑
- **[优化]** 浏览器槽位 — 架构师建议③：**槽位搜索/排序（可选）**，槽位超过 5-6 个时加按名称/在线状态排序 | 可定位性

### 作品面板 `components/Douyin/UnifiedWorksPanel.tsx`（1479 行）

- **[BUG]** `src/components/Douyin/UnifiedWorksPanel.tsx:96,852,1291,1299,1363` — 分页：`const [page, setPage] = useState(0)`（L96）；`<Pager>`（L852）；上一页/下一页（L1291/L1299）；`function Pager`（L1363）仅上/下页，**无页码跳转/首末页/每页大小** | 缺陷
- **[BUG]** `src/components/Douyin/UnifiedWorksPanel.tsx` — 筛选架构：无 URL 同步 | 缺陷
- **[BUG]** `src/components/Douyin/UnifiedWorksPanel.tsx` — 三态完整性：`worksQuery.isError` **被完全吞没** | 严重缺陷
- **[BUG]** `src/components/Douyin/UnifiedWorksPanel.tsx:176,198,30,46` — 数据刷新：`refetchInterval: 5_000`（L176/L198）无终态停止；有手动刷新（L30/L46）；`invalidate` 正确尚可 | 严重缺陷
- **[性能]** `src/components/Douyin/UnifiedWorksPanel.tsx` — 性能：无虚拟滚动（`pageSize 50`）；`selected` O(n) | 缺陷
- **[A11Y]** `src/components/Douyin/UnifiedWorksPanel.tsx:79,111,137,577` — 可访问性：Checkbox 有 `aria-label`（L79/L111/L137）并与「同步历史标签」区分；**搜索框仅 placeholder 无 `aria-label`**（L577） | 缺陷
- **[结论]** `src/components/Douyin/UnifiedWorksPanel.tsx:1368` — 响应式：`overflow-x-auto`（L1368） | 通过
- **[结论]** `src/components/Douyin/UnifiedWorksPanel.tsx:850,876,1407` — 行 key：`row.aweme.id`（L850/L876/L1407） | 通过
- **[结论]** `src/components/Douyin/UnifiedWorksPanel.tsx:830-858` — 翻页时 `setPage(nextPage)` + `setSelected([])`（L855-858）清空选择 | 行为正确，但翻页丢失选择
- **[BUG]** 作品面板 — 架构师建议①：**补齐错误态 + 重试**，`worksQuery.isError` 被完全吞没，网络失败时用户只看到「没有符合筛选条件的作品」 | 致命体验缺陷
- **[架构]** 作品面板 — 架构师建议②：**统一视图切换 + URL 双向同步**，改用 `usePersistentViewMode`；筛选变更应 `navigate({ search })` 写回 URL | `validateSearch` 形同虚设
- **[架构]** 作品面板 — 架构师建议③：**合并操作列实现**，内联操作复用 `WorkActionButtons` | 消除三视图分叉

### 跨列表汇总矩阵（12 维度 × 5 列表）

> 导出交错损坏，仅部分行可辨识；判定顺序为 5 个列表列。

- **[BUG]** 汇总矩阵 9. 性能 — 判定为「缺陷 缺陷 缺陷 缺陷 缺陷」（5 列表全部缺陷） | 性能通病普遍
- **[A11Y]** 汇总矩阵 10. 可访问性 — 判定为「✅ / 缺陷(checkbox) / ✅ / 缺陷(input) / ✅」 | Checkbox 与 Input 标签缺失为主要问题
- **[BUG]** 汇总矩阵 11. 响应式 — 判定为「缺陷 / 缺陷 / ✅ / 缺陷 / ✅」 | 3/5 列表响应式缺陷
- **[结论]** 汇总矩阵 12. 行 key — 判定为「✅ ✅ ✅ ✅ ✅」（全通过） | 行 key 普遍正确
- **[BUG]** 汇总矩阵 8. 组件复用 — 判定含「缺陷」（无 Table / 手写 thead-tbody） | 重复造轮子

### 全局共性问题（架构级）

- **[BUG]** 全局共性问题 1 — **错误态普遍缺失（最严重）**：5 个列表中 3 个（互动/日志/标签）无 `isError` 分支，接口失败被吞为「空态文案」，形成运维盲区；只有账号页和浏览器页用了 `QueryErrorState`。**建议统一封装 `<ListState empty/error/loading>` 容器强制三态** | 运维盲区，最严重
- **[架构]** 全局共性问题 2 — **手写 Table 重复造轮子**：4 个表格（35 页全部手写 `<Table>` + 内联列定义，操作列逻辑各自重复）。技术栈已声明 TanStack Table 却未使用。**建议抽取 `DataTable<T>` 通用组件，统一分页/排序/选择/列隐藏/三态** | 重复代码
- **[BUG]** 全局共性问题 3 — **分页两极化**：日志/标签有服务端分页，互动/账号硬编码 `limit:100` 无翻页——同一项目两套策略，**100 条上限是隐性数据丢失** | 数据丢失
- **[BUG]** 全局共性问题 4 — **筛选状态全未同步 URL**：5 个页面无一使用 router `searchParams`，刷新/分享/后退全部丢失筛选上下文，与 TanStack Router 的 URL-first 能力冲突 | 体验缺陷
- **[性能]** 全局共性问题 5 — **派生计算未 memo**：账号 3 次 `filter`（L46/L334）、日志 `taskMap` 重建、标签 2 次 `reduce`（L504）、互动 `rows.some`——每次渲染重复 O(n)，轮询场景下放大 | 轮询放大
- **[风格]** 全局共性问题 6 — **`formatDate` 重复定义 4+ 处**（互动 L617 / 账号 L927 / 日志 L601 / 标签 L242），应抽到 `@/utils` | 重复定义
- **[BUG]** 全局共性问题 7 — **轮询策略不一致**：互动页有终态门控（优秀），账号页 `limit:500` 5s 不停止，`overview` 查询是双重查询（浪费），浏览器页 5s（合理但需服务端分页 + 概览统计接口） | 资源浪费

### 六、架构师改进路线图

- **[架构]** 路线图 步骤 1 — **扩展 DataTable** 为服务端列表骨架：支持 `serverPagination`/`serverSorting`/`rowSelection`/`loading`/`error` props | 类型：架构基建；缓解 T5；ROI ⭐⭐⭐⭐⭐
- **[架构]** 路线图 步骤 2 — **提取 `ListShell` 统一外壳**：封装 筛选栏 + ViewModeToggle + 三态(`QueryErrorState`/骨架/空) + Pager + 刷新，业务列表只传 `query`+`columns`+`filters` | 架构基建；缓解 T2/T5/T9/T10；ROI ⭐⭐⭐⭐⭐
- **[架构]** 路线图 步骤 3 — **提取共享 `Pager`**：合并 3 份重复，支持页码跳转/首末页/每页大小 | 组件抽取；缓解 T10；ROI ⭐⭐⭐⭐
- **[性能]** 路线图 步骤 4 — **`main.tsx` 加 QueryClient defaultOptions**：`staleTime:30_000` + `refetchIntervalInBackground:false` | 1 行改动；缓解 T4；ROI ⭐⭐⭐⭐⭐
- **[优化]** 路线图 步骤 5 — **统一选择模型**：全部 `Array` → `Set<string>` + `.has()` | 批量小改；缓解 T6；ROI ⭐⭐⭐⭐
- **[架构]** 路线图 步骤 6 — **统一 URL 同步**：筛选/分页/排序用 TanStack Router `validateSearch` + `useSearch` | 批量中改；缓解 T3；ROI ⭐⭐⭐⭐
- **[性能]** 路线图 步骤 7 — **封装 `useSmartPolling`**：按业务终态自动停止 + visibility 暂停 | hook 抽取；缓解 T4；ROI ⭐⭐⭐⭐
- **[性能]** 路线图 步骤 8 — **搜索防抖**：6 处加 `useDeferredValue` | 批量小改；缓解 T7；ROI ⭐⭐⭐
- **[性能]** 路线图 步骤 9 — **派生计算 memo**：18 处加 `useMemo` | 批量小改；缓解 T8；ROI ⭐⭐⭐
- **[BUG]** 路线图 步骤 10 — **分页硬编码消除**：10 个 `limit:100` 列表接入服务端分页 | 批量中改；缓解 T1；ROI ⭐⭐⭐⭐
- **[风格]** 路线图 步骤 11 — **`formatDate` 等工具函数抽取** `@/utils` | 小改；缓解 T12；ROI ⭐⭐

### 七、架构师结论

- **[结论]** 架构师结论 — **当前列表架构处于「每个列表各自为政」的作坊式状态**，缺乏统一的列表骨架抽象。核心矛盾是：通用 DataTable 能力（仅客户端分页）≪ 业务需求（服务端分页+排序+选择+多视图+筛选+URL 同步+三态+轮询） | 架构债务定性
- **[结论]** 架构师结论 — 导致 **80% 列表被迫手写**，产生 **16 套重复的 Table 结构、3 份 Pager、4 份 `formatDate`、N 份空态/错误态**。这不是单个 bug 问题，而是**缺少列表层抽象**的架构债务 | 量化债务
- **[结论]** 架构师结论 — **根治方向**：步骤 1-2（扩展 DataTable + 提取 ListShell）是基建，做完后各业务列表从「手写 200 行」降为「配置 30 行」，重复代码自然消除，T2/T5/T9/T10 四项通病一并解决；步骤 4（QueryClient defaultOptions）一行代码缓解最大面积轮询问题 | 一劳永逸方向
- **[结论]** 架构师结论 — 提问：「需要我动手实现步骤 1-2（ListShell + 扩展 DataTable）的架构基建吗？这是提升最大、一劳永逸的方向。」 | 引出下一轮

### 补充：导出损坏区间内的可辨识零散项

- **[结论]** 文档行 68000 附近 — 第三部分报告的小节标题为「请求日志列表 `douyin-request-logs.tsx`（606 行）」/「任务列表 `douyin.tsx`（874 行）」/「视频资源库 `douyin-library.tsx`（1627 行）」/「评论列表 `douyin-comments.tsx`（1206 行）」/「达人列表 `douyin-creators.tsx`（1101 行）」/「浏览器槽位列表 `douyin-browsers.tsx`（233 行）」 | 共 6 个列表 + 标签列表 `douyin-tags.tsx`（249 行）
- **[结论]** 文档行 72074-72101（工具调用结果） — `UnifiedWorksPanel.tsx` 中 `Pager|setPage|pageCount|下一页|上一页` 共 13 处匹配：L96 `useState(0)`、L380/391/414/432/450 `setPage(0)`、L852 `<Pager`、L856 `setPage(nextPage)`、L1291 上一页、L1299 下一页、L1363 `function Pager`、L1385 上一页、L1393 下一页 | 定位分页实现
- **[结论]** 文档行 73122-73168（工具调用结果） — `UnifiedWorksPanel.tsx:830-836` 行选择用 `Array.from(new Set([...current, row.aweme.aweme_id]))` / `current.filter(...)`；L839-843 `onDownload`/`onRetry`/`onRetranslate`；L852-859 `<Pager page={page} count={worksQuery.data?.count ?? 0} onChange={... setPage; setSelected([])}>` | 选择与翻页实现证据
- **[结论]** 文档行 73196-73260（工具调用结果） — `src/components/Common/ViewModeToggle.tsx`（70 行）导出 `ListViewMode = "table" | "rows" | "cards"`、`usePersistentViewMode(storageKey)`（用 `localStorage` 读，仅接受 `rows`/`cards`，否则 `table`）、`ViewModeToggle`（`fieldset` + `sr-only legend` + 3 个 `Button`，`aria-pressed`，中文「表格/横条/卡片」） | 通用三视图组件已存在
- **[结论]** 文档行 73282-73316（工具调用结果） — `UnifiedWorksPanel.tsx:1363-1397` 的 `Pager` 实现：`pages = Math.max(1, Math.ceil(count / pageSize))`；`count <= pageSize` 返回 `null`；渲染「第 {page+1}/{pages} 页 · 共 {count} 项」+ 上一页/下一页按钮 | 无页码跳转
- **[结论]** 文档行 73118-73333（工具调用结果） — `downloadExport(taskId, kind: "comments" | "subtitles", body)` 直接 `fetch POST ${browserApiBase()}/api/v1/douyin/tasks/${taskId}/exports/${kind}`，token 取 `localStorage.getItem("access_token")` | 前端直连导出接口
- **[结论]** 文档行 73132-73168 + 73318 — `UnifiedWorksPanel.tsx` 共 1479 行；`EmptyWorksState loading={worksQuery.isLoading}`（L847） | 空态仅处理 loading
- **[结论]** 文档行 73046-73063（工具调用片段） — 架构建议片段：「补齐错误态：`comments.isError` 完全未处理，应加错误提示 + 重试」；「`comments.isError` 被 `QueryErrorState` 对齐」 | （原文交错，归属存疑）
- **[结论]** 文档行 68000-68050（交错片段） — 第三部分报告第 1 维度「分页」在多数列表判为「通过」，但普遍**缺页码跳转与首末页按钮** | 共性缺陷
- **[结论]** 文档行 68600-69100（交错片段） — 反复出现「全选功能」「列隐藏 `hidden` / `lg:table-cell`」「行号证据」「严重缺陷」等词 | 12 维度口径为：1 分页 / 2 筛选架构 / 3 排序 / 4 选择·批量 / 5 视图切换 / 6 三态完整性 / 7 数据刷新 / 8 组件复用 / 9 性能 / 10 可访问性 / 11 响应式 / 12 行 key
- **[结论]** 文档行 73659-73668 — 用户消息「继续」（附主项目 `https://atomgit.com/qq_41251172/MediaCrawler_Dy_V2`，分支 `main`），随后是 `## 六、架构师改进路线图` | 触发本区间后续交付物
- **[BUG]** 文档行 73758-73760（思考片段） — `main.tsx:39-46` 为 `new QueryClient({ queryCache, mutationCache })` **无 `defaultOptions`**；`DataTable.tsx` 共 194 行，仅 `getCoreRowModel` + `getPaginationRowModel` | 基建现状
- **[结论]** 文档行 74403-74442 — 用户消息：「你不用直接修改给出来计划就行了」；AI 随即**完整回退了刚对 `src/main.tsx` 的修改**（曾加 `defaultOptions: { queries: { staleTime: 30_000, gcTime: 5*60_000, refetchIntervalInBackground: false, retry: 1 }, mutations: { retry: 0 } }`），工作区恢复原状 | 用户要求「只给计划不改代码」
- **[结论]** 文档行 74376-74402 — AI 曾以 `todowrite` 建立 4 项任务：步骤4 `main.tsx` 加 defaultOptions / 步骤1 扩展 DataTable 加三态·中文化·响应式 / 步骤3 提取共享 Pager / 验证 tsc+biome+build | 该 todo 后被用户叫停
- **[结论]** 文档行 74434-74436（工具调用结果） — `DataTable.tsx` 当时签名仅 `{ columns: ColumnDef<TData,TValue>[]; data: TData[] }`；空态文案为英文 `No results found.`（L86）；分页区文案为英文 `Showing … to … of … entries` / `Rows per page` / `Page … of …`，`pageSize` 选项 `[5, 10, 25, 50]`，含首/上/下/末页按钮（`ChevronsLeft/ChevronLeft/ChevronRight/ChevronsRight` + `sr-only` 英文标签） | 中文化与 i18n 缺口
- **[结论]** 文档行 74151-74198（工具调用结果） — `src/components/Common/QueryErrorState.tsx`（46 行）：`props { title, description, onRetry, retrying, className }`；`role="alert"`，`AlertTriangle` 图标，按钮 `retrying ? "正在重试…" : "重试"` | 已有错误态范本

---

## 实施计划

> 《数据列表架构重构 · 实施计划》——基于前期审查（20 列表缺陷 + 40 性能问题 + 212 缺陷），目标是消除「每个列表各自为政」的架构债务，建立统一的列表层抽象。

### 阶段 0：全局配置修复（1 处改动，立即见效）

- **[性能]** 阶段 0-1 — `src/main.tsx:39`：QueryClient 加 `defaultOptions: { queries: { staleTime: 30_000, gcTime: 300_000, refetchIntervalInBackground: false, retry: 1 }, mutations: { retry: 0 } }` | 缓解 T4（12 处轮询不停止/后台轮询）+ 全局 refocus 风暴；1 行代码影响全部 query

### 阶段 1：架构基建（新建 4 个文件，不改现有列表）

- **[架构]** 阶段 1-1 — 扩展通用 DataTable：`src/components/Common/DataTable.tsx`（改写，向后兼容）
- **[架构]** 阶段 1-1 接口 — `DataTableProps<TData,TValue>` 新增（全可选）：`loading?: boolean`（显示骨架行）、`loadingRows?: number`（默认 5）、`error?: { title; description; onRetry?; retrying? } | null`、`emptyText?: string`（默认「暂无数据」） | 三态
- **[架构]** 阶段 1-1 接口 — `serverPagination?: { page: number /* 0-indexed */; pageSize: number; total: number; onPageChange: (page:number)=>void; onPageSizeChange?: (size:number)=>void; pageSizeOptions?: number[] }` | 服务端分页
- **[架构]** 阶段 1-1 接口 — `rowSelection?: { selected: Set<string> /* 统一用 Set */; getRowId: (row:TData)=>string; onToggle: (id:string)=>void; onToggleAll?: (ids:string[])=>void }` | 行选择
- **[架构]** 阶段 1-1 接口 — `scrollX?: boolean`（默认 true，包 `overflow-x-auto`） | 响应式
- **[BUG]** 阶段 1-1 改动要点 — 包裹 `<div className="overflow-x-auto rounded-xl border">`（修 T5 响应式缺失） | 窄屏可用
- **[BUG]** 阶段 1-1 改动要点 — `loading` → 渲染 N 行骨架（`<Skeleton>`），替代当前无加载态；`error` → 复用 `QueryErrorState`，替代当前吞错误 | 三态补齐
- **[i18n]** 阶段 1-1 改动要点 — `emptyText` 中文化，替代 `No results found.`；文案全中文化（`Showing… entries` → 「第 X-Y 条，共 N 条」） | 中文化
- **[BUG]** 阶段 1-1 改动要点 — `serverPagination` → 渲染共享 Pager（见 1-3），替代当前仅客户端分页；`rowSelection` → 表头全选 Checkbox + 行 Checkbox，用 `Set.has()` O(1) | 能力补齐
- **[架构]** 阶段 1-1 兼容性 — **向后兼容**：不传新 props 时行为与当前一致（仅文案中文化 + 加 `overflow-x-auto`） | 低风险
- **[架构]** 阶段 1-2 — 提取 ListShell 统一外壳：`src/components/Common/ListShell.tsx`（新建）
- **[架构]** 阶段 1-2 接口 — `ListShellProps`：`title: string`；`description?: string`；`actions?: React.ReactNode`（PageHero 右侧操作）；`filters?: React.ReactNode`（筛选栏内容）；`viewMode?: { value: ListViewMode; onChange: (v:ListViewMode)=>void }`；`loading: boolean`；`error: { title; description; onRetry; retrying } | null`；`empty: boolean`；`emptyText?: string`；`onRefresh?: () => void`；`refreshing?: boolean`；`children: React.ReactNode`（列表内容 table/cards/rows）；`pager?: PagerProps`（透传给 Pager） | 接口契约
- **[架构]** 阶段 1-2 职责 — 封装 `PageHero` + 筛选栏 + ViewModeToggle + 三态分发 + Pager + 刷新按钮；各业务列表只传配置，不再各自拼装 | 统一外壳
- **[架构]** 阶段 1-2 渲染结构 — `PageHero(title, description, actions=[Refresh, ...])` → `filters` → `Card` → `if error → QueryErrorState` / `else if loading → Skeleton` / `else if empty → EmptyState` / `else → children` → `pager` | 三态分发
- **[架构]** 阶段 1-3 — 提取共享 Pager：`src/components/Common/Pager.tsx`（新建）
- **[架构]** 阶段 1-3 接口 — `PagerProps`：`page: number`（0-indexed）；`pageSize: number`；`total: number`；`onPageChange: (page:number)=>void`；`pageSizeOptions?: number[]`（默认 `[20, 50, 100]`）；`onPageSizeChange?: (size:number)=>void`；`showJumper?: boolean`（页码跳转输入） | 接口契约
- **[架构]** 阶段 1-3 替换范围 — `keywords:1197` / `TaskResults:265` / `UnifiedWorksPanel:1363` / `library:1556` / `comments:648` **五份重复 Pager** | 消除重复
- **[架构]** 阶段 1-4 — 提取智能轮询 hook：`src/hooks/useSmartPolling.ts`（新建）
- **[架构]** 阶段 1-4 接口 — `useSmartPolling<T>(queryKey: unknown[], queryFn: () => Promise<T>, options: { isActive: (data:T)=>boolean; activeInterval: number /* 默认 2000 */; idleInterval?: number /* 默认 false 停止 */; enabled?: boolean }): UseQueryResult<T>` | 接口契约
- **[性能]** 阶段 1-4 替换范围 — 12 处手写 `refetchInterval` 终态判断，统一终态停止逻辑 | 消除轮询不停止

### 阶段 2：列表迁移（逐个接入新基建，可分批 PR）

> 按「缺陷严重度 × 改动成本」排序，分 4 批。

- **[架构]** 批次 2a — 用户管理 `admin.tsx`：已用 DataTable → 传 `serverPagination` + `loading`/`error` props，移除 `limit:100` 硬编码 | 高 ROI 小改
- **[架构]** 批次 2a — items `items.tsx`：同 admin | 高 ROI 小改
- **[BUG]** 批次 2a — 标签 `douyin-tags.tsx`：搜索加 `useDeferredValue`；接 ListShell + Pager；补错误态；`overflow-hidden`→`overflow-x-auto` | 高 ROI 小改
- **[性能]** 批次 2a — 请求日志 `douyin-request-logs.tsx`：`taskMap` 加 `useMemo`；补错误态；筛选状态上 URL | 高 ROI 小改
- **[架构]** 批次 2b — 任务管理 `douyin.tsx`：接 ListShell；筛选上 URL；补服务端排序；`limit:100` → 服务端分页 | 核心业务列表
- **[BUG]** 批次 2b — 视频资源库 `douyin-library.tsx`：筛选双向 URL 同步（修伪 `validateSearch`）；`viewMode` 改 `usePersistentViewMode`；补错误态；`VideoTable` 操作列复用 `WorkActionButtons`；`selected` 改 Set | 核心业务列表
- **[BUG]** 批次 2b — 评论 `douyin-comments.tsx`：补错误态；筛选上 URL；`CommentRow`/`CommentPreviewCard` 操作列合并 | 核心业务列表
- **[BUG]** 批次 2b — 达人 `douyin-creators.tsx`：`limit:200` → 服务端分页；`selected` 改 Set + 补全选；`overviewQuery` 改后端聚合接口；补手动刷新 | 核心业务列表
- **[架构]** 批次 2c — 互动任务 `douyin-interactions.tsx`：`limit:100` → 分页；补错误态；筛选上 URL | 运营管理列表
- **[BUG]** 批次 2c — 账号池 `douyin-accounts.tsx`：`limit:100` → 分页；轮询加终态门控；`CreatePoolDialog` `selected` 改 Set；补 pools 空态 + 账号搜索 | 运营管理列表
- **[BUG]** 批次 2c — 赛道 `douyin-tracks.tsx`：全量拉取 → 服务端分页；`viewMode` 改 `usePersistentViewMode`；补加载骨架 | 运营管理列表
- **[BUG]** 批次 2c — 赛道详情 `douyin-tracks_.$trackId.tsx`：关键词/达人容器内全量滚动 → 服务端分页；轮询加终态停止 | 运营管理列表
- **[BUG]** 批次 2d — 作品面板 `UnifiedWorksPanel.tsx`：`viewMode` 改 `usePersistentViewMode`；补错误态；`selected` 改 Set；8 处派生计算加 `useMemo`；行组件 `React.memo` | 组件内列表
- **[BUG]** 批次 2d — 任务结果 `TaskResults.tsx`：补错误态；三 tab 提取泛型列表；Pager 换共享 | 组件内列表
- **[BUG]** 批次 2d — 媒体任务 `MediaTaskManagement.tsx`：`limit:100` → 分页；轮询加终态停止 | 组件内列表
- **[BUG]** 批次 2d — 媒体管线 `MediaPipelinePanel.tsx`：`limit:100` → 分页；补错误态；`failedAssets` 加 `useMemo`；全局 `isPending` 改按行 | 组件内列表
- **[BUG]** 批次 2d — 任务互动 `TaskInteractionsPanel.tsx`：`limit:10` → 分页；补错误态；轮询终态改 false | 组件内列表

### 阶段 3：性能批量修复（不依赖架构基建，可并行）

- **[性能]** 阶段 3-1 — `UnifiedWorksPanel:646,794,829` + `creators:375` + `keywords:421` + `CreateTaskDialog:466`：`selected` 由 `Array` → `Set`（5 处） | O(n) → O(1)
- **[性能]** 阶段 3-2 — 18 处 render 体 `filter/map/reduce` 加 `useMemo`（依赖 `[rows, selected]`） | 消除重复遍历
- **[性能]** 阶段 3-3 — `Sidebar/Main.tsx:33`：`useRouterState({ select: (s) => s.location.pathname })` | 避免全量订阅
- **[性能]** 阶段 3-4 — 6 处搜索 `onChange` 包 `useDeferredValue` | 搜索防抖
- **[性能]** 阶段 3-5 — `UnifiedWorksPanel:694-942` + `TaskResults:126`：行组件 `React.memo` + 稳定 props | 减少重渲染
- **[性能]** 阶段 3-6 — `request-logs:87`：`taskMap` 加 `useMemo` | 避免每次渲染重建 Map
- **[性能]** 阶段 3-7 — `vite.config.ts`：加 `build.rollupOptions.output.manualChunks` 拆 react/radix/tanstack | 减小首屏 bundle
- **[优化]** 阶段 3-8 — `package.json`：移除 `react-icons` 死依赖 | 清理依赖

### 阶段 4：P0 卡死修复（需后端配合）

- **[BUG]** 阶段 4-1 — `douyin-comments.tsx:987`：导出改调后端流式接口下载 | 后端新增 `POST /comments/export` 返回 `StreamingResponse`
- **[BUG]** 阶段 4-2 — `douyin-library.tsx:420`：字幕导出改后端流式 | 后端新增 `POST /works/export-subtitles`
- **[BUG]** 阶段 4-3 — `douyin-interactions.tsx:161`：批量重试改后端批量接口 | 后端新增 `POST /interactions/batch-retry`
- **[性能]** 阶段 4-4 — `douyin-interactions.tsx:652`：截图懒加载 `IntersectionObserver` | 无需后端

### 验证计划

- **[结论]** 验证 — 每批次 PR 前执行：`cd frontend && npx tsc --noEmit`（类型检查）/ `npx @biomejs/biome check src/`（lint）/ `npm run build`（构建）/ `npx playwright test`（E2E，需后端） | 质量门禁
- **[结论]** 验证 — 架构基建（阶段 1）额外验证：现有 `admin.tsx`/`items.tsx` 不传新 props 时行为不变（回归测试）；DataTable 新 props 三态/服务端分页/行选择单测 | 回归保障

### 工作量估算与依赖

- **[结论]** 工作量 — 阶段 0：改动文件 1；依赖无；可并行 ✅ 立即 | 1 行
- **[结论]** 工作量 — 阶段 1：改动文件 4（新建 3 + 改 1）；依赖无；可并行 ✅ 与阶段 0 并行 | 基建
- **[结论]** 工作量 — 阶段 2a：4 个文件；依赖阶段 1；可并行 ✅ | 迁移
- **[结论]** 工作量 — 阶段 2b：4 个文件；依赖阶段 1；可并行 ✅ 与 2a 并行 | 迁移
- **[结论]** 工作量 — 阶段 2c：4 个文件；依赖阶段 1；可并行 ✅ | 迁移
- **[结论]** 工作量 — 阶段 2d：5 个文件；依赖阶段 1；可并行 ✅ | 迁移
- **[结论]** 工作量 — 阶段 3：约 15 个文件；依赖无；可并行 ✅ 与阶段 2 并行 | 性能
- **[结论]** 工作量 — 阶段 4：3 前端 + 3 后端；依赖后端接口；需跨端协作 | P0
- **[结论]** 建议执行顺序 — 阶段 0 + 1（基建）→ 阶段 3（性能，独立）→ 阶段 2a-2d（迁移）→ 阶段 4（P0，最后） | 推荐路径

---

## 功能增强

> 《列表功能增强与优化建议》——基于前期对 20 个列表的深入审查，从架构师 + 产品视角梳理可添加功能与可优化功能。

### 一、可添加的新功能（当前缺失，按价值排序）

- **[产品]** A1 列自定义/列可见性 — 用户可隐藏/显示列、拖拽排序，窄屏自动隐藏低优先级列。适用所有表格视图。实现：DataTable 加 `columnVisibility` state + 表头设置 DropdownMenu；列定义加 `priority` 字段控制响应式隐藏顺序 | 用户可隐藏/显示列、拖拽排序
- **[产品]** A2 筛选条件 chips 可视化 — 已应用筛选显示为可点 × 移除的标签，一眼看清当前筛选。适用资源库/评论/关键词/互动/日志（多维筛选页）。实现：ListShell 的 filters 区下方渲染 `FilterChip[]`，每个 chip 带 `onRemove` | 筛选可见性
- **[产品]** A3 批量操作工具栏 — 选中行后底部浮现操作栏（删除/导出/标签/状态变更），而非操作散在各处。适用任务/资源库/评论/达人/关键词/互动。实现：选中数 >0 时渲染 `BulkActionBar`（fixed bottom），操作按钮集中，带「已选 N 项 · 清空」 | 批量操作触手可及
- **[产品]** A4 空状态引导 — 空态不只是「暂无数据」文案，要有插图 + 「创建第一个 XX」主按钮。适用全部列表。实现：`EmptyState` 组件（插图 + 标题 + 描述 + CTA 按钮，如「创建赛道」「同步标签」） | 空态转化
- **[产品]** A5 行展开内联详情 — 点击行展开内联子区域看详情，减少弹窗跳转。适用任务/互动/日志/评论。实现：TanStack Table `getExpandedRowModel` + 行 `RowExpander`，展开区渲染摘要字段 | 减少弹窗
- **[产品]** A6 实时数据 diff 高亮 — 轮询返回新数据时，状态变化的行闪一下高亮（如任务状态 queued→running）。适用任务/媒体任务/互动/账号。实现：query `onSuccess` 对比前后 data，变更行 id 写入 state，行组件检测到自身 id 时加 `animate-highlight` class，2s 后清除 | 数据变化实时感知
- **[产品]** A7 行右键菜单 — 右键行弹出操作菜单（复制 ID/打开链接/重试/删除），操作列不再挤。适用任务/资源库/评论/互动。实现：`onContextMenu` + Radix `ContextMenu`，操作列只留 1-2 个高频操作，其余入右键 | 操作列减负
- **[产品]** A8 操作列冻结 — 操作列固定右侧，横向滚动时不消失。适用资源库/评论/日志/互动（列多）。实现：CSS `position: sticky; right: 0` + 背景色遮盖 | 操作列可达
- **[产品]** A9 密度切换 — 紧凑/宽松行高切换，小屏用紧凑看更多行。适用所有表格。实现：复用项目已有 `data-density` token，列表 Card 间距/行 padding 随 density 变化，偏好持久化 | 小屏信息密度
- **[产品]** A10 筛选预设/快捷视图 — 常用筛选组合保存为预设（如「仅失败」「仅今日」「待处理」），一键切换。适用任务/互动/评论/日志。实现：预设存 localStorage，筛选栏左侧渲染预设标签按钮组，点击一键应用全部筛选 | 常用视图一键切换
- **[产品]** A11 列聚合/合计行 — 表格底部显示数值列合计/均值（如任务总数、评论总数、耗时均值）。适用日志（耗时均值）/任务（成功率）/标签（关联数合计）。实现：`TableFooter` + 列定义加 `aggregate: 'sum'|'avg'|'count'` | 数据汇总
- **[产品]** A12 内置导出（当前页/全部/选中） — 列表右上角导出按钮，支持导出当前页/全部/选中为 CSV。适用任务/达人/评论/互动。实现：前端拼当前页 CSV（小量），全部走后端流式（接阶段 4） | 数据消费
- **[产品]** A13 键盘导航 — ↑↓ 选行、Enter 打开详情、Space 勾选、Esc 取消。适用所有列表。实现：`useRowNavigation` hook 管理 `activeRowIndex`，行 `aria-rowindex` + `onKeyDown` | 键盘可用性
- **[产品]** A14 刷新指示器 — 显示「上次更新 3 秒前」+ 自动刷新开关 + 手动刷新。适用所有轮询列表。实现：ListShell actions 区加 `<LastUpdated time={dataUpdatedAt} />` + 轮询 toggle | 刷新可感知
- **[产品]** A15 ID 列复制 — UUID 截断显示 + 悬停全文 + 点击复制。适用任务/作品/评论/互动。实现：`TaskIdentity` 已有短引用，扩展为可复制 `CopyableId` 组件 | ID 易用性
- **[产品]** A16 相对时间 — 「3 分钟前」相对时间 + 悬停显示绝对时间。适用所有时间列。实现：统一 `TimeAgo` 组件替代 4 份重复 `formatDate`，`title` 属性放绝对时间 | 时间可读性

### 二、可优化的现有功能（按影响排序）

- **[优化]** O1 分页器仅上/下一页 → 加页码跳转输入、首末页按钮、每页大小切换、总条数显示 | 5 份重复 Pager → 统一共享 Pager（阶段 1-3）
- **[性能]** O2 搜索无防抖，每次按键发请求 → `useDeferredValue` 300ms 防抖 + 搜索历史（localStorage 最近 5 条） | 8 处搜索框
- **[交互]** O3 筛选即时/draft 模式混用 → 统一为「即时+防抖」模式（赛道/状态等 Select 即时，文本搜索防抖），消除「改了 Select 还要再点查询」困惑 | 日志/评论/资源库
- **[交互]** O4 筛选不持久化，刷新丢失 → 全部上 TanStack Router `validateSearch` + `useSearch`，支持深链分享/书签/后退 | 12 个带筛选列表
- **[性能]** O5 轮询固定间隔不停止 → `useSmartPolling`：终态返回 false 停止 + `refetchIntervalInBackground:false` + 页面不可见暂停 | 12 处轮询
- **[性能]** O6 `selected` 用 `Array`+`includes` O(n) → 统一 `Set<string>` + `.has()` O(1) | 5 处
- **[交互]** O7 全选仅当前页 → 全选改为「本页/全部」两档：本页全选即时，全部全选弹确认（「将选中全部 N 条」） | 任务/资源库/评论/关键词
- **[交互]** O8 加载态纯文案「正在加载…」 → 骨架屏（`<Skeleton>` 行），保留表格结构，避免内容跳动 | 全部列表
- **[BUG]** O9 错误态缺失或文案误导 → 统一 `QueryErrorState`（已有范本），错误态明确区分「无数据」vs「加载失败」 | 13 个列表
- **[交互]** O10 操作列按钮挤一行，窄屏溢出 → 高频操作（1-2 个）保留按钮，低频收纳 `DropdownMenu`；操作列 `sticky right` 冻结 | 资源库/评论/互动/账号
- **[架构]** O11 视图切换持久化不统一 → 全部改 `usePersistentViewMode`，消除手写 localStorage / 无持久化 | 资源库/赛道/作品面板
- **[BUG]** O12 三视图功能不对等 → 统一操作列组件（如 `WorkActionButtons`），确保 cards/rows/table 三视图操作一致 | 资源库/赛道
- **[性能]** O13 派生计算未 memo，轮询重算 → 18 处 `filter/map/reduce` 加 `useMemo`，`lastMediaActivity` 用时间戳数字比较替代 `new Date()` | 全部列表
- **[性能]** O14 行组件每行挂载重 hook → `React.memo` + 稳定 props；或改为单实例 + `activeRowId` 驱动 | UnifiedWorksPanel/TaskResults
- **[交互]** O15 `window.confirm` 做危险确认 → 统一 `AlertDialog`，可自定义内容，可测试 | 10+ 处
- **[风格]** O16 状态徽章颜色硬编码 → 走 CSS 变量 token，响应 skin 切换 | MetricCard/StatusPill/CreatorAvatar/TaskExecutionProgress
- **[风格]** O17 `formatDate` 4+ 份重复且格式不一 → 抽 `@/utils/time.ts` 统一 `formatDate/formatUnix/timeAgo` | 互动/账号/日志/标签/作品面板/任务结果
- **[交互]** O18 全局 `isPending` 禁用所有行 → 追踪 `activeRowId`，仅禁用当前操作行 | MediaPipelinePanel/账号
- **[性能]** O19 大列表全量渲染 DOM → `@tanstack/react-virtual` 虚拟滚动，仅渲染可视区 + 上下缓冲 | 达人(200 行)/互动事件/监控步骤
- **[BUG]** O20 排序部分缺失 → 无排序的列表（任务/互动/账号/日志）补服务端排序，表头可点击 + 排序指示器 | 6 个列表

### 三、功能 × 列表优先级矩阵

- **[产品]** 任务管理 — 最该添加：A6 diff 高亮、A10 快捷视图、A14 刷新指示；最该优化：O4 筛选上 URL、O20 补排序、O5 轮询停止
- **[产品]** 视频资源库 — 最该添加：A1 列自定义、A2 筛选 chips、A3 批量工具栏、A8 操作列冻结；最该优化：O4 URL 双向同步、O9 错误态、O12 三视图对等
- **[产品]** 评论 — 最该添加：A5 行展开、A12 内置导出、A2 筛选 chips；最该优化：O9 错误态、O4 筛选上 URL、O10 操作列收纳
- **[产品]** 达人 — 最该添加：A3 批量工具栏、A19 虚拟滚动、A10 快捷视图；最该优化：O6 `selected` 改 Set、O5 轮询停止、O20 补排序
- **[产品]** 互动任务 — 最该添加：A6 diff 高亮、A5 行展开、A7 右键菜单；最该优化：O9 错误态、O4 筛选上 URL、O10 操作列收纳
- **[产品]** 请求日志 — 最该添加：A11 列聚合（耗时均值）、A16 相对时间、A1 列自定义；最该优化：O9 错误态、O20 补排序（按耗时）、O2 搜索防抖
- **[产品]** 账号池 — 最该添加：A9 密度切换、A14 刷新指示；最该优化：O5 轮询终态门控、O18 行级 loading、O6 `selected` 改 Set
- **[产品]** 关键词 — 最该添加：A2 筛选 chips、A10 快捷视图；最该优化：O9 错误态、O6 `selected` 改 Set、O2 搜索防抖
- **[产品]** 作品面板 — 最该添加：A6 diff 高亮、A1 列自定义、A8 操作列冻结；最该优化：O14 行组件 memo、O6 `selected` 改 Set、O13 派生计算 memo

### 四、实施建议

- **[架构]** 第一优先（基建赋能） — A1/A2/A3/A4/A8 五个功能都依赖阶段 1 的 `ListShell` + 扩展 `DataTable` 基建；基建完成后这些功能成为「配置项」而非「每列表重写」
- **[优化]** 独立可做（不依赖基建） — A15(复制 ID)/A16(相对时间)/O2(防抖)/O6(Set)/O13(memo)/O15(AlertDialog)/O17(统一 `formatDate`) 可立即逐项推进
- **[产品]** 产品价值最高 — A2(筛选 chips) + A3(批量工具栏) + A6(diff 高亮) + A10(快捷视图) 四项对用户体感提升最大：一眼看清筛选状态、批量操作触手可及、数据变化实时感知、常用视图一键切换

---

## 产品优化

> 《产品架构师视角 · 前端产品优化分析》——跳出代码层面，从产品体验闭环、信息架构、用户旅程、数据洞察、效率能力等维度分析。

### 一、信息架构与导航（产品骨架）

- **[产品]** IA1 — 现状：20 个页面平铺在侧边栏/顶部导航，无分组；问题：新用户面对 20 个一级入口认知过载，不知道从哪开始；优化：按「**采集配置 → 数据采集 → 内容运营 → 资源管理 → 系统**」四组折叠分组，每组带图标 + 说明 | 降低入门认知成本
- **[产品]** IA2 — 现状：赛道（track）是核心组织维度但入口不突出；问题：赛道详情是所有数据的归属枢纽，却在导航中与普通页平级；优化：赛道提升为**一级工作空间**概念，顶部赛道切换器（类似 Linear 的 team 切换），全站数据按当前赛道过滤 | 数据组织更清晰
- **[交互]** IA3 — 现状：深层页面（任务详情/沉浸播放/赛道详情）无面包屑；问题：用户在 `$taskId/feed` 不知道属于哪个赛道/任务；优化：加 `Breadcrumb`：赛道 > 任务 > 沉浸播放，可点击逐级返回 | 定位感
- **[交互]** IA4 — 现状：无全局快速跳转；问题：20 个页面只能通过导航逐个点；优化：`Cmd+K` Command Palette：搜索页面/任务/赛道/达人，快捷跳转 + 最近访问 | 专家用户效率
- **[产品]** IA5 — 现状：品牌名三处不一致（灵感采集台 / 运营工作台 / 抖音内容运营工作室）；问题：产品身份模糊；优化：统一产品名 + Logo，定义产品定位语 | 品牌一致性

### 二、用户旅程与任务流（体验闭环）

- **[产品]** UJ1 — 现状：新用户登录后看到空 dashboard，无引导；问题：不知道「先建赛道→加关键词→建任务→登录账号→运行」的流程；优化：**首次引导 Checklist**：4 步引导卡（①创建赛道 ②添加关键词 ③登录抖音账号 ④创建首个任务），完成打勾，可跳过 | 降低流失率
- **[交互]** UJ2 — 现状：创建任务是一个大 Dialog（828 行），所有参数一屏堆；问题：新手面对「来源类型/关键词/达人/并发/间隔/评论数/子评论…」20+ 参数迷失；优化：改为**分步向导**：①选赛道 → ②选来源(搜索/详情/达人/点赞/收藏) → ③配置参数(分基础/高级折叠) → ④预览确认，每步有说明 | 降低创建门槛
- **[交互]** UJ3 — 现状：创建任务时不知道有没有可用账号；问题：没登录账号也能建任务，运行时才报「无可用账号」；优化：创建任务 Dialog 顶部显示**账号可用性状态**（「3 个账号可用」/ ⚠️「无可用账号，去登录」），前置阻断 | 减少失败任务
- **[交互]** UJ4 — 现状：任务完成后无下一步引导；问题：任务 succeeded 后用户不知道去哪看数据；优化：任务完成态加**下一步快捷入口**：「查看作品数据 →」「进入沉浸播放 →」「批量互动 →」 | 形成体验闭环
- **[产品]** UJ5 — 现状：媒体流水线（下载→字幕→翻译→迁移）全手动逐步触发；问题：用户要守着任务，每步完成手动点下一步；优化：**Pipeline 编排**：配置一次「下载完自动转 9 字幕 → 自动翻译 → 自动迁移 MinIO」，任务跑完全自动。当前 `MediaPipelinePanel` 只展示状态，不编排 | 核心效率提升（原文此处损坏，已尽力还原）

### 三、数据洞察与可视化（产品价值呈现）

- **[产品]** DV1 — 现状：首页 dashboard 仅 4 个数字卡片 + 任务列表；问题：无趋势、无待办、无活动流，首页价值低；优化：重构 dashboard：①**采集趋势图**（近 7 天任务/作品/评论数折线）②**待办区**（失败任务/待登录账号/待确认互动）③**最近活动 timeline** ④**赛道健康度**概览卡片 | 首页成为指挥中心
- **[产品]** DV2 — 现状：无全局统计/报表；问题：无法回答「总采集了多少、成功率多少、互动转化多少」；优化：新增**统计概览页**：总作品数/评论数/达人数、采集成功率、互动发送成功率、账号利用率，支持按赛道/时间筛选 | 量化运营效果
- **[产品]** DV3 — 现状：任务进度是文字 + 数字；问题：缺少可视化阶段图，不知道卡在哪一步；优化：`TaskExecutionProgress` 改为**阶段流水图**（登录→采集→评论→媒体），每阶段带进度条 + 耗时 + 状态色，失败阶段高亮 + 错误详情 | 运行可观测性
- **[产品]** DV4 — 现状：请求日志只列表，无分析；问题：排查问题靠翻日志，无错误率/慢请求统计；优化：日志页加**分析面板**：错误率趋势、Top 5 慢请求、Top 5 错误接口、状态码分布饼图 | 运维效率
- **[产品]** DV5 — 现状：账号池只显示状态枚举；问题：不知道账号健康度、为何 cooldown、今日配额消耗；优化：账号卡片加**健康度评分**（成功率/响应时长/配额消耗环形图）+ cooldown 倒计时 + 最近错误 | 账号可观测性

### 四、效率能力（批量/模板/自动化）

- **[产品]** EF1 — 现状：任务只能逐个创建；问题：对多个赛道/关键词要重复创建 N 次；优化：**批量创建**：选多个赛道 + 共享配置 → 一次创建 N 个任务 | 批量运营
- **[产品]** EF2 — 现状：任务配置不能复用；问题：每次都要重设并发/间隔/评论数等；优化：**任务模板**：保存常用配置为模板（如「标准视频采集」「深度评论采集」），创建时一键套用 | 减少重复配置
- **[产品]** EF3 — 现状：无定时/周期任务；问题：不能「每天凌晨自动采集新作品」；优化：**定时任务**：cron 表达式配置周期采集，任务列表显示下次执行时间 | 自动化运营
- **[产品]** EF4 — 现状：无任务依赖/编排；问题：不能「采集完自动转字幕再迁移」；优化：**任务链**：配置 A→B→C 依赖，A 成功自动触发 B（与 UJ5 pipeline 编排互补） | 自动化流水线（原文此处损坏，已尽力还原）
- **[产品]** EF5 — 现状：互动内容（评论话术）每次手写；问题：不能管理话术库复用；优化：**话术模板库**：评论/私信话术存库 + 变量插槽（`{nickname}`），互动时选模板 | 互动效率
- **[产品]** EF6 — 现状：无数据导出中心；问题：导出散在各列表（评论/字幕），且前端全量加载卡死；优化：统一**导出中心**：选择数据类型/范围/格式 → 后端异步生成 → 下载中心拉取 | 数据消费

### 五、配置与个性化

- **[产品]** CF1 — 现状：主题/密度/布局切换散在用户菜单；问题：无统一偏好设置入口；优化：**偏好设置页**：外观（skin/密度/布局/圆角）+ 通知 + 默认筛选 + 语言，一处管理 | 个性化
- **[产品]** CF2 — 现状：无通知配置；问题：任务失败/完成无主动通知，靠用户刷新；优化：**通知配置**：任务完成/失败时 → 浏览器通知 / 邮件 / webhook，按赛道/严重度配置 | 主动触达
- **[产品]** CF3 — 现状：无自定义 dashboard 布局；问题：首页卡片固定，用户不能按关注点调整；优化：dashboard 卡片可拖拽排序 + 显隐，布局存 localStorage | 千人千面
- **[产品]** CF4 — 现状：筛选预设不能保存；问题：常用筛选每次重设（已在列表分析提 A10，此处产品视角）；优化：**保存当前筛选为预设**，命名后入快捷栏，可设为默认 | 效率

### 六、反馈与通知

- **[产品]** FB1 — 现状：toast 消息稍纵即逝；问题：错过 toast 就看不到操作结果；优化：**通知中心**：铃铛 icon + 未读角标，留存最近 50 条通知（任务完成/失败/账号掉线），可标记已读 | 信息不丢失
- **[产品]** FB2 — 现状：长任务完成无主动通知；问题：用户要反复刷新看任务是否完成；优化：任务终态时触发**浏览器 Notification API**（已授权）+ 标签页标题角标 `(2)` | 离开也能感知
- **[产品]** FB3 — 现状：前端错误只进 console；问题：用户遇到白屏/报错无法反馈；优化：**错误边界 + 上报**：捕获前端异常，展示友好错误页 + 「复制错误信息」+ 上报后端 | 可观测

### 七、帮助与引导

- **[产品]** HP1 — 现状：复杂概念（赛道/来源类型/CDP/互动写回/脱敏）无解释；问题：新手不懂「赛道」是什么、CDP 浏览器 vs 本机浏览器区别；优化：关键概念加**信息提示气泡**（`?` icon hover 出解释），首次出现时自动弹出 tooltip | 降低学习曲线
- **[产品]** HP2 — 现状：无用户使用文档；问题：developer-tools 只有 API 文档，无操作指南；优化：产品内嵌**帮助面板**：按页面提供操作指引（「如何创建采集任务」步骤图文），`Cmd+?` 触发 | 自助学习
- **[产品]** HP3 — 现状：空状态纯文案「暂无数据」；问题：不告诉用户怎么创建；优化：空状态加**引导 CTA**（「创建第一个赛道」按钮 + 简要说明），已在列表分析提 A4 | 空状态转化

### 八、多端与边界

- **[产品]** MB1 — 现状：整个应用为桌面 1280px+ 设计；问题：移动端表格溢出、Dialog 全屏、操作不可用；优化：**移动端适配**：列表改卡片堆叠、Dialog bottom-sheet、导航改底部 tab bar。优先适配「任务监控/账号状态」等需要移动查看的场景 | 移动可用性
- **[产品]** MB2 — 现状：无 PWA；问题：不能离线查看已采集数据；优化：**PWA 化离线壳**：缓存已加载列表数据，离线可浏览，在线自动同步 | 离线韧性

### 九、产品架构师优先级建议（按「产品影响 × 实现可行性」分四象限）

- **[产品]** 必做（高影响 + 可行）：**UJ1** 首次引导 Checklist — 直接降低新用户流失，无后端依赖
- **[产品]** 必做（高影响 + 可行）：**IA1** 导航分组 — 20 入口一级平铺造成认知过载，是当前最突出的产品体验问题（原文此处损坏，已尽力还原）
- **[产品]** 必做（高影响 + 可行）：**DV1** dashboard 重构 — 首页是指挥中心，当前价值极低
- **[产品]** 必做（高影响 + 可行）：**UJ3** 创建任务前账号可用性阻断 — 减少失败任务，前置体验
- **[产品]** 必做（高影响 + 可行）：**FB1** 通知中心 — 操作结果不丢失，基础体验
- **[产品]** 必做（高影响 + 可行）：**HP1** 概念信息气泡 — 降低学习曲线，低成本高回报
- **[产品]** 应做（高影响 + 中等可行）：**UJ2** 创建任务分步向导 — 828 行 Dialog 是最大门槛
- **[产品]** 应做（高影响 + 中等可行）：**UJ5/EF4** Pipeline 编排 + 任务链 — 核心效率，从手动到自动化的质变
- **[产品]** 应做（高影响 + 中等可行）：**EF2** 任务模板 — 减少重复配置
- **[产品]** 应做（高影响 + 中等可行）：**DV2** 统计概览页 — 量化运营效果
- **[产品]** 应做（高影响 + 中等可行）：**IA2** 赛道工作空间切换器 — 数据组织核心
- **[产品]** 应做（高影响 + 中等可行）：**IA4** Cmd+K 快速跳转 — 专家效率
- **[产品]** 可做（中影响 + 高可行）：**EF5** 话术模板库 — 互动效率
- **[产品]** 可做（中影响 + 高可行）：**CF1** 偏好设置页 — 个性化收口
- **[产品]** 可做（中影响 + 高可行）：**FB2** 浏览器通知 — 离开感知
- **[产品]** 可做（中影响 + 高可行）：**IA3** 面包屑 — 定位感
- **[产品]** 可做（中影响 + 高可行）：**DV5** 账号健康度 — 可观测性
- **[产品]** 远期（高影响 + 低可行/需后端）：**EF3** 定时任务 — 需后端调度器
- **[产品]** 远期（高影响 + 低可行/需后端）：**EF6** 导出中心 — 需后端异步导出
- **[产品]** 远期（高影响 + 低可行/需后端）：**MB1** 移动端适配 — 工作量大
- **[产品]** 远期（高影响 + 低可行/需后端）：**DV4** 日志分析面板 — 需后端聚合接口
- **[结论]** 核心结论 — 当前产品**功能齐全但体验闭环不完整**：能采集、能运营，但用户**不知道从哪开始**（缺引导）、**不知道做得怎样**（缺洞察）、**不能自动化**（缺编排）、**离开就失联**（缺通知）。产品架构师最该补的三件事：**①首次引导闭环 ②dashboard 洞察 ③Pipeline 自动化编排**——这三项让产品从「能用」升级为「好用且离不开」

---

## PRD

> 《PRD：媒体流水线自动编排（Pipeline Orchestration）》
> **导出损坏与截断说明**：该段原文混入 `-trackId）`、`5>`、`8>`、`Dy_V2`、`同时转9字幕`、`A处理A`、`�` 等垃圾 token，语义已尽力还原并就地标注「（原文此处损坏，已尽力还原）」；文件在 `interface PipelineTemplate { id; name; description?` 之后**中途截断**，已标注「（原文到此截断）」。

### 1. 概述

- **[产品]** 1.1 背景 — 当前媒体处理流程是**纯手动逐步触发**：采集完成 → 用户手动创建下载任务 → 下载完手动点「处理媒体」（字幕提取/翻译）→ 处理完手动点「迁移到 MinIO」。用户必须守着任务，每步完成手动点下一步。`MediaPipelinePanel` 只展示状态，不编排（原文此处损坏，已尽力还原）
- **[产品]** 1.2 目标 — 让用户**配置一次 Pipeline 模板**，任务采集完成后**自动执行** 下载 → 字幕提取 → 翻译 → 迁移 全链路，无需人工逐步触发；支持按赛道绑定不同 Pipeline，支持条件跳过/失败重试/通知
- **[产品]** 1.3 非目标 — 不改动采集任务本身的执行逻辑（爬虫引擎不变）
- **[产品]** 1.3 非目标 — 不做跨任务依赖编排（A 任务触发 B 任务，属「任务链」另立 PRD）
- **[产品]** 1.3 非目标 — 不做定时调度（属「定时任务」另立 PRD）

### 2. 用户问题与场景

- **[产品]** 2.1 问题陈述（用户原声）— 「我每天采集 5 个赛道的视频，每个赛道采集完都要手动点下载、等下载完手动再点转字幕、等字幕完再点迁移到云端。一天要重复几十次，经常忘记某步导致数据没就绪。」——运营人员（原文此处损坏，已尽力还原）
- **[产品]** 2.2 目标用户 — 运营人员：配置 Pipeline 后自动跑，不再守任务
- **[产品]** 2.2 目标用户 — 管理员：为不同赛道配置不同 Pipeline 策略
- **[产品]** 2.3 场景 S1 标准自动 — 采集完 → 自动下载 → 自动字幕 → 自动迁移 MinIO
- **[产品]** 2.3 场景 S2 按需字幕 — 采集完 → 自动下载 → 仅对 >30s 视频提取字幕 → 迁移（原文此处损坏，已尽力还原）
- **[产品]** 2.3 场景 S3 多语翻译 — 采集完 → 下载 → 字幕 → 翻译英/日 → 迁移
- **[产品]** 2.3 场景 S4 仅下载 — 采集完 → 仅自动下载，不转字幕（快速预览场景）（原文此处损坏，已尽力还原）
- **[产品]** 2.3 场景 S5 手动介入 — 「Pipeline 自动下载，但字幕和迁移我手动」（半自动）（原文此处损坏，已尽力还原）

### 3. 功能需求（用户故事 + 验收标准）

- **[产品]** US1 创建 Pipeline 模板 — 作为运营人员，我希望保存一套媒体处理流程为模板，以便复用到多个赛道
- **[产品]** US1 验收 — 可在「设置 > Pipeline 模板」页创建/编辑/删除模板
- **[产品]** US1 验收 — 模板含有序步骤列表，每步配置：动作类型 / 条件 / 失败策略
- **[产品]** US1 验收 — 模板可命名 + 描述，可设为某赛道默认（原文此处损坏，已尽力还原）
- **[产品]** US2 为赛道绑定 Pipeline — 作为运营人员，我希望给赛道绑定一个 Pipeline 模板，该赛道下任务采集完自动执行
- **[产品]** US2 验收 — 赛道详情页可选择绑定的 Pipeline 模板（或「无自动处理」）（原文此处损坏，已尽力还原）
- **[产品]** US2 验收 — 采集任务进入 `succeeded` 后，自动创建对应的媒体任务链，按模板步骤执行（原文此处损坏，已尽力还原）
- **[产品]** US2 验收 — 赛道列表显示「已绑定 Pipeline: 标准自动」标签
- **[产品]** US3 查看 Pipeline 执行进度 — 作为运营人员，我希望在任务详情看到 Pipeline 各步骤的实时进度和状态
- **[产品]** US3 验收 — 任务详情「媒体」tab 展示 Pipeline 步骤流水图（下载→字幕→翻译→迁移）
- **[产品]** US3 验收 — 每步显示：状态(pending/running/succeeded/failed/skipped) + 进度 + 耗时 + 错误信息
- **[产品]** US3 验收 — 失败步骤可单独「重试此步」（原文此处损坏，已尽力还原）
- **[产品]** US3 验收 — 条件跳过的步骤标记 `skipped` 并显示跳过原因
- **[产品]** US4 手动介入/暂停 — 作为运营人员，我希望能在某步暂停自动流程，手动处理后再继续
- **[产品]** US4 验收 — 模板步骤可标记「自动」或「手动确认」
- **[产品]** US4 验收 — 标记「手动确认」的步骤执行到时暂停，等用户在 UI 点「确认执行」
- **[产品]** US4 验收 — 可整体「暂停 Pipeline」，当前步完成后不再自动触发下一步
- **[产品]** US5 失败处理策略 — 作为运营人员，我希望某步失败时按策略处理，而不是整个 Pipeline 静默卡住（原文此处损坏，已尽力还原）
- **[产品]** US5 验收 — 每步可配失败策略：`重试N次` / `跳过继续` / `终止Pipeline` / `通知用户`（原文此处损坏，已尽力还原）
- **[产品]** US5 验收 — 重试有指数退避，达上限后按策略降级
- **[产品]** US5 验收 — 失败通知进入通知中心（接 FB1）

### 4. 信息架构与交互设计

- **[交互]** 4.1 新增页面/入口 — Pipeline 模板管理：路由 `/settings/pipelines`，入口为设置页新 tab「Pipeline」
- **[交互]** 4.1 新增页面/入口 — 赛道绑定：位于赛道详情页，赛道详情头部「Pipeline: [选择器]」（原文此处损坏，已尽力还原）
- **[交互]** 4.1 新增页面/入口 — 执行进度：任务详情「媒体」tab，现有 `MediaPipelinePanel` 升级
- **[交互]** 4.2 Pipeline 模板编辑器交互（线框）— 头部「Pipeline 模板：标准自动」+ 描述「采集完自动下载+字幕+迁移」；步骤卡片纵向排列并以 ↓ 连接；每张卡片含「动作 / [自动▼|手动确认▼] / 条件 / 失败策略」；底部「[+ 添加步骤]  [保存模板]」
- **[交互]** 4.2 线框-步骤 1 — 动作：下载媒体 `[自动 ▼]`；条件：所有作品；失败策略：重试 3 次 → 通知
- **[交互]** 4.2 线框-步骤 2 — 动作：提取字幕 `[自动 ▼]`；条件：时长 > 30 秒；失败策略：跳过继续
- **[交互]** 4.2 线框-步骤 3 — 动作：翻译字幕 `[手动确认 ▼]`；目标语言：英语、日语
- **[交互]** 4.2 线框-步骤 4 — 动作：迁移存储 `[自动 ▼]`；目标：MinIO
- **[交互]** 4.3 任务详情 Pipeline 执行视图（线框）— 头部「Pipeline: 标准自动   状态: 运行中   ⏸暂停」；步骤列表逐条展示：
  - `● 下载媒体  ✓ 成功 · 423 个   12s`
  - `● 提取字幕  ✓ 成功   387 个   45s`（附注：36 个跳过：时长 < 30s）
  - `● 翻译字幕  ⟳ 运行中 350/387  ──▓▓▓▓▓░░░ 72%`
  - `○ 迁移存储  ◌ 等待中`
  - 底部操作：`[重试失败] [跳过此步] [查看详情]`

### 5. 数据模型 / 接口设计

- **[数据]** 5.1 Pipeline 模板（前端类型，最终由后端 OpenAPI 生成）— `type PipelineStepAction = "download" | "extract_subtitle" | "translate_subtitle" | "migrate_storage"`；`type StepExecution = "auto" | "manual_confirm"`（原文此处损坏，已尽力还原）
- **[数据]** 5.1 `interface PipelineStep` — `id: string`；`action: PipelineStepAction`；`execution: StepExecution`
- **[数据]** 5.1 `PipelineStep.condition?` — `{ field: "duration_seconds" | "has_subtitle" | "storage_backend" | "all"; operator: "gt" | "lt" | "eq" | "exists"; value: number | string | boolean }`（原文此处损坏，已尽力还原）
- **[数据]** 5.1 `PipelineStep.params` — `{ /* download */; /* extract_subtitle: { language?: string } */; /* translate_subtitle: { target_languages: string[] } */; /* migrate_storage: { target: "minio" | "default" } */; [key: string]: unknown }`
- **[数据]** 5.1 `PipelineStep.failure_strategy` — `{ on_failure: "retry" | "skip" | "abort" | "notify"; max_retries?: number; retry_backoff_seconds?: number }`
- **[数据]** 5.1 `interface PipelineTemplate` — `id: string`；`name: string`；`description?: string` | **（原文到此截断）**——文件在 `description?: string` 之后无后续内容，会话导出结束

---

## 小结（本区间交付物清单）

- **[结论]** 交付物 1/5 — 列表缺陷报告收尾部分：7 个列表（`douyin.tsx`/`douyin-library.tsx`/`douyin-request-logs.tsx`/`douyin-tags.tsx`/`douyin-comments.tsx`/`douyin-creators.tsx`/`douyin-browsers.tsx`）+ `UnifiedWorksPanel.tsx` × 12 维度判定
- **[结论]** 交付物 2/5 — 全局共性问题 7 条 + 「六、架构师改进路线图」11 步 + 「七、架构师结论」
- **[结论]** 交付物 3/5 — 《数据列表架构重构 · 实施计划》（阶段 0/1/2/3/4 + 验证计划 + 工作量估算）
- **[结论]** 交付物 4/5 — 《列表功能增强与优化建议》（A1-A16 + O1-O20 + 优先级矩阵）
- **[结论]** 交付物 5/5 — 《产品架构师视角 · 前端产品优化分析》（IA/UJ/DV/EF/CF/FB/HP/MB + 四象限）与《PRD：媒体流水线自动编排》
