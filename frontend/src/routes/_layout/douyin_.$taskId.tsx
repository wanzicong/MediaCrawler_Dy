import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  Outlet,
  useRouterState,
} from "@tanstack/react-router"
import {
  ArrowLeft,
  Ban,
  Clock3,
  Database,
  MessageCircle,
  RefreshCw,
  RotateCcw,
  ThumbsUp,
} from "lucide-react"
import { useEffect, useState } from "react"

import { type CrawlTaskPublic, DouyinService, OpenAPI } from "@/client"
import { ResumeTaskDialog } from "@/components/Douyin/ResumeTaskDialog"
import { TaskInteractionsPanel } from "@/components/Douyin/TaskInteractionsPanel"
import {
  activeTaskStatuses,
  TaskStatusBadge,
} from "@/components/Douyin/TaskStatusBadge"
import { UnifiedWorksPanel } from "@/components/Douyin/UnifiedWorksPanel"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/douyin_/$taskId")({
  component: DouyinTaskDetail,
  head: () => ({ meta: [{ title: "任务详情 - Douyin Crawler" }] }),
})

const crawlTypeLabels: Record<CrawlTaskPublic["crawl_type"], string> = {
  search: "关键词搜索",
  detail: "指定作品",
  creator: "创作者作品",
  creator_from_aweme: "视频作者作品",
  liked: "账号点赞",
  collected: "账号收藏",
}

