import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  Camera,
  Eye,
  ImageOff,
  LoaderCircle,
  MessageCircleMore,
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
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/douyin-interactions")({
  component: DouyinInteractionsPage,
  head: () => ({ meta: [{ title: "互动任务 - Douyin Crawler" }] }),
})

type StatusFilter = DouyinInteractionStatus | "all"
type TypeFilter = DouyinInteractionType | "all"

function DouyinInteractionsPage() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all")
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all")
  const [detailId, setDetailId] = useState<string | null>(null)
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
  const cancel = useMutation({
    mutationFn: (id: string) =>
      DouyinInteractionsService.cancelInteraction({ interactionId: id }),
    onSuccess: invalidate,
    onError: handleError.bind(showErrorToast),
  })
  const rows = interactions.data?.data ?? []

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-3">
            <div className="rounded-xl bg-primary/10 p-2.5 text-primary">
              <MessageCircleMore className="size-6" />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight">互动任务</h1>
              <p className="text-sm text-muted-foreground">
                统一管理视频评论、评论回复和作者私信的确认、进度与重试。
              </p>
            </div>
          </div>
        </div>
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
      </div>

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
                  <TableHead>内容预览</TableHead>
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
                        <Link
                          to="/douyin/$taskId"
                          params={{ taskId: item.task_id }}
                          className="font-mono text-xs text-muted-foreground hover:text-primary"
                        >
                          {item.aweme_id}
                        </Link>
                      </TableCell>
                      <TableCell className="max-w-md">
                        <p className="line-clamp-2">{item.content_preview}</p>
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
                <p className="mt-3 whitespace-pre-wrap text-sm leading-6">
                  {detail.data.content}
                </p>
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
