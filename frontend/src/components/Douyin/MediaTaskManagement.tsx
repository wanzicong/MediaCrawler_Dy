import { Link } from "@tanstack/react-router"
import {
  ArrowRight,
  Captions,
  CheckCircle2,
  Clock3,
  Download,
  FileDown,
  Film,
  ListFilter,
  LoaderCircle,
  MoreHorizontal,
  RefreshCw,
  Search,
} from "lucide-react"
import { useMemo, useState } from "react"

import {
  type DouyinMediaTaskPublic,
  type DouyinMediaTaskStatus,
  DouyinService,
} from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import { FilterPanel } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { TableColumnMenu } from "@/components/Common/TableColumnMenu"
import {
  type ListViewMode,
  usePersistentViewMode,
  ViewModeToggle,
} from "@/components/Common/ViewModeToggle"
import { ProcessMediaDialog } from "@/components/Douyin/ProcessMediaDialog"
import { shortTaskReference } from "@/components/Douyin/TaskIdentity"
import {
  allTracksValue,
  TrackBadge,
  TrackSelect,
} from "@/components/Douyin/TrackSelect"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useHighlightedRows } from "@/hooks/useHighlightedRows"
import { hasActiveStatus, useSmartPolling } from "@/hooks/useSmartPolling"
import { type TableColumnDef, useTableColumns } from "@/hooks/useTableColumns"
import { type CsvColumn, downloadCsv } from "@/lib/csv"
import { formatDateTime } from "@/lib/time"
import { cn } from "@/lib/utils"

type MediaFilter = "all" | "active" | "ready" | "attention" | "completed"

const mediaFilters: Array<{ key: MediaFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "active", label: "处理中" },
  { key: "ready", label: "可创建" },
  { key: "attention", label: "需处理" },
  { key: "completed", label: "已完成" },
]

// 报告 A1：列可见性 —— 媒体任务表的列清单。
// 必须是模块级常量：放在组件内每次 render 都会新建，hook 里的默认隐藏列会被反复重置。
const MEDIA_TASK_COLUMNS = [
  { key: "source", title: "来源采集任务" },
  { key: "track", title: "所属赛道" },
  { key: "dependency", title: "依赖关系" },
  { key: "download", title: "视频下载" },
  { key: "subtitle", title: "字幕处理" },
  { key: "status", title: "状态" },
  // 操作列不允许隐藏，否则用户没有入口继续处理任务
  { key: "actions", title: "操作", alwaysVisible: true },
] as const satisfies readonly TableColumnDef[]

// 报告 O16：状态色收敛到唯一的 mediaStatusStyles 映射。
// 改造前状态色至少散落在三处 JSX（状态徽章、依赖图标、状态文案），改一处很容易漏掉另一处；
// 现在所有状态相关色值都从这里取，新增状态只需补一条记录。
//
// 关于 CSS 变量：这些是**语义状态色**（等待=黄 / 进行=蓝 / 成功=绿 / 失败=红），
// 表达的是业务含义而不是品牌色，本就不应跟随皮肤（data-preset）变化，
// 所以这里保留 Tailwind 语义色 + dark: 变体；后续若要支持高对比度等无障碍主题，
// 再把 badge/icon 两列换成 CSS 变量即可，调用方无需改动。
const mediaStatusStyles: Record<
  DouyinMediaTaskStatus,
  {
    label: string
    /** 状态徽章（Badge）的底色/边框/文字色 */
    badge: string
    /** 同状态下的图标/强调文字色（依赖关系、提示文字等复用同一色调） */
    icon: string
  }
