import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Download, Eye, FileSearch, Inbox } from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import {
  type DouyinListRequestLogsData,
  type DouyinRequestLogPublic,
  DouyinService,
} from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import { FilterChips } from "@/components/Common/FilterChips"
import { FilterPresetBar } from "@/components/Common/FilterPresetBar"
import { Pager } from "@/components/Common/Pager"
import { PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { RefreshIndicator } from "@/components/Common/RefreshIndicator"
// 报告 A1：列可见性菜单（手写 Table 用）
import { TableColumnMenu } from "@/components/Common/TableColumnMenu"
import { TimeAgo } from "@/components/Common/TimeAgo"
import {
  type ListViewMode,
  usePersistentViewMode,
  ViewModeToggle,
} from "@/components/Common/ViewModeToggle"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useRowKeyboardNav } from "@/hooks/useRowKeyboardNav"
// 报告 A1：列可见性 —— 手写 Table 的列开关（偏好按 storageKey 存本地）
import { type TableColumnDef, useTableColumns } from "@/hooks/useTableColumns"
// 报告 A12：本页数据即时导出（前端拼接，全量导出需后端流式接口，本次不做）
import { downloadCsv } from "@/lib/csv"
// 报告 O4：筛选上 URL —— 写入 / 读取查询参数的纯函数
import {
  compactSearch,
  readEnumParam,
  readStringParam,
} from "@/lib/search-params"
// 统一时间格式化，替代页面本地实现
import { formatDateTime } from "@/lib/time"

// 报告 O4：方法白名单（挡住手改 URL 的脏值）
const METHOD_VALUES = ["all", "GET", "POST"] as const
// 报告 O4：每页条数白名单，与 Pager 的 pageSizeOptions 保持一致
const PAGE_SIZE_VALUES = ["20", "50", "100"] as const

type MethodFilter = "all" | "GET" | "POST"

// 报告 O4：URL 查询参数结构 —— 只承载「已应用」的筛选，草稿值不进 URL
type RequestLogsSearch = {
  task?: string
  method?: MethodFilter
  path?: string
  status?: string
  from?: string
  to?: string
  page?: number
  size?: number
}