function DouyinTaskDetail() {
  const { taskId } = Route.useParams()
  const feedRouteActive = useRouterState({
    select: (state) => state.location.pathname.endsWith("/feed"),
  })
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const taskQuery = useQuery({
    queryKey: ["douyin-task", taskId],
    queryFn: () => DouyinService.getTask({ taskId }),
    refetchInterval: (query) =>
      query.state.data && activeTaskStatuses.includes(query.state.data.status)
        ? 2_000
        : false,
  })
  const cancelMutation = useMutation({
    mutationFn: () => DouyinService.cancelTask({ taskId }),
    onSuccess: async () => {
      showSuccessToast("取消请求已提交")
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["douyin-task", taskId] }),
        queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] }),
      ])
    },
    onError: handleError.bind(showErrorToast),
  })

  if (feedRouteActive) return <Outlet />

  if (taskQuery.isLoading) {
    return (
      <div className="py-16 text-center text-muted-foreground">
        加载任务详情…
      </div>
    )
  }
  if (taskQuery.isError || !taskQuery.data) {
    return (
      <Alert variant="destructive">
        <Ban />
        <AlertTitle>无法读取任务</AlertTitle>
        <AlertDescription>任务不存在，或当前账号无权访问。</AlertDescription>
      </Alert>
    )
  }

  const task = taskQuery.data
  const active = activeTaskStatuses.includes(task.status)

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <Button variant="ghost" size="sm" className="-ml-3" asChild>
            <Link to="/douyin">
              <ArrowLeft />
              返回任务列表
            </Link>
          </Button>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight">
              {crawlTypeLabels[task.crawl_type]}
            </h1>
            <TaskStatusBadge status={task.status} />
          </div>
          <p className="font-mono text-xs text-muted-foreground">{task.id}</p>
          {task.resume_count > 0 && (
            <p className="text-xs text-muted-foreground">
              已恢复 {task.resume_count} 次 · 当前阶段：
              {currentStageLabel(task)}
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => taskQuery.refetch()}
            disabled={taskQuery.isFetching}
          >
            <RefreshCw className={taskQuery.isFetching ? "animate-spin" : ""} />
            刷新
          </Button>
          {!active && (task.can_resume_crawl || task.can_resume_media) && (
            <ResumeTaskDialog task={task} />
          )}
          {active && (
            <Button
              variant="destructive"
              onClick={() => cancelMutation.mutate()}
              disabled={
                cancelMutation.isPending || task.status === "cancelling"
              }
            >
              <Ban />
              取消任务
            </Button>
          )}
        </div>
      </div>

      {task.error && (
        <Alert variant="destructive">
          <Ban />
          <AlertTitle>任务执行失败</AlertTitle>
          <AlertDescription className="break-all">
            {task.error}
          </AlertDescription>
        </Alert>
      )}

      {task.status === "waiting_login" && (
        <TaskQrCode taskId={task.id} available={task.has_qrcode} />
      )}

      {active && task.resume_count > 0 && (
        <Alert className="border-cyan-500/40 bg-cyan-500/5">
          <RotateCcw className="animate-spin text-cyan-600 [animation-duration:3s]" />
          <AlertTitle>第 {task.resume_count} 次恢复正在执行</AlertTitle>
          <AlertDescription>
            后端已于 {formatDate(task.last_resumed_at)} 接受恢复请求，当前阶段为
            {currentStageLabel(task)}。页面会自动刷新，无需重复点击继续任务。
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard icon={Database} label="作品" value={task.aweme_count} />
        <MetricCard
          icon={MessageCircle}
          label="评论"
          value={task.comment_count}
        />
        <MetricCard
          icon={ThumbsUp}
          label="互动记录"
          value={task.action_count}
        />
        <MetricCard
          icon={Clock3}
          label="创建时间"
          value={formatDate(task.created_at)}
          compact
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>任务配置</CardTitle>
          <CardDescription>Cookie 等敏感字段不会出现在这里。</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
            {Object.entries(task.request).map(([key, value]) => (
              <div key={key} className="rounded-lg bg-muted/50 p-3">
                <dt className="text-xs text-muted-foreground">{key}</dt>
                <dd className="mt-1 break-words font-medium">
                  {formatConfigValue(value)}
                </dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      <TaskShards taskId={task.id} active={active} />

      <UnifiedWorksPanel task={task} active={active} />

      <TaskInteractionsPanel taskId={task.id} />
    </div>
  )
}

function TaskShards({ taskId, active }: { taskId: string; active: boolean }) {
  const shards = useQuery({
    queryKey: ["douyin-task-shards", taskId],
    queryFn: () => DouyinService.listTaskShards({ taskId }),
    refetchInterval: active ? 2_000 : false,
  })
  if (!shards.data?.count) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle>账号并行分片</CardTitle>
        <CardDescription>
          每个分片使用独立 CDP Profile；任一分片失败均可在修复账号后继续任务。
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {shards.data.data.map((shard) => (
          <div key={shard.id} className="rounded-xl border bg-muted/20 p-4">
            <div className="flex items-center justify-between gap-3">
              <p className="font-medium">
                {shard.account_name || `账号分片 ${shard.shard_index + 1}`}
              </p>
              <span className="text-xs text-muted-foreground">
                {shard.status}
              </span>
            </div>
            <p className="mt-2 text-sm text-muted-foreground">
              作品 {shard.aweme_count} · 评论 {shard.comment_count}
            </p>
            {shard.error && (
              <p className="mt-2 line-clamp-2 text-xs text-destructive">
                {shard.error}
              </p>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function TaskQrCode({
  taskId,
  available,
}: {
  taskId: string
  available: boolean
}) {
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [error, setError] = useState("")

  useEffect(() => {
    if (!available) return
    const controller = new AbortController()
    let objectUrl = ""

    const load = async () => {
      try {
        const token = localStorage.getItem("access_token")
        const response = await fetch(
          `${OpenAPI.BASE}/api/v1/douyin/tasks/${taskId}/qrcode`,
          {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            signal: controller.signal,
          },
        )
        if (!response.ok) throw new Error(`二维码请求失败 (${response.status})`)
        if (objectUrl) URL.revokeObjectURL(objectUrl)
        objectUrl = URL.createObjectURL(await response.blob())
        setImageUrl(objectUrl)
        setError("")
      } catch (reason) {
        if (!controller.signal.aborted)
          setError(reason instanceof Error ? reason.message : "二维码加载失败")
      }
    }
    load()
    const refreshTimer = window.setInterval(load, 15_000)

    return () => {
      window.clearInterval(refreshTimer)
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [available, taskId])

  return (
    <Card className="border-amber-500/40 bg-amber-500/5">
      <CardHeader>
        <CardTitle>等待扫码登录</CardTitle>
        <CardDescription>
          请使用抖音 App 扫描二维码。登录成功后任务会自动继续。
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!available && (
          <p className="text-sm text-muted-foreground">正在生成二维码…</p>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
        {imageUrl && (
          <img
            src={imageUrl}
            alt="抖音登录二维码"
            className="size-64 rounded-lg border bg-white p-2"
          />
        )}
      </CardContent>
    </Card>
  )
}

function MetricCard({
  icon: Icon,
  label,
  value,
  compact = false,
}: {
  icon: typeof Clock3
  label: string
  value: number | string
  compact?: boolean
}) {
  return (
    <Card className="gap-3 py-5">
      <CardContent className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-muted-foreground">{label}</p>
          <p
            className={
              compact ? "truncate text-sm font-semibold" : "text-2xl font-bold"
            }
          >
            {value}
          </p>
        </div>
        <div className="rounded-lg bg-primary/10 p-3 text-primary">
          <Icon />
        </div>
      </CardContent>
    </Card>
  )
}

function formatDate(value: string | null) {
  return value
    ? new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "short",
        timeStyle: "medium",
      }).format(new Date(value))
    : "-"
}

function currentStageLabel(task: CrawlTaskPublic) {
  if (task.status === "processing_media") return "媒体处理"
  if (task.status === "waiting_login") return "等待登录"
  if (task.status === "queued") return "等待调度"
  if (task.status === "running" || task.status === "cancelling") return "爬取"
  if (task.status === "succeeded") return "已完成"
  if (task.checkpoint_phase === "media") return "媒体处理"
  if (task.checkpoint_phase === "crawl") return "爬取"
  return "已完成"
}

function formatConfigValue(value: unknown) {
  if (Array.isArray(value)) return value.length ? value.join("、") : "-"
  if (typeof value === "boolean") return value ? "是" : "否"
  if (value === null || value === undefined || value === "") return "-"
  return String(value)
}
