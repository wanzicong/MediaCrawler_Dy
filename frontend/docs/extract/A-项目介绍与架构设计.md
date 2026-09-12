# A - 项目介绍与架构设计（提取自 `docs/前端项目分析.md` 第 1-6041 行）

> 覆盖范围：第 1 行 ～ 第 6041 行。已剔除纯自我推演的思考过程正文、工具调用 JSON 参数原文、被读取文件内容原文、重复注入的 `# 项目开发约定`/`AGENTS.md` 章节、第 56-420 行的 `ag-cli` 技能文档。
> 条目类型：`BUG` / `性能` / `优化` / `架构` / `产品` / `交互` / `风格` / `安全` / `A11Y` / `i18n` / `数据` / `结论`

---

## 0. 仓库与分支基础事实

- **[数据]** 主项目 `https://atomgit.com/qq_41251172/MediaCrawler_Dy_V2`；会话中第 1 轮指定分支 `dev`，第 2/4 轮指定 `main`。
- **[结论]** 该仓库**不存在 `main` 分支**；默认分支为 `refactor/uv-workspace-modules`，另有 `dev` 分支（第 1122-1191 行实测）。
- **[数据]** 远程分支清单（第 1153-1191 行）：`dev`、`refactor/uv-workspace-modules`，以及 15 个 dependabot 分支（bun: lucide-react、radix-ui/react-scroll-area、sonner、tailwindcss/vite、tanstack/react-query-devtools；docker: frontend/playwright；github_actions: checkout-7、download-artifact-8、setup-python-7、dorny/paths-filter-4、tiangolo/latest-changes-0.7.2；uv: alembic、pwdlib、pydantic、pydantic-settings、ruff）。
- **[结论]** `dev` 与默认分支 `refactor/uv-workspace-modules` 的前端差异**仅 2 个文件**：`frontend/src/routes/login.tsx`（4 行）、`frontend/tsconfig.json`（1 行），共 3 插入 2 删除（第 1235-1238 行）；因此基于 dev 的前端结论对默认分支通用。
- **[数据]** 两分支 `frontend/src/routes` 下文件数均为 **26**（第 1239-1243 行）。
- **[结论]** 仓库根目录共 27 个条目，含 `frontend/`、`modules/`、`docs/`、`scripts/`、`tests/`、`compose.yml`、`compose.infra.yml`、`uv.lock`、`bun.lock`（第 244-273 行）。
- **[数据]** `frontend/` 目录共 22 个条目，含 `biome.json`、`components.json`、`Dockerfile`、`Dockerfile.playwright`、`nginx.conf`、`nginx-local-api.conf`、`nginx-backend-not-found.conf`、`openapi-ts.config.ts`、`playwright.config.ts`、`tsconfig.build.json`/`tsconfig.json`/`tsconfig.node.json`、`vite.config.ts`（第 294-318 行）。

## 1. 项目介绍（第 1 轮，第 1-1088 行）

### 1.1 项目定位与后端背景

- **[数据]** 项目全称「抖音采集工作台（Douyin Crawler Full Stack）」，基于 FastAPI 官方 `full-stack-fastapi-template` 0.10.0 构建（第 335-341 行）。
- **[数据]** 后端把 MediaCrawler 的抖音请求逻辑重构为**纯 HTTP API 服务**，面向搜索、作品详情、创作者主页、点赞/收藏等采集场景。
- **[架构]** 后端保留模板原有 FastAPI、React、JWT、SQLModel/PostgreSQL、Alembic、Docker Compose 与 CI/CD 体系。
- **[安全]** 合规声明：抖音适配代码沿用 MediaCrawler 的 **NON-COMMERCIAL LEARNING LICENSE 1.1**，仅限非商业学习与研究；官方模板部分遵循根目录 MIT LICENSE（第 343-345 行）。
- **[架构]** 后端采用 uv workspace 多项目架构，`modules/` 下**六个**独立 Python 项目共享 `crawler.*` 命名空间（PEP 420），依赖方向由打包元数据与 `tests/architecture/` 契约测试**双重强制**（第 408-409 行）。
- **[架构]** 后端模块边界（AGENTS.md 摘要，第 415-477 行）：`bootstrap`（运行配置/DB 引擎/安全日志原语，不依赖任何模块）→ `browser`（CDP-only 运行时，只依赖 bootstrap）→ `douyin-client`（抖音传输适配、a_bogus 签名、登录、互动写回、脱敏）→ `business`（业务域全部内容，含 models.py/service.py、resources/、concurrency/、alembic/）→ `api`（HTTP 入站适配）；`mcp -> bootstrap`。
- **[架构]** 依赖方向固定为 `api -> business -> douyin-client -> browser -> bootstrap`，**禁止反向依赖**；`crawler/api/main.py` 是运行时组合根，`crawler/bootstrap/settings.py` 提供全局配置。
- **[架构]** API 路由**禁止**直接使用 SQLAlchemy/SQLModel 查询（登记的运维脚本除外）、MinIO、Playwright、文件路径判断或事务操作；MinIO SDK 只允许出现在 `business/resources/storage/` 驱动中。
- **[架构]** 唯一登记的越界例外：`routes/system_docs.py` 自省 `crawler.mcp.server` 的工具元数据。
- **[数据]** 后端核心特性（README 第 374-386 行）：多类型采集任务五类 `search`/`detail`/`creator`/`liked`/`collected`；CDP-only 浏览器控制；扫码/Cookie 登录；断点恢复；媒体流水线（视频下载 + 远程 Whisper 字幕 + 本地/MinIO 双存储）；赛道归类（`track_id`）；MCP 接入（Streamable HTTP/stdio）；公平限流与账号槽位；隐私脱敏（HMAC + 昵称打码）。
- **[安全]** 必须遵守：Cookie、Token 和原始账号 ID 不得写入数据库、日志或 API 响应；创作者/评论用户信息必须经脱敏映射后落库。

