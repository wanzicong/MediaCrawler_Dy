import { useQuery } from "@tanstack/react-query"
import {
  AlertTriangle,
  Captions,
  CheckCircle2,
  CircleDashed,
  Download,
  MessageCircle,
  ScanSearch,
} from "lucide-react"

import {
  type CrawlTaskPublic,
  type DouyinMediaSummaryPublic,
  DouyinService,
} from "@/client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"

type ProgressTone = "active" | "complete" | "error" | "pending" | "skipped"

type StageProgress = {
  key: string
  label: string
  detail: string
  percent: number | null
  tone: ProgressTone
  icon: typeof ScanSearch
}

const terminalStatuses = new Set([
  "succeeded",
  "failed",
  "cancelled",
  "interrupted",
])

export function TaskListProgress({ task }: { task: CrawlTaskPublic }) {
  const progress = getListProgress(task)
  return (
    <div className="min-w-36 space-y-1.5">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="font-medium">{progress.label}</span>
        <span className="tabular-nums text-muted-foreground">
          {progress.percent === null ? "进行中" : `${progress.percent}%`}
        </span>
      </div>
      <ProgressBar
        percent={progress.percent}
        active={progress.active}
        error={progress.error}
        label={`${progress.label}：${progress.detail}`}
      />
      <p className="truncate text-[11px] text-muted-foreground">
        {progress.detail}
      </p>
    </div>
  )
}

export function TaskExecutionProgress({
  task,
  active,
}: {
  task: CrawlTaskPublic
  active: boolean
}) {
  const summaryQuery = useQuery({
    queryKey: ["douyin-media-summary", task.id],
    queryFn: () => DouyinService.getMediaSummary({ taskId: task.id }),
    refetchInterval: active ? 2_000 : 10_000,
    retry: false,
  })
  const stages = buildStages(task, summaryQuery.data, summaryQuery.isError)
  const current = stages.find((stage) => stage.tone === "active")
  const completed = stages.filter((stage) => stage.tone === "complete").length
  const skipped = stages.filter((stage) => stage.tone === "skipped").length
  const errors = stages.filter((stage) => stage.tone === "error").length
  const pending = stages.filter((stage) => stage.tone === "pending").length
  const enabled = stages.length - skipped
  const settledSummary = [
    completed > 0 ? `${completed} 个完成` : null,
    skipped > 0 ? `${skipped} 个未启用` : null,
    errors > 0 ? `${errors} 个异常` : null,
    pending > 0 ? `${pending} 个待处理` : null,
  ]
    .filter(Boolean)
    .join(" · ")

  return (
    <Card className="gap-3" data-testid="task-execution-progress">
      <CardHeader className="flex-row items-center justify-between gap-4">
        <div>
          <CardTitle className="text-base">任务执行进度</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            {current
              ? `当前：${current.label} · ${current.detail}`
              : settledSummary || "等待任务进度更新"}
          </p>
        </div>
        <span className="shrink-0 rounded-full bg-muted px-2.5 py-1 text-xs font-medium tabular-nums">
          已完成 {completed} / {enabled}
        </span>
      </CardHeader>
      <CardContent className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {stages.map((stage) => (
          <StageCard key={stage.key} stage={stage} />
        ))}
      </CardContent>
    </Card>
  )
}