> = {
  waiting_source: {
    label: "等待采集",
    badge:
      "border-amber-300 bg-amber-50 text-amber-800 dark:bg-amber-950/35 dark:text-amber-200",
    icon: "text-amber-600 dark:text-amber-400",
  },
  ready: {
    label: "可创建",
    badge:
      "border-sky-300 bg-sky-50 text-sky-800 dark:bg-sky-950/35 dark:text-sky-200",
    icon: "text-sky-600 dark:text-sky-400",
  },
  queued: {
    label: "排队中",
    badge:
      "border-violet-300 bg-violet-50 text-violet-800 dark:bg-violet-950/35 dark:text-violet-200",
    icon: "text-violet-600 dark:text-violet-400",
  },
  running: {
    label: "处理中",
    badge:
      "border-blue-300 bg-blue-50 text-blue-800 dark:bg-blue-950/35 dark:text-blue-200",
    icon: "text-blue-600 dark:text-blue-400",
  },
  attention: {
    label: "需处理",
    badge:
      "border-red-300 bg-red-50 text-red-800 dark:bg-red-950/35 dark:text-red-200",
    icon: "text-red-600 dark:text-red-400",
  },
  completed: {
    label: "已完成",
    badge:
      "border-emerald-300 bg-emerald-50 text-emerald-800 dark:bg-emerald-950/35 dark:text-emerald-200",
    icon: "text-emerald-600 dark:text-emerald-400",
  },
}

// 轮询终态：这些状态下后端不会自行推进（已完成 / 等用户创建 / 等用户处理），
// 其余状态（等待采集 / 排队中 / 处理中）仍在变化，需要继续轮询。
const TERMINAL_MEDIA_STATUSES: readonly DouyinMediaTaskStatus[] = [
  "completed",
  "ready",
  "attention",
]

// 报告 A12：导出**当前筛选结果**（本页最多 100 条，属于小数据量，前端即时拼接即可）。
// 数值列取「可下载数 / 下载完成 / 下载失败 / 字幕完成 / 字幕失败」，导出后可直接在 Excel 里核对。
// 「导出全部」需要后端流式接口，本次不做。
const mediaTaskCsvColumns: CsvColumn<DouyinMediaTaskPublic>[] = [
  { header: "来源任务 ID", value: (task) => task.source_task_id },
  { header: "来源标题", value: (task) => mediaSourceTitle(task) },
  { header: "赛道", value: (task) => task.track_name },
  { header: "状态", value: (task) => mediaStatusStyles[task.status].label },
  { header: "可下载数", value: (task) => task.eligible_count },
  { header: "下载完成", value: (task) => task.summary.downloaded },
  { header: "下载失败", value: (task) => task.summary.download_failed },
  { header: "字幕完成", value: (task) => task.summary.subtitle_completed },
  { header: "字幕失败", value: (task) => task.summary.subtitle_failed },
  { header: "创建时间", value: (task) => formatDateTime(task.created_at) },
]

// 报告 A6：行变化指纹 —— 状态 + 下载/字幕进度。
// 轮询刷新时只有这些字段真的变了才算「数据变化」，只是列表顺序变化不会误闪。
function mediaTaskFingerprint(task: DouyinMediaTaskPublic) {
  return [
    task.status,
    task.summary.downloaded,
    task.summary.downloading,
    task.summary.subtitle_completed,
    task.summary.subtitle_running,
  ].join(":")
}