### 1.2 前端技术栈与依赖（量化）

- **[数据]** 前端技术栈：React **19** + TypeScript **5.9**、Vite **7**（SWC 插件 `@vitejs/plugin-react-swc` 4.2.2）、Tailwind CSS **v4**（`@tailwindcss/vite` 4.1.18）+ `tailwindcss` 4.1.17、shadcn/ui（Radix UI 14 个 `@radix-ui/react-*` 包）、TanStack Router 1.142.11 / Query 5.90.12 / Table 8.21.3、react-hook-form 7.68.0 + zod 4.2.1 + `@hookform/resolvers` 5.2.2、axios 1.13.2 + `@hey-api/openapi-ts` 0.73.0（自动生成 OpenAPI 客户端）、lucide-react 0.562.0、next-themes 0.4.6、sonner 2.0.7、class-variance-authority 0.7.1、clsx 2.1.1、tailwind-merge 3.4.0、react-error-boundary 6.0.0、react-icons 5.5.0、form-data 4.0.5（第 585-635 行）。
- **[数据]** 前端 devDependencies：`@biomejs/biome` 2.3.10、`@playwright/test` 1.57.0、`@tanstack/router-plugin` 1.140.0、`@tanstack/router-devtools` 1.142.11、`@types/node` 25.0.2、`dotenv` 17.2.3、`tw-animate-css` 1.4.0、typescript 5.9.3、vite 7.3.0。
- **[数据]** `frontend/package.json` scripts（第 576-584 行）：`dev: vite`、`build: tsc -p tsconfig.build.json && vite build`、`lint: biome check --write --unsafe ...`、`preview: vite preview`、`generate-client: openapi-ts`、`test: bunx playwright test`、`test:ui: bunx playwright test --ui`。
- **[数据]** 包管理器为 **Bun**（README Requirements，第 687 行）；代码规范为 **Biome**；E2E 为 **Playwright**。
- **[架构]** OpenAPI 客户端生成方式（README 第 721-748 行）：自动 `bash ./scripts/generate-client.sh`，或手动从 `http://localhost/api/v1/openapi.json` 下载 JSON 后 `bun run generate-client`；**后端 OpenAPI schema 每次变更都需重新生成并提交**。
- **[架构]** 远程 API 通过环境变量 `VITE_API_URL` 指定（`frontend/.env`，第 750-756 行）。
- **[架构]** `vite.config.ts`（第 1290-1324 行）：别名 `@` → `./src`；dev server 代理 `/api` → `loadEnv(...).VITE_API_URL || "http://localhost:8000"`；插件 `tanstackRouter({ target: "react", autoCodeSplitting: true })` + `react()` + `tailwindcss()`。
- **[数据]** `tsconfig.json`（第 1342-1371 行）：target ES2020、module ESNext、`moduleResolution: bundler`、`strict: true`、`noUnusedLocals`、`noUnusedParameters`、`noFallthroughCasesInSwitch`、`paths: {"@/*": ["./src/*"]}`、include `["src","tests","playwright.config.ts"]`。
- **[数据]** `components.json`（shadcn 配置，第 2523-2543 行）：style `new-york`、rsc `false`、baseColor `neutral`、cssVariables `true`、iconLibrary `lucide`、tailwind.config 为空（Tailwind v4 无配置文件）。

### 1.3 目录结构与模块规模（量化）

