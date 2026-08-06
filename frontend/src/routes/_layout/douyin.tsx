import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Clock3, Database, MessageCircle, Search, ThumbsUp } from "lucide-react"

import { type CrawlTaskPublic, DouyinService } from "@/client"
import { CreateTaskDialog } from "@/components/Douyin/CreateTaskDialog"
import {
  activeTaskStatuses,
  TaskStatusBadge,
} from "@/components/Douyin/TaskStatusBadge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

export const Route = createFileRoute("/_layout/douyin")({
  component: DouyinTasks,
  head: () => ({
    meta: [{ title: "抖音任务 - Douyin Crawler" }],
  }),
})

const crawlTypeLabels: Record<CrawlTaskPublic["crawl_type"], string> = {
  search: "关键词搜索",
  detail: "指定作品",
  creator: "创作者作品",
  liked: "账号点赞",
  collected: "账号收藏",
}

function DouyinTasks() {
  const { data, isLoading } = useQuery({
    queryKey: ["douyin-tasks"],
    queryFn: () => DouyinService.listTasks({ skip: 0, limit: 100 }),
    refetchInterval: 3_000,
  })
  const tasks = data?.data ?? []
  const activeCount = tasks.filter((task) =>
    activeTaskStatuses.includes(task.status),
  ).length
  const totals = tasks.reduce(
    (current, task) => ({
      awemes: current.awemes + task.aweme_count,
      comments: current.comments + task.comment_count,
      actions: current.actions + task.action_count,
    }),
    { awemes: 0, comments: 0, actions: 0 },
  )

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">抖音爬取任务</h1>
          <p className="text-muted-foreground">
            通过 CDP 浏览器执行任务，结果写入 PostgreSQL。
          </p>
        </div>
        <CreateTaskDialog />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard icon={Clock3} label="运行中" value={activeCount} />
        <SummaryCard icon={Database} label="作品" value={totals.awemes} />
        <SummaryCard
          icon={MessageCircle}
          label="评论"
          value={totals.comments}
        />
        <SummaryCard icon={ThumbsUp} label="互动记录" value={totals.actions} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>任务记录</CardTitle>
          <CardDescription>
            活跃任务每 3 秒自动刷新，点击任务可查看二维码和抓取结果。
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="py-12 text-center text-muted-foreground">
              加载中…
            </div>
          ) : tasks.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 py-14 text-center">
              <div className="rounded-full bg-muted p-4">
                <Search className="size-8 text-muted-foreground" />
              </div>
              <div>
                <h3 className="font-semibold">还没有抖音任务</h3>
                <p className="text-sm text-muted-foreground">
                  点击右上角“创建任务”开始第一次抓取。
                </p>
              </div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>类型</TableHead>
                    <TableHead>目标</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>作品</TableHead>
                    <TableHead>评论</TableHead>
                    <TableHead>创建时间</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tasks.map((task) => (
                    <TableRow key={task.id}>
                      <TableCell className="font-medium">
                        {crawlTypeLabels[task.crawl_type]}
                      </TableCell>
                      <TableCell className="max-w-64 truncate text-muted-foreground">
                        {taskTarget(task)}
                      </TableCell>
                      <TableCell>
                        <TaskStatusBadge status={task.status} />
                      </TableCell>
                      <TableCell>{task.aweme_count}</TableCell>
                      <TableCell>{task.comment_count}</TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {formatDate(task.created_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button variant="outline" size="sm" asChild>
                          <Link
                            to="/douyin/$taskId"
                            params={{ taskId: task.id }}
                          >
                            查看
                          </Link>
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function SummaryCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Clock3
  label: string
  value: number
}) {
  return (
    <Card className="gap-3 py-5">
      <CardContent className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="text-2xl font-bold">{value}</p>
        </div>
        <div className="rounded-lg bg-primary/10 p-3 text-primary">
          <Icon />
        </div>
      </CardContent>
    </Card>
  )
}

function taskTarget(task: CrawlTaskPublic) {
  const request = task.request
  const candidates = [request.keywords, request.video_ids, request.creator_ids]
  for (const candidate of candidates) {
    if (Array.isArray(candidate) && candidate.length > 0) {
      return candidate.map(String).join("、")
    }
  }
  return task.crawl_type === "liked"
    ? "当前账号点赞"
    : task.crawl_type === "collected"
      ? "当前账号收藏"
      : "-"
}

function formatDate(value: string | null) {
  return value
    ? new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "short",
        timeStyle: "medium",
      }).format(new Date(value))
    : "-"
}
