import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  History,
  ListFilter,
  LoaderCircle,
  Play,
  Plus,
  Search,
  SearchX,
  Tags,
  Trash2,
} from "lucide-react"
import {
  type FormEvent,
  type ReactNode,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react"

import {
  DouyinAccountsService,
  type DouyinKeywordPublic,
  type DouyinKeywordStatus,
  DouyinKeywordsService,
  DouyinTracksService,
} from "@/client"
import { BulkActionBar } from "@/components/Common/BulkActionBar"
// 报告 O15：统一确认框替代 window.confirm
import { confirmDialog } from "@/components/Common/confirm-dialog"
// 报告 A4/O8：统一空态（图标 + 标题 + 说明 + 主行动）
import { EmptyState } from "@/components/Common/EmptyState"
import { FilterChips } from "@/components/Common/FilterChips"
import { FilterPresetBar } from "@/components/Common/FilterPresetBar"
import { Pager } from "@/components/Common/Pager"
import { PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { RefreshIndicator } from "@/components/Common/RefreshIndicator"
// 报告 A1：手写表格的列可见性
import { TableColumnMenu } from "@/components/Common/TableColumnMenu"
import { TimeAgo } from "@/components/Common/TimeAgo"
import {
  type ListViewMode,
  usePersistentViewMode,
  ViewModeToggle,
} from "@/components/Common/ViewModeToggle"
import { TaskStatusBadge } from "@/components/Douyin/TaskStatusBadge"
import {
  allTracksValue,
  TrackBadge,
  TrackSelect,
  useTrackCatalog,
} from "@/components/Douyin/TrackSelect"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
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
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
// 报告 A6：行级数据变化高亮
import { useHighlightedRows } from "@/hooks/useHighlightedRows"
import { type TableColumnDef, useTableColumns } from "@/hooks/useTableColumns"
// 报告 O4：筛选上 URL
import {
  compactSearch,
  readEnumParam,
  readStringParam,
} from "@/lib/search-params"
import { cn } from "@/lib/utils"
import { handleError } from "@/utils"

/**
 * 报告 O4：筛选上 URL 的 search 形状。
 * 字段一律声明为**可选属性**（`x?: T` 而非 `x: T | undefined`）：
 * TS 里后者的键是必填的，会让所有指向本路由的 Link/navigate 被要求显式传 search。
 * 各字段的取值上界与页面 state 对齐（status/enabled 都含 "all" 这一「不筛选」值）。
 */
type KeywordSearch = {
  q?: string
  track?: string
  category?: string
  status?: DouyinKeywordStatus | "all"
  enabled?: "all" | "true" | "false"
  sort?: string
  page?: number
}

export const Route = createFileRoute("/_layout/douyin-keywords")({
  component: DouyinKeywordsPage,
  head: () => ({ meta: [{ title: "关键词管理 - 灵感采集台" }] }),
  // 报告 O4：筛选上 URL —— 刷新/分享/深链都能还原筛选，白名单挡住手改 URL 的脏值
  validateSearch: (search: Record<string, unknown>): KeywordSearch => ({
    q: readStringParam(search, "q"),
    track: readStringParam(search, "track"),
    category: readStringParam(search, "category"),
    status: readEnumParam(search, "status", KEYWORD_STATUS_VALUES),
    enabled: readEnumParam(search, "enabled", ENABLED_FILTER_VALUES),
    sort: readEnumParam(search, "sort", SORT_VALUES),
    page: readPageParam(search),
  }),
})

const pageSize = 50
const statusLabels: Record<DouyinKeywordStatus, string> = {
  unprocessed: "未爬取",
  active: "进行中",
  crawled: "已爬取",
  failed: "需要重试",
}
// 排序下拉与排序 chip 共用同一份文案，避免两处维护不一致
const sortLabels: Record<string, string> = {
  "last_crawled_at:desc": "最近爬取",
  "created_at:desc": "最近创建",
  "keyword:asc": "关键词 A-Z",
  "task_count:desc": "关联任务最多",
  "aweme_count:desc": "作品最多",
  "status:asc": "优先处理状态",
}
const defaultSort = "last_crawled_at:desc"
const enabledLabels: Record<"true" | "false", string> = {
  true: "已启用",
  false: "已停用",
}

// 报告 O4：筛选上 URL —— 白名单枚举，与上面的标签表保持一致
const KEYWORD_STATUS_VALUES = [
  "all",
  "unprocessed",
  "active",
  "crawled",
  "failed",
] as const
const ENABLED_FILTER_VALUES = ["all", "true", "false"] as const
const SORT_VALUES = [
  "last_crawled_at:desc",
  "created_at:desc",
  "keyword:asc",
  "task_count:desc",
  "aweme_count:desc",
  "status:asc",
] as const

/**
 * 报告 A1：列可见性 —— 关键词表格视图的列清单。
 * 必须是模块级稳定常量：放在组件内每次 render 都会新建数组，
 * useTableColumns 的内部 memo 会失效、本地偏好被反复重置。
 */
const KEYWORD_COLUMNS = [
  { key: "select", title: "选择", alwaysVisible: true },
  { key: "keyword", title: "关键词" },
  { key: "track", title: "所属赛道" },
  { key: "status", title: "爬取状态" },
  { key: "tasks", title: "任务表现" },
  { key: "aweme", title: "来源作品" },
  { key: "crawled", title: "最近爬取" },
  // 操作列不允许隐藏，否则用户就没法停用/移动/删除
  { key: "actions", title: "操作", alwaysVisible: true },
] as const satisfies readonly TableColumnDef[]

/** 报告 O4：页码从 URL 取非负整数，非法值一律忽略（回落到第一页） */
function readPageParam(search: Record<string, unknown>) {
  const raw = readStringParam(search, "page")
  if (raw === undefined) return undefined
  const value = Number(raw)
  return Number.isInteger(value) && value >= 0 ? value : undefined
}

/** 筛选预设（报告 A10）持久化的筛选快照结构 */
type KeywordFilters = {
  search: string
  trackId: string
  category: string
  status: DouyinKeywordStatus | "all"
  enabled: "all" | "true" | "false"
  sort: string
}

function DouyinKeywordsPage() {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  // 报告 O4：筛选上 URL —— 筛选初值来自 URL，深链/刷新因此能还原
  const routeSearch = Route.useSearch()
  const navigate = Route.useNavigate()
  const [page, setPage] = useState(routeSearch.page ?? 0)
  // 默认查全部关键词：赛道是可选筛选，未指定时按“全部赛道”查询
  const [trackId, setTrackId] = useState(routeSearch.track ?? allTracksValue)
  /** 传给接口的赛道作用域：全部赛道 → 不传该参数 */
  const scopeTrackId = trackId === allTracksValue ? undefined : trackId
  const [search, setSearch] = useState(routeSearch.q ?? "")
  // 输入框即时回显，查询与查询键跟随延迟值，避免每次按键都打一次列表请求
  const deferredSearch = useDeferredValue(search)
  const [status, setStatus] = useState<DouyinKeywordStatus | "all">(
    routeSearch.status ?? "all",
  )
  const [category, setCategory] = useState(routeSearch.category ?? "all")
  const [enabled, setEnabled] = useState<"all" | "true" | "false">(
    routeSearch.enabled ?? "all",
  )
  const [sort, setSort] = useState<string>(routeSearch.sort ?? defaultSort)
  // 报告 A14：自动刷新开关，默认开启以保留原有 5 秒轮询节奏
  const [autoRefresh, setAutoRefresh] = useState(true)
  // 用 Set 存选中项，把 O(n) 的 includes 判断换成 O(1) 的 has
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [viewMode, setViewMode] = usePersistentViewMode("douyin-keywords-view")
  // 报告 A1：列可见性（只作用于表格视图；cards / rows 视图不是表格，不做处理）
  const { isVisible, visibleCount, menuProps } = useTableColumns({
    storageKey: "douyin-keywords-columns",
    columns: KEYWORD_COLUMNS,
  })
  // 报告 O4：筛选变化回写 URL；只把「已应用」的筛选值写进去（搜索框去掉首尾空白后写）
  // 用 replace 而不是 push：否则每改一次筛选就多一条历史记录，后退十次才离得开本页。
  // 取舍：刷新/分享/深链/收藏全部生效，但浏览器「后退」回到上一个页面而非上一条筛选。
  useEffect(() => {
    void navigate({
      to: "/douyin-keywords",
      replace: true,
      search: compactSearch(
        {
          q: search.trim() || undefined,
          track: scopeTrackId,
          category,
          status,
          enabled,
          sort,
          page,
        },
        // 等于默认值的键不进 URL，未筛选时地址栏就保持 /douyin-keywords
        {
          category: "all",
          status: "all",
          enabled: "all",
          sort: defaultSort,
          page: 0,
        },
      ),
    })
  }, [search, category, status, enabled, sort, page, navigate, scopeTrackId])
  const tracksQuery = useTrackCatalog()
  const selectedTrack = tracksQuery.data?.data.find(
    (track) => track.id === scopeTrackId,
  )
  const trackDetailQuery = useQuery({
    queryKey: ["douyin-track", scopeTrackId],
    queryFn: () => DouyinTracksService.getTrack({ trackId: scopeTrackId! }),
    enabled: Boolean(scopeTrackId),
  })
  const categories = trackDetailQuery.data?.keyword_categories ?? []
  const [sortBy, sortOrder] = sort.split(":") as [
    (
      | "keyword"
      | "status"
      | "task_count"
      | "aweme_count"
      | "last_crawled_at"
      | "created_at"
    ),
    "asc" | "desc",
  ]
  const query = useQuery({
    queryKey: [
      "douyin-keywords",
      trackId,
      page,
      deferredSearch,
      status,
      category,
      enabled,
      sort,
    ],
    queryFn: () =>
      DouyinKeywordsService.listKeywords({
        trackId: scopeTrackId,
        search: deferredSearch.trim() || undefined,
        category: category === "all" ? undefined : category,
        status: status === "all" ? undefined : status,
        enabled: enabled === "all" ? undefined : enabled === "true",
        sortBy,
        sortOrder,
        skip: page * pageSize,
        limit: pageSize,
      }),
    placeholderData: (previous) => previous,
    // 全部赛道也要能查：赛道只是可选筛选，不再是必填作用域
    enabled: true,
    // 报告 A14：轮询节奏交给刷新指示器的「自动刷新」开关（默认开启，与改造前一致）
    refetchInterval: autoRefresh ? 5_000 : false,
  })
  const overviewQuery = useQuery({
    queryKey: ["douyin-keywords-overview", scopeTrackId],
    queryFn: () =>
      DouyinKeywordsService.listKeywords({
        trackId: scopeTrackId,
        limit: 500,
      }),
    enabled: true,
    // 概览计数与列表共用同一个自动刷新开关，避免关掉后计数仍在后台轮询
    refetchInterval: autoRefresh ? 10_000 : false,
  })
  const rows = query.data?.data ?? []
  const allRows = overviewQuery.data?.data ?? []
  // 概览数据是全量列表，每次 render 都重算四类计数会拖慢输入回显，这里 memo 掉
  const metrics = useMemo(
    () => ({
      total: overviewQuery.data?.count ?? 0,
      unprocessed: allRows.filter((item) => item.status === "unprocessed")
        .length,
      active: allRows.filter((item) => item.status === "active").length,
      crawled: allRows.filter((item) => item.status === "crawled").length,
      failed: allRows.filter((item) => item.status === "failed").length,
    }),
    [allRows, overviewQuery.data?.count],
  )
  // 本页 id 与全选状态同属派生计算，一并 memo，避免翻页/勾选时全量重算
  const pageIds = useMemo(() => rows.map((item) => item.id), [rows])
  const allPageSelected = useMemo(
    () => pageIds.length > 0 && pageIds.every((id) => selected.has(id)),
    [pageIds, selected],
  )
  // 报告 A6：轮询刷新后状态/作品数变化的行闪一下，指纹取真正代表数据变化的字段
  const highlighted = useHighlightedRows(
    rows,
    (item) => item.id,
    (item) => `${item.status}:${item.task_count}:${item.aweme_count}`,
  )
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["douyin-keywords"] }),
      queryClient.invalidateQueries({ queryKey: ["douyin-keywords-overview"] }),
    ])
  }
  const historySync = useMutation({
    mutationFn: () => DouyinKeywordsService.syncHistoricalKeywords(),
    onSuccess: async (result) => {
      showSuccessToast(
        `已扫描 ${result.task_count} 个任务，新增 ${result.created_count} 个关键词、${result.binding_count} 个绑定`,
      )
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const toggle = useMutation({
    mutationFn: (item: DouyinKeywordPublic) =>
      DouyinKeywordsService.editKeyword({
        keywordId: item.id,
        requestBody: { enabled: !item.enabled },
      }),
    onSuccess: invalidate,
    onError: handleError.bind(showErrorToast),
  })
  const remove = useMutation({
    mutationFn: (id: string) =>
      DouyinKeywordsService.deleteKeyword({ keywordId: id }),
    onSuccess: async (result) => {
      showSuccessToast(result.message)
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const bulkRemove = useMutation({
    mutationFn: (ids: string[]) =>
      DouyinKeywordsService.bulkDeleteKeywords({ requestBody: { ids } }),
    onSuccess: async (result) => {
      showSuccessToast(result.message)
      setSelected(new Set())
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })

  // 赛道是可选筛选：chip 的「移除」与预设回退都回到「全部赛道」
  // 报告 O8：区分「该赛道真的还没有关键词」与「筛选后无结果」，
  // 两者空态要给不同出口：前者引导创建/同步，后者引导清除筛选。
  const scopedToTrack = trackId !== allTracksValue
  const hasActiveFilters =
    Boolean(deferredSearch.trim()) ||
    category !== "all" ||
    status !== "all" ||
    enabled !== "all" ||
    scopedToTrack
  // 报告 A2：筛选 chips 的「清除全部」，一次性回到初始筛选
  const resetFilters = () => {
    setSearch("")
    setTrackId(allTracksValue)
    setCategory("all")
    setStatus("all")
    setEnabled("all")
    setSort(defaultSort)
    setSelected(new Set())
    setPage(0)
  }
  // 报告 A10：当前筛选快照，存预设与套预设共用同一份结构
  const presetFilters: KeywordFilters = {
    search,
    trackId,
    category,
    status,
    enabled,
    sort,
  }
  const applyPreset = (next: KeywordFilters) => {
    setSearch(next.search)
    setTrackId(next.trackId || allTracksValue)
    setCategory(next.category)
    setStatus(next.status)
    setEnabled(next.enabled)
    setSort(next.sort)
    setSelected(new Set())
    setPage(0)
  }
  // 报告 A4/O8：表格内与卡片视图共用同一份空态，避免两处文案漂移；
  // compact 只在表格单元格里用，表格外沿用带虚线边框的完整形态。
  const renderEmpty = (compact: boolean) => (
    <EmptyState
      compact={compact}
      icon={hasActiveFilters ? SearchX : Tags}
      title={
        hasActiveFilters
          ? "没有符合当前条件的关键词"
          : scopedToTrack
            ? "该赛道还没有关键词"
            : "还没有关键词"
      }
      description={
        hasActiveFilters
          ? "可以放宽赛道、分类、爬取状态或启用状态等筛选条件后再试。"
          : "添加关键词后就能按词创建采集任务；也可以先同步历史任务里已经用过的关键词。"
      }
      action={
        hasActiveFilters ? (
          <Button size="sm" variant="outline" onClick={resetFilters}>
            清除筛选条件
          </Button>
        ) : (
          <div className="flex flex-wrap items-center justify-center gap-2">
            <CreateKeywordsDialog
              initialTrackId={trackId}
              onCreated={invalidate}
            />
            <Button
              size="sm"
              variant="outline"
              disabled={historySync.isPending}
              onClick={() => historySync.mutate()}
            >
              <History
                className={historySync.isPending ? "animate-spin" : ""}
              />
              同步历史任务
            </Button>
          </div>
        )
      }
    />
  )

  return (
    <div className="page-stack">
      <PageHero
        compact
        title="关键词管理"
        actions={
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            <span className="mr-1 whitespace-nowrap text-xs text-muted-foreground">
              总数 <strong className="text-foreground">{metrics.total}</strong>{" "}
              · 未爬取{" "}
              <strong className="text-foreground">{metrics.unprocessed}</strong>{" "}
              · 进行中{" "}
              <strong className="text-foreground">{metrics.active}</strong> ·
              已爬取{" "}
              <strong className="text-foreground">{metrics.crawled}</strong> ·
              重试 <strong className="text-foreground">{metrics.failed}</strong>
            </span>
            <Button
              size="sm"
              variant="outline"
              disabled={historySync.isPending}
              onClick={() => historySync.mutate()}
            >
              <History
                className={historySync.isPending ? "animate-spin" : ""}
              />
              同步历史任务
            </Button>
            <CreateKeywordsDialog
              initialTrackId={trackId}
              onCreated={invalidate}
            />
          </div>
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-56 flex-[2]">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value)
                setPage(0)
              }}
              placeholder="搜索关键词或备注"
              aria-label="搜索关键词"
              className="h-9 pl-9"
            />
          </div>
          <TrackSelect
            value={trackId}
            onValueChange={(value) => {
              setTrackId(value)
              setCategory("all")
              setSelected(new Set())
              setPage(0)
            }}
            includeAll
            // 默认就是「全部赛道」，不要再自动跳到默认赛道
            autoSelectDefault={false}
            ariaLabel="按赛道筛选关键词"
            allowDisabled
            className="h-9 min-w-44 flex-1"
          />
          <Select
            value={category}
            onValueChange={(value) => {
              setCategory(value)
              setPage(0)
            }}
          >
            <SelectTrigger
              className="h-9 min-w-32"
              aria-label="按关键词分类筛选"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部分类</SelectItem>
              {categories.map((item) => (
                <SelectItem key={item} value={item}>
                  {item}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={status}
            onValueChange={(value) => {
              setStatus(value as typeof status)
              setPage(0)
            }}
          >
            <SelectTrigger className="h-9 min-w-32" aria-label="按爬取状态筛选">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部状态</SelectItem>
              {Object.entries(statusLabels).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={enabled}
            onValueChange={(value) => {
              setEnabled(value as typeof enabled)
              setPage(0)
            }}
          >
            <SelectTrigger className="h-9 min-w-36" aria-label="按启用状态筛选">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部启用状态</SelectItem>
              {Object.entries(enabledLabels).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={sort}
            onValueChange={(value) => {
              setSort(value)
              setPage(0)
            }}
          >
            <SelectTrigger className="h-9 min-w-36" aria-label="关键词排序方式">
              <ListFilter />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(sortLabels).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="whitespace-nowrap text-xs text-muted-foreground">
            已选 {selected.size}
          </span>
          <ViewModeToggle value={viewMode} onChange={setViewMode} />
          {/* 报告 A14：刷新指示器，替换原先缺位的刷新入口；updatedAt 取主列表 query */}
          <RefreshIndicator
            updatedAt={query.dataUpdatedAt}
            refreshing={query.isFetching}
            onRefresh={() => void query.refetch()}
            autoRefresh={autoRefresh}
            onAutoRefreshChange={setAutoRefresh}
            className="ml-auto"
          />
        </div>
        {/* 报告 A2：已应用筛选的 chips，可单个移除或一键清除 */}
        <FilterChips
          chips={[
            // 条件写成布尔表达式，chips 数组只接受 false/undefined 作为「不展示」
            Boolean(deferredSearch.trim()) && {
              key: "q",
              label: "搜索",
              value: deferredSearch.trim(),
              onRemove: () => {
                setSearch("")
                setPage(0)
              },
            },
            // 赛道是可选筛选，只有选定某个赛道时才算「筛选项」
            scopedToTrack && {
              key: "track",
              label: "赛道",
              value: selectedTrack?.name ?? trackId,
              onRemove: () => {
                setTrackId(allTracksValue)
                setCategory("all")
                setSelected(new Set())
                setPage(0)
              },
            },
            category !== "all" && {
              key: "category",
              label: "分类",
              value: category,
              onRemove: () => {
                setCategory("all")
                setPage(0)
              },
            },
            status !== "all" && {
              key: "status",
              label: "状态",
              value: statusLabels[status],
              onRemove: () => {
                setStatus("all")
                setPage(0)
              },
            },
            enabled !== "all" && {
              key: "enabled",
              label: "启用",
              value: enabledLabels[enabled],
              onRemove: () => {
                setEnabled("all")
                setPage(0)
              },
            },
            sort !== defaultSort && {
              key: "sort",
              label: "排序",
              value: sortLabels[sort] ?? sort,
              onRemove: () => {
                setSort(defaultSort)
                setPage(0)
              },
            },
          ]}
          onClearAll={resetFilters}
          className="mt-2"
        />
        {/* 报告 A10：筛选预设，存下常用筛选组合一键复用 */}
        <FilterPresetBar
          storageKey="douyin-keywords-filter-presets"
          currentFilters={presetFilters}
          onApply={applyPreset}
          className="mt-2"
        />
      </PageHero>

      <Card>
        <CardContent className="space-y-4 p-3">
          {viewMode === "table" ? (
            <div className="space-y-2">
              {/* 报告 A1：列可见性入口，只挂在表格视图上 */}
              <div className="flex justify-end">
                <TableColumnMenu {...menuProps} />
              </div>
              <div className="overflow-x-auto rounded-xl border">
                {/* 报告 21：列较多，给表格加最小宽度，窄屏改为横向滚动而不是压扁列 */}
                <Table className="min-w-[900px]">
                  <TableHeader>
                    <TableRow>
                      {/* 报告 A1：选择列固定可见，不参与隐藏 */}
                      <TableHead className="w-10">
                        <Checkbox
                          checked={allPageSelected}
                          // 报告 7：表头全选只覆盖当前页，标签里写明条数，避免误解成跨页全选
                          aria-label={`全选本页（共 ${pageIds.length} 条）`}
                          onCheckedChange={(checked) =>
                            setSelected((current) => {
                              const next = new Set(current)
                              if (checked) {
                                for (const id of pageIds) next.add(id)
                              } else {
                                for (const id of pageIds) next.delete(id)
                              }
                              return next
                            })
                          }
                        />
                      </TableHead>
                      {/* 报告 A1：表头按列可见性渲染，与下方每个单元格一一对应 */}
                      {isVisible("keyword") && <TableHead>关键词</TableHead>}
                      {isVisible("track") && <TableHead>所属赛道</TableHead>}
                      {isVisible("status") && <TableHead>爬取状态</TableHead>}
                      {isVisible("tasks") && <TableHead>任务表现</TableHead>}
                      {isVisible("aweme") && <TableHead>来源作品</TableHead>}
                      {isVisible("crawled") && <TableHead>最近爬取</TableHead>}
                      <TableHead className="text-right">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.length ? (
                      rows.map((item) => (
                        // 报告 A6：数据变化的行短暂高亮
                        <TableRow
                          key={item.id}
                          className={cn(
                            highlighted.has(item.id) && "row-highlight",
                          )}
                        >
                          <TableCell>
                            <Checkbox
                              checked={selected.has(item.id)}
                              aria-label={`选择关键词 ${item.keyword}`}
                              onCheckedChange={(checked) =>
                                setSelected((current) => {
                                  const next = new Set(current)
                                  if (checked) next.add(item.id)
                                  else next.delete(item.id)
                                  return next
                                })
                              }
                            />
                          </TableCell>
                          {/* 报告 A1：每个单元格都要跟表头同步判断，漏一处整列错位 */}
                          {isVisible("keyword") && (
                            <TableCell className="min-w-64">
                              <div className="flex items-center gap-2">
                                <span className="font-medium">
                                  {item.keyword}
                                </span>
                                {item.category && (
                                  <Badge variant="outline">
                                    {item.category}
                                  </Badge>
                                )}
                                {!item.enabled && (
                                  <Badge variant="secondary">已停用</Badge>
                                )}
                              </div>
                              {item.notes && (
                                <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                                  {formatKeywordNotes(item.notes)}
                                </p>
                              )}
                            </TableCell>
                          )}
                          {isVisible("track") && (
                            <TableCell>
                              <TrackBadge
                                trackId={item.track_id}
                                trackName={item.track_name}
                                isDefault={item.track_is_default}
                              />
                            </TableCell>
                          )}
                          {isVisible("status") && (
                            <TableCell>
                              <KeywordStatusBadge status={item.status} />
                            </TableCell>
                          )}
                          {isVisible("tasks") && (
                            <TableCell className="min-w-40 text-sm">
                              <p>{item.task_count} 个任务</p>
                              <p className="mt-1 text-xs text-muted-foreground">
                                成功 {item.success_task_count} · 失败{" "}
                                {item.failed_task_count} · 运行{" "}
                                {item.active_task_count}
                              </p>
                            </TableCell>
                          )}
                          {isVisible("aweme") && (
                            <TableCell>{item.aweme_count}</TableCell>
                          )}
                          {/* 报告 A16：时间点列改用相对时间，悬停看绝对时间 */}
                          {isVisible("crawled") && (
                            <TableCell className="text-sm text-muted-foreground">
                              <TimeAgo
                                value={item.last_crawled_at}
                                neverText="从未"
                              />
                            </TableCell>
                          )}
                          {/* 报告 A1：操作列固定可见 */}
                          <TableCell>
                            <div className="flex min-w-max justify-end gap-1">
                              <KeywordTasksDialog item={item} />
                              <MoveKeywordDialog
                                item={item}
                                onMoved={invalidate}
                              />
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => toggle.mutate(item)}
                              >
                                {item.enabled ? "停用" : "启用"}
                              </Button>
                              <DeleteKeywordDialog
                                item={item}
                                pending={remove.isPending}
                                onConfirm={() => remove.mutate(item.id)}
                              />
                            </div>
                          </TableCell>
                        </TableRow>
                      ))
                    ) : query.isLoading ? (
                      // 报告 A4：加载态从「正在加载…」换成骨架屏，保留表格结构，
                      // 数据到达时列宽不会跳一下。
                      // 报告 A1：骨架单元格数跟随可见列数，隐藏列后不会多出一格撑破表格。
                      Array.from({ length: 6 }, (_, index) => (
                        <TableRow key={`keywords-skeleton-${index}`}>
                          {Array.from({ length: visibleCount }, (_, cell) => (
                            <TableCell key={cell}>
                              <Skeleton className="h-5 w-full" />
                            </TableCell>
                          ))}
                        </TableRow>
                      ))
                    ) : query.isError ? (
                      // 接口失败原先被并入空态，用户会误以为真的没有数据，这里单独给出错误态与重试
                      <TableRow>
                        {/* 报告 A1：colSpan 跟随可见列数，否则隐藏列后错误态只占一半宽度 */}
                        <TableCell colSpan={visibleCount} className="p-3">
                          <QueryErrorState
                            title="关键词加载失败"
                            description="无法获取关键词列表，请检查网络或后端服务后重试。"
                            onRetry={() => query.refetch()}
                            retrying={query.isFetching}
                          />
                        </TableCell>
                      </TableRow>
                    ) : (
                      // 报告 A4/O8：空态给出图标、说明与主行动按钮（创建 / 同步 / 清除筛选）
                      <TableRow>
                        {/* 报告 A1：colSpan 跟随可见列数，否则隐藏列后空态只占一半宽度 */}
                        <TableCell colSpan={visibleCount} className="p-0">
                          {renderEmpty(true)}
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
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
                <KeywordPreview
                  key={item.id}
                  item={item}
                  viewMode={viewMode}
                  selected={selected.has(item.id)}
                  onSelect={(checked) =>
                    setSelected((current) => {
                      const next = new Set(current)
                      if (checked) next.add(item.id)
                      else next.delete(item.id)
                      return next
                    })
                  }
                  onToggle={() => toggle.mutate(item)}
                  onRemove={() => remove.mutate(item.id)}
                  removePending={remove.isPending}
                  onMoved={invalidate}
                />
              ))}
            </div>
          ) : query.isLoading ? (
            // 报告 A4：与表格视图一致的骨架屏，形态跟随当前视图模式
            viewMode === "cards" ? (
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {Array.from({ length: 6 }, (_, index) => (
                  <Skeleton
                    key={`keywords-skeleton-${index}`}
                    className="h-32 w-full rounded-xl"
                  />
                ))}
              </div>
            ) : (
              <div className="space-y-2">
                {Array.from({ length: 8 }, (_, index) => (
                  <Skeleton
                    key={`keywords-skeleton-${index}`}
                    className="h-16 w-full rounded-xl"
                  />
                ))}
              </div>
            )
          ) : query.isError ? (
            // 同表格视图：错误态不能退化成空态文案
            <QueryErrorState
              title="关键词加载失败"
              description="无法获取关键词列表，请检查网络或后端服务后重试。"
              onRetry={() => query.refetch()}
              retrying={query.isFetching}
            />
          ) : (
            // 报告 A4/O8：非表格视图的空态同样带图标、说明与主行动按钮
            renderEmpty(false)
          )}
          <Pager
            page={page}
            pageSize={pageSize}
            total={query.data?.count ?? 0}
            onPageChange={setPage}
            showJumper
          />
        </CardContent>
      </Card>

      {/* 报告 A3：依赖选中项的批量操作集中到浮起的操作栏，未选中时不渲染 */}
      <BulkActionBar
        count={selected.size}
        onClear={() => setSelected(new Set())}
        actions={
          <>
            <BatchTaskDialog
              keywordIds={Array.from(selected)}
              trackId={trackId}
              trackName={selectedTrack?.name ?? "当前赛道"}
              onCreated={() => {
                setSelected(new Set())
                void invalidate()
              }}
            />
            <Button
              size="sm"
              variant="destructive"
              disabled={bulkRemove.isPending}
              onClick={async () => {
                // 报告 O15：改用统一确认框
                const ok = await confirmDialog({
                  title: `确定永久删除选中的 ${selected.size} 个关键词吗？`,
                  description:
                    "将同时删除这些关键词独占的任务、作品、评论和互动记录，此操作不可撤销。",
                  confirmText: "删除",
                  variant: "destructive",
                })
                if (ok) bulkRemove.mutate(Array.from(selected))
              }}
            >
              <Trash2 />
              批量删除
            </Button>
          </>
        }
      />
    </div>
  )
}

function KeywordPreview({
  item,
  viewMode,
  selected,
  onSelect,
  onToggle,
  onRemove,
  removePending,
  onMoved,
}: {
  item: DouyinKeywordPublic
  viewMode: Exclude<ListViewMode, "table">
  selected: boolean
  onSelect: (checked: boolean) => void
  onToggle: () => void
  onRemove: () => void
  removePending: boolean
  onMoved: () => Promise<void>
}) {
  return (
    <div
      className={`rounded-xl border bg-card p-4 ${
        viewMode === "rows" ? "flex flex-wrap items-center gap-4" : "space-y-4"
      }`}
    >
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <Checkbox
          checked={selected}
          aria-label={`选择关键词 ${item.keyword}`}
          onCheckedChange={(checked) => onSelect(checked === true)}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate font-medium">{item.keyword}</p>
            {item.category && <Badge variant="outline">{item.category}</Badge>}
            {!item.enabled && <Badge variant="secondary">已停用</Badge>}
            <KeywordStatusBadge status={item.status} />
          </div>
          {item.notes && (
            <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
              {formatKeywordNotes(item.notes)}
            </p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <TrackBadge
              trackId={item.track_id}
              trackName={item.track_name}
              isDefault={item.track_is_default}
            />
            <span>{item.task_count} 个任务</span>
            <span>{item.aweme_count} 个作品</span>
            {/* 报告 A16：时间点列改用相对时间 */}
            <span>
              最近爬取 <TimeAgo value={item.last_crawled_at} neverText="从未" />
            </span>
          </div>
        </div>
      </div>
      <div className="ml-auto flex flex-wrap justify-end gap-1">
        <KeywordTasksDialog item={item} />
        <MoveKeywordDialog item={item} onMoved={onMoved} />
        <Button size="sm" variant="outline" onClick={onToggle}>
          {item.enabled ? "停用" : "启用"}
        </Button>
        <DeleteKeywordDialog
          item={item}
          pending={removePending}
          onConfirm={onRemove}
        />
      </div>
    </div>
  )
}

function formatKeywordNotes(notes: string) {
  return notes.startsWith("赛道：")
    ? `历史备注（不代表当前归属）：${notes}`
    : `备注：${notes}`
}

function CreateKeywordsDialog({
  onCreated,
  initialTrackId,
}: {
  onCreated: () => Promise<void>
  initialTrackId: string
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState("")
  const [notes, setNotes] = useState("")
  const [category, setCategory] = useState("uncategorized")
  const [trackId, setTrackId] = useState(initialTrackId)
  useEffect(() => {
    if (open && initialTrackId) setTrackId(initialTrackId)
  }, [initialTrackId, open])
  const trackQuery = useQuery({
    queryKey: ["douyin-track", trackId],
    queryFn: () => DouyinTracksService.getTrack({ trackId }),
    enabled: open && Boolean(trackId),
  })
  const categories = trackQuery.data?.keyword_categories ?? []
  const mutation = useMutation({
    mutationFn: () =>
      DouyinKeywordsService.bulkCreateKeywords({
        requestBody: {
          keywords: parseKeywords(value),
          notes,
          track_id: trackId,
          category: category === "uncategorized" ? "" : category,
        },
      }),
    onSuccess: async (result) => {
      showSuccessToast(
        `新增 ${result.created_count} 个，已存在 ${result.existing_count} 个`,
      )
      setValue("")
      setNotes("")
      setCategory("uncategorized")
      setOpen(false)
      await onCreated()
    },
    onError: handleError.bind(showErrorToast),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!trackId) return showErrorToast("请选择关键词所属赛道")
    if (!parseKeywords(value).length)
      return showErrorToast("请填写至少一个关键词")
    mutation.mutate()
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus />
          添加关键词
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit} className="space-y-5">
          <DialogHeader>
            <DialogTitle>批量添加关键词</DialogTitle>
            <DialogDescription>
              每行或逗号分隔一个关键词；系统会自动清理空格并忽略大小写重复。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label>所属赛道</Label>
            <TrackSelect
              value={trackId}
              onValueChange={(value) => {
                setTrackId(value)
                setCategory("uncategorized")
              }}
              enabled={open}
            />
            <p className="text-xs text-muted-foreground">
              新关键词会直接归入所选赛道，后续任务和内容筛选会沿用该归属。
            </p>
          </div>
          <div className="space-y-2">
            <Label>关键词分类（可选）</Label>
            <Select value={category} onValueChange={setCategory}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="uncategorized">不分类</SelectItem>
                {categories.map((item) => (
                  <SelectItem key={item} value={item}>
                    {item}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              分类由赛道配置统一维护，用于整理数量较多的关键词。
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="keyword-values">关键词</Label>
            <Textarea
              id="keyword-values"
              value={value}
              rows={8}
              placeholder={"FastAPI\nPython 爬虫\n短视频运营"}
              onChange={(event) => setValue(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="keyword-notes">统一备注（可选）</Label>
            <Input
              id="keyword-notes"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
            >
              取消
            </Button>
            <Button type="submit" disabled={mutation.isPending || !trackId}>
              保存关键词
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function BatchTaskDialog({
  keywordIds,
  trackId,
  trackName,
  onCreated,
}: {
  keywordIds: string[]
  trackId: string
  trackName: string
  onCreated: () => void
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [open, setOpen] = useState(false)
  const [maxAwemes, setMaxAwemes] = useState(10)
  const [fetchComments, setFetchComments] = useState(true)
  const [maxComments, setMaxComments] = useState(10)
  const [delayLevel, setDelayLevel] = useState<
    "fast" | "steady" | "ultra_steady"
  >("steady")
  const [taskInterval, setTaskInterval] = useState("")
  const [accountChoice, setAccountChoice] = useState("adhoc")
  const [accountStrategy, setAccountStrategy] = useState<
    "least_loaded" | "round_robin" | "weighted_round_robin"
  >("least_loaded")
  const accounts = useQuery({
    queryKey: ["douyin-accounts"],
    queryFn: () => DouyinAccountsService.listAccounts({ limit: 100 }),
    enabled: open,
  })
  const pools = useQuery({
    queryKey: ["douyin-account-pools"],
    queryFn: () => DouyinAccountsService.listPools(),
    enabled: open,
  })
  const mutation = useMutation({
    mutationFn: () => {
      const requestBody: Parameters<
        typeof DouyinKeywordsService.createKeywordTasks
      >[0]["requestBody"] = {
        keyword_ids: keywordIds,
        track_id: trackId,
        mode: "separate",
        max_awemes: maxAwemes,
        fetch_comments: fetchComments,
        max_comments_per_aweme: maxComments,
        request_delay_level: delayLevel,
        ...(taskInterval.trim()
          ? { task_interval_seconds: Number(taskInterval) }
          : {}),
        download_media: false,
        translate_subtitles: false,
        media_processing_mode: "none",
      }
      if (accountChoice.startsWith("account:"))
        requestBody.account_id = accountChoice.slice(8)
      if (accountChoice.startsWith("pool:")) {
        requestBody.account_pool_id = accountChoice.slice(5)
        requestBody.account_strategy = accountStrategy
      }
      return DouyinKeywordsService.createKeywordTasks({ requestBody })
    },
    onSuccess: (result) => {
      showSuccessToast(`已创建 ${result.count} 个关键词任务`)
      setOpen(false)
      onCreated()
    },
    onError: handleError.bind(showErrorToast),
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="secondary" disabled={!keywordIds.length}>
          <Play />
          批量创建任务
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>从 {keywordIds.length} 个关键词创建任务</DialogTitle>
          <DialogDescription>
            将创建 {keywordIds.length} 个独立任务，每个任务只采集一个关键词。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2 rounded-xl border bg-muted/30 p-3">
          <p className="text-xs font-medium text-muted-foreground">所属赛道</p>
          <p className="text-sm font-medium">{trackName}</p>
          <p className="text-xs text-muted-foreground">
            已选关键词会在该赛道内创建任务，不允许跨赛道混合运行。
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="rounded-xl border bg-muted/20 p-3 sm:col-span-2">
            <p className="text-xs font-medium text-muted-foreground">
              任务组织方式
            </p>
            <p className="mt-1 text-sm font-medium">每个关键词独立任务</p>
            <p className="mt-1 text-xs text-muted-foreground">
              固定一词一任务，便于查看进度、失败原因和断点续爬。
            </p>
          </div>
          <Field label="执行账号">
            <Select value={accountChoice} onValueChange={setAccountChoice}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="adhoc">临时浏览器登录</SelectItem>
                {(accounts.data?.data ?? [])
                  .filter(
                    (item) =>
                      item.enabled && ["ready", "busy"].includes(item.status),
                  )
                  .map((item) => (
                    <SelectItem key={item.id} value={`account:${item.id}`}>
                      账号 · {item.name}
                    </SelectItem>
                  ))}
                {(pools.data?.data ?? [])
                  .filter((item) => item.enabled)
                  .map((item) => (
                    <SelectItem key={item.id} value={`pool:${item.id}`}>
                      账号池 · {item.name}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </Field>
          {accountChoice.startsWith("pool:") && (
            <Field label="账号池调度策略">
              <Select
                value={accountStrategy}
                onValueChange={(value) =>
                  setAccountStrategy(value as typeof accountStrategy)
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="least_loaded">最少负载</SelectItem>
                  <SelectItem value="round_robin">顺序轮询</SelectItem>
                  <SelectItem value="weighted_round_robin">加权轮询</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          )}
          <Field label="每任务最大作品">
            <Input
              type="number"
              min={1}
              max={1000}
              value={maxAwemes}
              onChange={(event) => setMaxAwemes(Number(event.target.value))}
            />
          </Field>
          <Field label="每作品最大评论">
            <Input
              type="number"
              min={1}
              max={1000}
              disabled={!fetchComments}
              value={maxComments}
              onChange={(event) => setMaxComments(Number(event.target.value))}
            />
          </Field>
          <Field label="风控节奏">
            <Select
              value={delayLevel}
              onValueChange={(value) =>
                setDelayLevel(value as typeof delayLevel)
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="fast">快 · 1–2 秒随机</SelectItem>
                <SelectItem value="steady">稳 · 3–6 秒随机</SelectItem>
                <SelectItem value="ultra_steady">
                  超级稳 · 6–12 秒随机
                </SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label="任务完成后间隔（秒）">
            <Input
              type="number"
              min={0}
              max={3600}
              step={1}
              value={taskInterval}
              onChange={(event) => setTaskInterval(event.target.value)}
              placeholder="跟随请求风控节奏"
            />
          </Field>
        </div>
        <div className="space-y-3 rounded-xl border p-4">
          <Check
            checked={fetchComments}
            label="抓取评论"
            onChange={setFetchComments}
          />
          <p className="rounded-lg border border-blue-200/70 bg-blue-50/60 p-3 text-xs leading-5 text-blue-950 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-100">
            本次只创建关键词采集任务。作品产出后，请到任务中心的“下载与字幕”页签创建关联处理任务。
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button
            disabled={mutation.isPending || !keywordIds.length || !trackId}
            onClick={() => mutation.mutate()}
          >
            确认创建并运行
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function KeywordTasksDialog({ item }: { item: DouyinKeywordPublic }) {
  const [open, setOpen] = useState(false)
  const query = useQuery({
    queryKey: ["douyin-keyword-tasks", item.id],
    queryFn: () =>
      DouyinKeywordsService.listKeywordTasks({ keywordId: item.id }),
    enabled: open,
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          任务 {item.task_count}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{item.keyword} · 关联任务</DialogTitle>
          <DialogDescription>
            任务绑定会永久保留，删除关键词也不会删除任务或作品。
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[55vh] space-y-2 overflow-y-auto">
          {query.data?.map((task) => (
            <div
              key={task.id}
              className="flex items-center gap-3 rounded-xl border p-3"
            >
              <TaskStatusBadge status={task.status} />
              {/* 报告 A16：任务创建时间同样用相对时间展示 */}
              <TimeAgo
                value={task.created_at}
                className="text-sm text-muted-foreground"
              />
              <span className="ml-auto text-sm">{task.aweme_count} 作品</span>
              <Button size="sm" variant="ghost" asChild>
                <Link to="/douyin/$taskId" params={{ taskId: task.id }}>
                  查看
                </Link>
              </Button>
            </div>
          ))}
          {/* 报告 A4/O8：加载态补骨架屏，空态从「暂无关联任务」换成带图标的说明 */}
          {query.isLoading &&
            Array.from({ length: 3 }, (_, index) => (
              <Skeleton
                key={`keyword-task-skeleton-${index}`}
                className="h-14 w-full rounded-xl"
              />
            ))}
          {!query.isLoading && !query.data?.length && (
            <EmptyState
              compact
              icon={Tags}
              title="暂无关联任务"
              description="这个关键词还没有创建过采集任务；在列表里勾选后即可批量创建。"
              className="rounded-xl border border-dashed"
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function MoveKeywordDialog({
  item,
  onMoved,
}: {
  item: DouyinKeywordPublic
  onMoved: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [trackId, setTrackId] = useState(item.track_id)
  const { showErrorToast, showSuccessToast } = useCustomToast()
  useEffect(() => {
    if (open) setTrackId(item.track_id)
  }, [item.track_id, open])
  const mutation = useMutation({
    mutationFn: () =>
      DouyinKeywordsService.editKeyword({
        keywordId: item.id,
        requestBody: { track_id: trackId },
      }),
    onSuccess: async () => {
      setOpen(false)
      showSuccessToast("关键词赛道归属已更新")
      await onMoved()
    },
    onError: handleError.bind(showErrorToast),
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          移动
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>移动关键词“{item.keyword}”</DialogTitle>
          <DialogDescription>
            关键词及其采集内容会按最新归属参与目标赛道筛选；历史任务仍保留原始赛道用于审计。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label>目标赛道</Label>
          <TrackSelect
            value={trackId}
            onValueChange={setTrackId}
            enabled={open}
            autoSelectDefault={false}
            ariaLabel={`选择“${item.keyword}”的目标赛道`}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button
            disabled={
              !trackId || trackId === item.track_id || mutation.isPending
            }
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "正在移动…" : "确认移动"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function DeleteKeywordDialog({
  item,
  pending,
  onConfirm,
}: {
  item: DouyinKeywordPublic
  pending: boolean
  onConfirm: () => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="icon-sm" variant="ghost" aria-label="删除关键词">
          <Trash2 />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>删除关键词“{item.keyword}”？</DialogTitle>
          <DialogDescription>
            将同时删除该关键词独占的任务、作品、评论和互动记录，此操作不可撤销。
            如果历史任务还关联其他关键词，则会保留该共享任务及其数据。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button
            variant="destructive"
            disabled={pending}
            onClick={() => {
              onConfirm()
              setOpen(false)
            }}
          >
            确认删除
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function KeywordStatusBadge({ status }: { status: DouyinKeywordStatus }) {
  return (
    <Badge
      variant={
        status === "failed"
          ? "destructive"
          : status === "crawled"
            ? "default"
            : "outline"
      }
    >
      {status === "active" && <LoaderCircle className="animate-spin" />}
      {statusLabels[status]}
    </Badge>
  )
}
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      {children}
    </div>
  )
}
function Check({
  checked,
  disabled,
  label,
  onChange,
}: {
  checked: boolean
  disabled?: boolean
  label: string
  onChange: (checked: boolean) => void
}) {
  return (
    <div className="flex items-center gap-2">
      <Checkbox
        checked={checked}
        disabled={disabled}
        aria-label={label}
        onCheckedChange={(value) => onChange(value === true)}
      />
      <Label className="font-normal">{label}</Label>
    </div>
  )
}
function parseKeywords(value: string) {
  return value
    .split(/[\n,，]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}