- **[数据]** `frontend/src/` 共 **10** 个条目：`client/`、`components/`、`hooks/`、`index.css`、`lib/`、`main.tsx`、`routes/`、`routeTree.gen.ts`、`utils.ts`、`vite-env.d.ts`（第 653-665 行）。
- **[数据]** `src/routes/` 共 **7** 个条目：`__root.tsx`、`_layout.tsx`、`_layout/`、`login.tsx`、`recover-password.tsx`、`reset-password.tsx`、`signup.tsx`（第 822-831 行）。
- **[数据]** `src/routes/_layout/` 共 **20** 个条目：`admin.tsx`、`developer-tools.tsx`、`douyin.tsx`、`douyin_.$taskId.tsx`、`douyin_.$taskId.feed.tsx`、`douyin-accounts.tsx`、`douyin-browsers.tsx`、`douyin-comments.tsx`、`douyin-creators.tsx`、`douyin-interactions.tsx`、`douyin-keywords.tsx`、`douyin-library.tsx`、`douyin-library.feed.tsx`、`douyin-request-logs.tsx`、`douyin-tags.tsx`、`douyin-tracks.tsx`、`douyin-tracks_.$trackId.tsx`、`index.tsx`、`items.tsx`、`settings.tsx`（第 899-923 行）。
- **[数据]** `src/components/` 共 **10** 个条目：`Admin/`、`Common/`、`Douyin/`、`Items/`、`Navigation/`、`Pending/`、`Sidebar/`、`theme-provider.tsx`、`ui/`、`UserSettings/`（第 845-858 行）。
- **[数据]** `src/components/Douyin/` 共 **25** 个组件：`AwemeActions.tsx`、`BatchCommentDialog.tsx`、`CreateTaskDialog.tsx`、`CreatorAvatar.tsx`、`InteractionComposerDialog.tsx`、`InteractionContentSummary.tsx`、`InteractionLiveMonitor.tsx`、`InteractionStatusBadge.tsx`、`MediaMigrationDialog.tsx`、`MediaPipelinePanel.tsx`、`MediaTaskManagement.tsx`、`presentation.ts`、`ProcessMediaDialog.tsx`、`ResumeTaskDialog.tsx`、`SourceSelect.tsx`、`SubtitlePanel.tsx`、`TaskExecutionProgress.tsx`、`TaskIdentity.tsx`、`TaskInteractionsPanel.tsx`、`taskParameters.ts`、`TaskResults.tsx`、`TaskStatusBadge.tsx`、`TrackSelect.tsx`、`UnifiedWorksPanel.tsx`、`VideoPreviewDialog.tsx`（第 938-965 行）。
- **[数据]** `src/components/Sidebar/` 共 **3** 个：`AppSidebar.tsx`、`Main.tsx`、`User.tsx`（第 980-986 行）。
- **[数据]** `src/components/Common/` 共 **10** 个：`Appearance.tsx`、`AuthLayout.tsx`、`DataTable.tsx`、`ErrorComponent.tsx`、`Footer.tsx`、`Logo.tsx`、`NotFound.tsx`、`PageShell.tsx`、`QueryErrorState.tsx`、`ViewModeToggle.tsx`（第 4318-4331 行）。
- **[数据]** `src/hooks/` 共 **4** 个：`useAuth.ts`、`useCopyToClipboard.ts`、`useCustomToast.ts`、`useMobile.ts`（第 1697-1703 行）。
- **[数据]** `src/lib/` 仅 **1** 个文件：`utils.ts`（第 1679-1682 行）——共享层极薄。
- **[数据]** `src/client/` 共 **5** 个：`core/`、`index.ts`、`schemas.gen.ts`、`sdk.gen.ts`、`types.gen.ts`（第 872-880 行）。
- **[数据]** `src/components/ui/`（shadcn 组件）共 **25** 个（第 1791-1792 行）。
- **[数据]** `src/routes/_layout` 页面总行数 **16018** 行；最大文件：`douyin-tracks_.$trackId.tsx` 2205 行、`douyin-tracks.tsx` 1936 行、`douyin-library.tsx` 1627 行、`douyin-keywords.tsx` 1245 行、`douyin-comments.tsx` 1206 行、`douyin-creators.tsx` 1101 行（第 2984-3010 行）。
- **[数据]** `components/Douyin/` 组件总行数 **7715** 行；最大：`UnifiedWorksPanel.tsx` 1479 行、`CreateTaskDialog.tsx` 828 行、`MediaTaskManagement.tsx` 571 行、`MediaPipelinePanel.tsx` 487 行、`AwemeActions.tsx` 487 行（第 3010-3026 行）。

### 1.4 前端架构决策与入口组合根