export function MediaTaskManagement({
  trackId,
  onTrackChange,
}: {
  trackId: string
  onTrackChange: (value: string) => void
}) {
  const [filter, setFilter] = useState<MediaFilter>("all")
  const [search, setSearch] = useState("")
  const [viewMode, setViewMode] = usePersistentViewMode(
    "douyin-media-tasks-view",
  )
  // 报告 A1：列可见性 —— 表头、正常行、加载骨架三处都要用同一个 isVisible，
  // 所以放在父组件里取一次再往下传，避免各处各建一份状态导致列数不一致。
  const { isVisible, menuProps } = useTableColumns({
    storageKey: "media-task-management-columns",
    columns: MEDIA_TASK_COLUMNS,
  })
  const query = useSmartPolling(
    ["douyin-media-tasks", trackId],
    () =>
      DouyinService.listMediaTasks({
        trackId: trackId === allTracksValue ? undefined : trackId,
        skip: 0,
        // 已知截断：这里固定只取 100 条，超过 100 个的媒体任务不会出现在列表中（本页暂无分页）。
        limit: 100,
      }),
    {
      // 有活跃任务才按 3s 轮询；全部到终态后停止，避免空转（原来是固定 3s 无条件轮询）。
      isActive: (data) =>
        hasActiveStatus(
          data.data,
          (task) => task.status,
          TERMINAL_MEDIA_STATUSES,
        ),
      activeInterval: 3_000,
    },
  )
  const tasks = query.data?.data ?? []
  // 聚合结果只与 tasks 有关，条数可能上百，缓存下来避免每次 render 重算。
  const counts = useMemo(
    () =>
      tasks.reduce(
        (current, task) => ({
          active:
            current.active +
            (task.status === "queued" || task.status === "running" ? 1 : 0),
          ready: current.ready + (task.status === "ready" ? 1 : 0),
          attention:
            current.attention +
            (task.status === "attention" || task.status === "waiting_source"
              ? 1
              : 0),
          downloaded: current.downloaded + task.summary.downloaded,
          completed: current.completed + (task.status === "completed" ? 1 : 0),
        }),
        { active: 0, ready: 0, attention: 0, downloaded: 0, completed: 0 },
      ),
    [tasks],
  )
  // 报告 A6：轮询刷新后状态/进度变化的行闪一下；首次加载不闪（hook 内部已处理）。
  const highlighted = useHighlightedRows(
    tasks,
    (task) => task.source_task_id,
    mediaTaskFingerprint,
  )
  const filtered = useMemo(() => {
    const keyword = search.trim().toLocaleLowerCase("zh-CN")
    return tasks.filter((task) => {
      const matchesFilter =
        filter === "all" ||
        (filter === "active" && ["queued", "running"].includes(task.status)) ||
        (filter === "ready" && task.status === "ready") ||
        (filter === "attention" &&
          ["attention", "waiting_source"].includes(task.status)) ||
        (filter === "completed" && task.status === "completed")
      if (!matchesFilter) return false
      if (!keyword) return true
      return [
        mediaSourceTitle(task),
        task.source_author ?? "",
        ...(task.source_creator_names ?? []),
        task.track_name,
        shortTaskReference(task.source_task_id),
      ].some((value) => value.toLocaleLowerCase("zh-CN").includes(keyword))
    })
  }, [filter, search, tasks])
  // 报告 A4/O8：空态的主行动 —— 一键回到未筛选状态。
  // 赛道是服务端筛选条件，若它把结果筛空了（trackId 指向的赛道在本页没有任务），
  // 只清本地状态仍然为空，所以这里一并回到「全部赛道」，避免用户反复清筛选却看不到变化。
  const clearFilters = () => {
    setFilter("all")
    setSearch("")
    if (trackId !== allTracksValue) onTrackChange(allTracksValue)
  }

  return (
    <div className="space-y-3">
      <section className="space-y-3">
        <FilterPanel className="p-2">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <fieldset className="flex items-center gap-2 overflow-x-auto pb-1 lg:pb-0">
              <legend className="sr-only">媒体任务状态筛选</legend>
              {mediaFilters.map((item) => (
                <Button
                  key={item.key}
                  type="button"
                  size="sm"
                  variant={filter === item.key ? "default" : "ghost"}
                  aria-pressed={filter === item.key}
                  className="shrink-0"
                  onClick={() => setFilter(item.key)}
                >
                  {item.label}
                  <span className="text-[10px] tabular-nums text-muted-foreground">
                    {item.key === "all"
                      ? tasks.length
                      : item.key === "completed"
                        ? counts.completed
                        : counts[item.key]}
                  </span>
                </Button>
              ))}
            </fieldset>
            <div className="flex w-full flex-col gap-2 sm:flex-row lg:max-w-2xl">
              <TrackSelect
                value={trackId}
                onValueChange={onTrackChange}
                includeAll
                allowDisabled
                className="h-9 bg-background sm:w-48"
                ariaLabel="按赛道筛选媒体任务"
              />
              <label
                htmlFor="media-task-search"
                className="relative block flex-1"
              >
                <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="media-task-search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="搜索来源任务、作者或赛道…"
                  aria-label="搜索媒体任务"
                  className="h-9 rounded-xl bg-background pl-9"
                />
              </label>
              <Button
                variant="outline"
                size="icon-sm"
                aria-label="刷新下载与字幕任务"
                disabled={query.isFetching}
                onClick={() => void query.refetch()}
              >
                <RefreshCw className={cn(query.isFetching && "animate-spin")} />
              </Button>
              {/* 报告 A12：导出当前筛选结果（数据量小，前端即时生成 CSV） */}
              <Button
                variant="outline"
                size="icon-sm"
                aria-label="导出当前筛选的媒体任务为 CSV"
                disabled={filtered.length === 0}
                onClick={() =>
                  downloadCsv("媒体任务", filtered, mediaTaskCsvColumns)
                }
              >
                <FileDown />
              </Button>
              <ViewModeToggle
                value={viewMode}
                onChange={setViewMode}
                label="切换媒体任务展示方式"
              />
              {/* 报告 A1：列可见性 —— 只有表格视图才有列，卡片/列表视图不显示这个入口 */}
              {viewMode === "table" && <TableColumnMenu {...menuProps} />}
            </div>
          </div>
        </FilterPanel>

        {query.isLoading ? (
          // 报告 A4/O8：加载态改为骨架屏（保留当前视图的结构，数据到位时不跳动）
          <MediaTaskListSkeleton viewMode={viewMode} isVisible={isVisible} />
        ) : query.isError ? (
          <QueryErrorState
            title="媒体任务读取失败"
            description="暂时无法读取下载与字幕任务，请检查服务连接后重试。"
            onRetry={() => void query.refetch()}
            retrying={query.isFetching}
          />
        ) : tasks.length === 0 ? (
          // 报告 A4/O8：真空态（不是筛选筛空的）—— 给出下一步该做什么的主行动
          <EmptyState
            icon={Film}
            title="还没有可下载的媒体任务"
            description="先完成一次内容采集，采集产出的作品就能在这里创建视频下载与字幕任务。"
            action={
              <Button
                variant="outline"
                size="sm"
                disabled={query.isFetching}
                onClick={() => void query.refetch()}
              >
                <RefreshCw className={cn(query.isFetching && "animate-spin")} />
                刷新列表
              </Button>
            }
          />
        ) : filtered.length === 0 ? (
          // 报告 A4/O8：筛选筛空 —— 主行动是「清除筛选」而不是「去创建」
          <EmptyState
            icon={ListFilter}
            title="没有匹配的媒体任务"
            description="当前的状态、赛道或搜索条件没有命中任何任务，放宽条件后再试。"
            action={
              <Button variant="secondary" size="sm" onClick={clearFilters}>
                清除筛选
              </Button>
            }
          />
        ) : viewMode === "cards" ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {filtered.map((task) => (
              <MediaTaskCard key={task.source_task_id} task={task} />
            ))}
          </div>
        ) : viewMode === "rows" ? (
          <div className="space-y-2">
            {filtered.map((task) => (
              <MediaTaskRow key={task.source_task_id} task={task} />
            ))}
          </div>
        ) : (
          <MediaTaskTable
            tasks={filtered}
            highlightedIds={highlighted}
            isVisible={isVisible}
          />
        )}
      </section>
    </div>
  )
}

