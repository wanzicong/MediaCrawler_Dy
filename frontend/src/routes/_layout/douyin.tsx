import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router"
import {
  ArrowRight,
  ChevronDown,
  Copy,
  Download,
  FileDown,
  Inbox,
  ListFilter,
  MoreHorizontal,
  Play,
  RotateCcw,
  Search,
  SearchX,
  Tags,
  Trash2,
} from "lucide-react"
import {
  Fragment,
  type ReactNode,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react"

import {
  type CrawlTaskPublic,
  type CrawlTaskStatus,
  DouyinKeywordsService,
  DouyinService,
} from "@/client"
import { BulkActionBar } from "@/components/Common/BulkActionBar"
import { CopyableId } from "@/components/Common/CopyableId"
// 报告 O15：统一确认框，替代 window.confirm
import { confirmDialog } from "@/components/Common/confirm-dialog"
// 报告 A4/O8：统一空态组件（图标 + 标题 + 说明 + 主行动按钮）
import { EmptyState } from "@/components/Common/EmptyState"
import { FilterChips } from "@/components/Common/FilterChips"
import { FilterPresetBar } from "@/components/Common/FilterPresetBar"
import { Pager } from "@/components/Common/Pager"
import { FilterPanel, PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { RefreshIndicator } from "@/components/Common/RefreshIndicator"
import {
  RowContextMenu,
  type RowMenuItem,
} from "@/components/Common/RowContextMenu"
import { TableColumnMenu } from "@/components/Common/TableColumnMenu"
import { TimeAgo } from "@/components/Common/TimeAgo"
import {
  type ListViewMode,
  usePersistentViewMode,
  ViewModeToggle,
} from "@/components/Common/ViewModeToggle"
import { CreateTaskDialog } from "@/components/Douyin/CreateTaskDialog"
import { MediaTaskManagement } from "@/components/Douyin/MediaTaskManagement"
import {
  allSourcesValue,
  parseSourceSelection,
  SourceBadge,
  SourceSelect,
  sourceSelectionValue,
  useSourceCatalog,
} from "@/components/Douyin/SourceSelect"
import { TaskListProgress } from "@/components/Douyin/TaskExecutionProgress"
import {
  TaskGroupToggle,
  usePersistentGroupMode,
} from "@/components/Douyin/TaskGrouping"
import {
  getTaskSearchValues,
  TaskIdentity,
} from "@/components/Douyin/TaskIdentity"
import {
  activeTaskStatuses,
  TaskStatusBadge,
} from "@/components/Douyin/TaskStatusBadge"
import {
  allTracksValue,
  TrackBadge,
  TrackSelect,
  useTrackCatalog,
} from "@/components/Douyin/TrackSelect"
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
// 报告 A4/O8：首屏加载用骨架屏保留列表结构，避免数据到达后内容跳动
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import useCustomToast from "@/hooks/useCustomToast"
// 报告 A6：轮询刷新后数据变化的行高亮
import { useHighlightedRows } from "@/hooks/useHighlightedRows"
// 报告 A13：表视图键盘导航
import { useRowKeyboardNav } from "@/hooks/useRowKeyboardNav"
// 报告 A1：手写表格的列可见性
import { type TableColumnDef, useTableColumns } from "@/hooks/useTableColumns"
import { type CsvColumn, downloadCsv } from "@/lib/csv"
// 报告 O4：筛选状态 ↔ URL 查询参数
import {
  compactSearch,
  readEnumParam,
  readStringParam,
} from "@/lib/search-params"
import { formatDateTime } from "@/lib/time"
import { cn } from "@/lib/utils"
import { handleError } from "@/utils"

/**
 * 报告 O4：状态筛选白名单，取值与下方 filterLabels 的 key（FilterKey）一一对应。
 * 交给 readEnumParam 校验 URL 里的 status，手改地址栏传入的脏值会被丢弃。
 */
const TASK_FILTER_VALUES: readonly FilterKey[] = [
  "all",
  "active",
  "attention",
  "succeeded",
]

/**
 * 报告 O4：筛选查询参数的类型。
 * 字段一律声明成**可选属性**（`x?: T` 而不是 `x: T | undefined`）：
 * TanStack Router 只看属性是否必填来决定 `Link` / `navigate` 是否强制传 `search`，
 * 写成必填会让所有指向本路由的 `<Link to="/douyin">` 报「缺少 search」。
 * status 的取值覆盖筛选白名单全部 FilterKey（含默认值 "all"），与页面 state 一致。
 */
type DouyinTaskSearch = {
  status?: FilterKey
  track?: string
  source?: string
  q?: string
}

export const Route = createFileRoute("/_layout/douyin")({
  // 报告 O4：筛选上 URL —— 状态 / 赛道 / 来源 / 关键词四项写进查询参数，
  // 刷新、分享链接、收藏夹、深链都能还原出同一份筛选。
  validateSearch: (search: Record<string, unknown>): DouyinTaskSearch => ({
    status: readEnumParam(search, "status", TASK_FILTER_VALUES),
    track: readStringParam(search, "track"),
    source: readStringParam(search, "source"),
    q: readStringParam(search, "q"),
  }),
  component: DouyinTasks,
  head: () => ({ meta: [{ title: "抖音任务 - 灵感采集台" }] }),
})

const crawlTypeLabels: Record<CrawlTaskPublic["crawl_type"], string> = {
  search: "关键词搜索",
  detail: "指定作品",
  creator: "创作者作品",
  creator_from_aweme: "视频作者作品",
  liked: "账号点赞",
  collected: "账号收藏",
}

type FilterKey = "all" | "active" | "attention" | "succeeded"

const filterLabels: { key: FilterKey; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "active", label: "进行中" },
  { key: "attention", label: "需处理" },
  { key: "succeeded", label: "已完成" },
]

/**
 * 「需关注」状态集合（本页口径）：已进入终态但未成功、需要人工介入的任务。
 * 注意与工作台（dashboard）的口径差异：工作台只统计 failed/interrupted/waiting_login，
 * 本页额外计入 cancelled——本页的已取消任务同样可删除/可重启，属于需处理范围。
 * 此前该集合在计数与筛选两处各写一份字面量，容易改漏，故抽成常量统一口径。
 */
const attentionTaskStatuses: CrawlTaskStatus[] = [
  "failed",
  "cancelled",
  "interrupted",
  "waiting_login",
]

/**
 * 状态中文名（报告 A12：导出 CSV 时用中文而不是英文 key）。
 * TaskStatusBadge 内部已有同一份映射但没有导出，这里只能维护副本；
 * 新增状态时需要两处同步。
 */
const taskStatusLabels: Record<CrawlTaskStatus, string> = {
  queued: "排队中",
  waiting_login: "等待扫码",
  running: "运行中",
  processing_media: "处理视频/字幕",
  cancelling: "取消中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  interrupted: "已中断",
}

/** 报告 A12：任务导出列定义，只用于当前页 / 已选中的小数据量导出。 */
/* ── 任务列表聚合（任务 + 内容） ─────────────────────────────────────────
 *
 * 背景：同一条赛道、同一个采集类型、同一批目标内容（关键词 / 作品 / 达人）
 * 反复跑，列表里就是一行一行重复的任务，用户没法一眼看出「这件事跑了几次、
 * 一共采到多少」。这里把这类任务合并成一组展示，并给列表补上分页。
 */

/**
 * 「任务 + 内容」聚合键：任务维度 = 赛道 + 采集类型；内容维度 = 目标内容
 * （关键词 / 作品号 / 达人 id，排序后拼接，所以「小红书,露营」与「露营,小红书」
 * 归为同一组）。
 *
 * 想把口径换成「按作品聚合」之类，只需要改这一个函数。
 */
function taskGroupKey(task: CrawlTaskPublic): string {
  const request = task.request as {
    keywords?: string[]
    video_ids?: string[]
    creator_ids?: string[]
  }
  const targets = [
    ...(request.keywords ?? []).map((value) => `k:${value}`),
    ...(request.video_ids ?? []).map((value) => `v:${value}`),
    ...(request.creator_ids ?? []).map((value) => `c:${value}`),
  ].sort()
  return [task.track_id, task.crawl_type, targets.join("|")].join("::")
}

type TaskGroup = {
  key: string
  trackId: string
  trackName: string
  trackIsDefault: boolean
  crawlType: CrawlTaskPublic["crawl_type"]
  sourceLabel: string
  /** 组内最近一次运行（列表按创建时间倒序，第一条即最近） */
  latest: CrawlTaskPublic
  /** 组内全部运行，最近一次在前 */
  runs: CrawlTaskPublic[]
  awemeCount: number
  commentCount: number
  actionCount: number
  lastRunAt: string
}

function buildTaskGroups(tasks: CrawlTaskPublic[]): TaskGroup[] {
  const groups = new Map<string, TaskGroup>()
  for (const task of tasks) {
    const key = taskGroupKey(task)
    const existing = groups.get(key)
    if (!existing) {
      groups.set(key, {
        key,
        trackId: task.track_id,
        trackName: task.track_name,
        trackIsDefault: task.track_is_default,
        crawlType: task.crawl_type,
        sourceLabel: task.source_label || "指定作品",
        latest: task,
        runs: [task],
        awemeCount: task.aweme_count,
        commentCount: task.comment_count,
        actionCount: task.action_count,
        lastRunAt: task.created_at,
      })
      continue
    }
    existing.runs.push(task)
    existing.awemeCount += task.aweme_count
    existing.commentCount += task.comment_count
    existing.actionCount += task.action_count
  }
  return [...groups.values()].sort((a, b) =>
    b.lastRunAt.localeCompare(a.lastRunAt),
  )
}

const taskCsvColumns: CsvColumn<CrawlTaskPublic>[] = [
  { header: "任务 ID", value: (task) => task.id },
  { header: "状态", value: (task) => taskStatusLabels[task.status] },
  { header: "赛道", value: (task) => task.track_name },
  { header: "来源", value: (task) => task.source_label ?? "" },
  { header: "作品数", value: (task) => task.aweme_count },
  { header: "评论数", value: (task) => task.comment_count },
  { header: "创建时间", value: (task) => formatDateTime(task.created_at) },
]

/**
 * 报告 A1：列可见性 —— 任务表格的列清单（只作用于 table 视图）。
 * 必须是模块级稳定常量：放进组件里每次渲染都会新建，会让用户勾选的偏好被重置。
 * key 与下方 isVisible(...) 的调用一一对应，改名要两处同步。
 */
const TASK_TABLE_COLUMNS = [
  // 该列的表头与每个单元格里都带行选择 / 全选复选框，藏掉就没法勾选任务，故永远可见
  { key: "track", title: "所属赛道", alwaysVisible: true },
  { key: "target", title: "任务目标" },
  // 长 ID 属于次要信息，默认收起；表格行的右键菜单仍提供「复制任务 ID」
  { key: "id", title: "任务 ID", defaultHidden: true },
  { key: "status", title: "状态" },
  { key: "account", title: "账号" },
  { key: "progress", title: "数据进度" },
  { key: "created", title: "创建时间" },
  // 操作列冻结在右侧，藏掉用户就没法续爬 / 重启 / 进详情，永远可见
  { key: "actions", title: "操作", alwaysVisible: true },
] as const satisfies readonly TableColumnDef[]

function DouyinTasks() {
  // 报告 O4：初值取自 URL，于是刷新 / 深链 / 分享链接都能还原出同一份筛选
  const routeSearch = Route.useSearch()
  const routeNavigate = Route.useNavigate()
  const [businessTab, setBusinessTab] = useState<"crawl" | "media">("crawl")
  const [statusFilter, setStatusFilter] = useState<FilterKey>(
    routeSearch.status ?? "all",
  )
  const [searchTerm, setSearchTerm] = useState(routeSearch.q ?? "")
  const [trackId, setTrackId] = useState(routeSearch.track ?? allTracksValue)
  const [sourceValue, setSourceValue] = useState(
    routeSearch.source ?? allSourcesValue,
  )
  const [viewMode, changeViewMode] = usePersistentViewMode("douyin-tasks-view")
  // 任务列表默认聚合展示（同一条赛道的同类目标只占一行），可切回逐条
  const [groupMode, changeGroupMode] = usePersistentGroupMode(
    "douyin-tasks-group-mode",
  )
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(10)
  // 报告 A1：列可见性 —— 用户可自行勾选表格里显示哪几列，偏好按 storageKey 存本地
  const { isVisible, menuProps } = useTableColumns({
    storageKey: "douyin-tasks-columns",
    columns: TASK_TABLE_COLUMNS,
  })
  const [selectedTaskIds, setSelectedTaskIds] = useState<Set<string>>(
    () => new Set(),
  )
  // 报告 O4：筛选变化时写回 URL。
  // 用 replace: true 是有意的取舍 —— 不用 replace 的话每改一次筛选就多一条浏览器历史，
  // 用户要按十次「后退」才能离开本页；用 replace 后，刷新 / 分享 / 深链 / 收藏都能还原筛选，
  // 而「后退」回到的是上一个页面（而不是上一条筛选）。
  // 依赖只放筛选 state 与 navigate，不放 routeSearch，避免写回 → search 变化 → 再写回的循环。
  useEffect(() => {
    void routeNavigate({
      to: "/douyin",
      replace: true,
      search: compactSearch(
        {
          status: statusFilter,
          track: trackId === allTracksValue ? undefined : trackId,
          source: sourceValue === allSourcesValue ? undefined : sourceValue,
          q: searchTerm.trim() || undefined,
        },
        // 等于默认值的键不写进 URL，未筛选时地址栏就是干净的 /douyin
        { status: "all" },
      ),
    })
  }, [statusFilter, trackId, sourceValue, searchTerm, routeNavigate])
  const { data, isLoading, isFetching, isError, refetch, dataUpdatedAt } =
    useQuery({
      queryKey: ["douyin-tasks", trackId, sourceValue],
      queryFn: () =>
        DouyinService.listTasks({
          trackId: trackId && trackId !== allTracksValue ? trackId : undefined,
          ...parseSourceSelection(sourceValue),
          skip: 0,
          // 已知截断：服务端固定只取前 100 条，超过 100 条的任务不会出现在列表里。
          // 本页暂不做服务端分页，去掉该限制即可恢复完整数据（后端已支持 skip/limit）。
          limit: 100,
        }),
      retry: false,
      // 只有还有任务在排队 / 执行时才轮询；全部终态后停止空转
      refetchInterval: (query) =>
        query.state.data?.data.some((task) =>
          activeTaskStatuses.includes(task.status),
        )
          ? 3_000
          : false,
    })
  // tasks 每次 render 都会因 `?? []` 生成新数组，会击穿下方所有派生 memo，因此一并 memo
  const tasks = useMemo(() => data?.data ?? [], [data])
  const attentionCount = useMemo(
    () =>
      tasks.filter((task) => attentionTaskStatuses.includes(task.status))
        .length,
    [tasks],
  )
  // 输入框即时更新，重过滤延后到浏览器空闲，避免每次按键都重算整张列表
  const deferredSearchTerm = useDeferredValue(searchTerm)
  // biome-ignore lint/correctness/useExhaustiveDependencies: trackId/sourceValue 是服务端筛选入参，经 data→tasks 间接影响结果，需显式声明
  const filteredTasks = useMemo(() => {
    const keyword = deferredSearchTerm.trim().toLocaleLowerCase()
    return tasks.filter((task) => {
      const matchesStatus =
        statusFilter === "all" ||
        (statusFilter === "active" &&
          activeTaskStatuses.includes(task.status)) ||
        (statusFilter === "attention" &&
          attentionTaskStatuses.includes(task.status)) ||
        (statusFilter === "succeeded" && task.status === "succeeded")
      if (!matchesStatus) return false
      if (!keyword) return true
      return [
        ...getTaskSearchValues(task),
        crawlTypeLabels[task.crawl_type],
        taskBrowserMode(task),
      ].some((value) => value.toLocaleLowerCase().includes(keyword))
    })
    // trackId / sourceValue 是服务端筛选入参，变化会导致 data（进而 tasks）更新，
    // 显式列入依赖，避免依赖数组不完整导致筛选结果滞后一帧
  }, [deferredSearchTerm, statusFilter, tasks, trackId, sourceValue])
  const selectableTasks = useMemo(
    () => filteredTasks.filter(isDeletableTask),
    [filteredTasks],
  )
  // 聚合视图：同一赛道 + 同一采集类型 + 同一目标内容的多次运行合并成一行
  const taskGroups = useMemo(
    () => buildTaskGroups(filteredTasks),
    [filteredTasks],
  )
  const grouping = groupMode === "group"
  const pageTotal = grouping ? taskGroups.length : filteredTasks.length
  const pageCount = Math.max(1, Math.ceil(pageTotal / pageSize))
  // 数据变少（删除 / 筛选）时把越界的页码夹回最后一页，避免停在空白页
  const currentPage = Math.min(page, pageCount - 1)
  const pagedGroups = useMemo(
    () =>
      taskGroups.slice(currentPage * pageSize, (currentPage + 1) * pageSize),
    [taskGroups, currentPage, pageSize],
  )
  const pagedTasks = useMemo(
    () =>
      filteredTasks.slice(currentPage * pageSize, (currentPage + 1) * pageSize),
    [filteredTasks, currentPage, pageSize],
  )
  // 筛选 / 切换聚合方式后回到第一页
  // biome-ignore lint/correctness/useExhaustiveDependencies: 只关心筛选与展示方式变化，页码本身不进依赖
  useEffect(() => {
    setPage(0)
  }, [deferredSearchTerm, statusFilter, trackId, sourceValue, groupMode])
  const allSelectableTasksSelected =
    selectableTasks.length > 0 &&
    selectableTasks.every((task) => selectedTaskIds.has(task.id))

  // 报告 A6：轮询刷新后数据变化的行闪一下，让「后台悄悄变了什么」可见。
  // 本页任务模型没有 updated_at，改用 status + 断点阶段 + 三个计数字段作指纹，
  // 覆盖「状态流转」与「采集数量增长」这两类用户能感知的变化。
  const highlightedTaskIds = useHighlightedRows(
    filteredTasks,
    (task) => task.id,
    (task) =>
      `${task.status}:${task.checkpoint_phase}:${task.aweme_count}:${task.comment_count}:${task.action_count}`,
  )
  // 报告 A13：表视图键盘导航（↑↓ 移动、回车打开详情）
  const navigate = useNavigate()
  const taskRowIds = useMemo(
    () => pagedTasks.map((task) => task.id),
    [pagedTasks],
  )
  const keyboardNav = useRowKeyboardNav({
    rowIds: taskRowIds,
    onActivate: (taskId) =>
      void navigate({ to: "/douyin/$taskId", params: { taskId } }),
  })
  // 报告 A11：表尾合计的口径与表格实际渲染的行一致 —— 分页之后就是「本页」，
  // 全部筛选结果的合计由分页器的「共 N 条」承担。
  const taskTotals = useMemo(() => {
    let activeCount = 0
    let awemeTotal = 0
    let commentTotal = 0
    for (const task of pagedTasks) {
      if (activeTaskStatuses.includes(task.status)) activeCount += 1
      awemeTotal += task.aweme_count
      commentTotal += task.comment_count
    }
    return { activeCount, awemeTotal, commentTotal }
  }, [pagedTasks])
  // 报告 A12：有选中就导出选中，否则导出当前这一页
  // （聚合视图下「本页」= 当前页各组包含的全部任务）
  const currentPageTasks = useMemo(
    () => (grouping ? pagedGroups.flatMap((group) => group.runs) : pagedTasks),
    [grouping, pagedGroups, pagedTasks],
  )
  const exportTasks = useMemo(
    () =>
      selectedTaskIds.size > 0
        ? filteredTasks.filter((task) => selectedTaskIds.has(task.id))
        : currentPageTasks,
    [currentPageTasks, filteredTasks, selectedTaskIds],
  )

  // 报告 A2/A10：chip 与预设条要展示中文的赛道名 / 来源名，而不是裸 id。
  // 这两个目录 hook 与 TrackSelect / SourceSelect 共用同一 queryKey，命中同一份缓存，不会多发请求。
  const trackCatalog = useTrackCatalog()
  const trackName = useMemo(() => {
    if (trackId === allTracksValue) return ""
    const matched = (trackCatalog.data?.data ?? []).find(
      (track) => track.id === trackId,
    )
    return matched?.name ?? trackId
  }, [trackCatalog.data, trackId])
  const sourceCatalog = useSourceCatalog(trackId)
  const sourceName = useMemo(() => {
    if (sourceValue === allSourcesValue) return ""
    const matched = (sourceCatalog.data?.data ?? []).find(
      (option) =>
        sourceSelectionValue(option.source_type, option.id) === sourceValue,
    )
    return matched?.name ?? sourceValue
  }, [sourceCatalog.data, sourceValue])
  // 状态 chip 复用页面已有的中文映射，避免把英文 key 暴露给用户
  const statusFilterLabel =
    filterLabels.find((item) => item.key === statusFilter)?.label ?? ""

  /** 切换赛道时同步清空来源筛选与已选任务（与 TrackSelect 原有行为一致）。 */
  function applyTrackFilter(value: string) {
    setTrackId(value)
    setSourceValue(allSourcesValue)
    setSelectedTaskIds(new Set())
  }

  /** 一次性清空全部筛选条件（报告 A2 的「清除全部」）。 */
  function clearAllFilters() {
    setStatusFilter("all")
    applyTrackFilter(allTracksValue)
    setSearchTerm("")
  }

  function toggleTaskSelection(taskId: string, checked: boolean) {
    setSelectedTaskIds((current) => {
      const next = new Set(current)
      if (checked) next.add(taskId)
      else next.delete(taskId)
      return next
    })
  }

  function toggleAllSelectableTasks(checked: boolean) {
    setSelectedTaskIds((current) => {
      const next = new Set(current)
      for (const task of selectableTasks) {
        if (checked) next.add(task.id)
        else next.delete(task.id)
      }
      return next
    })
  }

  /**
   * 报告 A1：表尾合计行的跨列数 = 这组列里当前可见的列数。
   * track 列永远可见，因此第一段至少占 1 列，不会出现非法的 colSpan=0。
   */
  function visibleColSpan(keys: string[]) {
    return keys.filter((key) => isVisible(key)).length
  }

  return (
    <div className="page-stack">
      <Tabs
        defaultValue="crawl"
        onValueChange={(value) => setBusinessTab(value as "crawl" | "media")}
        className="space-y-3"
      >
        <PageHero
          title="抖音任务管理"
          compact
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <TabsList className="h-9 rounded-lg border bg-card p-0.5">
                <TabsTrigger value="crawl" className="h-8 gap-1.5 px-2.5">
                  <Search />
                  采集任务
                  {/* 计数与当前列表实际渲染的行数保持一致：原先取 data.count（全量）
                      再回退 tasks.length，与筛选后的行数对不上，容易误解为漏渲染 */}
                  <span className="text-xs tabular-nums">
                    {filteredTasks.length}
                  </span>
                </TabsTrigger>
                <TabsTrigger value="media" className="h-8 gap-1.5 px-2.5">
                  <Download />
                  下载与字幕
                </TabsTrigger>
              </TabsList>
              {businessTab === "crawl" && (
                <CreateTaskDialog
                  initialTrackId={
                    trackId && trackId !== allTracksValue ? trackId : undefined
                  }
                  triggerLabel="创建采集任务"
                />
              )}
            </div>
          }
        />

        <TabsContent value="crawl" className="mt-0 space-y-3">
          <section className="space-y-3" aria-labelledby="task-list-heading">
            <h2 id="task-list-heading" className="sr-only">
              任务记录
            </h2>
            <FilterPanel className="p-2">
              <div className="flex flex-col gap-2 xl:flex-row xl:items-center">
                <fieldset className="flex items-center gap-2 overflow-x-auto pb-1 lg:pb-0">
                  <legend className="sr-only">任务状态筛选</legend>
                  <ListFilter
                    className="mr-1 size-4 shrink-0 text-muted-foreground"
                    aria-hidden="true"
                  />
                  {filterLabels.map((item) => (
                    <Button
                      key={item.key}
                      type="button"
                      size="sm"
                      variant={statusFilter === item.key ? "default" : "ghost"}
                      aria-pressed={statusFilter === item.key}
                      className="h-9 shrink-0 px-3"
                      onClick={() => setStatusFilter(item.key)}
                    >
                      {item.label}
                      {item.key === "attention" && attentionCount > 0 && (
                        <span className="rounded-full bg-amber-100 px-1.5 text-[10px] font-bold text-amber-700">
                          {attentionCount}
                        </span>
                      )}
                    </Button>
                  ))}
                </fieldset>
                <div className="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row xl:justify-end">
                  <TrackSelect
                    value={trackId}
                    onValueChange={applyTrackFilter}
                    includeAll
                    allowDisabled
                    className="h-9 bg-background sm:w-48"
                    ariaLabel="按赛道筛选任务"
                  />
                  <SourceSelect
                    trackId={trackId}
                    value={sourceValue}
                    onValueChange={(value) => {
                      setSourceValue(value)
                      setSelectedTaskIds(new Set())
                    }}
                    className="h-9 bg-background sm:w-56"
                    ariaLabel="按关键词或作者筛选任务"
                  />
                  <label
                    htmlFor="task-search"
                    className="relative block min-w-48 flex-1 xl:max-w-sm"
                  >
                    <Search
                      className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
                      aria-hidden="true"
                    />
                    <Input
                      id="task-search"
                      value={searchTerm}
                      onChange={(event) => setSearchTerm(event.target.value)}
                      placeholder="搜索任务目标、类型或浏览器…"
                      aria-label="搜索任务目标、类型或浏览器"
                      className="h-9 rounded-xl bg-background pl-9"
                    />
                  </label>
                  <div className="flex shrink-0 items-center gap-2">
                    <BulkResumeButton
                      tasks={filteredTasks}
                      selectedTaskIds={selectedTaskIds}
                    />
                    {/* 报告 A14：刷新按钮替换为「上次更新时间 + 刷新」指示器 */}
                    <RefreshIndicator
                      updatedAt={dataUpdatedAt}
                      refreshing={isFetching}
                      onRefresh={() => void refetch()}
                    />
                    {/* 报告 A12：导出当前页 / 已选中任务为 CSV（导出全部需后端流式接口，本页不做） */}
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-9 gap-1.5"
                      disabled={exportTasks.length === 0}
                      aria-label={
                        selectedTaskIds.size > 0
                          ? `导出选中的 ${exportTasks.length} 个任务为 CSV`
                          : `导出本页 ${exportTasks.length} 个任务为 CSV`
                      }
                      onClick={() =>
                        downloadCsv("抖音任务", exportTasks, taskCsvColumns)
                      }
                    >
                      <FileDown />
                      <span className="hidden sm:inline">导出</span>
                    </Button>
                    <TaskGroupToggle
                      value={groupMode}
                      onChange={changeGroupMode}
                    />
                    {/* 聚合视图是固定表头的汇总表，逐条视图各自保留原先的三种展示方式 */}
                    {!grouping && (
                      <ViewModeToggle
                        value={viewMode}
                        onChange={changeViewMode}
                        label="切换任务展示方式"
                      />
                    )}
                    {/* 报告 A1：列显示勾选，只对逐条的 table 视图生效 */}
                    {!grouping && viewMode === "table" && (
                      <TableColumnMenu {...menuProps} />
                    )}
                  </div>
                </div>
              </div>
              {/* 报告 A2：已应用筛选的可视化 chips */}
              <FilterChips
                className="mt-2"
                chips={[
                  statusFilter !== "all" && {
                    key: "status",
                    label: "状态",
                    value: statusFilterLabel,
                    onRemove: () => setStatusFilter("all"),
                  },
                  trackId !== allTracksValue && {
                    key: "track",
                    label: "赛道",
                    value: trackName,
                    onRemove: () => applyTrackFilter(allTracksValue),
                  },
                  sourceValue !== allSourcesValue && {
                    key: "source",
                    label: "来源",
                    value: sourceName,
                    onRemove: () => {
                      setSourceValue(allSourcesValue)
                      setSelectedTaskIds(new Set())
                    },
                  },
                  searchTerm.trim() !== "" && {
                    key: "search",
                    label: "搜索",
                    value: searchTerm,
                    onRemove: () => setSearchTerm(""),
                  },
                ]}
                onClearAll={clearAllFilters}
              />
              {/* 报告 A10：筛选预设，把高频筛选组合存到本地一键复用 */}
              <FilterPresetBar
                className="mt-2"
                storageKey="douyin-tasks-filter-presets"
                currentFilters={{
                  status: statusFilter,
                  trackId,
                  sourceValue,
                  search: searchTerm,
                }}
                onApply={(filters) => {
                  const next = filters as {
                    status: FilterKey
                    trackId: string
                    sourceValue: string
                    search: string
                  }
                  setStatusFilter(next.status)
                  setTrackId(next.trackId)
                  setSourceValue(next.sourceValue)
                  setSearchTerm(next.search)
                  // 套用预设可能切换赛道/来源，清空选中项避免残留上一批选中
                  setSelectedTaskIds(new Set())
                }}
              />
            </FilterPanel>

            {isLoading ? (
              // 报告 A4/O8：骨架屏替代「正在加载…」纯文字，保留列表结构避免内容跳动
              <TaskListSkeleton viewMode={viewMode} isVisible={isVisible} />
            ) : isError ? (
              <QueryErrorState
                title="任务列表读取失败"
                description="暂时无法获取任务数据，请检查服务连接后重试。"
                onRetry={() => void refetch()}
                retrying={isFetching}
              />
            ) : tasks.length === 0 ? (
              // 报告 A4/O8：真的没有任务 —— 给出「创建第一个任务」主行动
              <EmptyState
                icon={Inbox}
                title="还没有抖音任务"
                description="创建第一个采集任务，选好赛道、来源与账号后即可开始抓取作品、评论与互动数据。"
                action={
                  <CreateTaskDialog
                    initialTrackId={
                      trackId && trackId !== allTracksValue
                        ? trackId
                        : undefined
                    }
                    triggerLabel="创建第一个任务"
                  />
                }
              />
            ) : grouping ? (
              taskGroups.length ? (
                <div className="space-y-3">
                  <TaskGroupTable groups={pagedGroups} />
                  <Pager
                    page={currentPage}
                    pageSize={pageSize}
                    total={taskGroups.length}
                    onPageChange={setPage}
                    pageSizeOptions={[10, 20, 50]}
                    onPageSizeChange={(size) => {
                      setPageSize(size)
                      setPage(0)
                    }}
                    totalLabel={(total) =>
                      `共 ${total} 组（${filteredTasks.length} 个任务）`
                    }
                  />
                </div>
              ) : (
                <EmptyState
                  icon={SearchX}
                  title="没有符合筛选条件的任务"
                  description="当前搜索词或状态 / 赛道 / 来源筛选下没有匹配的任务，试试放宽条件。"
                  action={
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={clearAllFilters}
                    >
                      清除筛选条件
                    </Button>
                  }
                />
              )
            ) : filteredTasks.length === 0 ? (
              // 报告 A4/O8：空是因为筛选条件 —— 主行动改成「清除筛选条件」
              <EmptyState
                icon={SearchX}
                title="没有符合筛选条件的任务"
                description="当前搜索词或状态 / 赛道 / 来源筛选下没有匹配的任务，试试放宽条件。"
                action={
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={clearAllFilters}
                  >
                    清除筛选条件
                  </Button>
                }
              />
            ) : viewMode === "cards" ? (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {pagedTasks.map((task) => (
                  <TaskMobileCard
                    key={task.id}
                    task={task}
                    selected={selectedTaskIds.has(task.id)}
                    onSelectedChange={(checked) =>
                      toggleTaskSelection(task.id, checked)
                    }
                    // 报告 A6：卡片视图同样标记数据变化的行
                    highlighted={highlightedTaskIds.has(task.id)}
                  />
                ))}
              </div>
            ) : viewMode === "rows" ? (
              <div className="space-y-2">
                {pagedTasks.map((task) => (
                  <TaskCompactRow
                    key={task.id}
                    task={task}
                    selected={selectedTaskIds.has(task.id)}
                    onSelectedChange={(checked) =>
                      toggleTaskSelection(task.id, checked)
                    }
                    // 报告 A6：横条视图同样标记数据变化的行
                    highlighted={highlightedTaskIds.has(task.id)}
                  />
                ))}
              </div>
            ) : (
              <Card className="overflow-hidden py-0">
                <CardContent className="p-0">
                  <div className="overflow-x-auto">
                    {/* 报告 A13：容器接收 ↑↓/Enter/Home/End 等按键 */}
                    {/* 报告通病 21：列多，给表格一个最小宽度，窄屏下横向滚动而不是压扁列 */}
                    <Table
                      {...keyboardNav.containerProps}
                      className="min-w-[900px]"
                    >
                      <TableHeader>
                        {/* 报告 A1：表头与每一行的单元格都要各自包 isVisible，漏一处列就整体错位 */}
                        <TableRow>
                          {isVisible("track") && (
                            <TableHead>
                              <div className="flex items-center gap-2">
                                <Checkbox
                                  checked={
                                    allSelectableTasksSelected
                                      ? true
                                      : selectableTasks.some((task) =>
                                            selectedTaskIds.has(task.id),
                                          )
                                        ? "indeterminate"
                                        : false
                                  }
                                  disabled={selectableTasks.length === 0}
                                  // 报告通病 7：全选只覆盖当前页（本页无服务端分页，即当前筛选结果），
                                  // 故在标签里注明「本页」与总数，避免被误读为跨页全选
                                  aria-label={`全选本页可删除任务（共 ${selectableTasks.length} 条）`}
                                  onCheckedChange={(value) =>
                                    toggleAllSelectableTasks(value === true)
                                  }
                                />
                                所属赛道
                              </div>
                            </TableHead>
                          )}
                          {isVisible("target") && (
                            <TableHead>任务目标</TableHead>
                          )}
                          {isVisible("id") && <TableHead>任务 ID</TableHead>}
                          {isVisible("status") && <TableHead>状态</TableHead>}
                          {isVisible("account") && <TableHead>账号</TableHead>}
                          {isVisible("progress") && (
                            <TableHead>数据进度</TableHead>
                          )}
                          {isVisible("created") && (
                            <TableHead>创建时间</TableHead>
                          )}
                          {/* 报告 A8：列表列数多，操作列冻结在右侧避免横向滚动后找不到 */}
                          {isVisible("actions") && (
                            <TableHead className="sticky right-0 z-10 bg-background/95 text-right backdrop-blur">
                              操作
                            </TableHead>
                          )}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {pagedTasks.map((task) => (
                          // 报告 A7：行右键菜单承载「复制 ID / 进详情 / 重启 / 删除」等低频操作
                          <TaskRowContextMenu key={task.id} task={task}>
                            <TableRow
                              className={cn(
                                // 报告 A13：键盘导航的当前行
                                "data-[active=true]:bg-muted/60",
                                // 报告 A6：轮询后数据变化的行闪一下
                                highlightedTaskIds.has(task.id) &&
                                  "row-highlight",
                              )}
                              data-active={keyboardNav.activeId === task.id}
                            >
                              {isVisible("track") && (
                                <TableCell>
                                  <div className="flex items-center gap-2">
                                    <TaskSelectionCheckbox
                                      task={task}
                                      selected={selectedTaskIds.has(task.id)}
                                      onSelectedChange={(checked) =>
                                        toggleTaskSelection(task.id, checked)
                                      }
                                    />
                                    <TrackBadge
                                      trackId={task.track_id}
                                      trackName={task.track_name}
                                      isDefault={task.track_is_default}
                                    />
                                    <SourceBadge
                                      sourceType={task.source_type}
                                      sourceLabel={task.source_label}
                                      className="max-w-48"
                                    />
                                  </div>
                                </TableCell>
                              )}
                              {isVisible("target") && (
                                <TableCell className="max-w-80">
                                  <TaskIdentity task={task} />
                                </TableCell>
                              )}
                              {/* 报告 A15：任务 ID 截断显示 + 悬停看全文 + 点击复制 */}
                              {isVisible("id") && (
                                <TableCell className="max-w-40">
                                  <CopyableId value={task.id} label="任务 ID" />
                                </TableCell>
                              )}
                              {isVisible("status") && (
                                <TableCell>
                                  <TaskStatusBadge status={task.status} />
                                </TableCell>
                              )}
                              {isVisible("account") && (
                                <TableCell className="whitespace-nowrap text-sm">
                                  <TaskAccount task={task} />
                                </TableCell>
                              )}
                              {isVisible("progress") && (
                                <TableCell>
                                  <TaskListProgress task={task} />
                                </TableCell>
                              )}
                              {isVisible("created") && (
                                <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                                  {/* 报告 A16：创建时间改相对时间，悬停看绝对时间 */}
                                  <TimeAgo value={task.created_at} />
                                </TableCell>
                              )}
                              {isVisible("actions") && (
                                <TableCell className="sticky right-0 bg-background/95 text-right backdrop-blur">
                                  <TaskActions task={task} />
                                </TableCell>
                              )}
                            </TableRow>
                          </TaskRowContextMenu>
                        ))}
                      </TableBody>
                      {/* 报告 A11：表尾合计（口径 = 当前筛选结果，与上方行数一致） */}
                      <TableFooter>
                        {/* 报告 A1：合计行的跨列数按可见列算，写死 colSpan 在隐藏列后必然错位 */}
                        <TableRow>
                          <TableCell
                            colSpan={visibleColSpan(["track", "target", "id"])}
                            className="text-sm"
                          >
                            合计 {filteredTasks.length} 个任务，进行中{" "}
                            {taskTotals.activeCount} 个
                          </TableCell>
                          {(isVisible("status") || isVisible("account")) && (
                            <TableCell
                              colSpan={visibleColSpan(["status", "account"])}
                            />
                          )}
                          {isVisible("progress") && (
                            <TableCell className="text-sm">
                              作品 {taskTotals.awemeTotal} · 评论{" "}
                              {taskTotals.commentTotal}
                            </TableCell>
                          )}
                          {isVisible("created") && <TableCell />}
                          {isVisible("actions") && (
                            <TableCell className="sticky right-0 bg-background/95 backdrop-blur" />
                          )}
                        </TableRow>
                      </TableFooter>
                    </Table>
                  </div>
                </CardContent>
              </Card>
            )}
            {/* 逐条视图同样补上分页：此前最多一次性铺满 100 行 */}
            {!grouping && (
              <Pager
                page={currentPage}
                pageSize={pageSize}
                total={filteredTasks.length}
                onPageChange={setPage}
                pageSizeOptions={[10, 20, 50]}
                onPageSizeChange={(size) => {
                  setPageSize(size)
                  setPage(0)
                }}
                totalLabel={(total) =>
                  `共 ${total} 个任务（合计 ${taskTotals.awemeTotal} 作品 · ${taskTotals.commentTotal} 评论）`
                }
              />
            )}
          </section>
        </TabsContent>

        <TabsContent value="media" className="mt-0">
          <MediaTaskManagement trackId={trackId} onTrackChange={setTrackId} />
        </TabsContent>
      </Tabs>

      {/* 报告 A3：批量操作栏，选中任务后从底部浮现，仅采集任务页生效 */}
      {businessTab === "crawl" && (
        <BulkActionBar
          count={selectedTaskIds.size}
          // 报告通病 7：勾选范围只限本页，计数文案里点明，避免误解为全量选中
          label={`已选本页 ${selectedTaskIds.size} 项`}
          onClear={() => setSelectedTaskIds(new Set())}
          actions={
            <BulkDeleteButton
              selectedTaskIds={selectedTaskIds}
              onDeleted={() => setSelectedTaskIds(new Set())}
            />
          }
        />
      )}
    </div>
  )
}