- **[架构]** 单 Vite 应用、单入口（`index.html` → `src/main.tsx`）；TanStack **文件路由**，`routeTree.gen.ts` 由插件自动生成；`autoCodeSplitting: true` 已实现按路由自动代码分割（第 1734-1735 行）。
- **[架构]** `main.tsx`（第 1389-1452 行）是前端运行时组合根：`OpenAPI.BASE = import.meta.env.VITE_API_URL`；`OpenAPI.TOKEN` 从 `localStorage.getItem("access_token")` 异步取；创建 `QueryClient` 并挂 `queryCache/mutationCache` 的 `onError: handleApiError`；`createRouter({ routeTree })` + `declare module` 注册；渲染树为 `StrictMode > ThemeProvider(defaultTheme="light", storageKey="vite-ui-theme") > QueryClientProvider > RouterProvider + Toaster(richColors, closeButton)`。
- **[安全]** `handleApiError`（第 1409-1426 行）：仅在 `error instanceof ApiError` 时处理；判定会话失效条件为 `status ∈ [401,403]` 或 `status === 404 && detail === "User not found"`；命中后 `localStorage.removeItem("access_token")` 并 `window.location.href = "/login"`。
- **[架构]** `_layout.tsx` 的 `beforeLoad` 用 `isLoggedIn()` 做路由守卫，未登录 `throw redirect({ to: "/login" })`（第 1541-1550 行）。
- **[架构]** `__root.tsx`（第 1479-1497 行）：`notFoundComponent: NotFound`、`errorComponent: ErrorComponent`；devtools 仅在 `import.meta.env.DEV && import.meta.env.VITE_ENABLE_DEVTOOLS === "true"` 时挂载 `TanStackRouterDevtools` + `ReactQueryDevtools`。
- **[架构]** 布局双模式：`_layout.tsx` 用 `useState<NavigationLayout>` + `localStorage`（key `NAVIGATION_LAYOUT_STORAGE_KEY`）在 `horizontal` / `sidebar` 间切换，`usesSidebar` 条件渲染 `AppSidebar` 或 `HorizontalNavigation`（第 1552-1659 行）。
- **[A11Y]** `_layout.tsx` 第 91-96 行实现了「跳到主要内容」skip-link（`href="#main-content"`，默认 `-translate-y-20`，focus 时 `translate-y-0`）；`main` 元素带 `id="main-content"`。
- **[架构]** `AppSidebar.tsx`：`getNavigationModules(Boolean(currentUser?.is_superuser))` 生成导航分组，`<Sidebar collapsible="icon">`，含 Header(Logo responsive)/Content(Main)/Footer(User)（第 2562-2596 行）。
- **[架构]** `navigation.ts`（第 4000-4133 行）集中定义导航：5 个 `NavigationModule`——`overview`(工作台 `/`) / `collection`(赛道管理 `/douyin-tracks`、抖音任务 `/douyin`、关键词管理 `/douyin-keywords`) / `content`(视频资源库、评论管理、达人列表、标签管理) / `operations`(互动任务、账号池、浏览器监控、请求日志) / `system`(开发者中心、用户管理 `/admin` 带 `requiresSuperuser: true`)；导出 `getNavigationModules(isSuperuser)`、`isNavigationItemActive(pathname, itemPath)`、`findActiveNavigation(pathname, isSuperuser)`（**结论**：后者未被 `_layout.tsx` 使用）。
- **[数据]** `AuthLayout.tsx`：桌面端左右分栏 `lg:grid-cols-[1.08fr_0.92fr]`，左侧品牌区含渐变 + 装饰圆 + 卖点文案（「任务状态实时更新」「账号与隐私安全隔离」），右侧卡片区右上角放 `Appearance` 组件、底部放 `Footer`（第 4808-4853 行）。
- **[产品]** 前端消费的是**已脱敏数据**：创作者/评论用户信息经 HMAC 脱敏 + 昵称打码后入库（第 1085 行）。
- **[架构]** 类型安全的全栈契约：前端 SDK 由后端 OpenAPI 自动生成，配合后端 `tests/architecture/` 的 OpenAPI 哈希契约测试，前后端不会静默脱节（第 1083 行）。

## 2. 前端模块拆分可行性分析（第 2 轮，第 1090-1922 行）

### 2.1 耦合度实测（拆分可行性依据）

- **[数据]** 各业务域对 `@/client` 的引用文件数：`Douyin` **24**、`Admin` **5**、`Items` **5**、`UserSettings` **3**、`Common` **0**、`Navigation` **0**、`Sidebar` **0**（第 1809-1816 行）。
- **[数据]** `Douyin/` 组件域内互引最高仅 **3 次**（`ProcessMediaDialog`），其余多为 1-2 次（第 1793-1808 行）。
- **[数据]** `routes/` 大量复用 Douyin 的叶子组件：`TrackSelect` 5 次、`TaskStatusBadge` 4 次、`SourceSelect` 4 次、`presentation` 3 次、`TaskIdentity` 2 次、`taskParameters` 2 次（第 1817-1827 行）。
- **[结论]** 关键事实：**业务域之间零互引**，共享 UI 层零业务依赖（`ui/`、`Common/`、`Navigation/`、`Sidebar/`、`hooks/`、`lib/` 都不引用 `@/client`）——这是理想的拆分前提。
- **[结论]** `components/ui/` 25 个 shadcn 组件为纯展示、无业务，天然可抽包边界；`client/`（OpenAPI SDK）是天然包边界。

### 2.2 三种拆分方案对比

- **[架构]** 方案 A｜逻辑模块化（推荐先做）：保持单 Vite 应用，把 `components/Douyin/` 按子域重组为 `tasks/`（CreateTask/Resume/ExecutionProgress/Results/StatusBadge）、`media/`（MediaPipeline/Migration/Subtitle/VideoPreview/ProcessMedia）、`interactions/`（Composer/LiveMonitor/BatchComment/StatusBadge/ContentSummary）、`creators/`（CreatorAvatar/UnifiedWorksPanel/AwemeActions）、`shared/`（TrackSelect/SourceSelect/TaskIdentity/presentation/taskParameters）；配 `eslint-plugin-boundary` 禁止 `tasks/` 直接 import `media/` 等；保留 TanStack 文件路由 + `autoCodeSplitting`。**成本最低，立刻可做、零构建改动。**
- **[架构]** 方案 B｜Monorepo 抽包（进阶）：用 bun/pnpm workspace 拆为 `packages/ui`（shadcn + Common，0 业务依赖）、`packages/client`（OpenAPI SDK，后端改 schema → bump 版本 → 各应用升级）、`packages/shared`（hooks + lib + Navigation + Sidebar）+ `apps/workbench`（路由 + 业务组件）。收益：`client` 独立版本化，与后端 OpenAPI 哈希契约形成「后端 → client 包 → 应用」明确链路；`ui` 可被未来第二个应用复用。成本：构建配置、包间引用、生成脚本改造。
- **[架构]** 方案 C｜多应用/微前端（**不推荐**）：按域拆 `apps/auth`、`apps/douyin`、`apps/admin` 独立部署。理由：TanStack 文件路由强绑定单应用（`routeTree.gen.ts` 编译一棵树），拆应用要按域切路由目录，跨应用跳转退化为 URL 跳转、丢失 SPA 体验；`autoCodeSplitting: true` 已解决按页懒加载，"性能"不是动机；26 个路由、域间零耦合但共享同一布局/导航/认证，独立部署收益不抵成本；仅当出现多团队、独立发版需求时才值得。
- **[结论]** 推荐路径：①先做方案 A（零风险、立刻改善可维护性）；②出现「需要第二个前端应用复用 UI/client」「希望 OpenAPI SDK 独立版本化」「团队 ≥2 组并行开发不同域」任一信号时升级到方案 B；③方案 C 暂不考虑。

