import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  Camera,
  ExternalLink,
  Eye,
  ImageOff,
  LoaderCircle,
  MessageCircleMore,
  MonitorPlay,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  ZoomIn,
} from "lucide-react"
import { useEffect, useState } from "react"

import {
  type DouyinInteractionEventPublic,
  type DouyinInteractionPublic,
  type DouyinInteractionStatus,
  DouyinInteractionsService,
  type DouyinInteractionType,
  OpenAPI,
} from "@/client"
import { PageHero } from "@/components/Common/PageShell"
import { InteractionContentSummary } from "@/components/Douyin/InteractionContentSummary"
import { InteractionLiveMonitor } from "@/components/Douyin/InteractionLiveMonitor"
import {
  InteractionStatusBadge,
  interactionTypeLabels,
} from "@/components/Douyin/InteractionStatusBadge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
import { getDouyinVideoUrl, handleError } from "@/utils"

export const Route = createFileRoute("/_layout/douyin-interactions")({
  component: DouyinInteractionsPage,
  head: () => ({ meta: [{ title: "互动任务 - 灵感采集台" }] }),
})

type StatusFilter = DouyinInteractionStatus | "all"
type TypeFilter = DouyinInteractionType | "all"

function DouyinInteractionsPage() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all")
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all")
  const [detailId, setDetailId] = useState<string | null>(null)
  const [monitorId, setMonitorId] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const interactions = useQuery({
    queryKey: ["douyin-interactions", statusFilter, typeFilter],
    queryFn: () =>
      DouyinInteractionsService.listInteractions({
        status: statusFilter === "all" ? undefined : statusFilter,
        interactionType: typeFilter === "all" ? undefined : typeFilter,
        limit: 100,
      }),
    refetchInterval: (query) =>
      query.state.data?.data.some((item) =>
        ["queued", "running"].includes(item.status),
      )
        ? 2_000
        : 5_000,
  })
  const quotas = useQuery({
    queryKey: ["douyin-interaction-quota"],
    queryFn: () => DouyinInteractionsService.listInteractionQuota(),
    refetchInterval: 5_000,
  })
  const detail = useQuery({
    queryKey: ["douyin-interaction-detail", detailId],
    queryFn: () =>
      DouyinInteractionsService.getInteraction({ interactionId: detailId! }),
    enabled: Boolean(detailId),
    refetchInterval: (query) =>
      query.state.data &&
      ["queued", "running"].includes(query.state.data.status)
        ? 2_000
        : false,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["douyin-interactions"] }),
      queryClient.invalidateQueries({
        queryKey: ["douyin-task-interactions"],
      }),
      queryClient.invalidateQueries({ queryKey: ["douyin-interaction-quota"] }),
      detailId
        ? queryClient.invalidateQueries({
            queryKey: ["douyin-interaction-detail", detailId],
          })
        : Promise.resolve(),
    ])
  }
  const confirm = useMutation({
    mutationFn: (id: string) =>
      DouyinInteractionsService.confirmInteraction({ interactionId: id }),
    onSuccess: async () => {
      showSuccessToast("互动任务已确认并进入发送队列")
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const retry = useMutation({
    mutationFn: (item: DouyinInteractionPublic) =>
      DouyinInteractionsService.retryInteraction({
        interactionId: item.id,
        requestBody: { confirm_not_sent: item.status === "needs_review" },
      }),
    onSuccess: async () => {
      showSuccessToast("互动任务已重新排队")
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const retryAll = useMutation({
    mutationFn: async () => {
      const all: DouyinInteractionPublic[] = []
      let skip = 0
      let total = 0
      do {
        const page = await DouyinInteractionsService.listInteractions({
          skip,
          limit: 100,
        })
        all.push(...page.data)
        total = page.count
        skip += page.data.length
      } while (skip < total)

      const candidates = all.filter(
        (item) => item.status !== "succeeded" && item.can_retry,
      )
      const unavailable = all.filter(
        (item) => item.status !== "succeeded" && !item.can_retry,
      )
      const results = await Promise.allSettled(
        candidates.map((item) =>
          DouyinInteractionsService.retryInteraction({
            interactionId: item.id,
            requestBody: { confirm_not_sent: item.status === "needs_review" },
          }),
        ),
      )
      const failed = results.filter((result) => result.status === "rejected")
      if (failed.length || unavailable.length) {
        throw new Error(
          `已重新排队 ${results.length - failed.length} 条；${failed.length} 条请求失败，${unavailable.length} 条目标不可用或内容损坏，无法安全重试`,
        )
      }
      return candidates.length
    },
    onSuccess: async (count) => {
      showSuccessToast(`已将 ${count} 条非成功互动任务重新排队`)
      await invalidate()
    },
    onError: async (error) => {
      showErrorToast(error instanceof Error ? error.message : "批量重试失败")
      await invalidate()
    },
  })
  const cancel = useMutation({
    mutationFn: (id: string) =>
      DouyinInteractionsService.cancelInteraction({ interactionId: id }),
    onSuccess: invalidate,
    onError: handleError.bind(showErrorToast),
  })
  const rows = interactions.data?.data ?? []

  return (
    <div className="page-stack">
      <PageHero
        eyebrow="互动运营与风控"
        icon={MessageCircleMore}
        title="互动任务"
        description="统一管理视频评论、评论回复和作者私信的确认、进度与重试；发送配额和异常状态保持可见。"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => interactions.refetch()}
              disabled={interactions.isFetching}
            >
              <RefreshCw
                className={interactions.isFetching ? "animate-spin" : undefined}
              />
              刷新
            </Button>
            <Button
              variant="outline"
              disabled={
                retryAll.isPending ||
                !rows.some((item) => item.status !== "succeeded")
              }
              onClick={() => {
                if (
                  window.confirm(
                    "将重新调度全部非成功互动任务；待人工核对的任务也会按“确认未发送”处理并再次发送。是否继续？",
                  )
                ) {
                  retryAll.mutate()
                }
              }}
            >
              <RotateCcw
                className={retryAll.isPending ? "animate-spin" : undefined}
              />
              {retryAll.isPending ? "正在重试全部" : "重试全部非成功项"}
            </Button>
          </div>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {(quotas.data ?? []).map((quota) => (
          <Card key={quota.account_id}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="font-medium">{quota.account_name}</p>
                <Badge variant={quota.available ? "outline" : "destructive"}>
                  {quota.available ? "可用" : "暂停"}
                </Badge>
              </div>
              <p className="mt-2 text-2xl font-semibold">
                {quota.remaining_today}
                <span className="ml-1 text-sm font-normal text-muted-foreground">
                  / {quota.daily_limit} 今日剩余
                </span>
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                操作间隔至少 {quota.min_interval_seconds} 秒
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardContent className="space-y-4 p-5">
          <div className="flex flex-wrap gap-2">
            <Select
              value={statusFilter}
              onValueChange={(value) => setStatusFilter(value as StatusFilter)}
            >
              <SelectTrigger className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部状态</SelectItem>
                <SelectItem value="pending_confirmation">待确认</SelectItem>
                <SelectItem value="queued">排队中</SelectItem>
                <SelectItem value="running">发送中</SelectItem>
                <SelectItem value="succeeded">已成功</SelectItem>
                <SelectItem value="failed">失败</SelectItem>
                <SelectItem value="blocked">已暂停</SelectItem>
                <SelectItem value="needs_review">待人工核对</SelectItem>
                <SelectItem value="cancelled">已取消</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={typeFilter}
              onValueChange={(value) => setTypeFilter(value as TypeFilter)}
            >
              <SelectTrigger className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部类型</SelectItem>
                <SelectItem value="video_comment">视频评论</SelectItem>
                <SelectItem value="comment_reply">评论回复</SelectItem>
                <SelectItem value="creator_message">作者私信</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="overflow-x-auto rounded-xl border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>类型 / 目标</TableHead>
                  <TableHead>互动内容 / 目标内容</TableHead>
                  <TableHead>账号</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>更新时间</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.length ? (
                  rows.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell>
                        <p className="font-medium">
                          {interactionTypeLabels[item.interaction_type]}
                        </p>
                        <div className="mt-1 flex flex-wrap items-center gap-2">
                          <a
                            href={
                              item.target_video_url ||
                              getDouyinVideoUrl(item.aweme_id)
                            }
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 font-mono text-xs text-primary hover:underline"
                          >
                            视频 {item.aweme_id}
                            <ExternalLink className="size-3" />
                          </a>
                          <Link
                            to="/douyin/$taskId"
                            params={{ taskId: item.task_id }}
                            className="text-xs text-muted-foreground hover:text-primary"
                          >
                            查看采集任务
                          </Link>
                        </div>
                      </TableCell>
                      <TableCell className="max-w-md">
                        <InteractionContentSummary
                          interactionType={item.interaction_type}
                          targetCommentId={item.target_comment_id}
                          targetCommentContent={item.target_comment_content}
                          content={item.content_preview}
                          compact
                        />
                        {item.error && (
                          <p className="mt-1 line-clamp-2 text-xs text-destructive">
                            {item.failure_code}: {item.error}
                          </p>
                        )}
                      </TableCell>
                      <TableCell>{item.account_name || "账号已删除"}</TableCell>
                      <TableCell>
                        <InteractionStatusBadge status={item.status} />
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                        {formatDate(item.updated_at)}
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-1">
                          <Button
                            size="icon-sm"
                            variant="ghost"
                            aria-label="查看详情"
                            onClick={() => setDetailId(item.id)}
                          >
                            <Eye />
                          </Button>
                          <Button
                            size="icon-sm"
                            variant="ghost"
                            aria-label="查看实时监控"
                            onClick={() => setMonitorId(item.id)}
                          >
                            <MonitorPlay />
                          </Button>
                          {item.can_confirm && (
                            <Button
                              size="sm"
                              onClick={() => confirm.mutate(item.id)}
                            >
                              确认发送
                            </Button>
                          )}
                          {item.can_retry && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() =>
                                retryAfterReview(item, retry.mutate)
                              }
                            >
                              <RotateCcw />
                              重试
                            </Button>
                          )}
                          {item.can_cancel && (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => cancel.mutate(item.id)}
                            >
                              取消
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell
                      colSpan={6}
                      className="h-36 text-center text-muted-foreground"
                    >
                      {interactions.isLoading
                        ? "加载互动任务..."
                        : "没有符合筛选条件的互动任务"}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Dialog open={Boolean(detailId)} onOpenChange={() => setDetailId(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>互动任务详情</DialogTitle>
            <DialogDescription>
              完整内容仅对任务所有者可见，不会写入应用日志。
            </DialogDescription>
          </DialogHeader>
          {detail.data ? (
            <div className="space-y-5">
              {detail.data.status === "needs_review" && (
                <Alert>
                  <ShieldCheck />
                  <AlertTitle>需要人工检查</AlertTitle>
                  <AlertDescription>
                    请先打开抖音确认内容没有发送成功，再执行重试，以免重复发送。
                  </AlertDescription>
                </Alert>
              )}
              <div className="rounded-xl border bg-muted/25 p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="font-medium">
                    {interactionTypeLabels[detail.data.interaction_type]}
                  </p>
                  <InteractionStatusBadge status={detail.data.status} />
                </div>
                <div className="mt-3">
                  <InteractionContentSummary
                    interactionType={detail.data.interaction_type}
                    targetCommentId={detail.data.target_comment_id}
                    targetCommentContent={detail.data.target_comment_content}
                    content={detail.data.content}
                  />
                </div>
                <div className="mt-3 flex flex-wrap gap-2 border-t pt-3">
                  <Button variant="outline" size="sm" asChild>
                    <a
                      href={
                        detail.data.target_video_url ||
                        getDouyinVideoUrl(detail.data.aweme_id)
                      }
                      target="_blank"
                      rel="noreferrer"
                    >
                      <ExternalLink />
                      打开抖音视频 {detail.data.aweme_id}
                    </a>
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setMonitorId(detail.data.id)}
                  >
                    <MonitorPlay />
                    查看实时监控
                  </Button>
                </div>
              </div>
              <div>
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h3 className="font-medium">浏览器操作日志</h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      自动记录关键 CDP 操作；截图仅任务所有者可查看。
                    </p>
                  </div>
                  <Badge variant="outline">
                    <Camera />
                    {
                      detail.data.events.filter((event) => event.has_screenshot)
                        .length
                    }{" "}
                    张截图
                  </Badge>
                </div>
                <div className="mt-4 space-y-4 border-l pl-4">
                  {detail.data.events.map((event) => (
                    <div
                      key={event.id}
                      className="relative rounded-xl border bg-card p-3 shadow-sm before:absolute before:-left-[1.3rem] before:top-5 before:size-2 before:rounded-full before:bg-primary"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div>
                          <p className="text-sm font-medium">
                            {interactionEventLabel(event.event)}
                          </p>
                          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            <InteractionStatusBadge status={event.to_status} />
                            {event.attempt_number > 0 && (
                              <span>第 {event.attempt_number} 次执行</span>
                            )}
                            <span>{formatDate(event.created_at)}</span>
                          </div>
                        </div>
                      </div>
                      <a
                        href={
                          detail.data.target_video_url ||
                          getDouyinVideoUrl(detail.data.aweme_id)
                        }
                        target="_blank"
                        rel="noreferrer"
                        className="mt-2 inline-flex items-center gap-1 text-xs text-primary hover:underline"
                      >
                        目标视频 {detail.data.aweme_id}
                        <ExternalLink className="size-3" />
                      </a>
                      {event.detail && (
                        <p className="mt-2 text-sm text-muted-foreground">
                          {event.detail}
                        </p>
                      )}
                      {event.has_screenshot && detailId && (
                        <InteractionEvidence
                          interactionId={detailId}
                          event={event}
                        />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <p className="py-12 text-center text-muted-foreground">
              加载详情...
            </p>
          )}
        </DialogContent>
      </Dialog>
      <InteractionLiveMonitor
        interactionId={monitorId}
        open={Boolean(monitorId)}
        onOpenChange={(open) => !open && setMonitorId(null)}
      />
    </div>
  )
}

function retryAfterReview(
  item: DouyinInteractionPublic,
  retry: (item: DouyinInteractionPublic) => void,
) {
  if (
    item.status === "needs_review" &&
    !window.confirm(
      "请先到抖音页面确认这条内容没有发送成功。确认未发送并重试吗？",
    )
  ) {
    return
  }
  retry(item)
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(new Date(value))
}

const interactionEventLabels: Record<string, string> = {
  created: "已创建互动任务",
  confirmed: "用户已确认发送",
  retried: "用户已确认重试",
  started: "开始执行互动任务",
  succeeded: "互动任务执行成功",
  execution_failed: "互动任务执行失败",
  cancelled: "互动任务已取消",
  worker_cancelled: "执行进程被中断",
  service_restarted: "服务重启时恢复任务",
  browser_browser_connected: "连接账号浏览器",
  browser_login_verified: "验证账号登录状态",
  browser_video_opened: "打开目标视频",
  browser_comment_editor_ready: "打开评论输入框",
  browser_reply_target_found: "定位目标评论",
  browser_reply_editor_ready: "打开回复输入框",
  browser_creator_profile_opened: "打开作者主页",
  browser_message_editor_ready: "打开私信窗口",
  browser_content_filled: "填写互动内容",
  browser_submit_triggered: "触发发送",
  browser_platform_accepted: "平台确认接收",
  browser_execution_failed: "保留异常页面现场",
}

function interactionEventLabel(event: string) {
  return interactionEventLabels[event] || event.replace(/_/g, " ")
}

function InteractionEvidence({
  interactionId,
  event,
}: {
  interactionId: string
  event: DouyinInteractionEventPublic
}) {
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    if (!event.has_screenshot) return
    const controller = new AbortController()
    let objectUrl: string | null = null
    const load = async () => {
      try {
        const token = localStorage.getItem("access_token")
        const response = await fetch(
          `${interactionApiBase()}/api/v1/douyin/interactions/${interactionId}/events/${event.id}/screenshot`,
          {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            signal: controller.signal,
          },
        )
        if (!response.ok) throw new Error(`截图加载失败 (${response.status})`)
        objectUrl = URL.createObjectURL(await response.blob())
        setImageUrl(objectUrl)
      } catch (reason) {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "截图加载失败")
        }
      }
    }
    void load()
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [event.has_screenshot, event.id, interactionId])

  if (error) {
    return (
      <div className="mt-3 flex h-24 items-center justify-center gap-2 rounded-lg border border-dashed text-xs text-muted-foreground">
        <ImageOff className="size-4" />
        {error}
      </div>
    )
  }
  if (!imageUrl) {
    return (
      <div className="mt-3 flex h-24 items-center justify-center gap-2 rounded-lg border border-dashed text-xs text-muted-foreground">
        <LoaderCircle className="size-4 animate-spin" />
        正在加载操作截图…
      </div>
    )
  }
  return (
    <>
      <button
        type="button"
        className="group relative mt-3 block w-full overflow-hidden rounded-lg border bg-black text-left"
        onClick={() => setExpanded(true)}
        aria-label="查看操作截图大图"
      >
        <img
          src={imageUrl}
          alt={`${interactionEventLabel(event.event)}操作截图`}
          className="max-h-52 w-full object-contain transition group-hover:opacity-80"
        />
        <span className="absolute right-2 bottom-2 flex items-center gap-1 rounded-md bg-black/70 px-2 py-1 text-xs text-white">
          <ZoomIn className="size-3.5" />
          查看大图
        </span>
      </button>
      <Dialog open={expanded} onOpenChange={setExpanded}>
        <DialogContent className="sm:max-w-6xl">
          <DialogHeader>
            <DialogTitle>{interactionEventLabel(event.event)}</DialogTitle>
            <DialogDescription>
              第 {event.attempt_number || 1} 次执行 ·{" "}
              {formatDate(event.created_at)}
            </DialogDescription>
          </DialogHeader>
          <div className="overflow-hidden rounded-lg border bg-black">
            <img
              src={imageUrl}
              alt={`${interactionEventLabel(event.event)}操作截图大图`}
              className="max-h-[72vh] w-full object-contain"
            />
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}

function interactionApiBase() {
  return new URL(OpenAPI.BASE || window.location.origin, window.location.origin)
    .toString()
    .replace(/\/$/, "")
}