function MediaTaskTable({
  tasks,
  highlightedIds,
  isVisible,
}: {
  tasks: DouyinMediaTaskPublic[]
  /** 报告 A6：本次刷新后数据变化的行 id */
  highlightedIds: Set<string>
  /** 报告 A1：列可见性判断（表头与每一行的单元格都要包，漏一处就会列错位） */
  isVisible: (key: string) => boolean
}) {
  return (
    <Card className="overflow-hidden py-0">
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          {/* 报告 通病21：7 列在窄屏会被压扁，给表格一个最小宽度让它横向滚动而不是挤压换行 */}
          <Table className="min-w-[900px]">
            <TableHeader>
              <TableRow>
                {/* 报告 A1：列可见性 —— 表头与下方每一行的单元格必须成对出现 isVisible 判断 */}
                {isVisible("source") && <TableHead>来源采集任务</TableHead>}
                {isVisible("track") && <TableHead>所属赛道</TableHead>}
                {isVisible("dependency") && <TableHead>依赖关系</TableHead>}
                {isVisible("download") && <TableHead>视频下载</TableHead>}
                {isVisible("subtitle") && <TableHead>字幕处理</TableHead>}
                {isVisible("status") && <TableHead>状态</TableHead>}
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tasks.map((task) => (
                <TableRow
                  key={task.source_task_id}
                  className={cn(
                    // 报告 A6：数据变化的行闪一下（见 index.css 的 .row-highlight）
                    highlightedIds.has(task.source_task_id) && "row-highlight",
                  )}
                >
                  {isVisible("source") && (
                    <TableCell className="max-w-72">
                      <MediaSourceIdentity task={task} />
                    </TableCell>
                  )}
                  {isVisible("track") && (
                    <TableCell>
                      <TrackBadge
                        trackId={task.track_id}
                        trackName={task.track_name}
                        isDefault={task.track_is_default}
                      />
                    </TableCell>
                  )}
                  {isVisible("dependency") && (
                    <TableCell className="max-w-64">
                      <DependencyState task={task} />
                    </TableCell>
                  )}
                  {isVisible("download") && (
                    <TableCell className="min-w-44">
                      <MediaProgress task={task} kind="download" />
                    </TableCell>
                  )}
                  {isVisible("subtitle") && (
                    <TableCell className="min-w-44">
                      <MediaProgress task={task} kind="subtitle" />
                    </TableCell>
                  )}
                  {isVisible("status") && (
                    <TableCell>
                      <MediaStatusBadge status={task.status} />
                    </TableCell>
                  )}
                  <TableCell className="text-right">
                    <MediaTaskActions task={task} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

function MediaTaskRow({ task }: { task: DouyinMediaTaskPublic }) {
  return (
    <Card className="gap-0 py-0">
      <CardContent className="grid gap-3 p-3 md:grid-cols-2 xl:grid-cols-[minmax(10rem,1.3fr)_minmax(8rem,.8fr)_minmax(11rem,1.2fr)_minmax(8rem,.8fr)_minmax(8rem,.8fr)_auto] xl:items-center">
        <div className="min-w-0">
          <MediaSourceIdentity task={task} />
        </div>
        <div className="flex min-w-0 flex-wrap gap-2">
          <TrackBadge
            trackId={task.track_id}
            trackName={task.track_name}
            isDefault={task.track_is_default}
          />
          <MediaStatusBadge status={task.status} />
        </div>
        <div className="min-w-0">
          <DependencyState task={task} compact />
        </div>
        <div className="min-w-0">
          <MediaProgress task={task} kind="download" />
        </div>
        <div className="min-w-0">
          <MediaProgress task={task} kind="subtitle" />
        </div>
        <MediaTaskActions task={task} />
      </CardContent>
    </Card>
  )
}

function MediaTaskCard({ task }: { task: DouyinMediaTaskPublic }) {
  return (
    <Card className="gap-4 p-4 py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <MediaSourceIdentity task={task} />
        </div>
        <MediaStatusBadge status={task.status} />
      </div>
      <TrackBadge
        trackId={task.track_id}
        trackName={task.track_name}
        isDefault={task.track_is_default}
      />
      <DependencyState task={task} />
      <div className="grid gap-3 rounded-xl bg-muted/45 p-3 sm:grid-cols-2">
        <MediaProgress task={task} kind="download" />
        <MediaProgress task={task} kind="subtitle" />
      </div>
      <div className="flex justify-end">
        <MediaTaskActions task={task} />
      </div>
    </Card>
  )
}

function MediaSourceIdentity({ task }: { task: DouyinMediaTaskPublic }) {
  const author =
    task.source_author?.trim() || task.source_creator_names?.[0]?.trim()
  return (
    <div className="min-w-0">
      <p className="truncate font-medium" title={mediaSourceTitle(task)}>
        {mediaSourceTitle(task)}
      </p>
      <p className="mt-1 truncate text-xs text-muted-foreground">
        {author ? `作者：${author} · ` : ""}
        {shortTaskReference(task.source_task_id)} ·{" "}
        {formatDateTime(task.created_at, { short: true })}
      </p>
    </div>
  )
}

function DependencyState({
  task,
  compact = false,
}: {
  task: DouyinMediaTaskPublic
  compact?: boolean
}) {
  return (
    <div className={cn("flex items-start gap-2", compact && "items-center")}>
      {/* 报告 O16：图标色原先就地硬编码（emerald/amber），改为复用状态映射表中同语义的色调 */}
      {task.dependency_ready ? (
        <CheckCircle2
          className={cn(
            "mt-0.5 size-4 shrink-0",
            mediaStatusStyles.completed.icon,
          )}
        />
      ) : (
        <Clock3
          className={cn(
            "mt-0.5 size-4 shrink-0",
            mediaStatusStyles.waiting_source.icon,
          )}
        />
      )}
      <p className="text-xs text-muted-foreground">{task.dependency_message}</p>
    </div>
  )
}

function MediaProgress({
  task,
  kind,
}: {
  task: DouyinMediaTaskPublic
  kind: "download" | "subtitle"
}) {
  const summary = task.summary
  const completed =
    kind === "download"
      ? summary.downloaded + summary.temporary
      : summary.subtitle_completed
  const failed =
    kind === "download" ? summary.download_failed : summary.subtitle_failed
  const active =
    kind === "download"
      ? summary.queued + summary.downloading
      : summary.subtitle_pending + summary.subtitle_running
  const subtitleTotal =
    summary.subtitle_pending +
    summary.subtitle_running +
    summary.subtitle_completed +
    summary.subtitle_failed
  const total = kind === "download" ? task.eligible_count : subtitleTotal
  const percent = total
    ? Math.min(100, Math.round((completed / total) * 100))
    : 0
  const Icon = kind === "download" ? Download : Captions
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <Icon className="size-3.5" />
          {kind === "download" ? "下载" : "字幕"}
        </span>
        <span className="tabular-nums">
          {completed} / {total}
        </span>
      </div>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-label={kind === "download" ? "视频下载进度" : "字幕处理进度"}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <div
          className={cn(
            "h-full rounded-full transition-[width] motion-reduce:transition-none",
            failed ? "bg-destructive" : "bg-primary",
          )}
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="text-[10px] text-muted-foreground">
        {kind === "subtitle" && total === 0
          ? "未创建字幕任务"
          : active
            ? `${active} 条处理中`
            : failed
              ? `${failed} 条失败`
              : "当前无排队"}
      </p>
    </div>
  )
}

function MediaStatusBadge({ status }: { status: DouyinMediaTaskStatus }) {
  // 报告 O16：色值统一从 mediaStatusStyles 取，不再就地写 Tailwind 色
  const style = mediaStatusStyles[status]
  return (
    <Badge variant="outline" className={style.badge}>
      {style.label}
    </Badge>
  )
}

function MediaTaskActions({ task }: { task: DouyinMediaTaskPublic }) {
  const source = {
    id: task.source_task_id,
    track_id: task.track_id,
    aweme_count: task.eligible_count,
    request: task.source_request ?? {},
  }
  const active = task.status === "queued" || task.status === "running"
  const triggerLabel =
    task.status === "ready"
      ? "创建下载任务"
      : task.status === "attention"
        ? "继续处理"
        : "补充处理"
  return (
    <div className="flex items-center justify-end gap-2">
      {!task.dependency_ready ? (
        <Button size="sm" variant="outline" disabled>
          <Clock3 /> 等待采集
        </Button>
      ) : active ? (
        <Button size="sm" variant="outline" disabled>
          <LoaderCircle className="animate-spin" /> 处理中
        </Button>
      ) : (
        <ProcessMediaDialog
          task={source}
          triggerLabel={triggerLabel}
          triggerVariant={task.status === "completed" ? "outline" : "default"}
        />
      )}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            size="icon-sm"
            variant="outline"
            aria-label={`更多媒体任务操作：${mediaSourceTitle(task)}`}
          >
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem asChild>
            <Link to="/douyin/$taskId" params={{ taskId: task.source_task_id }}>
              <ArrowRight /> 查看来源与作品
            </Link>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

// 报告 A4/O8：加载骨架按当前视图形态渲染，保持与真实内容一致的行/卡片结构，
// 数据到位时不会因为「骨架是一张表、结果是卡片网格」而整页跳动。
function MediaTaskListSkeleton({
  viewMode,
  isVisible,
}: {
  viewMode: ListViewMode
  /** 报告 A1：骨架的表头/单元格也要跟随列设置，否则加载完的瞬间列会跳一下 */
  isVisible: (key: string) => boolean
}) {
  if (viewMode === "cards") {
    return (
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }, (_, index) => (
          <Card
            key={`media-task-card-skeleton-${index}`}
            className="gap-4 p-4 py-4"
          >
            <Skeleton className="h-5 w-3/4" />
            <Skeleton className="h-5 w-24" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-16 w-full rounded-xl" />
          </Card>
        ))}
      </div>
    )
  }
  if (viewMode === "rows") {
    return (
      <div className="space-y-2">
        {Array.from({ length: 6 }, (_, index) => (
          <Card key={`media-task-row-skeleton-${index}`} className="gap-0 py-0">
            <CardContent className="grid gap-3 p-3 md:grid-cols-2 xl:grid-cols-[minmax(10rem,1.3fr)_minmax(8rem,.8fr)_minmax(11rem,1.2fr)_minmax(8rem,.8fr)_minmax(8rem,.8fr)_auto] xl:items-center">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-6 w-full" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>
    )
  }
  return (
    <Card className="overflow-hidden py-0">
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <Table className="min-w-[900px]">
            <TableHeader>
              <TableRow>
                {/* 报告 A1：列可见性 —— 骨架表头与骨架单元格同步包裹 */}
                {isVisible("source") && <TableHead>来源采集任务</TableHead>}
                {isVisible("track") && <TableHead>所属赛道</TableHead>}
                {isVisible("dependency") && <TableHead>依赖关系</TableHead>}
                {isVisible("download") && <TableHead>视频下载</TableHead>}
                {isVisible("subtitle") && <TableHead>字幕处理</TableHead>}
                {isVisible("status") && <TableHead>状态</TableHead>}
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {Array.from({ length: 6 }, (_, index) => (
                <TableRow key={`media-task-skeleton-${index}`}>
                  {isVisible("source") && (
                    <TableCell className="max-w-72">
                      <Skeleton className="h-10 w-full" />
                    </TableCell>
                  )}
                  {isVisible("track") && (
                    <TableCell>
                      <Skeleton className="h-5 w-20" />
                    </TableCell>
                  )}
                  {isVisible("dependency") && (
                    <TableCell className="max-w-64">
                      <Skeleton className="h-4 w-full" />
                    </TableCell>
                  )}
                  {isVisible("download") && (
                    <TableCell className="min-w-44">
                      <Skeleton className="h-12 w-full" />
                    </TableCell>
                  )}
                  {isVisible("subtitle") && (
                    <TableCell className="min-w-44">
                      <Skeleton className="h-12 w-full" />
                    </TableCell>
                  )}
                  {isVisible("status") && (
                    <TableCell>
                      <Skeleton className="h-5 w-16" />
                    </TableCell>
                  )}
                  <TableCell className="text-right">
                    <Skeleton className="ml-auto h-8 w-24" />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

function mediaSourceTitle(task: DouyinMediaTaskPublic) {
  const requestKeywords = task.source_request?.keywords
  if (Array.isArray(requestKeywords) && requestKeywords.length) {
    return requestKeywords.map(String).join("、")
  }
  if (task.source_title?.trim()) return task.source_title.trim()
  if (task.source_creator_names?.length) {
    return `${task.source_creator_names[0]} · 达人作品`
  }
  return "内容采集产出"
}