/**
 * 聚合视图的表格：一行 = 一组「任务 + 内容」，点开可以看到组内每次运行。
 */
function TaskGroupTable({ groups }: { groups: TaskGroup[] }) {
  const [expandedKey, setExpandedKey] = useState<string | null>(null)
  return (
    <Card className="overflow-hidden py-0">
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <Table className="min-w-[900px]">
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-64">目标内容</TableHead>
                <TableHead>所属赛道</TableHead>
                <TableHead>采集类型</TableHead>
                <TableHead className="text-right">运行次数</TableHead>
                <TableHead>数据合计</TableHead>
                <TableHead>最新状态</TableHead>
                <TableHead>最近运行</TableHead>
                <TableHead className="sticky right-0 z-10 bg-background/95 text-right backdrop-blur">
                  操作
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {groups.map((group) => {
                const expanded = expandedKey === group.key
                return (
                  <Fragment key={group.key}>
                    <TableRow>
                      <TableCell className="max-w-72">
                        <button
                          type="button"
                          className="flex items-start gap-2 text-left"
                          aria-expanded={expanded}
                          onClick={() =>
                            setExpandedKey(expanded ? null : group.key)
                          }
                        >
                          <ChevronDown
                            aria-hidden="true"
                            className={cn(
                              "mt-0.5 size-3.5 shrink-0 text-muted-foreground transition",
                              expanded && "rotate-180",
                            )}
                          />
                          <span
                            className="line-clamp-2 text-sm font-medium"
                            title={group.sourceLabel}
                          >
                            {group.sourceLabel}
                          </span>
                        </button>
                      </TableCell>
                      <TableCell>
                        <TrackBadge
                          trackId={group.trackId}
                          trackName={group.trackName}
                          isDefault={group.trackIsDefault}
                          className="max-w-40"
                        />
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {crawlTypeLabels[group.crawlType]}
                      </TableCell>
                      <TableCell className="text-right text-sm tabular-nums">
                        {group.runs.length}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-3 text-xs">
                          <span title="已采集作品">
                            作品{" "}
                            <strong className="tabular-nums">
                              {group.awemeCount}
                            </strong>
                          </span>
                          <span title="已采集评论">
                            评论{" "}
                            <strong className="tabular-nums">
                              {group.commentCount}
                            </strong>
                          </span>
                          <span title="已记录行为">
                            互动{" "}
                            <strong className="tabular-nums">
                              {group.actionCount}
                            </strong>
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <TaskStatusBadge status={group.latest.status} />
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        <TimeAgo value={group.latest.created_at} />
                      </TableCell>
                      <TableCell className="sticky right-0 bg-background/95 text-right backdrop-blur">
                        <Button size="sm" variant="outline" asChild>
                          <Link
                            to="/douyin/$taskId"
                            params={{ taskId: group.latest.id }}
                            aria-label={`查看最近一次运行：${group.sourceLabel}`}
                          >
                            最近一次
                          </Link>
                        </Button>
                      </TableCell>
                    </TableRow>
                    {expanded && (
                      <TableRow className="bg-muted/25 hover:bg-muted/25">
                        <TableCell colSpan={8} className="whitespace-normal">
                          <div className="space-y-1.5">
                            <p className="text-xs font-medium text-muted-foreground">
                              组内运行记录（{group.runs.length} 次，最近在前）
                            </p>
                            {group.runs.map((run) => (
                              <div
                                key={run.id}
                                className="flex flex-wrap items-center gap-2 text-xs"
                              >
                                <TaskStatusBadge status={run.status} />
                                <TimeAgo
                                  value={run.created_at}
                                  className="text-muted-foreground"
                                />
                                <span className="text-muted-foreground">
                                  作品 {run.aweme_count} · 评论{" "}
                                  {run.comment_count} · 互动 {run.action_count}
                                </span>
                                <CopyableId
                                  value={run.id}
                                  label="任务 ID"
                                  className="text-muted-foreground"
                                />
                                <Link
                                  to="/douyin/$taskId"
                                  params={{ taskId: run.id }}
                                  className="text-primary hover:underline"
                                >
                                  查看任务
                                </Link>
                              </div>
                            ))}
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                )
              })}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

function TaskMobileCard({
  task,
  selected,
  onSelectedChange,
  highlighted,
}: {
  task: CrawlTaskPublic
  selected: boolean
  onSelectedChange: (checked: boolean) => void
  /** 报告 A6：数据发生变化时闪一下 */
  highlighted?: boolean
}) {
  return (
    <Card className={cn("gap-4 p-4 py-4", highlighted && "row-highlight")}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <TaskSelectionCheckbox
            task={task}
            selected={selected}
            onSelectedChange={onSelectedChange}
          />
          <TrackBadge
            trackId={task.track_id}
            trackName={task.track_name}
            isDefault={task.track_is_default}
          />
          <SourceBadge
            sourceType={task.source_type}
            sourceLabel={task.source_label}
            className="max-w-48"
          />
        </div>
        <TaskStatusBadge status={task.status} />
      </div>
      <TaskIdentity task={task} className="text-sm" />
      <div className="grid grid-cols-3 gap-2 rounded-xl bg-muted/55 p-3 text-center">
        <MobileMetric label="作品" value={task.aweme_count} />
        <MobileMetric label="评论" value={task.comment_count} />
        <MobileMetric label="互动" value={task.action_count} />
      </div>
      <TaskListProgress task={task} />
      <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
        <TaskAccount task={task} />
        {/* 报告 A16：创建时间改相对时间 */}
        <TimeAgo value={task.created_at} />
      </div>
      <div className="flex justify-end">
        <TaskActions task={task} />
      </div>
    </Card>
  )
}

function TaskCompactRow({
  task,
  selected,
  onSelectedChange,
  highlighted,
}: {
  task: CrawlTaskPublic
  selected: boolean
  onSelectedChange: (checked: boolean) => void
  /** 报告 A6：数据发生变化时闪一下 */
  highlighted?: boolean
}) {
  return (
    <Card className={cn("gap-0 py-0", highlighted && "row-highlight")}>
      <CardContent className="flex flex-col gap-2 p-2 lg:flex-row lg:items-center">
        <div className="flex flex-wrap items-center gap-2 lg:w-52">
          <TaskSelectionCheckbox
            task={task}
            selected={selected}
            onSelectedChange={onSelectedChange}
          />
          <TrackBadge
            trackId={task.track_id}
            trackName={task.track_name}
            isDefault={task.track_is_default}
          />
          <SourceBadge
            sourceType={task.source_type}
            sourceLabel={task.source_label}
            className="max-w-48"
          />
        </div>
        <div className="min-w-0 flex-1 lg:max-w-sm">
          <TaskIdentity task={task} className="text-sm" />
        </div>
        <div className="flex flex-wrap items-center gap-2 lg:w-24">
          <TaskStatusBadge status={task.status} />
        </div>
        <div className="min-w-44 text-xs">
          <TaskAccount task={task} />
        </div>
        <div className="min-w-48 flex-1">
          <TaskListProgress task={task} />
        </div>
        {/* 报告 A16：创建时间改相对时间 */}
        <TimeAgo
          value={task.created_at}
          className="text-xs text-muted-foreground"
        />
        <TaskActions task={task} />
      </CardContent>
    </Card>
  )
}

function MobileMetric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <p className="font-semibold text-foreground">{value}</p>
      <p className="mt-0.5 text-[10px]">{label}</p>
    </div>
  )
}

/**
 * 报告 A4/O8：首屏加载骨架屏。
 * 按用户实际选中的视图形态铺占位（表格保留表头与列结构），
 * 数据到达后布局不跳动；对读屏器仍播报「正在加载任务…」。
 */
function TaskListSkeleton({
  viewMode,
  isVisible,
}: {
  viewMode: ListViewMode
  /** 报告 A1：骨架的列要跟随列可见性，否则隐藏列后加载结束的瞬间列数会跳变 */
  isVisible: (key: string) => boolean
}) {
  // 报告 A1：骨架表头 / 占位格都按可见列渲染，与真实表格保持一致
  const skeletonColumns = TASK_TABLE_COLUMNS.filter((column) =>
    isVisible(column.key),
  )
  if (viewMode === "cards") {
    return (
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-busy>
        <span className="sr-only">正在加载任务…</span>
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton
            key={`task-card-skeleton-${index}`}
            className="h-48 w-full rounded-2xl"
          />
        ))}
      </div>
    )
  }
  if (viewMode === "rows") {
    return (
      <div className="space-y-2" aria-busy>
        <span className="sr-only">正在加载任务…</span>
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton
            key={`task-row-skeleton-${index}`}
            className="h-16 w-full rounded-xl"
          />
        ))}
      </div>
    )
  }
  return (
    <Card className="overflow-hidden py-0" aria-busy>
      <CardContent className="p-0">
        <span className="sr-only">正在加载任务…</span>
        <div className="overflow-x-auto">
          <Table className="min-w-[900px]">
            <TableHeader>
              <TableRow>
                {skeletonColumns.map((column) => (
                  <TableHead
                    key={column.key}
                    className={column.key === "actions" ? "text-right" : ""}
                  >
                    {column.title}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {Array.from({ length: 8 }, (_, rowIndex) => (
                <TableRow
                  key={`task-skeleton-${rowIndex}`}
                  className="hover:bg-transparent"
                >
                  {skeletonColumns.map((column) => (
                    <TableCell
                      key={`task-skeleton-cell-${rowIndex}-${column.key}`}
                    >
                      <Skeleton className="h-4 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

function TaskActions({ task }: { task: CrawlTaskPublic }) {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const resume = useMutation({
    mutationFn: () =>
      DouyinService.resumeTask({ taskId: task.id, requestBody: {} }),
    onSuccess: async () => {
      showSuccessToast("任务已从最近断点继续")
      await queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] })
    },
    onError: handleError.bind(showErrorToast),
  })
  const restart = useMutation({
    mutationFn: () => DouyinService.restartTask({ taskId: task.id }),
    onSuccess: async () => {
      showSuccessToast("任务已清空断点并从头重新入队")
      await queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] })
    },
    onError: handleError.bind(showErrorToast),
  })
  const sync = useMutation({
    mutationFn: () =>
      DouyinKeywordsService.syncKeywordsFromTask({ taskId: task.id }),
    onSuccess: async (result) => {
      showSuccessToast(
        result.created_count || result.binding_count
          ? `已新增 ${result.created_count} 个关键词、${result.binding_count} 个任务绑定`
          : "任务关键词已经同步，无需重复处理",
      )
      await queryClient.invalidateQueries({ queryKey: ["douyin-keywords"] })
    },
    onError: handleError.bind(showErrorToast),
  })
  /** 报告 O15：改用统一确认框（原来是 window.confirm） */
  async function askRestart() {
    const ok = await confirmDialog({
      title: "确认从头重启？",
      description: "已保存的数据保留，但断点会清空。",
      confirmText: "重启",
    })
    if (ok) restart.mutate()
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          size="icon-sm"
          variant="outline"
          aria-label={`管理任务 ${task.display_title || task.id}`}
        >
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-40">
        <DropdownMenuItem asChild>
          <Link to="/douyin/$taskId" params={{ taskId: task.id }}>
            <ArrowRight /> 查看详情
          </Link>
        </DropdownMenuItem>
        {(task.can_resume_crawl || task.can_resume_media) && (
          <DropdownMenuItem
            disabled={resume.isPending}
            onSelect={() => resume.mutate()}
          >
            <Play /> 断点续爬
          </DropdownMenuItem>
        )}
        {restartableTaskStatuses.includes(task.status) && (
          <DropdownMenuItem
            disabled={restart.isPending}
            onSelect={() => void askRestart()}
          >
            <RotateCcw /> 从头重启
          </DropdownMenuItem>
        )}
        {task.crawl_type === "search" && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              disabled={sync.isPending}
              onSelect={() => sync.mutate()}
            >
              <Tags /> 同步关键词
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/**
 * 报告 A7：表视图的行右键菜单。
 * 把「复制任务 ID、进入详情、从头重启、删除」这类低频或不可逆操作从操作列
 * 挪到右键菜单（操作列本身保留查看详情等高频入口，见 TaskActions）。
 */
function TaskRowContextMenu({
  task,
  children,
}: {
  task: CrawlTaskPublic
  /** 只能是一个能接受 ref 的元素（这里固定是 <TableRow>） */
  children: ReactNode
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [, copy] = useCopyToClipboard()
  const restart = useMutation({
    mutationFn: () => DouyinService.restartTask({ taskId: task.id }),
    onSuccess: async () => {
      showSuccessToast("任务已清空断点并从头重新入队")
      await queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] })
    },
    onError: handleError.bind(showErrorToast),
  })
  const remove = useMutation({
    mutationFn: () => DouyinService.deleteTask({ taskId: task.id }),
    onSuccess: async (result) => {
      showSuccessToast(result.message)
      await queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  async function copyTaskId() {
    const ok = await copy(task.id)
    if (ok) showSuccessToast("已复制任务 ID")
    else showErrorToast("复制失败，请手动选择复制")
  }

  /** 报告 O15：改用统一确认框 */
  async function askRestart() {
    const ok = await confirmDialog({
      title: "确认从头重启？",
      description: "已保存的数据保留，但断点会清空。",
      confirmText: "重启",
    })
    if (ok) restart.mutate()
  }

  /** 报告 O15：删除不可恢复，确认按钮标红 */
  async function askDelete() {
    const ok = await confirmDialog({
      title: `确认删除任务「${task.display_title || task.id}」？`,
      description: "任务关联的作品、评论、互动记录也会一并删除，且无法恢复。",
      confirmText: "删除",
      variant: "destructive",
    })
    if (ok) remove.mutate()
  }

  const items: RowMenuItem[] = [
    { label: "复制任务 ID", icon: Copy, onSelect: () => void copyTaskId() },
    {
      label: "进入任务详情",
      icon: ArrowRight,
      onSelect: () =>
        void navigate({ to: "/douyin/$taskId", params: { taskId: task.id } }),
    },
  ]
  // 只有可重启 / 可删除的任务才出现对应菜单项，与操作列的条件保持一致
  if (restartableTaskStatuses.includes(task.status)) {
    items.push({
      separatorBefore: true,
      label: "从头重启",
      icon: RotateCcw,
      disabled: restart.isPending,
      onSelect: () => void askRestart(),
    })
  }
  if (isDeletableTask(task)) {
    items.push({
      separatorBefore: true,
      label: "删除任务",
      icon: Trash2,
      destructive: true,
      disabled: remove.isPending,
      onSelect: () => void askDelete(),
    })
  }

  return (
    <RowContextMenu label={task.display_title || task.id} items={items}>
      {children}
    </RowContextMenu>
  )
}

function taskBrowserMode(task: CrawlTaskPublic) {
  const mode = task.request.browser_mode
  if (mode === "remote") return "云端浏览器"
  if (mode === "local") return "本机浏览器"
  return "系统默认"
}

function taskAccountLabel(task: CrawlTaskPublic) {
  if (task.account_name) return task.account_name
  if (task.account_pool_name) return `账号池 ${task.account_pool_name}`
  const accountIds = task.request.account_ids
  if (Array.isArray(accountIds) && accountIds.length)
    return `已指定 ${accountIds.length} 个账号`
  return "未指定账号"
}

function TaskAccount({ task }: { task: CrawlTaskPublic }) {
  return (
    <span title={`${taskAccountLabel(task)}（${taskBrowserMode(task)}）`}>
      <span className="font-medium text-foreground">
        {taskAccountLabel(task)}
      </span>
      <span className="text-muted-foreground">（{taskBrowserMode(task)}）</span>
    </span>
  )
}

/** 只有失效终态允许删除，活动任务与成功任务不可删除。 */
const deletableTaskStatuses = ["failed", "cancelled", "interrupted"]

function isDeletableTask(task: CrawlTaskPublic) {
  return deletableTaskStatuses.includes(task.status)
}

function TaskSelectionCheckbox({
  task,
  selected,
  onSelectedChange,
}: {
  task: CrawlTaskPublic
  selected: boolean
  onSelectedChange: (checked: boolean) => void
}) {
  return (
    <Checkbox
      checked={selected}
      disabled={!isDeletableTask(task)}
      aria-label={`选择任务 ${task.display_title || task.id}`}
      onCheckedChange={(value) => onSelectedChange(value === true)}
    />
  )
}

/** 可重启的任务状态：失败或异常中断（活动任务与成功任务不可重启）。 */
const restartableTaskStatuses = ["failed", "interrupted"]

function BulkResumeButton({
  tasks,
  selectedTaskIds,
}: {
  tasks: CrawlTaskPublic[]
  selectedTaskIds: Set<string>
}) {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const candidates = tasks.filter(
    (task) =>
      restartableTaskStatuses.includes(task.status) &&
      (task.can_resume_crawl || task.can_resume_media),
  )
  const selectedResumable = candidates.filter((task) =>
    selectedTaskIds.has(task.id),
  )
  const resumable = selectedTaskIds.size ? selectedResumable : candidates
  const [open, setOpen] = useState(false)
  const [taskInterval, setTaskInterval] = useState("10")
  const mutation = useMutation({
    mutationFn: () =>
      DouyinService.bulkResumeTasks({
        requestBody: {
          ids: resumable.map((task) => task.id),
          task_interval_seconds: Number(taskInterval),
        },
      }),
    onSuccess: async (result) => {
      setOpen(false)
      showSuccessToast(
        `已受理 ${result.count} 个任务${result.failed_count ? `，${result.failed_count} 个任务未能恢复` : ""}`,
      )
      await queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] })
    },
    onError: handleError.bind(showErrorToast),
  })
  return (
    resumable.length > 0 && (
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button variant="outline" size="sm">
            <Play />
            一键断点续爬（{resumable.length}）
          </Button>
        </DialogTrigger>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>批量恢复任务</DialogTitle>
            <DialogDescription>
              将恢复 {resumable.length}{" "}
              个失败或中断任务。服务端会按完成顺序串行执行，避免批量任务同时触发请求。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <Label htmlFor="bulk-resume-task-interval">
              任务完成后间隔（秒）
            </Label>
            <Input
              id="bulk-resume-task-interval"
              type="number"
              min={0}
              max={3600}
              step={1}
              value={taskInterval}
              onChange={(event) => setTaskInterval(event.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              默认 10 秒；填 0
              表示不额外等待。该间隔只影响这次恢复任务，单任务内请求间隔仍按原风控配置执行。
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button
              disabled={
                mutation.isPending ||
                taskInterval.trim() === "" ||
                Number(taskInterval) < 0 ||
                Number(taskInterval) > 3600
              }
              onClick={() => mutation.mutate()}
            >
              {mutation.isPending ? "正在受理…" : "确认恢复"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    )
  )
}

function BulkDeleteButton({
  selectedTaskIds,
  onDeleted,
}: {
  selectedTaskIds: Set<string>
  onDeleted: () => void
}) {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const selectedCount = selectedTaskIds.size
  const mutation = useMutation({
    mutationFn: () =>
      DouyinService.bulkDeleteTasks({
        requestBody: { ids: [...selectedTaskIds] },
      }),
    onSuccess: async (result) => {
      showSuccessToast(result.message)
      onDeleted()
      await queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] })
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <Button
      variant="destructive"
      size="sm"
      disabled={selectedCount === 0 || mutation.isPending}
      aria-label="删除选中任务"
      onClick={async () => {
        // 报告 O15：改用统一确认框（原来是 window.confirm）
        const ok = await confirmDialog({
          title: `确认删除选中的 ${selectedCount} 条失效任务？`,
          description:
            "任务关联的作品、评论、互动记录也会一并删除，且无法恢复。",
          confirmText: "删除",
          variant: "destructive",
        })
        if (ok) mutation.mutate()
      }}
    >
      <Trash2 />
      {mutation.isPending
        ? "正在删除…"
        : `删除选中${selectedCount ? `（${selectedCount}）` : ""}`}
    </Button>
  )
}
