import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ArrowRight,
  Database,
  MessageCircle,
  Music2,
  PlaySquare,
  ShieldCheck,
} from "lucide-react"

import { DouyinAccountsService, DouyinService } from "@/client"
import { TaskStatusBadge } from "@/components/Douyin/TaskStatusBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import useAuth from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({ meta: [{ title: "运营工作台 - Douyin Crawler" }] }),
})

function Dashboard() {
  const { user } = useAuth()
  const tasks = useQuery({
    queryKey: ["douyin-tasks", "dashboard"],
    queryFn: () => DouyinService.listTasks({ limit: 8 }),
    refetchInterval: 5_000,
  })
  const accounts = useQuery({
    queryKey: ["douyin-accounts"],
    queryFn: () => DouyinAccountsService.listAccounts({ limit: 100 }),
  })
  const rows = tasks.data?.data ?? []
  const accountRows = accounts.data?.data ?? []
  const total = rows.reduce(
    (sum, task) => ({
      works: sum.works + task.aweme_count,
      comments: sum.comments + task.comment_count,
    }),
    { works: 0, comments: 0 },
  )
  return (
    <div className="space-y-6">
      <section className="relative overflow-hidden rounded-3xl border bg-card p-6 shadow-sm md:p-9">
        <div className="absolute -right-16 -top-24 size-72 rounded-full bg-primary/15 blur-3xl" />
        <div className="relative max-w-3xl">
          <p className="text-sm font-medium text-primary">
            Content intelligence workspace
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight md:text-4xl">
            你好，{user?.full_name || user?.email}
          </h1>
          <p className="mt-3 max-w-2xl text-muted-foreground">
            在一个工作台里管理 CDP
            账号、抖音爬取、视频存储、远程字幕处理和可恢复任务。
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Button asChild>
              <Link to="/douyin">
                进入任务中心
                <ArrowRight />
              </Link>
            </Button>
            <Button variant="outline" asChild>
              <Link to="/douyin-accounts">
                <ShieldCheck />
                管理账号池
              </Link>
            </Button>
          </div>
        </div>
      </section>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Metric icon={Music2} label="最近任务" value={rows.length} />
        <Metric icon={Database} label="已抓作品" value={total.works} />
        <Metric icon={MessageCircle} label="已存评论" value={total.comments} />
        <Metric
          icon={ShieldCheck}
          label="可用账号"
          value={accountRows.filter((item) => item.status === "ready").length}
        />
      </div>
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle>最近任务</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              状态与数据进度实时更新
            </p>
          </div>
          <Button variant="ghost" asChild>
            <Link to="/douyin">
              查看全部
              <ArrowRight />
            </Link>
          </Button>
        </CardHeader>
        <CardContent className="grid gap-3 lg:grid-cols-2">
          {rows.length ? (
            rows.slice(0, 6).map((task) => (
              <Link
                key={task.id}
                to="/douyin/$taskId"
                params={{ taskId: task.id }}
                className="group flex items-center gap-4 rounded-2xl border bg-muted/15 p-4 transition hover:border-primary/40 hover:bg-primary/5"
              >
                <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <PlaySquare />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="truncate font-medium">
                      {taskTarget(task.request)}
                    </p>
                    <TaskStatusBadge status={task.status} />
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    作品 {task.aweme_count} · 评论 {task.comment_count} ·{" "}
                    {formatDate(task.created_at)}
                  </p>
                </div>
                <ArrowRight className="size-4 text-muted-foreground transition group-hover:translate-x-1 group-hover:text-primary" />
              </Link>
            ))
          ) : (
            <p className="py-12 text-center text-sm text-muted-foreground lg:col-span-2">
              暂无任务，前往任务中心创建第一个任务。
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function Metric({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Music2
  label: string
  value: number
}) {
  return (
    <Card>
      <CardContent className="flex items-center justify-between p-5">
        <div>
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="mt-1 text-3xl font-semibold">{value}</p>
        </div>
        <span className="rounded-2xl bg-primary/10 p-3 text-primary">
          <Icon />
        </span>
      </CardContent>
    </Card>
  )
}
function taskTarget(request: Record<string, unknown>) {
  for (const value of [
    request.keywords,
    request.video_ids,
    request.creator_ids,
  ]) {
    if (Array.isArray(value) && value.length)
      return value.map(String).join("、")
  }
  return "账号内容任务"
}
function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value))
}
