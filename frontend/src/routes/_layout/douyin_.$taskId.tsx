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
  ChevronDown,
  Clock3,
  Database,
  MessageCircle,
  RefreshCw,
  RotateCcw,
  Settings2,
  ThumbsUp,
  Workflow,
} from "lucide-react"
import { useEffect, useState } from "react"

import {
  ApiError,
  type CrawlTaskPublic,
  type CrawlTaskShardStatus,
  DouyinService,
  OpenAPI,
} from "@/client"
import { MetricCard, PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { ResumeTaskDialog } from "@/components/Douyin/ResumeTaskDialog"
import { TaskExecutionProgress } from "@/components/Douyin/TaskExecutionProgress"
import {
  getTaskDisplayAuthor,
  getTaskDisplayTitle,
  shortTaskReference,
} from "@/components/Douyin/TaskIdentity"
import { TaskInteractionsPanel } from "@/components/Douyin/TaskInteractionsPanel"
import {
  activeTaskStatuses,
  TaskStatusBadge,
} from "@/components/Douyin/TaskStatusBadge"
import { TrackBadge } from "@/components/Douyin/TrackSelect"
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/douyin_/$taskId")({
  component: DouyinTaskDetail,
  head: () => ({ meta: [{ title: "任务详情 - 灵感采集台" }] }),
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
    retry: false,
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
    const unavailable =
      taskQuery.error instanceof ApiError &&
      [403, 404].includes(taskQuery.error.status)
    return (
      <Alert variant="destructive">
        <Ban />
        <AlertTitle>
          {unavailable ? "任务不可用" : "任务详情读取失败"}
        </AlertTitle>
        <AlertDescription className="space-y-3">
          <p>
            {unavailable
              ? "任务不存在，或当前账号无权访问。"
              : "暂时无法读取任务详情，请检查服务连接后重试。"}
          </p>
          {!unavailable && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={taskQuery.isFetching}
              onClick={() => void taskQuery.refetch()}
            >
              <RefreshCw
                className={taskQuery.isFetching ? "animate-spin" : ""}
              />
              {taskQuery.isFetching ? "正在重试…" : "重试"}
            </Button>
          )}
        </AlertDescription>
      </Alert>
    )
  }

  const task = taskQuery.data
  const active = activeTaskStatuses.includes(task.status)
  const displayAuthor = getTaskDisplayAuthor(task)

  return (
    <div className="page-stack">
      <PageHero
        eyebrow="任务执行详情"
        icon={Workflow}
        title={getTaskDisplayTitle(task)}
        description={`${crawlTypeLabels[task.crawl_type]}${displayAuthor ? ` · @${displayAuthor}` : ""} · 查看任务状态、采集数据与互动记录；任务运行中页面会自动刷新。`}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => taskQuery.refetch()}
              disabled={taskQuery.isFetching}
            >
              <RefreshCw
                className={taskQuery.isFetching ? "animate-spin" : ""}
              />
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
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" size="sm" className="-ml-3" asChild>
            <Link to="/douyin">
              <ArrowLeft />
              返回任务列表
            </Link>
          </Button>
          <TaskStatusBadge status={task.status} />
          <TrackBadge
            trackId={task.track_id}
            trackName={task.track_name}
            isDefault={task.track_is_default}
          />
          {displayAuthor && (
            <span className="rounded-full border bg-card/70 px-3 py-1 text-xs font-medium">
              @{displayAuthor}
            </span>
          )}
          {task.account_name && (
            <span className="rounded-full border bg-card/70 px-3 py-1 text-xs font-medium">
              执行账号：{task.account_name}
            </span>
          )}
          {task.account_pool_name && (
            <span className="rounded-full border bg-card/70 px-3 py-1 text-xs font-medium">
              账号池：{task.account_pool_name}
            </span>
          )}
          <span
            className="max-w-full truncate rounded-full border bg-card/70 px-3 py-1 text-[11px] font-medium text-muted-foreground"
            title={`完整任务编号：${task.id}`}
          >
            {shortTaskReference(task.id)}
          </span>
          {task.resume_count > 0 && (
            <span className="rounded-full bg-cyan-500/10 px-3 py-1 text-xs font-medium text-cyan-700 dark:text-cyan-300">
              已恢复 {task.resume_count} 次 · {currentStageLabel(task)}
            </span>
          )}
        </div>
      </PageHero>

      <Tabs defaultValue="overview" className="gap-5">
        <TabsList
          aria-label="任务详情页面"
          className="grid h-auto w-full grid-cols-3 rounded-2xl border bg-card p-1 shadow-sm"
        >
          <TabsTrigger value="overview" className="min-h-11 px-3 py-2.5">
            <Workflow aria-hidden="true" />
            任务概览
          </TabsTrigger>
          <TabsTrigger value="works" className="min-h-11 px-3 py-2.5">
            <Database aria-hidden="true" />
            作品数据
            <span className="rounded-full bg-muted px-1.5 text-xs">
              {task.aweme_count}
            </span>
          </TabsTrigger>
          <TabsTrigger value="interactions" className="min-h-11 px-3 py-2.5">
            <MessageCircle aria-hidden="true" />
            互动记录
            <span className="rounded-full bg-muted px-1.5 text-xs">
              {task.action_count}
            </span>
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="mt-0 space-y-5">
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
                系统已于 {formatDate(task.last_resumed_at)}{" "}
                接受恢复请求，当前阶段为
                {currentStageLabel(task)}
                。页面会自动刷新，无需重复点击继续任务。
              </AlertDescription>
            </Alert>
          )}

          <TaskExecutionProgress task={task} active={active} />

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              icon={Database}
              label="作品"
              value={task.aweme_count}
              tone="blue"
              compact
            />
            <MetricCard
              icon={MessageCircle}
              label="评论"
              value={task.comment_count}
              tone="mint"
              compact
            />
            <MetricCard
              icon={ThumbsUp}
              label="互动记录"
              value={task.action_count}
              tone="coral"
              compact
            />
            <MetricCard
              icon={Clock3}
              label="创建时间"
              value={formatDate(task.created_at)}
              tone="slate"
              compact
            />
          </div>

          <TaskShards taskId={task.id} active={active} />

          <Card className="gap-0 overflow-hidden py-0">
            <details className="group">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-5 py-4 transition hover:bg-primary/[0.035] focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none [&::-webkit-details-marker]:hidden">
                <span className="flex items-center gap-3">
                  <span className="rounded-xl bg-slate-500/10 p-2 text-slate-700 dark:text-slate-300">
                    <Settings2 className="size-4" />
                  </span>
                  <span>
                    <span className="block font-semibold">任务配置</span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      默认收起，敏感登录信息不会展示
                    </span>
                  </span>
                </span>
                <ChevronDown className="size-4 text-muted-foreground transition group-open:rotate-180" />
              </summary>
              <CardContent className="border-t bg-muted/15 p-5">
                <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
                  <div className="rounded-xl border bg-card p-3">
                    <dt className="text-xs text-muted-foreground">任务编号</dt>
                    <dd className="mt-1 break-all font-mono text-xs font-medium">
                      {task.id}
                    </dd>
                  </div>
                  {Object.entries(task.request).map(([key, value]) => (
                    <div key={key} className="rounded-xl border bg-card p-3">
                      <dt className="text-xs text-muted-foreground">
                        {configLabel(key)}
                      </dt>
                      <dd className="mt-1 break-words font-medium">
                        {formatTaskConfigValue(task, key, value)}
                      </dd>
                    </div>
                  ))}
                </dl>
              </CardContent>
            </details>
          </Card>
        </TabsContent>

        <TabsContent value="works" className="mt-0">
          <UnifiedWorksPanel task={task} active={active} />
        </TabsContent>

        <TabsContent value="interactions" className="mt-0">
          <TaskInteractionsPanel taskId={task.id} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function TaskShards({ taskId, active }: { taskId: string; active: boolean }) {
  const shards = useQuery({
    queryKey: ["douyin-task-shards", taskId],
    queryFn: () => DouyinService.listTaskShards({ taskId }),
    retry: false,
    refetchInterval: active ? 2_000 : false,
  })
  if (shards.isError) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>账号并行分片</CardTitle>
          <CardDescription>分片执行信息读取失败。</CardDescription>
        </CardHeader>
        <CardContent>
          <QueryErrorState
            title="账号分片读取失败"
            description="暂时无法获取各账号的执行进度，请检查服务连接后重试。"
            onRetry={() => void shards.refetch()}
            retrying={shards.isFetching}
            className="py-8"
          />
        </CardContent>
      </Card>
    )
  }
  if (!shards.data?.count) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle>账号并行分片</CardTitle>
        <CardDescription>
          每个分片使用独立浏览器空间；任一分片失败均可在修复账号后继续任务。
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
                {shardStatusLabels[shard.status]}
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