### 2.3 拆分时必须保留的契约

- **[架构]** `client/` 必须作为整体**不能拆**（由 `openapi-ts` 从单一 OpenAPI schema 生成）。
- **[架构]** `main.tsx` 里 `OpenAPI.BASE/TOKEN` + `QueryClient` 全局配置是组合根，抽包后要留在 `apps/workbench` 入口，**不能进 `packages/`**。
- **[架构]** `_layout.tsx` 的 pathname→section 映射（第 54-80 行硬编码）应随路由一起走，抽包时别拆散。
- **[架构]** 当前是 if/else 硬分支而非注册表/插件式，无「风格包」概念——布局与风格未解耦成可注册（第 2621 行）。

## 3. 多风格与多布局架构设计（第 3 轮，第 1924-2890 行）

### 3.1 现状盘点：已有组合雏形

- **[数据]** 当前已有 4 个外观维度（第 2722-2727 行）：明暗 `theme` = light/dark/system（`.dark` class，3 值）；配色 `preset` = ocean/graphite/violet（`data-preset` + CSS 覆盖 `--primary` 等，3 值）；密度 `density` = comfortable/compact（`data-density` + CSS 覆盖 card/table 间距，2 值）；布局 `layout` = horizontal/sidebar（`_layout.tsx` 里 `usesSidebar` if/else，2 值）。
- **[数据]** 理论 **3×3×2×2 = 36** 种组合（第 2729 行；第 2614 行表述为 24 种，口径差异为是否计入 system）。
- **[架构]** `theme-provider.tsx`（第 1977-2131 行）自定义实现：类型 `Theme = "dark"|"light"|"system"`、`ThemePreset = "ocean"|"graphite"|"violet"`、`Density = "comfortable"|"compact"`；持久化 key 为 `storageKey`、`${storageKey}-preset`、`${storageKey}-density`；`useEffect` 把 `preset`/`density` 写到 `document.documentElement.dataset`；`resolvedTheme` 通过 `matchMedia("(prefers-color-scheme: dark)")` 计算并监听 change。
- **[数据]** Design tokens 全用 oklch CSS 变量，`@theme inline` 映射到 Tailwind；分 `:root` / `.dark` / `[data-preset=...]` / `[data-density="compact"]` 四层覆盖（`index.css` 共 **338** 行）。
- **[架构]** `index.css` 的分层：`@import "tailwindcss"` + `tw-animate-css`、`@custom-variant dark (&:is(.dark *))`、`@theme inline`（radius + 全部颜色 token 映射）、`:root`（40+ 个 oklch 变量，`--radius: 0.875rem`）、3 个 `[data-preset]` 覆盖块、`.dark` 全量覆盖、2 个 `.dark[data-preset]` 覆盖块、4 条 `[data-density="compact"]` 覆盖规则（card/table 间距）、`@layer base`（reset + body 字体栈 Inter/"Noto Sans SC"/"Microsoft YaHei UI" + 三层 radial-gradient 光晕 + `::selection`）、`@layer components`（`.page-stack`/`.page-hero`/`.page-hero-glow*`/`.eyebrow`/`.filter-panel`/`.status-pulse`）、`@keyframes status-pulse`、`@media (min-width: 640px)` 与 `@media (prefers-reduced-motion: reduce)` 降级。
- **[A11Y]** `index.css` 第 329-338 行提供 `prefers-reduced-motion: reduce` 全局降级（animation/transition duration → 0.01ms，iteration-count → 1）。
- **[A11Y]** `html`/`body` 设 `min-width: 320px`；`body` 设 `text-rendering: optimizeLegibility`。

### 3.2 现有架构的 4 项局限

- **[风格]** 局限 1：`preset` 只换主色不换风格语言——ocean/graphite/violet 仅覆盖 `--primary/--ring/--chart`，而背景光晕（body 三层 radial-gradient）、`page-hero`、`filter-panel` 写死在 `index.css` base 层；想要「科技暗黑风 vs 简约白净风」的整体视觉差异，当前粒度不够。
- **[风格]** 局限 2：风格 CSS 散落在单文件——`index.css` 338 行里 `:root`/`.dark`/`[data-preset]`/`[data-density]` 全混在一起，加风格要改大文件、易冲突，**违反开闭原则**。
- **[架构]** 局限 3：布局硬编码在 `_layout.tsx`——`usesSidebar` 是 if/else（第 87 行），pathname→section 映射硬编码（第 54-80 行）；加第三种布局要改 `_layout.tsx` 本身。
- **[架构]** 局限 4：风格与布局**未正交注册**——没有注册表，无法运行时枚举/热切换/按权限过滤。

### 3.3 设计目标与架构方案