function StageCard({ stage }: { stage: StageProgress }) {
  const Icon = stage.icon
  const StateIcon =
    stage.tone === "complete"
      ? CheckCircle2
      : stage.tone === "error"
        ? AlertTriangle
        : CircleDashed
  return (
    <div
      data-stage={stage.key}
      className={cn(
        "rounded-xl border p-3",
        stage.tone === "active" && "border-cyan-500/40 bg-cyan-500/5",
        stage.tone === "error" && "border-destructive/35 bg-destructive/5",
        stage.tone === "skipped" && "bg-muted/35 opacity-70",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-sm font-semibold">
          <Icon className="size-4" />
          {stage.label}
        </span>
        <StateIcon
          className={cn(
            "size-4 text-muted-foreground",
            stage.tone === "active" && "animate-spin text-cyan-600",
            stage.tone === "complete" && "text-emerald-600",
            stage.tone === "error" && "text-destructive",
          )}
        />
      </div>
      <p className="mt-2 min-h-8 text-xs leading-4 text-muted-foreground">
        {stage.detail}
      </p>
      <div className="mt-2 flex items-center gap-2">
        <ProgressBar
          percent={stage.percent}
          active={stage.tone === "active"}
          error={stage.tone === "error"}
          skipped={stage.tone === "skipped"}
          label={`${stage.label}：${stage.detail}`}
        />
        <span className="w-12 text-right text-[11px] tabular-nums text-muted-foreground">
          {stage.tone === "skipped"
            ? "未启用"
            : stage.percent === null
              ? "--"
              : `${stage.percent}%`}
        </span>
      </div>
    </div>
  )
}

function ProgressBar({
  percent,
  active,
  error,
  skipped = false,
  label,
}: {
  percent: number | null
  active: boolean
  error: boolean
  skipped?: boolean
  label: string
}) {
  if (skipped) {
    return (
      <div
        data-progress-state="skipped"
        className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted-foreground/15"
      />
    )
  }

  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent ?? undefined}
      className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted"
    >
      {percent === null ? (
        active && (
          <div className="h-full w-1/3 animate-pulse rounded-full bg-cyan-500" />
        )
      ) : (
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-500",
            error
              ? "bg-destructive"
              : percent === 100
                ? "bg-emerald-500"
                : "bg-cyan-500",
          )}
          style={{ width: `${percent}%` }}
        />
      )}
    </div>
  )
}

function getListProgress(task: CrawlTaskPublic) {
  const target = requestNumber(task, "max_awemes") ?? task.aweme_count
  const crawlPercent = target
    ? clampPercent((task.aweme_count / target) * 100)
    : 0
  if (task.status === "succeeded") {
    return {
      label: "已完成",
      detail: `${task.aweme_count} 作品 · ${task.comment_count} 评论`,
      percent: 100,
      active: false,
      error: false,
    }
  }
  if (task.status === "processing_media") {
    return {
      label: "采集已完成",
      detail: `${task.aweme_count} 作品 · 媒体任务独立处理中`,
      percent: 100,
      active: false,
      error: false,
    }
  }
  if (task.status === "queued") {
    return {
      label: "等待调度",
      detail: "尚未开始执行",
      percent: 0,
      active: true,
      error: false,
    }
  }
  if (task.status === "waiting_login") {
    return {
      label: "等待登录",
      detail: "登录后自动继续",
      percent: null,
      active: true,
      error: false,
    }
  }
  const stopped = terminalStatuses.has(task.status)
  return {
    label: stopped ? "采集已停止" : "采集作品",
    detail: `${task.aweme_count} / ${target || "未知目标"} 作品`,
    percent: crawlPercent,
    active: !stopped,
    error: task.status === "failed" || task.status === "interrupted",
  }
}