function formatDate(value: string | null) {
  return value
    ? new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "short",
        timeStyle: "medium",
      }).format(new Date(value))
    : "-"
}

const configLabels: Record<string, string> = {
  crawl_type: "采集类型",
  login_type: "登录方式",
  browser_mode: "浏览器模式",
  keywords: "搜索关键词",
  video_ids: "作品 ID",
  creator_ids: "创作者",
  start_page: "起始页",
  max_awemes: "最大作品数",
  fetch_comments: "抓取评论",
  fetch_sub_comments: "抓取子评论",
  max_comments_per_aweme: "单作品评论上限",
  concurrency: "并发数",
  request_delay_level: "风控节奏",
  request_interval_seconds: "请求间隔（秒）",
  request_interval_range_seconds: "实际随机间隔（秒）",
  publish_time: "发布时间范围",
  download_media: "下载视频",
  translate_subtitles: "生成翻译字幕",
  media_processing_mode: "媒体处理策略",
  media_storage: "媒体存储",
  transcription_language: "视频语言",
  account_id: "执行账号",
  account_ids: "执行账号",
  account_pool_id: "执行账号池",
  account_strategy: "账号调度策略",
}

const configValueLabels: Record<string, Record<string, string>> = {
  crawl_type: {
    search: "关键词搜索",
    detail: "指定作品",
    creator: "创作者作品",
    creator_from_aweme: "视频作者作品",
    liked: "账号点赞内容",
    collected: "账号收藏内容",
  },
  login_type: {
    qrcode: "扫码登录",
    cookie: "已有登录凭证",
  },
  browser_mode: {
    local: "本机浏览器",
    remote: "云端托管浏览器",
  },
  request_delay_level: {
    fast: "快 · 随机 1–2 秒",
    steady: "稳 · 随机 3–6 秒",
    ultra_steady: "超级稳 · 随机 6–12 秒",
  },
  publish_time: {
    "0": "不限",
    "1": "一天内",
    "7": "一周内",
    "180": "半年内",
  },
  media_processing_mode: {
    none: "不处理",
    immediate: "逐条异步处理",
    batch: "采集完成后批量处理",
  },
  media_storage: {
    local: "本地服务器",
    minio: "云端存储",
  },
  transcription_language: {
    auto: "自动识别",
    zh: "中文",
    en: "英文",
  },
  account_strategy: {
    least_loaded: "最少负载",
    round_robin: "轮询",
    weighted_round_robin: "加权轮询",
  },
}

