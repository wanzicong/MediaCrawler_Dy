import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ArrowRight,
  Download,
  ListFilter,
  MoreHorizontal,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  Tags,
  Trash2,
} from "lucide-react"
import { useMemo, useState } from "react"

import {
  type CrawlTaskPublic,
  DouyinKeywordsService,
  DouyinService,
} from "@/client"
import { FilterPanel, PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import {
  usePersistentViewMode,
  ViewModeToggle,
} from "@/components/Common/ViewModeToggle"
import { CreateTaskDialog } from "@/components/Douyin/CreateTaskDialog"
import { MediaTaskManagement } from "@/components/Douyin/MediaTaskManagement"
import { TaskListProgress } from "@/components/Douyin/TaskExecutionProgress"
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
} from "@/components/Douyin/TrackSelect"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useCustomToast from "@/hooks/useCustomToast"
import { cn } from "@/lib/utils"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/douyin")({
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

function DouyinTasks() {
  const [businessTab, setBusinessTab] = useState<"crawl" | "media">("crawl")
  const [statusFilter, setStatusFilter] = useState<FilterKey>("all")
  const [searchTerm, setSearchTerm] = useState("")
  const [trackId, setTrackId] = useState(allTracksValue)
  const [viewMode, changeViewMode] = usePersistentViewMode("douyin-tasks-view")
  const [selectedTaskIds, setSelectedTaskIds] = useState<Set<string>>(
    () => new Set(),
  )
  const { data, isLoading, isFetching, isError, refetch } = useQuery({
    queryKey: ["douyin-tasks", trackId],
    queryFn: () =>
      DouyinService.listTasks({
        trackId: trackId && trackId !== allTracksValue ? trackId : undefined,
        skip: 0,
        limit: 100,
      }),
    retry: false,
    refetchInterval: 3_000,
  })
  const tasks = data?.data ?? []
  const attentionCount = tasks.filter((task) =>
    ["failed", "cancelled", "interrupted", "waiting_login"].includes(
      task.status,
    ),
  ).length
  const filteredTasks = useMemo(() => {
    const keyword = searchTerm.trim().toLocaleLowerCase()
    return tasks.filter((task) => {
      const matchesStatus =
        statusFilter === "all" ||
        (statusFilter === "active" &&
          activeTaskStatuses.includes(task.status)) ||
        (statusFilter === "attention" &&
          ["failed", "cancelled", "interrupted", "waiting_login"].includes(
            task.status,
          )) ||
        (statusFilter === "succeeded" && task.status === "succeeded")
      if (!matchesStatus) return false
      if (!keyword) return true
      return [
        ...getTaskSearchValues(task),
        crawlTypeLabels[task.crawl_type],
        taskBrowserMode(task),
      ].some((value) => value.toLocaleLowerCase().includes(keyword))
    })
  }, [searchTerm, statusFilter, tasks])
  const selectableTasks = filteredTasks.filter(isDeletableTask)
  const allSelectableTasksSelected =
    selectableTasks.length > 0 &&
    selectableTasks.every((task) => selectedTaskIds.has(task.id))

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
                  <span className="text-xs tabular-nums">
                    {data?.count ?? tasks.length}
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
                  <ListFilter className="mr-1 size-4 shrink-0 text-muted-foreground" />
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
                    onValueChange={(value) => {
                      setTrackId(value)
                      setSelectedTaskIds(new Set())
                    }}
                    includeAll
                    allowDisabled
                    className="h-9 bg-background sm:w-48"
                    ariaLabel="按赛道筛选任务"
                  />
                  <label
                    htmlFor="task-search"
                    className="relative block min-w-48 flex-1 xl:max-w-sm"
                  >
                    <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      id="task-search"
                      value={searchTerm}
                      onChange={(event) => setSearchTerm(event.target.value)}
                      placeholder="搜索任务目标、类型或浏览器…"
                      className="h-9 rounded-xl bg-background pl-9"
                    />
                  </label>
                  <div className="flex shrink-0 items-center gap-2">
                    <BulkResumeButton tasks={filteredTasks} />
                    <BulkDeleteButton
                      selectedTaskIds={selectedTaskIds}
                      onDeleted={() => setSelectedTaskIds(new Set())}
                    />
                    <Button
                      variant="outline"
                      size="icon-sm"
                      disabled={isFetching}
                      aria-label="刷新任务"
                      onClick={() => refetch()}
                    >
                      <RefreshCw className={cn(isFetching && "animate-spin")} />
                    </Button>
                    <ViewModeToggle
                      value={viewMode}
                      onChange={changeViewMode}
                      label="切换任务展示方式"
                    />
                  </div>
                </div>
              </div>
            </FilterPanel>

            {isLoading ? (
              <div className="rounded-2xl border bg-card py-16 text-center text-muted-foreground">
                正在加载任务…
              </div>
            ) : isError ? (
              <QueryErrorState
                title="任务列表读取失败"
                description="暂时无法获取任务数据，请检查服务连接后重试。"
                onRetry={() => void refetch()}
                retrying={isFetching}
              />
            ) : tasks.length === 0 ? (
              <EmptyState
                title="还没有抖音任务"
                description="点击上方“创建任务”开始第一次抓取。"
              />
            ) : filteredTasks.length === 0 ? (
              <EmptyState
                title="没有匹配的任务"
                description="试试切换状态或清空搜索条件。"
              />
            ) : viewMode === "cards" ? (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {filteredTasks.map((task) => (
                  <TaskMobileCard
                    key={task.id}
                    task={task}
                    selected={selectedTaskIds.has(task.id)}
                    onSelectedChange={(checked) =>
                      toggleTaskSelection(task.id, checked)
                    }
                  />
                ))}
              </div>
            ) : viewMode === "rows" ? (
              <div className="space-y-2">
                {filteredTasks.map((task) => (
                  <TaskCompactRow
                    key={task.id}
                    task={task}
                    selected={selectedTaskIds.has(task.id)}
                    onSelectedChange={(checked) =>
                      toggleTaskSelection(task.id, checked)
                    }
                  />
                ))}
              </div>
            ) : (
              <Card className="overflow-hidden py-0">
                <CardContent className="p-0">
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
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
                                aria-label="全选可删除任务"
                                onCheckedChange={(value) =>
                                  toggleAllSelectableTasks(value === true)
                                }
                              />
                              所属赛道
                            </div>
                          </TableHead>
                          <TableHead>任务目标</TableHead>
                          <TableHead>状态</TableHead>
                          <TableHead>账号</TableHead>
                          <TableHead>数据进度</TableHead>
                          <TableHead>创建时间</TableHead>
                          <TableHead className="text-right">操作</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {filteredTasks.map((task) => (
                          <TableRow key={task.id}>
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
                              </div>
                            </TableCell>
                            <TableCell className="max-w-80">
                              <TaskIdentity task={task} />
                            </TableCell>
                            <TableCell>
                              <TaskStatusBadge status={task.status} />
                            </TableCell>
                            <TableCell className="whitespace-nowrap text-sm">
                              <TaskAccount task={task} />
                            </TableCell>
                            <TableCell>
                              <TaskListProgress task={task} />
                            </TableCell>
                            <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                              {formatDate(task.created_at)}
                            </TableCell>
                            <TableCell className="text-right">
                              <TaskActions task={task} />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </CardContent>
              </Card>
            )}
          </section>
        </TabsContent>

        <TabsContent value="media" className="mt-0">
          <MediaTaskManagement trackId={trackId} onTrackChange={setTrackId} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function TaskMobileCard({
  task,
  selected,
  onSelectedChange,
}: {
  task: CrawlTaskPublic
  selected: boolean
  onSelectedChange: (checked: boolean) => void
}) {
  return (
    <Card className="gap-4 p-4 py-4">
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
        <span>{formatDate(task.created_at)}</span>
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
}: {
  task: CrawlTaskPublic
  selected: boolean
  onSelectedChange: (checked: boolean) => void
}) {
  return (
    <Card className="gap-0 py-0">
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
        <span className="whitespace-nowrap text-xs text-muted-foreground">
          {formatDate(task.created_at)}
        </span>
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

function EmptyState({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed bg-card/60 py-16 text-center">
      <div className="rounded-2xl bg-primary/10 p-4 text-primary">
        <Search className="size-7" />
      </div>
      <div>
        <h3 className="font-semibold">{title}</h3>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
    </div>
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
            onSelect={() => {
              if (
                window.confirm("确认从头重启？已保存的数据保留，但断点会清空。")
              )
                restart.mutate()
            }}
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
      aria-label={`选择删除任务 ${task.display_title || task.id}`}
      onCheckedChange={(value) => onSelectedChange(value === true)}
    />
  )
}

/** 可重启的任务状态：失败或异常中断（活动任务与成功任务不可重启）。 */
const restartableTaskStatuses = ["failed", "interrupted"]

function BulkResumeButton({ tasks }: { tasks: CrawlTaskPublic[] }) {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const resumable = tasks.filter(
    (task) =>
      restartableTaskStatuses.includes(task.status) &&
      (task.can_resume_crawl || task.can_resume_media),
  )
  const mutation = useMutation({
    mutationFn: async () => {
      let succeeded = 0
      for (const task of resumable) {
        try {
          await DouyinService.resumeTask({ taskId: task.id, requestBody: {} })
          succeeded += 1
        } catch {
          // 单个任务失败不阻断其余任务，最终统一反馈成功/失败数量。
        }
      }
      return succeeded
    },
    onSuccess: async (succeeded) => {
      showSuccessToast(
        `已恢复 ${succeeded} 个任务${succeeded < resumable.length ? `，${resumable.length - succeeded} 个恢复失败` : ""}`,
      )
      await queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] })
    },
    onError: handleError.bind(showErrorToast),
  })
  return (
    resumable.length > 0 && (
      <Button
        variant="outline"
        size="sm"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        <Play />
        {mutation.isPending
          ? "正在恢复…"
          : `一键断点续爬（${resumable.length}）`}
      </Button>
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
      onClick={() => {
        if (
          window.confirm(
            `确认删除选中的 ${selectedCount} 条失效任务？任务关联的作品、评论、互动记录也会一并删除，且无法恢复。`,
          )
        ) {
          mutation.mutate()
        }
      }}
    >
      <Trash2 />
      {mutation.isPending
        ? "正在删除…"
        : `删除选中${selectedCount ? `（${selectedCount}）` : ""}`}
    </Button>
  )
}

function formatDate(value: string | null) {
  return value
    ? new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "short",
        timeStyle: "short",
      }).format(new Date(value))
    : "-"
}
