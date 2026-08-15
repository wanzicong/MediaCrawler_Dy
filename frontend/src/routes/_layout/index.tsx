import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  AlertTriangle,
  ArrowRight,
  Database,
  MessageCircle,
  Music2,
  PlaySquare,
  ShieldCheck,
  Sparkles,
} from "lucide-react"

import { DouyinAccountsService, DouyinService } from "@/client"
import {
  MetricCard,
  PageHero,
  SectionHeading,
} from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { TaskIdentity } from "@/components/Douyin/TaskIdentity"
import {
  activeTaskStatuses,
  TaskStatusBadge,
} from "@/components/Douyin/TaskStatusBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import useAuth from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({ meta: [{ title: "运营工作台 - 灵感采集台" }] }),
})

function Dashboard() {
  const { user } = useAuth()
  const tasks = useQuery({
    queryKey: ["douyin-tasks", "dashboard"],
    queryFn: () => DouyinService.listTasks({ limit: 100 }),
    retry: false,
    refetchInterval: 5_000,
  })
  const accounts = useQuery({
    queryKey: ["douyin-accounts"],
    queryFn: () => DouyinAccountsService.listAccounts({ limit: 100 }),
    retry: false,
  })
  const rows = tasks.data?.data ?? []
  const accountRows = accounts.data?.data ?? []
  const activeCount = rows.filter((task) =>
    activeTaskStatuses.includes(task.status),
  ).length
  const attentionCount = rows.filter((task) =>
    ["failed", "interrupted", "waiting_login"].includes(task.status),
  ).length
  const total = rows.reduce(
    (sum, task) => ({
      works: sum.works + task.aweme_count,
      comments: sum.comments + task.comment_count,
    }),
    { works: 0, comments: 0 },
  )
  const readyAccounts = accountRows.filter(
    (item) => item.status === "ready",
  ).length
  const dataScope =
    (tasks.data?.count ?? 0) > rows.length ? "近 100 个任务" : "全部任务"

  return (
    <div className="page-stack">
      <PageHero
        eyebrow="今日运营概览"
        icon={Sparkles}
        title={
          user?.full_name?.trim()
            ? `你好，${user.full_name.trim()}`
            : "欢迎回来"
        }
        description="从任务调度、账号可用性到内容沉淀，一眼掌握当前运营状态；需要处理的异常会优先浮到前面。"
        actions={
          <>
            <Button variant="brand" asChild>
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
          </>
        }
      >
        <div className="flex flex-wrap gap-2 text-xs">
          <StatusPill
            tone={tasks.isError ? "amber" : "blue"}
            label={
              tasks.isError ? "任务状态读取失败" : `${activeCount} 个任务进行中`
            }
          />
          <StatusPill
            tone={tasks.isError || attentionCount ? "amber" : "green"}
            label={
              tasks.isError
                ? "无法判断任务异常"
                : attentionCount
                  ? `${attentionCount} 项需要关注`
                  : "暂无待处理异常"
            }
          />
          <StatusPill
            tone={accounts.isError ? "amber" : "violet"}
            label={
              accounts.isError
                ? "账号状态读取失败"
                : `${readyAccounts} 个账号可用`
            }
          />
        </div>
      </PageHero>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          icon={Music2}
          label="任务总数"
          value={tasks.isError ? "—" : (tasks.data?.count ?? rows.length)}
          detail={
            tasks.isError ? "任务数据读取失败" : `${activeCount} 个正在执行`
          }
          tone="violet"
        />
        <MetricCard
          icon={Database}
          label={`${dataScope}作品`}
          value={tasks.isError ? "—" : total.works}
          detail="已入库内容"
          tone="blue"
        />
        <MetricCard
          icon={MessageCircle}
          label={`${dataScope}评论`}
          value={tasks.isError ? "—" : total.comments}
          detail="可用于洞察分析"
          tone="mint"
        />
        <MetricCard
          icon={ShieldCheck}
          label="可用账号"
          value={accounts.isError ? "—" : readyAccounts}
          detail={
            accounts.isError
              ? "账号数据读取失败"
              : `账号池共 ${accountRows.length} 个`
          }
          tone={readyAccounts ? "coral" : "rose"}
        />
      </div>

      {accounts.isError && (
        <QueryErrorState
          title="账号状态读取失败"
          description="工作台暂时无法获取账号可用性，请检查服务连接后重试。"
          onRetry={() => void accounts.refetch()}
          retrying={accounts.isFetching}
          className="py-6"
        />
      )}

      {attentionCount > 0 && (
        <Card className="border-amber-200/80 bg-amber-50/70 py-0 dark:border-amber-900/70 dark:bg-amber-950/30">
          <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <span className="rounded-xl bg-amber-500/15 p-2.5 text-amber-700 dark:text-amber-300">
                <AlertTriangle className="size-5" />
              </span>
              <div>
                <p className="font-semibold">
                  有 {attentionCount} 项任务需要处理
                </p>
                <p className="mt-0.5 text-sm text-muted-foreground">
                  包括等待扫码、失败或中断的任务，建议优先检查。
                </p>
              </div>
            </div>
            <Button variant="outline" asChild>
              <Link to="/douyin">立即查看</Link>
            </Button>
          </CardContent>
        </Card>
      )}

      <section className="space-y-4">
        <SectionHeading
          title="最近任务"
          description="状态与数据进度每 5 秒自动刷新"
          action={
            <Button variant="ghost" asChild>
              <Link to="/douyin">
                查看全部
                <ArrowRight />
              </Link>
            </Button>
          }
        />
        <div className="grid gap-3 lg:grid-cols-2">
          {tasks.isError ? (
            <QueryErrorState
              title="最近任务读取失败"
              description="暂时无法获取任务状态，请检查服务连接后重试。"
              onRetry={() => void tasks.refetch()}
              retrying={tasks.isFetching}
              className="lg:col-span-2"
            />
          ) : rows.length ? (
            rows.slice(0, 6).map((task) => (
              <Link
                key={task.id}
                to="/douyin/$taskId"
                params={{ taskId: task.id }}
                className="group flex min-w-0 items-center gap-4 rounded-2xl border bg-card p-4 shadow-[0_12px_32px_-28px_oklch(0.45_0.16_285/0.45)] transition hover:-translate-y-0.5 hover:border-primary/30 hover:bg-primary/[0.025] motion-reduce:transform-none"
              >
                <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <PlaySquare className="size-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 items-start gap-2">
                    <TaskIdentity
                      task={task}
                      showCreatedAt
                      className="min-w-0 flex-1"
                    />
                    <TaskStatusBadge status={task.status} />
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    作品 {task.aweme_count} · 评论 {task.comment_count}
                  </p>
                </div>
                <ArrowRight className="size-4 shrink-0 text-muted-foreground transition group-hover:translate-x-1 group-hover:text-primary motion-reduce:transform-none" />
              </Link>
            ))
          ) : (
            <div className="rounded-2xl border border-dashed bg-card/60 py-14 text-center text-sm text-muted-foreground lg:col-span-2">
              暂无任务，前往任务中心创建第一个任务。
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

function StatusPill({
  tone,
  label,
}: {
  tone: "blue" | "green" | "amber" | "violet"
  label: string
}) {
  const styles = {
    blue: "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-950/50 dark:text-blue-300",
    green:
      "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-300",
    amber:
      "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-300",
    violet:
      "border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-900 dark:bg-violet-950/50 dark:text-violet-300",
  }
  return (
    <span
      className={`rounded-full border px-3 py-1.5 font-medium ${styles[tone]}`}
    >
      {label}
    </span>
  )
}