// 报告 O4：页码从 URL 安全取正整数，非法值（0 / -1 / abc）一律当未提供
function readPageParam(search: Record<string, unknown>): number | undefined {
  const raw = readStringParam(search, "page")
  if (raw === undefined) return undefined
  const parsed = Number.parseInt(raw, 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined
}

export const Route = createFileRoute("/_layout/douyin-request-logs")({
  // 报告 O4：筛选上 URL —— 刷新 / 分享 / 深链 / 收藏都能还原已应用的筛选
  validateSearch: (search: Record<string, unknown>): RequestLogsSearch => {
    const size = readEnumParam(search, "size", PAGE_SIZE_VALUES)
    return {
      task: readStringParam(search, "task"),
      method: readEnumParam(search, "method", METHOD_VALUES),
      path: readStringParam(search, "path"),
      status: readStringParam(search, "status"),
      from: readStringParam(search, "from"),
      to: readStringParam(search, "to"),
      page: readPageParam(search),
      size: size === undefined ? undefined : Number(size),
    }
  },
  component: DouyinRequestLogsPage,
  head: () => ({ meta: [{ title: "请求日志 - 灵感采集台" }] }),
})

const PAGE_SIZE = 50
const ALL_TASKS = "all"

// 报告 A1：列可见性 —— 表头里真实存在的列，key 用英文短名，title 用表头中文原文。
// 必须是模块级稳定常量：放组件里每次渲染都会重建，列偏好会被反复重置。
const REQUEST_LOG_COLUMNS = [
  { key: "time", title: "时间" },
  { key: "method", title: "方法" },
  { key: "path", title: "路径" },
  { key: "status", title: "状态" },
  { key: "duration", title: "耗时" },
  { key: "task", title: "任务" },
  // 操作列不允许隐藏，藏掉用户就没法看详情了
  { key: "actions", title: "操作", alwaysVisible: true },
] as const satisfies readonly TableColumnDef[]

// 报告 A1：表尾合计行首格默认跨的列（时间 / 方法 / 路径 / 状态）
const FOOTER_LEAD_KEYS = ["time", "method", "path", "status"] as const

type AppliedFilters = {
  taskId?: string
  method?: string
  path?: string
  responseStatus?: number
  createdFrom?: string
  createdTo?: string
}

// 报告 A10：筛选预设保存/回填的是「草稿态」的原始输入值（含 all 与空串）
type FilterValues = {
  taskId: string
  method: string
  path: string
  responseStatus: string
  createdFrom: string
  createdTo: string
}

// 草稿值 → 实际查询参数，供「查询」按钮、chips 移除、预设套用三处共用
function toApplied(values: FilterValues): AppliedFilters {
  const status =
    values.responseStatus.trim() === ""
      ? undefined
      : Number.parseInt(values.responseStatus.trim(), 10)
  return {
    taskId: values.taskId === ALL_TASKS ? undefined : values.taskId,
    method: values.method === "all" ? undefined : values.method,
    path: values.path.trim() || undefined,
    responseStatus:
      status !== undefined && !Number.isNaN(status) ? status : undefined,
    createdFrom: values.createdFrom || undefined,
    createdTo: values.createdTo || undefined,
  }
}

function DouyinRequestLogsPage() {
  const search = Route.useSearch()
  const navigate = Route.useNavigate()

  // 报告 O4：初值来自 URL，于是刷新 / 深链能还原「已应用」的筛选；
  // 草稿态用同一份初值回填，避免出现「chips 有值但输入框是空的」
  const [taskId, setTaskId] = useState(search.task ?? ALL_TASKS)
  const [method, setMethod] = useState<MethodFilter>(search.method ?? "all")
  const [pathContains, setPathContains] = useState(search.path ?? "")
  const [responseStatus, setResponseStatus] = useState(search.status ?? "")
  const [createdFrom, setCreatedFrom] = useState(search.from ?? "")
  const [createdTo, setCreatedTo] = useState(search.to ?? "")
  const [applied, setApplied] = useState<AppliedFilters>(() =>
    toApplied({
      taskId: search.task ?? ALL_TASKS,
      method: search.method ?? "all",
      path: search.path ?? "",
      responseStatus: search.status ?? "",
      createdFrom: search.from ?? "",
      createdTo: search.to ?? "",
    }),
  )
  // 报告 O4：翻页与每页条数也进 URL（page 为 1-based，区别于内部的 skip）
  const [page, setPage] = useState(search.page ?? 1)
  const [pageSize, setPageSize] = useState(search.size ?? PAGE_SIZE)
  const skip = (page - 1) * pageSize
  const [detail, setDetail] = useState<DouyinRequestLogPublic | null>(null)
  const [viewMode, setViewMode] = usePersistentViewMode(
    "douyin-request-logs-view",
  )
  // 报告 A1：列可见性 —— 表格视图下用户自己勾选要显示的列
  const { isVisible, visibleCount, menuProps } = useTableColumns({
    storageKey: "douyin-request-logs-columns",
    columns: REQUEST_LOG_COLUMNS,
  })

  // 报告 O4：把「已应用」的筛选 / 页码 / 每页条数写回 URL。
  // 用 replace 而不是 push：否则每改一次筛选就多一条浏览器历史，
  // 用户得按十次「后退」才能离开本页。用 replace 后刷新 / 分享 / 深链 / 收藏
  // 都生效，代价是浏览器「后退」回到上一个页面而不是上一条筛选 —— 有意的取舍。
  useEffect(() => {
    void navigate({
      to: "/douyin-request-logs",
      replace: true,
      search: compactSearch(
        {
          task: applied.taskId,
          method: applied.method,
          path: applied.path,
          status:
            applied.responseStatus === undefined
              ? undefined
              : String(applied.responseStatus),
          from: applied.createdFrom,
          to: applied.createdTo,
          page,
          size: pageSize,
        },
        // 等于默认值的键不写进 URL，未筛选时地址栏就是 /douyin-request-logs
        { page: 1, size: PAGE_SIZE },
      ) as RequestLogsSearch,
      // 依赖只放筛选 state 与 navigate；把 search 放进来会自激成死循环
    })
  }, [applied, page, pageSize, navigate])

  const tasks = useQuery({
    queryKey: ["douyin-task-options"],
    queryFn: () => DouyinService.listTasks({ limit: 200 }),
  })
  // 任务名映射被表格每一行读取；原先每次 render 都重建整个 Map，
  // 翻页/开关弹窗时都会白跑一遍，故按任务列表缓存
  const taskMap = useMemo(
    () =>
      new Map(
        (tasks.data?.data ?? []).map((item) => [
          item.id,
          item.display_title || item.track_name || item.id.slice(0, 8),
        ]),
      ),
    [tasks.data],
  )

  const logs = useQuery({
    // 报告 O4：页码 / 每页条数进 URL 后可为任意值，缓存键必须带上 pageSize
    queryKey: ["douyin-request-logs", applied, skip, pageSize],
    queryFn: () =>
      DouyinService.listRequestLogs(buildQuery(applied, skip, pageSize)),
  })
  // rows 作为下方 useMemo 的依赖，需保持引用稳定（`?? []` 每次渲染都会新建数组）
  const rows = useMemo(() => logs.data?.data ?? [], [logs.data])
  const total = logs.data?.count ?? 0

  // 报告 A11：表尾合计只算「本页」——平均耗时与成功率（当前页数据，不代表全量）
  const pageStats = useMemo(() => {
    if (!rows.length) return null
    const okCount = rows.filter(
      (item) =>
        item.response_status !== null &&
        item.response_status >= 200 &&
        item.response_status < 400,
    ).length
    return {
      avgDuration: Math.round(
        rows.reduce((sum, item) => sum + item.duration_ms, 0) / rows.length,
      ),
      successRate: Math.round((okCount / rows.length) * 100),
    }
  }, [rows])

  // 报告 A13：表视图键盘导航（↑↓ 移动、回车打开详情），仅在表格视图启用
  const rowIds = useMemo(() => rows.map((item) => item.id), [rows])
  const nav = useRowKeyboardNav({
    rowIds,
    enabled: viewMode === "table",
    onActivate: (id) => {
      const item = rows.find((row) => row.id === id)
      if (item) setDetail(item)
    },
  })

  // 报告 A1：表尾合计行随可见列变形 —— 首格默认跨「可见的前 4 列」；
  // 这 4 列全被隐藏时，把文案并入 耗时 → 任务 → 操作 里第一个可见的单元格，
  // 保证表尾格子总数与表头始终一致（否则隐藏列后合计行会整体错位）
  const footerLeadSpan = FOOTER_LEAD_KEYS.filter(isVisible).length
  const footerSummaryKey =
    footerLeadSpan > 0
      ? null
      : (["duration", "task", "actions"].find((key) => isVisible(key)) ?? null)
  const footerSummary = pageStats
    ? `本页均值（${rows.length} 条 · 成功率 ${pageStats.successRate}%）`
    : ""

  // 报告 A4：是否有「已应用」的筛选 —— 空态据此区分「筛选无结果」与「确实没有日志」
  const hasActiveFilters = Boolean(
    applied.taskId ||
      applied.method ||
      applied.path ||
      applied.responseStatus !== undefined ||
      applied.createdFrom ||
      applied.createdTo,
  )

  // 当前草稿态筛选值，供查询、chips、预设三处复用
  const currentValues: FilterValues = {
    taskId,
    method,
    path: pathContains,
    responseStatus,
    createdFrom,
    createdTo,
  }

  const applyFilters = () => {
    setPage(1)
    setApplied(toApplied(currentValues))
  }

  // 报告 A2：移除单个 chip 时同步回填草稿并立即触发查询
  const resetDraft = (patch: Partial<FilterValues>) => {
    setTaskId(patch.taskId ?? ALL_TASKS)
    setMethod((patch.method ?? "all") as MethodFilter)
    setPathContains(patch.path ?? "")
    setResponseStatus(patch.responseStatus ?? "")
    setCreatedFrom(patch.createdFrom ?? "")
    setCreatedTo(patch.createdTo ?? "")
    setPage(1)
    setApplied(toApplied({ ...currentValues, ...patch }))
  }

  // 报告 A10：套用预设时回填草稿并立即查询
  const applyPreset = (raw: Record<string, unknown>) => {
    const values: FilterValues = {
      taskId: typeof raw.taskId === "string" ? raw.taskId : ALL_TASKS,
      method: typeof raw.method === "string" ? raw.method : "all",
      path: typeof raw.path === "string" ? raw.path : "",
      responseStatus:
        typeof raw.responseStatus === "string" ? raw.responseStatus : "",
      createdFrom: typeof raw.createdFrom === "string" ? raw.createdFrom : "",
      createdTo: typeof raw.createdTo === "string" ? raw.createdTo : "",
    }
    setTaskId(values.taskId)
    setMethod(values.method as MethodFilter)
    setPathContains(values.path)
    setResponseStatus(values.responseStatus)
    setCreatedFrom(values.createdFrom)
    setCreatedTo(values.createdTo)
    setPage(1)
    setApplied(toApplied(values))
  }

  const clearAllFilters = () =>
    resetDraft({
      taskId: ALL_TASKS,
      method: "all",
      path: "",
      responseStatus: "",
      createdFrom: "",
      createdTo: "",
    })

  return (
    <div className="page-stack">
      <PageHero
        compact
        title="请求日志"
        actions={
          // 报告 A14：请求日志只做手动刷新（不轮询），仅替换原刷新按钮
          <RefreshIndicator
            updatedAt={logs.dataUpdatedAt}
            refreshing={logs.isFetching}
            onRefresh={() => void logs.refetch()}
          />
        }
      />

      <Card>
        <CardContent className="space-y-2 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <div>
              <label htmlFor="request-log-task" className="sr-only">
                采集任务
              </label>
              <Select value={taskId} onValueChange={setTaskId}>
                <SelectTrigger
                  id="request-log-task"
                  className="h-9 w-48"
                  aria-label="采集任务"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_TASKS}>全部任务</SelectItem>
                  {(tasks.data?.data ?? []).map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.display_title ||
                        item.track_name ||
                        item.id.slice(0, 8)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label htmlFor="request-log-method" className="sr-only">
                请求方法
              </label>
              <Select
                value={method}
                onValueChange={(value) => setMethod(value as MethodFilter)}
              >
                <SelectTrigger
                  id="request-log-method"
                  className="h-9 w-32"
                  aria-label="请求方法"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部方法</SelectItem>
                  <SelectItem value="GET">GET</SelectItem>
                  <SelectItem value="POST">POST</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label htmlFor="request-log-path" className="sr-only">
                路径包含
              </label>
              <Input
                id="request-log-path"
                aria-label="路径包含"
                placeholder="如 aweme/detail"
                className="h-9 w-44"
                value={pathContains}
                onChange={(event) => setPathContains(event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="request-log-status" className="sr-only">
                响应状态码
              </label>
              <Input
                id="request-log-status"
                aria-label="响应状态码"
                placeholder="如 403"
                className="h-9 w-28"
                inputMode="numeric"
                value={responseStatus}
                onChange={(event) => setResponseStatus(event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="request-log-from" className="sr-only">
                开始时间
              </label>
              <Input
                id="request-log-from"
                aria-label="开始时间"
                type="datetime-local"
                className="h-9 w-44"
                value={createdFrom}
                onChange={(event) => setCreatedFrom(event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="request-log-to" className="sr-only">
                结束时间
              </label>
              <Input
                id="request-log-to"
                aria-label="结束时间"
                type="datetime-local"
                className="h-9 w-44"
                value={createdTo}
                onChange={(event) => setCreatedTo(event.target.value)}
              />
            </div>
            <Button size="sm" className="h-9" onClick={applyFilters}>
              <FileSearch aria-hidden="true" />
              查询
            </Button>
            {/* 报告 A12：导出当前页请求日志（不做全量导出，需后端流式接口） */}
            <Button
              size="sm"
              variant="outline"
              className="h-9 gap-1.5"
              aria-label="导出当前页请求日志为 CSV"
              disabled={rows.length === 0}
              onClick={() =>
                downloadCsv("请求日志", rows, [
                  {
                    header: "时间",
                    value: (item) => formatDateTime(item.created_at),
                  },
                  { header: "方法", value: (item) => item.method },
                  { header: "路径", value: (item) => item.path },
                  { header: "状态码", value: (item) => item.response_status },
                  { header: "耗时(ms)", value: (item) => item.duration_ms },
                  { header: "任务 ID", value: (item) => item.task_id },
                ])
              }
            >
              <Download aria-hidden="true" />
              导出
            </Button>
            {/* 报告 A1：列可见性 —— 卡片/行视图不是表格，只在表格视图露出入口 */}
            {viewMode === "table" && <TableColumnMenu {...menuProps} />}
            <ViewModeToggle
              value={viewMode}
              onChange={setViewMode}
              className="ml-auto"
            />
          </div>

          {/* 报告 A2：已应用筛选条件的 chips 可视化 */}
          <FilterChips
            chips={[
              Boolean(applied.taskId) && {
                key: "task",
                label: "任务",
                value:
                  taskMap.get(applied.taskId as string) ??
                  (applied.taskId as string).slice(0, 8),
                onRemove: () => resetDraft({ taskId: ALL_TASKS }),
              },
              Boolean(applied.method) && {
                key: "method",
                label: "方法",
                value: applied.method as string,
                onRemove: () => resetDraft({ method: "all" }),
              },
              Boolean(applied.path) && {
                key: "path",
                label: "路径包含",
                value: applied.path as string,
                onRemove: () => resetDraft({ path: "" }),
              },
              applied.responseStatus !== undefined && {
                key: "status",
                label: "状态码",
                value: String(applied.responseStatus),
                onRemove: () => resetDraft({ responseStatus: "" }),
              },
              Boolean(applied.createdFrom) && {
                key: "from",
                label: "开始时间",
                value: formatDateTime(applied.createdFrom),
                onRemove: () => resetDraft({ createdFrom: "" }),
              },
              Boolean(applied.createdTo) && {
                key: "to",
                label: "结束时间",
                value: formatDateTime(applied.createdTo),
                onRemove: () => resetDraft({ createdTo: "" }),
              },
            ]}
            onClearAll={clearAllFilters}
          />

          {/* 报告 A10：筛选预设（本页 storageKey 唯一） */}
          <FilterPresetBar
            storageKey="douyin-request-logs-filter-presets"
            currentFilters={currentValues}
            onApply={applyPreset}
          />

          {logs.isError ? (
            <QueryErrorState
              title="请求日志加载失败"
              description="无法获取请求日志，可能是后端不可用，请稍后重试。"
              onRetry={() => logs.refetch()}
              retrying={logs.isFetching}
            />
          ) : viewMode === "table" ? (
            // 报告 A13：容器接管 ↑↓ / Enter / Esc，只标 data-active，不抢行内按钮焦点
            <div
              className="overflow-x-auto rounded-xl border outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
              {...nav.containerProps}
            >
              {/* 报告 O21：列多，窄屏靠外层 overflow-x-auto 横滚，给表格一个最小宽度避免列被压扁 */}
              <Table className="min-w-[900px]">
                <TableHeader>
                  <TableRow>
                    {/* 报告 A1：列可见性 —— 表头与每一行的单元格都要同步包 isVisible，漏一处就列错位 */}
                    {isVisible("time") && <TableHead>时间</TableHead>}
                    {isVisible("method") && <TableHead>方法</TableHead>}
                    {isVisible("path") && <TableHead>路径</TableHead>}
                    {isVisible("status") && <TableHead>状态</TableHead>}
                    {isVisible("duration") && <TableHead>耗时</TableHead>}
                    {isVisible("task") && <TableHead>任务</TableHead>}
                    {/* 报告 A8：操作列冻结 */}
                    {isVisible("actions") && (
                      <TableHead className="sticky right-0 z-10 bg-background/95 text-right backdrop-blur">
                        操作
                      </TableHead>
                    )}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {logs.isLoading ? (
                    // 报告 O8：加载态用骨架屏顶住表格结构，避免内容就位时整页跳动
                    Array.from({ length: 6 }).map((_, index) => (
                      <TableRow
                        key={`log-skeleton-${index}`}
                        aria-hidden="true"
                      >
                        {/* 报告 A1：占位行与真实行同构，每个单元格同样要跟着 isVisible */}
                        {isVisible("time") && (
                          <TableCell>
                            <Skeleton className="h-4 w-20" />
                          </TableCell>
                        )}
                        {isVisible("method") && (
                          <TableCell>
                            <Skeleton className="h-4 w-12" />
                          </TableCell>
                        )}
                        {isVisible("path") && (
                          <TableCell>
                            <Skeleton className="h-4 w-full max-w-md" />
                          </TableCell>
                        )}
                        {isVisible("status") && (
                          <TableCell>
                            <Skeleton className="h-5 w-12 rounded-full" />
                          </TableCell>
                        )}
                        {isVisible("duration") && (
                          <TableCell>
                            <Skeleton className="h-4 w-14" />
                          </TableCell>
                        )}
                        {isVisible("task") && (
                          <TableCell>
                            <Skeleton className="h-4 w-24" />
                          </TableCell>
                        )}
                        {/* 占位行也要保持操作列的冻结底色，否则横滚时会透出下层 */}
                        {isVisible("actions") && (
                          <TableCell className="sticky right-0 bg-background/95 backdrop-blur" />
                        )}
                      </TableRow>
                    ))
                  ) : rows.length ? (
                    rows.map((item) => (
                      <TableRow
                        key={item.id}
                        data-active={nav.activeId === item.id}
                        className="data-[active=true]:bg-primary/[0.05]"
                      >
                        {/* 报告 A16：时间点改用相对时间；耗时列是时长，保持原样 */}
                        {isVisible("time") && (
                          <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                            <TimeAgo value={item.created_at} />
                          </TableCell>
                        )}
                        {isVisible("method") && (
                          <TableCell>
                            <span className="font-mono text-xs">
                              {item.method}
                            </span>
                          </TableCell>
                        )}
                        {isVisible("path") && (
                          <TableCell className="max-w-md">
                            <p
                              className="truncate font-mono text-xs"
                              title={item.path}
                            >
                              {item.path}
                            </p>
                            {item.error && (
                              <p className="mt-1 text-xs text-destructive">
                                {item.error}
                              </p>
                            )}
                            {item.failure_detail && (
                              <p
                                className="mt-1 truncate text-xs text-destructive/85"
                                title={failureSummary(item.failure_detail)}
                              >
                                返回：{failureSummary(item.failure_detail)}
                              </p>
                            )}
                          </TableCell>
                        )}
                        {isVisible("status") && (
                          <TableCell>
                            <StatusBadge status={item.response_status} />
                          </TableCell>
                        )}
                        {isVisible("duration") && (
                          <TableCell className="whitespace-nowrap text-xs">
                            {item.duration_ms} ms
                          </TableCell>
                        )}
                        {isVisible("task") && (
                          <TableCell>
                            {item.task_id ? (
                              <Link
                                to="/douyin/$taskId"
                                params={{ taskId: item.task_id }}
                                className="text-xs text-muted-foreground hover:text-primary"
                              >
                                {taskMap.get(item.task_id) ??
                                  item.task_id.slice(0, 8)}
                              </Link>
                            ) : (
                              <span className="text-xs text-muted-foreground">
                                —
                              </span>
                            )}
                          </TableCell>
                        )}
                        {isVisible("actions") && (
                          <TableCell className="sticky right-0 bg-background/95 backdrop-blur">
                            <div className="flex justify-end">
                              <Button
                                size="icon-sm"
                                variant="ghost"
                                aria-label="查看请求详情"
                                onClick={() => setDetail(item)}
                              >
                                <Eye aria-hidden="true" />
                              </Button>
                            </div>
                          </TableCell>
                        )}
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      {/* 报告 A1：空态行的 colSpan 必须用 visibleCount，写死数字隐藏列后会只占一半宽 */}
                      <TableCell colSpan={visibleCount} className="p-0">
                        <RequestLogsEmpty
                          filtered={hasActiveFilters}
                          onClearFilters={clearAllFilters}
                          onRefresh={() => void logs.refetch()}
                        />
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
                {/* 报告 A11：表尾合计 —— 只统计当前页，故显式标注「本页均值」 */}
                {/* 报告 A1：表尾单元格也要跟着 isVisible，否则合计行会错位 */}
                {pageStats && (
                  <TableFooter>
                    <TableRow>
                      {footerLeadSpan > 0 && (
                        <TableCell
                          colSpan={footerLeadSpan}
                          className="text-xs font-normal text-muted-foreground"
                        >
                          {footerSummary}
                        </TableCell>
                      )}
                      {isVisible("duration") && (
                        <TableCell className="whitespace-nowrap text-xs">
                          {footerSummaryKey === "duration"
                            ? `${footerSummary} · `
                            : null}
                          平均 {pageStats.avgDuration} ms
                        </TableCell>
                      )}
                      {isVisible("task") && (
                        <TableCell>
                          {footerSummaryKey === "task" ? (
                            <span className="text-xs font-normal text-muted-foreground">
                              {footerSummary}
                            </span>
                          ) : null}
                        </TableCell>
                      )}
                      <TableCell className="sticky right-0 bg-background/95 backdrop-blur">
                        {footerSummaryKey === "actions" ? (
                          <span className="text-xs font-normal text-muted-foreground">
                            {footerSummary}
                          </span>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  </TableFooter>
                )}
              </Table>
            </div>
          ) : logs.isLoading ? (
            // 报告 O8：卡片/行视图的加载骨架，保持与真实卡片相同的分栏
            <div
              className={
                viewMode === "cards"
                  ? "grid gap-3 md:grid-cols-2 xl:grid-cols-3"
                  : "space-y-2"
              }
            >
              {Array.from({ length: 6 }).map((_, index) => (
                <div
                  key={`log-skeleton-${index}`}
                  aria-hidden="true"
                  className="space-y-3 rounded-xl border bg-card p-4"
                >
                  <Skeleton className="h-4 w-28" />
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-40" />
                </div>
              ))}
            </div>
          ) : rows.length ? (
            <div
              className={
                viewMode === "cards"
                  ? "grid gap-3 md:grid-cols-2 xl:grid-cols-3"
                  : "space-y-2"
              }
            >
              {rows.map((item) => (
                <RequestLogPreview
                  key={item.id}
                  log={item}
                  taskLabel={
                    item.task_id
                      ? (taskMap.get(item.task_id) ?? item.task_id.slice(0, 8))
                      : null
                  }
                  viewMode={viewMode}
                  onOpen={() => setDetail(item)}
                />
              ))}
            </div>
          ) : (
            <RequestLogsEmpty
              filtered={hasActiveFilters}
              compact={false}
              onClearFilters={clearAllFilters}
              onRefresh={() => void logs.refetch()}
            />
          )}

          {/* 出错时不渲染分页器，避免「共 0 条」与实际状态不符 */}
          {!logs.isError && (
            <Pager
              page={page - 1}
              pageSize={pageSize}
              total={total}
              onPageChange={(nextPage) => setPage(nextPage + 1)}
              // 报告 O4：每页条数也进 URL；改条数后回到第 1 页
              onPageSizeChange={(nextSize) => {
                setPageSize(nextSize)
                setPage(1)
              }}
              showJumper
              totalLabel={(count) => `共 ${count} 条记录`}
            />
          )}
        </CardContent>
      </Card>

      <RequestLogDetail
        log={detail}
        taskLabel={
          detail?.task_id ? (taskMap.get(detail.task_id) ?? null) : null
        }
        onClose={() => setDetail(null)}
      />
    </div>
  )
}

/**
 * 报告 A4 / O8：空态区分两种成因 ——
 * 有筛选条件时是「筛选无结果」，引导清除筛选；没有筛选条件才是「确实没有日志」，
 * 引导刷新。两者原先共用一句「没有符合筛选条件的请求日志」，用户无从下手。
 */
function RequestLogsEmpty({
  filtered,
  compact = true,
  onClearFilters,
  onRefresh,
}: {
  filtered: boolean
  compact?: boolean
  onClearFilters: () => void
  onRefresh: () => void
}) {
  if (filtered) {
    return (
      <EmptyState
        compact={compact}
        icon={FileSearch}
        title="没有符合筛选条件的请求日志"
        description="当前筛选组合下没有记录，可以放宽或清除筛选条件后重试。"
        action={
          <Button size="sm" variant="outline" onClick={onClearFilters}>
            清除筛选条件
          </Button>
        }
      />
    )
  }
  return (
    <EmptyState
      compact={compact}
      icon={Inbox}
      title="还没有请求日志"
      description="采集任务运行时的接口调用会记录在这里，运行一次任务后再回来查看。"
      action={
        <Button size="sm" variant="outline" onClick={onRefresh}>
          刷新日志
        </Button>
      }
    />
  )
}

function RequestLogPreview({
  log,
  taskLabel,
  viewMode,
  onOpen,
}: {
  log: DouyinRequestLogPublic
  taskLabel: string | null
  viewMode: Exclude<ListViewMode, "table">
  onOpen: () => void
}) {
  return (
    <div
      className={`rounded-xl border bg-card p-4 ${
        viewMode === "rows" ? "flex items-center gap-4" : "space-y-3"
      }`}
    >
      <div className={viewMode === "rows" ? "min-w-0 flex-1" : "min-w-0"}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs font-semibold">{log.method}</span>
          <StatusBadge status={log.response_status} />
          <span className="text-xs text-muted-foreground">
            {log.duration_ms} ms
          </span>
        </div>
        <p className="mt-2 truncate font-mono text-xs" title={log.path}>
          {log.path}
        </p>
        {log.error && (
          <p className="mt-1 truncate text-xs text-destructive">{log.error}</p>
        )}
        {log.failure_detail && (
          <p className="mt-1 line-clamp-2 text-xs text-destructive/85">
            返回：{failureSummary(log.failure_detail)}
          </p>
        )}
      </div>
      <div
        className={`flex items-center gap-3 text-xs text-muted-foreground ${
          viewMode === "rows" ? "shrink-0" : "justify-between"
        }`}
      >
        {/* 报告 A16：时间点改用相对时间 */}
        <TimeAgo value={log.created_at} />
        {taskLabel && <span className="max-w-32 truncate">{taskLabel}</span>}
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label="查看请求详情"
          onClick={onOpen}
        >
          <Eye aria-hidden="true" />
        </Button>
      </div>
    </div>
  )
}

function buildQuery(
  applied: AppliedFilters,
  skip: number,
  // 报告 O4：每页条数可被 URL 覆盖，不再是常量 PAGE_SIZE
  pageSize: number,
): DouyinListRequestLogsData {
  return {
    ...applied,
    skip,
    limit: pageSize,
  }
}

function StatusBadge({ status }: { status: number | null }) {
  if (status === null) {
    return <Badge variant="destructive">异常</Badge>
  }
  if (status >= 500) {
    return <Badge variant="destructive">{status}</Badge>
  }
  if (status >= 400) {
    return <Badge variant="secondary">{status}</Badge>
  }
  return <Badge variant="outline">{status}</Badge>
}

function RequestLogDetail({
  log,
  taskLabel,
  onClose,
}: {
  log: DouyinRequestLogPublic | null
  taskLabel: string | null
  onClose: () => void
}) {
  return (
    <Dialog open={Boolean(log)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>抖音接口请求详情</DialogTitle>
          <DialogDescription>
            请求信息和失败返回均经过脱敏；超长失败正文只保留诊断预览，日志仅对任务所有者可见。
          </DialogDescription>
        </DialogHeader>
        {log && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm font-semibold">
                {log.method}
              </span>
              <StatusBadge status={log.response_status} />
              <span className="text-xs text-muted-foreground">
                {log.duration_ms} ms · {formatDateTime(log.created_at)}
              </span>
              {taskLabel && (
                <span className="text-xs text-muted-foreground">
                  任务：{taskLabel}
                </span>
              )}
            </div>
            {log.error && (
              <p className="text-sm text-destructive">异常类型：{log.error}</p>
            )}
            <JsonSection title="完整请求地址" value={log.url} mono />
            <JsonSection title="查询参数" value={log.query_params} />
            <JsonSection title="请求头" value={log.request_headers} />
            {log.request_body !== null && (
              <JsonSection title="请求体" value={log.request_body} />
            )}
            {log.failure_detail !== null && (
              <JsonSection
                title="失败返回信息（已脱敏）"
                value={log.failure_detail}
              />
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function JsonSection({
  title,
  value,
  mono = false,
}: {
  title: string
  value: unknown
  mono?: boolean
}) {
  const text =
    typeof value === "string" ? value : (JSON.stringify(value, null, 2) ?? "{}")
  return (
    <div>
      <h3 className="mb-1.5 text-sm font-medium">{title}</h3>
      <pre
        className={`max-h-56 overflow-auto rounded-lg border bg-muted/25 p-3 text-xs ${
          mono ? "font-mono" : ""
        }`}
      >
        {text}
      </pre>
    </div>
  )
}

function failureSummary(value: Record<string, unknown>) {
  const body = value.body
  if (typeof body === "string" && body.trim()) return body.trim().slice(0, 120)
  if (body && typeof body === "object" && !Array.isArray(body)) {
    const payload = body as Record<string, unknown>
    const messageKeys = [
      "status_msg",
      "message",
      "msg",
      "detail",
      "description",
    ]
    for (const key of messageKeys) {
      if (typeof payload[key] === "string" && payload[key]) {
        return String(payload[key]).slice(0, 120)
      }
    }
    const nilInfo = payload.search_nil_info
    if (nilInfo && typeof nilInfo === "object" && !Array.isArray(nilInfo)) {
      const nilType = (nilInfo as Record<string, unknown>).search_nil_type
      if (typeof nilType === "string" && nilType) return nilType
    }
    if (payload.status_code !== undefined) {
      return `业务状态 ${String(payload.status_code)}`
    }
  }
  if (typeof value.message === "string" && value.message) {
    return value.message.slice(0, 120)
  }
  return "已记录失败返回信息"
}
