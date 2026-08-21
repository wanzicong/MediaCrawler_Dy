import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  AlertTriangle,
  ArrowRight,
  Captions,
  CheckCircle2,
  Clock3,
  Download,
  Film,
  Link2,
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
import {
  FilterPanel,
  MetricCard,
  SectionHeading,
} from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import {
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"

type MediaFilter = "all" | "active" | "ready" | "attention" | "completed"

const mediaFilters: Array<{ key: MediaFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "active", label: "处理中" },
  { key: "ready", label: "可创建" },
  { key: "attention", label: "需处理" },
  { key: "completed", label: "已完成" },
]

const mediaStatusCopy: Record<
  DouyinMediaTaskStatus,
  { label: string; className: string }
> = {
  waiting_source: {
    label: "等待采集",
    className:
      "border-amber-300 bg-amber-50 text-amber-800 dark:bg-amber-950/35 dark:text-amber-200",
  },
  ready: {
    label: "可创建",
    className:
      "border-sky-300 bg-sky-50 text-sky-800 dark:bg-sky-950/35 dark:text-sky-200",
  },
  queued: {
    label: "排队中",
    className:
      "border-violet-300 bg-violet-50 text-violet-800 dark:bg-violet-950/35 dark:text-violet-200",
  },
  running: {
    label: "处理中",
    className:
      "border-blue-300 bg-blue-50 text-blue-800 dark:bg-blue-950/35 dark:text-blue-200",
  },
  attention: {
    label: "需处理",
    className:
      "border-red-300 bg-red-50 text-red-800 dark:bg-red-950/35 dark:text-red-200",
  },
  completed: {
    label: "已完成",
    className:
      "border-emerald-300 bg-emerald-50 text-emerald-800 dark:bg-emerald-950/35 dark:text-emerald-200",
  },
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
  const query = useQuery({
    queryKey: ["douyin-media-tasks", trackId],
    queryFn: () =>
      DouyinService.listMediaTasks({
        trackId: trackId === allTracksValue ? undefined : trackId,
        skip: 0,
        limit: 100,
      }),
    retry: false,
    refetchInterval: 3_000,
  })
  const tasks = query.data?.data ?? []
  const counts = tasks.reduce(
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
    }),
    { active: 0, ready: 0, attention: 0, downloaded: 0 },
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

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          icon={LoaderCircle}
          label="处理中"
          value={query.isError ? "—" : counts.active}
          detail="下载与字幕队列"
          tone="violet"
          compact
        />
        <MetricCard
          icon={Link2}
          label="可创建"
          value={query.isError ? "—" : counts.ready}
          detail="来源采集已完成"
          tone="blue"
          compact
        />
        <MetricCard
          icon={AlertTriangle}
          label="需要处理"
          value={query.isError ? "—" : counts.attention}
          detail="等待依赖或存在失败"
          tone="coral"
          compact
        />
        <MetricCard
          icon={Download}
          label="已下载视频"
          value={query.isError ? "—" : counts.downloaded}
          detail="跨来源任务汇总"
          tone="mint"
          compact
        />
      </div>

      <section className="space-y-4">
        <SectionHeading
          title="下载与字幕任务"
          description="每个处理任务都关联一个来源采集任务；采集完成后才能创建，处理数量不会超过来源产出。"
          action={
            <Button
              variant="outline"
              size="sm"
              disabled={query.isFetching}
              onClick={() => void query.refetch()}
            >
              <RefreshCw className={cn(query.isFetching && "animate-spin")} />
              刷新
            </Button>
          }
        />
        <FilterPanel>
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
                </Button>
              ))}
            </fieldset>
            <div className="flex w-full flex-col gap-2 sm:flex-row lg:max-w-2xl">
              <TrackSelect
                value={trackId}
                onValueChange={onTrackChange}
                includeAll
                allowDisabled
                className="h-10 bg-background sm:w-52"
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
                  className="h-10 rounded-xl bg-background pl-9"
                />
              </label>
            </div>
          </div>
        </FilterPanel>
        <div className="flex justify-end">
          <ViewModeToggle
            value={viewMode}
            onChange={setViewMode}
            label="切换媒体任务展示方式"
          />
        </div>

        {query.isLoading ? (
          <MediaEmpty message="正在加载下载与字幕任务…" />
        ) : query.isError ? (
          <QueryErrorState
            title="媒体任务读取失败"
            description="暂时无法读取下载与字幕任务，请检查服务连接后重试。"
            onRetry={() => void query.refetch()}
            retrying={query.isFetching}
          />
        ) : tasks.length === 0 ? (
          <MediaEmpty message="还没有可关联的采集任务。先完成一次内容采集，再回来创建下载任务。" />
        ) : filtered.length === 0 ? (
          <MediaEmpty message="没有匹配的媒体任务，请调整状态、赛道或搜索条件。" />
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
          <MediaTaskTable tasks={filtered} />
        )}
      </section>
    </div>
  )
}

function MediaTaskTable({ tasks }: { tasks: DouyinMediaTaskPublic[] }) {
  return (
    <Card className="overflow-hidden py-0">
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>来源采集任务</TableHead>
                <TableHead>所属赛道</TableHead>
                <TableHead>依赖关系</TableHead>
                <TableHead>视频下载</TableHead>
                <TableHead>字幕处理</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tasks.map((task) => (
                <TableRow key={task.source_task_id}>
                  <TableCell className="max-w-72">
                    <MediaSourceIdentity task={task} />
                  </TableCell>
                  <TableCell>
                    <TrackBadge
                      trackId={task.track_id}
                      trackName={task.track_name}
                      isDefault={task.track_is_default}
                    />
                  </TableCell>
                  <TableCell className="max-w-64">
                    <DependencyState task={task} />
                  </TableCell>
                  <TableCell className="min-w-44">
                    <MediaProgress task={task} kind="download" />
                  </TableCell>
                  <TableCell className="min-w-44">
                    <MediaProgress task={task} kind="subtitle" />
                  </TableCell>
                  <TableCell>
                    <MediaStatusBadge status={task.status} />
                  </TableCell>
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
        {formatDate(task.created_at)}
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
      {task.dependency_ready ? (
        <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" />
      ) : (
        <Clock3 className="mt-0.5 size-4 shrink-0 text-amber-600" />
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
    kind === "download" ? summary.downloaded : summary.subtitle_completed
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
      <p className="text-[11px] text-muted-foreground">
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
  const copy = mediaStatusCopy[status]
  return (
    <Badge variant="outline" className={copy.className}>
      {copy.label}
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

function MediaEmpty({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed bg-card/60 px-6 py-16 text-center">
      <div className="rounded-2xl bg-primary/10 p-4 text-primary">
        <Film className="size-7" />
      </div>
      <p className="max-w-xl text-sm text-muted-foreground">{message}</p>
    </div>
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

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value))
}