- **[架构]** 设计目标：风格（Skin）为一个自包含包 = 完整 token（明/暗两套）+ 装饰层（背景光晕、hero、卡片质感）+ 可选字体，可注册、可热切换；布局（Layout）为一个自包含壳组件 = 导航 + 头部 + 内容区，可注册、可热切换；任意 Skin × 任意 Layout 正交组合；加新风格/新布局 = 加一个文件 + 注册一行，不改核心（开闭原则）；统一偏好中心 `AppearanceProvider` 管所有维度，一个设置面板切换，全部持久化 localStorage。
- **[架构]** 风格系统目录设计：`src/styles/skins/{violet,ocean,graphite,neon,minimal}.css`（每 skin 一个自包含文件，用 `[data-skin="xxx"]` 作用域，既覆盖 token 也覆盖装饰）+ `src/styles/base.css`（只留 `@theme inline` 映射 + base reset + 兜底 token）+ `src/styles/registry.ts`（skin 元数据 `{ id, name, description, swatch }[]`）。
- **[架构]** 风格系统聚合方式：`index.css` 只做 `@import` 聚合，加新 skin 只加一行 `@import "./styles/skins/xxx.css"`。
- **[架构]** 关键升级：把 `data-preset` 统一改为 `data-skin`，skin 语义从「配色」升级为「完整视觉语言」；`body` 装饰光晕从 base 移除，由各 skin 自己定义，base 只给纯白兜底。
- **[架构]** 布局系统目录设计：`src/layouts/registry.tsx`（`LayoutRegistry: { id, name, icon, component, minRole }[]`）+ `SidebarLayout.tsx` / `HorizontalLayout.tsx`（抽自现有壳）+ 新增 `CompactLayout.tsx`（紧凑双栏 dashboard）/ `FocusLayout.tsx`（专注模式，折叠导航、隐藏 header 装饰）。
- **[架构]** 布局注册表接口契约：`interface LayoutDef { id: string; name: string; icon: LucideIcon; component: React.ComponentType<{ children: React.ReactNode }>; minRole?: "superuser" }`；预置 4 项 `sidebar/horizontal/compact/focus`。
- **[架构]** `_layout.tsx` 从 148 行硬编码瘦身为约 15 行派发器：`const def = layouts.find(l => l.id === layout) ?? layouts[0]; const Shell = def.component; return <Shell><Outlet /></Shell>`。
- **[架构]** 偏好中心：把 `ThemeProvider` 升级为 `AppearanceProvider`，接口 `Appearance { mode, resolvedMode, skin, density, layout, radius }` + 各 setter，全部持久化 localStorage；`useEffect` 把 `data-mode`/`data-skin`/`data-density` 写到 `<html>`、`--radius` 写到 `:root`。
- **[架构]** 外观设置面板：替换写死两个选项的 `NavigationLayoutSwitch`，改为统一 `AppearancePanel`，含 `SkinGrid`（缩略色卡）/`LayoutList`/`ModeToggle`/`DensityToggle`/`RadiusSlider`，选项全部来自注册表。
- **[架构]** 导航标题解耦：`_layout.tsx` 第 54-80 行的 pathname→section 硬编码移到 `navigation.ts`，每个 nav module 自带 `label` 和 `match(pathname)`，布局壳通过 `useRouterState` 拿 pathname 后查表，所有布局共享同一映射。
- **[产品]** `radius`（圆角）也可调，shadcn 已用 `--radius` 变量（新增维度建议）。

### 3.4 落地扩展演示与关键约束

- **[架构]** 加新风格「日落」三步：新建 `src/styles/skins/sunset.css`；`index.css` 加一行 `@import`；`registry.ts` 加一行元数据——**不改任何组件、不改 `_layout.tsx`**。
- **[架构]** 加新布局「双栏」两步：新建 `src/layouts/SplitLayout.tsx`（纯壳）；`registry.tsx` 数组加一项——**不改 `_layout.tsx`、不改其他布局**。
- **[架构]** 约束 1：`data-skin` 取代 `data-preset` 需一次性迁移，`theme-provider.tsx` 的 `ThemePreset` 类型升级为 `SkinId`；迁移期可保留 `data-preset` 兼容读取旧 localStorage。
- **[风格]** 约束 2：`base.css` 不含装饰——`body` 的 radial-gradient 必须移出 base，否则会和新 skin 的装饰叠加。
- **[架构]** 约束 3：Tailwind v4 `@theme inline` 不动（只把 CSS 变量映射成 Tailwind 颜色名，与 skin 无关，留在 base）。
- **[架构]** 约束 4：SSR 安全——`window`/`localStorage` 访问保留现有 `typeof window === "undefined"` 守卫（`_layout.tsx` 第 39 行已有）。
- **[架构]** 约束 5：shadcn `components.json` 不变（`baseColor: neutral` + `cssVariables: true` 仍成立，skin 只覆盖变量值）。
- **[结论]** 建议分两步实施：① 先做布局注册表重构（收益大、改动集中在 `_layout.tsx` + 新建 `layouts/`）；② 再做 skin 注册表（迁移 `index.css` + 升级 provider）。

## 4. 风格 / 交互 / 页面缺陷审查报告（第 4 轮，第 2892-6039 行）

### 4.0 审查环境与工具结论

