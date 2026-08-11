import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ArrowRight,
  Clock3,
  Database,
  ListFilter,
  MessageCircle,
  RefreshCw,
  Search,
  Tags,
  ThumbsUp,
  Workflow,
} from "lucide-react"
import { useMemo, useState } from "react"

import {
  type CrawlTaskPublic,
  DouyinKeywordsService,
  DouyinService,
} from "@/client"
import {
  FilterPanel,
  MetricCard,
  PageHero,
  SectionHeading,
} from "@/components/Common/PageShell"
import { CreateTaskDialog } from "@/components/Douyin/CreateTaskDialog"
import {
  activeTaskStatuses,
  TaskStatusBadge,
} from "@/components/Douyin/TaskStatusBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
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
  const [statusFilter, setStatusFilter] = useState<FilterKey>("all")
  const [searchTerm, setSearchTerm] = useState("")
  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ["douyin-tasks"],
    queryFn: () => DouyinService.listTasks({ skip: 0, limit: 100 }),
    refetchInterval: 3_000,
  })
  const tasks = data?.data ?? []
  const activeCount = tasks.filter((task) =>
    activeTaskStatuses.includes(task.status),
  ).length
  const attentionCount = tasks.filter((task) =>
    ["failed", "interrupted", "waiting_login"].includes(task.status),
  ).length
  const totals = tasks.reduce(
    (current, task) => ({
      awemes: current.awemes + task.aweme_count,
      comments: current.comments + task.comment_count,
      actions: current.actions + task.action_count,
    }),
    { awemes: 0, comments: 0, actions: 0 },
  )
  const filteredTasks = useMemo(() => {
    const keyword = searchTerm.trim().toLocaleLowerCase()
    return tasks.filter((task) => {
      const matchesStatus =
        statusFilter === "all" ||
        (statusFilter === "active" &&
          activeTaskStatuses.includes(task.status)) ||
        (statusFilter === "attention" &&
          ["failed", "interrupted", "waiting_login"].includes(task.status)) ||
        (statusFilter === "succeeded" && task.status === "succeeded")
      if (!matchesStatus) return false
      if (!keyword) return true
      return [
        taskTarget(task),
        crawlTypeLabels[task.crawl_type],
        taskBrowserMode(task),
      ].some((value) => value.toLocaleLowerCase().includes(keyword))
    })
  }, [searchTerm, statusFilter, tasks])

  return (
    <div className="page-stack">
      <PageHero
        eyebrow="采集任务中心"
        icon={Workflow}
        title="抖音采集任务"
        description="创建、跟踪并管理通过 CDP 浏览器执行的内容采集任务；异常任务会集中提示，结果自动写入 PostgreSQL。"
        actions={<CreateTaskDialog />}
      >
        <p className="text-xs text-muted-foreground">
          数据每 3 秒自动刷新 · 当前加载 {tasks.length} / {data?.count ?? 0}{" "}
          个任务
        </p>
      </PageHero>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          icon={Clock3}
          label="进行中"
          value={activeCount}
          detail={
            attentionCount ? `${attentionCount} 项需要处理` : "运行状态正常"
          }
          tone={attentionCount ? "coral" : "violet"}
          compact
        />
        <MetricCard
          icon={Database}
          label="已抓作品"
          value={totals.awemes}
          tone="blue"
          compact
        />
        <MetricCard
          icon={MessageCircle}
          label="已存评论"
          value={totals.comments}
          tone="mint"
          compact
        />
        <MetricCard
          icon={ThumbsUp}
          label="互动记录"
          value={totals.actions}
          tone="coral"
          compact
        />
      </div>

      <section className="space-y-4">
        <SectionHeading
          title="任务记录"
          description="按状态或目标快速定位任务，移动端自动切换为卡片视图。"
          action={
            <Button
              variant="outline"
              size="sm"
              disabled={isFetching}
              onClick={() => refetch()}
            >
              <RefreshCw className={cn(isFetching && "animate-spin")} />
              刷新
            </Button>
          }
        />
        <FilterPanel>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
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
                  className="shrink-0"
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
            <label
              htmlFor="task-search"
              className="relative block w-full lg:max-w-sm"
            >
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="task-search"
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                placeholder="搜索任务目标、类型或浏览器…"
                className="h-10 rounded-xl bg-background pl-9"
              />
            </label>
          </div>
        </FilterPanel>

        {isLoading ? (
          <div className="rounded-2xl border bg-card py-16 text-center text-muted-foreground">
            正在加载任务…
          </div>
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
        ) : (
          <>
            <div className="grid gap-3 md:hidden">
              {filteredTasks.map((task) => (
                <TaskMobileCard key={task.id} task={task} />
              ))}
            </div>
            <Card className="hidden overflow-hidden py-0 md:block">
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>类型与目标</TableHead>
                      <TableHead>状态</TableHead>
                      <TableHead>浏览器</TableHead>
                      <TableHead>数据进度</TableHead>
                      <TableHead>创建时间</TableHead>
                      <TableHead className="text-right">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredTasks.map((task) => (
                      <TableRow key={task.id}>
                        <TableCell className="max-w-80">
                          <p className="font-medium">
                            {crawlTypeLabels[task.crawl_type]}
                          </p>
                          <p className="mt-1 truncate text-xs text-muted-foreground">
                            {taskTarget(task)}
                          </p>
                        </TableCell>
                        <TableCell>
                          <TaskStatusBadge status={task.status} />
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {taskBrowserMode(task)}
                        </TableCell>
                        <TableCell>
                          <p className="text-sm">
                            {task.aweme_count} 作品 · {task.comment_count} 评论
                          </p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {task.action_count} 条互动
                          </p>
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                          {formatDate(task.created_at)}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex min-w-max justify-end gap-1">
                            {task.crawl_type === "search" && (
                              <SyncTaskKeywordsButton taskId={task.id} />
                            )}
                            <Button variant="outline" size="sm" asChild>
                              <Link
                                to="/douyin/$taskId"
                                params={{ taskId: task.id }}
                              >
                                查看
                                <ArrowRight />
                              </Link>
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </>
        )}
      </section>
    </div>
  )
}

function TaskMobileCard({ task }: { task: CrawlTaskPublic }) {
  return (
    <Card className="gap-4 p-4 py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold">
            {crawlTypeLabels[task.crawl_type]}
          </p>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {taskTarget(task)}
          </p>
        </div>
        <TaskStatusBadge status={task.status} />
      </div>
      <div className="grid grid-cols-3 gap-2 rounded-xl bg-muted/55 p-3 text-center">
        <MobileMetric label="作品" value={task.aweme_count} />
        <MobileMetric label="评论" value={task.comment_count} />
        <MobileMetric label="互动" value={task.action_count} />
      </div>
      <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
        <span>{taskBrowserMode(task)}</span>
        <span>{formatDate(task.created_at)}</span>
      </div>
      <div className="flex gap-2">
        {task.crawl_type === "search" && (
          <SyncTaskKeywordsButton taskId={task.id} />
        )}
        <Button variant="outline" size="sm" className="ml-auto" asChild>
          <Link to="/douyin/$taskId" params={{ taskId: task.id }}>
            查看详情
            <ArrowRight />
          </Link>
        </Button>
      </div>
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

function SyncTaskKeywordsButton({ taskId }: { taskId: string }) {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const mutation = useMutation({
    mutationFn: () => DouyinKeywordsService.syncKeywordsFromTask({ taskId }),
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
    <Button
      variant="ghost"
      size="sm"
      disabled={mutation.isPending}
      onClick={() => mutation.mutate()}
    >
      <Tags />
      同步关键词
    </Button>
  )
}

function taskTarget(task: CrawlTaskPublic) {
  const candidates = [
    task.request.keywords,
    task.request.video_ids,
    task.request.creator_ids,
  ]
  for (const candidate of candidates) {
    if (Array.isArray(candidate) && candidate.length > 0)
      return candidate.map(String).join("、")
  }
  return task.crawl_type === "liked"
    ? "当前账号点赞"
    : task.crawl_type === "collected"
      ? "当前账号收藏"
      : "未填写目标"
}

function taskBrowserMode(task: CrawlTaskPublic) {
  const mode = task.request.browser_mode
  if (mode === "remote") return "远程 Docker"
  if (mode === "local") return "本机浏览器"
  return "服务默认"
}

function formatDate(value: string | null) {
  return value
    ? new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "short",
        timeStyle: "short",
      }).format(new Date(value))
    : "-"
}