function buildStages(
  task: CrawlTaskPublic,
  summary?: DouyinMediaSummaryPublic,
  summaryError = false,
): StageProgress[] {
  const target = requestNumber(task, "max_awemes") ?? task.aweme_count
  const crawlPassed = task.checkpoint_phase !== "crawl"
  const crawlPercent = crawlPassed
    ? 100
    : target
      ? clampPercent((task.aweme_count / target) * 100)
      : 0
  const crawlError =
    !crawlPassed && ["failed", "interrupted", "cancelled"].includes(task.status)
  const fetchComments = requestBoolean(task, "fetch_comments")
  const downloadMedia = requestBoolean(task, "download_media")
  const translateSubtitles = requestBoolean(task, "translate_subtitles")

  const mediaDone = summary ? summary.downloaded + summary.download_failed : 0
  const mediaPercent = summary?.total
    ? clampPercent((mediaDone / summary.total) * 100)
    : null
  const subtitleTotal = summary
    ? summary.subtitle_pending +
      summary.subtitle_running +
      summary.subtitle_completed +
      summary.subtitle_failed
    : 0
  const subtitleDone = summary
    ? summary.subtitle_completed + summary.subtitle_failed
    : 0
  const subtitlePercent = subtitleTotal
    ? clampPercent((subtitleDone / subtitleTotal) * 100)
    : null
  const emptyMedia =
    task.status === "succeeded" && summary !== undefined && summary.total === 0
  const emptySubtitles =
    task.status === "succeeded" && summary !== undefined && subtitleTotal === 0

  return [
    {
      key: "crawl",
      label: "作品采集",
      detail: crawlPassed
        ? `已结束，共保存 ${task.aweme_count} 条作品`
        : `已保存 ${task.aweme_count} / ${target || "未知目标"} 条作品`,
      percent: crawlPercent,
      tone: crawlError ? "error" : crawlPassed ? "complete" : "active",
      icon: ScanSearch,
    },
    {
      key: "comments",
      label: "评论采集",
      detail: fetchComments
        ? `${task.comment_count} 条已落库；总量由抖音实际返回决定`
        : "任务未启用评论采集",
      percent: fetchComments ? crawlPercent : null,
      tone: !fetchComments
        ? "skipped"
        : crawlError
          ? "error"
          : crawlPassed
            ? "complete"
            : "active",
      icon: MessageCircle,
    },
    {
      key: "download",
      label: "视频下载",
      detail: !downloadMedia
        ? "任务未启用视频下载"
        : summaryError
          ? "媒体进度读取失败，系统将自动重试"
          : emptyMedia
            ? "任务已结束，无可处理内容"
            : summary?.total
              ? `${summary.downloaded} 完成 · ${summary.downloading} 处理中 · ${summary.queued} 排队 · ${summary.download_failed} 失败`
              : crawlPassed
                ? "尚未生成可处理的媒体记录"
                : "等待作品采集后进入媒体队列",
      percent: !downloadMedia ? null : emptyMedia ? 100 : mediaPercent,
      tone: !downloadMedia
        ? "skipped"
        : summaryError
          ? "error"
          : emptyMedia
            ? "complete"
            : (summary?.download_failed ?? 0) > 0 &&
                terminalStatuses.has(task.status)
              ? "error"
              : mediaPercent === 100
                ? "complete"
                : task.status === "processing_media"
                  ? "active"
                  : "pending",
      icon: Download,
    },
    {
      key: "subtitle",
      label: "字幕处理",
      detail: !translateSubtitles
        ? "任务未启用字幕处理"
        : summaryError
          ? "媒体进度读取失败，系统将自动重试"
          : emptySubtitles
            ? "任务已结束，无可处理内容"
            : subtitleTotal
              ? `${summary?.subtitle_completed ?? 0} 完成 · ${summary?.subtitle_running ?? 0} 处理中 · ${summary?.subtitle_pending ?? 0} 排队 · ${summary?.subtitle_failed ?? 0} 失败`
              : crawlPassed
                ? "尚未生成字幕处理记录"
                : "等待视频下载后进入字幕队列",
      percent: !translateSubtitles
        ? null
        : emptySubtitles
          ? 100
          : subtitlePercent,
      tone: !translateSubtitles
        ? "skipped"
        : summaryError
          ? "error"
          : emptySubtitles
            ? "complete"
            : (summary?.subtitle_failed ?? 0) > 0 &&
                terminalStatuses.has(task.status)
              ? "error"
              : subtitlePercent === 100
                ? "complete"
                : task.status === "processing_media"
                  ? "active"
                  : "pending",
      icon: Captions,
    },
  ]
}

function requestNumber(task: CrawlTaskPublic, key: string) {
  const value = task.request[key]
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function requestBoolean(task: CrawlTaskPublic, key: string) {
  return task.request[key] === true
}

function clampPercent(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)))
}