- **[数据]** 审查环境：`bun` **不可用**，`node` **v22.11.0**（第 2981-2983 行）；用 `npm install`（EXIT:0，约 180s 内完成）替代 bun 安装成功。
- **[BUG]** 运行环境告警：Vite 7 要求 Node **20.19+ 或 22.12+**，当前 22.11.0，启动时打印版本不符警告，但仍能 ready（Vite v7.3.6，1658ms，`http://127.0.0.1:5173` 返回 200）（第 4381-4387 行）。
- **[结论]** Playwright MCP 截图失败：Chromium 沙箱限制（`Running as root without --no-sandbox is not supported`，`Target page, context or browser has been closed`），因此**本报告全部基于源码审查**，无视觉截图佐证（第 5921-5990 行）。

### 4.1 风格缺陷（F1-F6）

- **[风格]** F1 — `Common/PageShell.tsx:47, 53-95`：`PageHero` 声明了 `description?: string` prop，但组件体**从未渲染它**（只渲染 eyebrow/title/actions/children）| **所有页面传入的 hero 描述文案全部丢失**（`index.tsx:79`、`settings.tsx:44`、`admin.tsx:67`、`douyin_.$taskId.tsx:155` 都传了却不显示）。
- **[风格]** F2 — `Common/AuthLayout.tsx:14`：左侧大渐变硬编码 `from-violet-700 via-primary to-blue-500` + 装饰圆 `bg-cyan-300/20` | 切换 ocean/graphite skin 时登录页左侧仍是紫蓝渐变，与主题割裂。
- **[风格]** F3 — `Common/PageShell.tsx:8-33`（`toneStyles` 用 `violet-500/blue-500/emerald-500/orange-500/rose-500/slate-500`）、`routes/_layout/index.tsx:262-270`（`StatusPill` 的 blue/green/amber/violet）| 这些卡片/药丸配色**不响应 skin 切换**，永远固定色；与走 token 的主色系并存，视觉不统一。
- **[风格]** F4 — `Common/Appearance.tsx:88-93`：主题风格选项 `[ocean→"清透蓝", graphite→"专业灰", violet→"跃动紫"]` 硬编码在组件里 | 加新 skin 必须改此组件，无注册表（印证「未解耦注册表」结论）。
- **[交互]** F5 — `Common/Appearance.tsx:134-169`（`Appearance`，仅明暗 3 项）vs `23-132`（`UserMenuAppearance`，明暗 + 主题风格 + 信息密度）| **登录页无法切换 skin/density**，登录前后外观控制能力不一致。
- **[风格]** F6 — `index.css:199-216`：`body` 的三层 `radial-gradient` 装饰光晕写死在 `@layer base` | 所有 skin 共享同一背景光晕，skin 无法定义自己的装饰语言。

### 4.2 交互缺陷（I1-I8）

- **[BUG]/[安全]** I1 — `routes/_layout/settings.tsx:30-32`：`const finalTabs = currentUser?.is_superuser ? tabsConfig.slice(0, 3) : tabsConfig`，而 `tabsConfig` 恰好 3 项，`slice(0,3)` 与原数组等长，**两个分支结果完全相同** | 逻辑无效；普通用户也能看到「危险操作」（删除账号）tab。本意应为 `slice(0,2)` 给超管。
- **[安全]** I2 — `routes/login.tsx:57-58`：`defaultValues` 硬编码 `username: "admin@example.com"`、`password: "changethis"` | **生产环境表单预填默认凭据**，安全隐患；应仅 dev 环境注入。
- **[BUG]** I3 — `routes/_layout/admin.tsx:23-29`：`beforeLoad` 直接 `await UsersService.readUserMe()` 做鉴权 | token 失效时路由抛错；与 `_layout` 的 `isLoggedIn()` **双重鉴权**，网络慢则白屏卡住。
- **[BUG]** I4 — `routes/_layout/douyin_.$taskId.tsx:439-466`：二维码 `TaskQrCode` 用原生 `fetch` + `localStorage.getItem("access_token")` 手动拼 `Authorization` header，请求 `${OpenAPI.BASE}/api/v1/douyin/tasks/${taskId}/qrcode` | 绕过统一 OpenAPI client 与全局错误处理（`main.tsx` 的 401 跳登录逻辑不生效）；token 读取逻辑重复。
- **[交互]** I5 — `routes/_layout/douyin_.$taskId.tsx:465`：二维码 `window.setInterval(load, 15_000)` 固定刷新 | 无 loading 态、无失败重试退避；二维码过期/网络抖动时体验差。
- **[交互]/[优化]** I6 — `components/Douyin/CreateTaskDialog.tsx:127-204`：手写 `useState<FormState>` + `update()` 管理表单，校验散落在 `submit()` 里（`showErrorToast` 链式校验） | 项目已装 `react-hook-form`+`zod`（login 在用），核心创建表单却不用，校验不一致、无 onBlur 实时反馈、难维护。
- **[性能]** I7 — 多处轮询策略不一致：任务列表 3s（`douyin.tsx:127`）、任务详情 2s（`douyin_.$taskId.tsx:86`，仅在 active 状态）、工作台 5s（`index.tsx:41`）、任务分片 2s（`douyin_.$taskId.tsx:373`）| **无页面可见性暂停**（切后台仍轮询），多标签页时 N×3s 压力。
- **[BUG]/[交互]** I8 — `routes/_layout/douyin.tsx:183-186`：`Tabs defaultValue="crawl"` + `onValueChange` 设置 `businessTab`，但 `businessTab` 仅用于控制 `CreateTaskDialog` 显隐，`TabsContent` 两块是静态的 | state 与 Tabs 重复控制，逻辑绕。