const shardStatusLabels: Record<CrawlTaskShardStatus, string> = {
  queued: "等待调度",
  running: "执行中",
  succeeded: "已完成",
  failed: "失败",
  interrupted: "已中断",
  cancelled: "已取消",
}

function configLabel(key: string) {
  return configLabels[key] ?? key.replace(/_/g, " ")
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

function formatConfigValue(key: string, value: unknown) {
  if (Array.isArray(value)) {
    return value.length
      ? value.map((item) => formatConfigScalar(key, item)).join("、")
      : "-"
  }
  if (typeof value === "boolean") return value ? "是" : "否"
  if (value === null || value === undefined || value === "") return "-"
  return formatConfigScalar(key, value)
}

function formatTaskConfigValue(
  task: CrawlTaskPublic,
  key: string,
  value: unknown,
) {
  if (key !== "creator_ids") return formatConfigValue(key, value)

  const rawIds = new Set(
    Array.isArray(value) ? value.map((item) => String(item)) : [],
  )
  const fallbackAuthors = ["creator", "creator_from_aweme"].includes(
    task.crawl_type,
  )
    ? [task.display_author ?? ""]
    : []
  const names = [...(task.creator_names ?? []), ...fallbackAuthors]
    .map((item) => item.trim().replace(/^@/, ""))
    .filter((item, index, values) => {
      return (
        Boolean(item) && !rawIds.has(item) && values.indexOf(item) === index
      )
    })
  if (names.length) return names.join("、")
  return rawIds.size ? `已选择 ${rawIds.size} 位创作者` : "-"
}

function formatConfigScalar(key: string, value: unknown) {
  const rawValue = String(value)
  return configValueLabels[key]?.[rawValue] ?? rawValue
}