### 4.3 页面缺陷（P1-P8）

- **[产品]/[BUG]** P1 — `douyin.tsx:124`、`admin.tsx:16`、`index.tsx:39,45`、`CreateTaskDialog.tsx:137,151` 等多处：所有列表 `limit: 100` **硬编码，无分页/无限滚动** | 超过 100 条的数据直接丢失且无提示；工作台用 `dataScope = "近 100 个任务" / "全部任务"` 文案掩盖但未提供查看全部入口。
- **[架构]/[BUG]** P2 — `routes/_layout.tsx:54-80` vs `Navigation/navigation.ts:119-128`：pathname→section 标题映射在 `_layout` 硬编码 **27 行嵌套三元 if/else**；`navigation.ts` 已有 `findActiveNavigation()` 却未被 `_layout` 使用 | 两套导航逻辑并存，加菜单项要改两处，易不同步。
- **[i18n]/[风格]** P3 — 品牌名三处不一致：`login.tsx:44`/`settings.tsx:22`/`admin.tsx:34`/任务详情用「**灵感采集台**」；`index.tsx:32` 用「**运营工作台**」；`AuthLayout.tsx:39` 底部用「**抖音内容运营工作室**」| 无统一品牌常量。
- **[架构]** P4 — `douyin.tsx:89-96` 与 `douyin_.$taskId.tsx:64-71`：`crawlTypeLabels`（search/detail/creator/creator_from_aweme/liked/collected 六项映射）完全相同的表在两个文件各定义一份 | 重复，改类型标签要改两处。
- **[BUG]/[数据]** P5 — `index.tsx:54` vs `douyin.tsx:131-134,143-145`：「需关注」状态集合定义不一致——工作台用 `["failed","interrupted","waiting_login"]`，任务列表用 `["failed","cancelled","interrupted","waiting_login"]`（多 `cancelled`）| 跨页面「需关注」计数口径不一致，dashboard 和任务列表数字对不上。
- **[A11Y]/[交互]** P6 — `douyin_.$taskId.tsx:229-251`：详情页 `TabsList` 写死 `grid grid-cols-3`，`TabsTrigger` 有 `min-h-11` 但无横向滚动 | 窄屏三个 tab（任务概览/作品数据/互动记录）挤一行，标签 + 计数 badge 会换行/截断。
- **[BUG]** P7 — `routes/_layout/douyin.tsx:135-155`：`filteredTasks` 的 `useMemo` 依赖数组为 `[searchTerm, statusFilter, tasks]`，未列 `trackId/sourceValue`；搜索匹配里调用了 `taskBrowserMode(task)` 却未在依赖中体现 | 潜在陈旧闭包（当前因 `tasks` 已含筛选结果而影响轻微）。
- **[BUG]** P8 — `vite.config.ts` + 运行环境：Vite 7 要求 Node ≥22.12，当前 22.11.0 | 非代码缺陷，但 CI/容器需固定 Node ≥22.12，否则构建可能异常。

### 4.4 优先级排序（最该先修的 5 项）

- **[结论]** 修复优先级（第 6031-6039 行）：
  1. **F1** `PageHero` 不渲染 `description` —— 一行修复，影响全站 hero 文案。
  2. **I1** `settings.tsx` 超管分支逻辑无效 —— 安全相关，普通用户可见删除账号。
  3. **I2** `login.tsx` 默认凭据预填 —— 生产安全。
  4. **P1** 列表无分页 —— 功能性数据丢失。
  5. **F2/F3** `AuthLayout`/`MetricCard` 不响应 skin —— 直接阻碍「多风格」目标。
- **[结论]** F1/I1/I2 均为一两行的小修，可立刻动手。

### 4.5 审查过程中确认但未单列为缺陷的观察

- **[交互]** `douyin.tsx:108` 的 `businessTab` state 与 `Tabs` 的 `defaultValue` 并存，是 I8 的根因（两处 state 同源不同步）。
- **[优化]** `douyin.tsx` 的列表刷新按钮 `RefreshCw` 与 `isFetching` 联动（`animate-spin` + `disabled`），已实现加载反馈（正面项）。
- **[A11Y]** 任务列表筛选已具备 A11Y 处理：`<fieldset>` + `<legend className="sr-only">任务状态筛选</legend>`、按钮 `aria-pressed`、`<h2 id="task-list-heading" className="sr-only">` + `<section aria-labelledby>`、`aria-label="按赛道筛选任务"`/`"按关键词或作者筛选任务"`/`"刷新任务"`/`"全选可删除任务"`（第 3718-3805 行）。
- **[交互]** 任务列表支持三种视图模式（`ViewModeToggle` + `usePersistentViewMode("douyin-tasks-view")`：`cards` / `rows` / 表格），并有空状态 `EmptyState`（无任务 / 无匹配任务）与 `QueryErrorState` 重试态（第 332-358 行）。
- **[产品]** 工作台首页有「X 项任务需要处理」告警卡（`attentionCount > 0` 时显示，引导跳 `/douyin`）与三个 `StatusPill` 状态摘要、四个 `MetricCard`（任务总数/作品/评论/可用账号）（第 329-3364 行）。
