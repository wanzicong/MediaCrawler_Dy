import { useQuery } from "@tanstack/react-query"
import {
  CircleAlert,
  ExternalLink,
  MonitorPlay,
  RefreshCw,
  Route,
  ServerOff,
} from "lucide-react"
import { useMemo } from "react"

import { DouyinAccountsService, DouyinInteractionsService } from "@/client"
import { InteractionContentSummary } from "@/components/Douyin/InteractionContentSummary"
import {
  InteractionStatusBadge,
  interactionTypeLabels,
} from "@/components/Douyin/InteractionStatusBadge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"

const eventLabels: Record<string, string> = {
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

export function InteractionLiveMonitor({
  interactionId,
  open,
  onOpenChange,
}: {
  interactionId: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const detail = useQuery({
    queryKey: ["douyin-interaction-live", interactionId],
    queryFn: () =>
      DouyinInteractionsService.getInteraction({
        interactionId: interactionId!,
      }),
    enabled: open && Boolean(interactionId),
    refetchInterval: open ? 1_000 : false,
  })
  const slots = useQuery({
    queryKey: ["douyin-browser-monitor"],
    queryFn: () => DouyinAccountsService.listBrowserSlots(),
    enabled: open,
    refetchInterval: open ? 2_000 : false,
  })
  const selectedSlot = useMemo(() => {
    const accountId = detail.data?.account_id
    const accountName = detail.data?.account_name
    return slots.data?.data.find(
      (slot) =>
        (accountId && slot.occupied_account_id === accountId) ||
        (accountName && slot.occupied_account_name === accountName),
    )
  }, [detail.data?.account_id, detail.data?.account_name, slots.data?.data])
  const events = detail.data?.events ?? []
  const latestEvent = events.length ? events[events.length - 1] : undefined

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[96vw] gap-0 p-0 sm:max-w-[96vw] xl:w-[86vw] xl:max-w-[1500px]">
        <SheetHeader className="border-b px-5 py-4 pr-12">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <SheetTitle className="flex items-center gap-2">
                  <MonitorPlay className="size-5 text-primary" />
                  评论实时监控
                </SheetTitle>
                {detail.data && (
                  <InteractionStatusBadge status={detail.data.status} />
                )}
                {selectedSlot && (
                  <Badge
                    variant={
                      selectedSlot.cdp_healthy ? "outline" : "destructive"
                    }
                  >
                    {selectedSlot.cdp_healthy ? "浏览器在线" : "浏览器离线"}
                  </Badge>
                )}
              </div>
              <SheetDescription className="mt-1">
                实时观察账号浏览器和执行链路；关闭监控不会中断评论任务。
              </SheetDescription>
            </div>
            <div className="flex flex-wrap gap-2">
              {detail.data?.target_video_url && (
                <Button variant="outline" size="sm" asChild>
                  <a
                    href={detail.data.target_video_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <ExternalLink />
                    打开抖音原视频
                  </a>
                </Button>
              )}
              {selectedSlot?.viewer_url && (
                <Button variant="outline" size="sm" asChild>
                  <a
                    href={selectedSlot.viewer_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <MonitorPlay />
                    新窗口监控
                  </a>
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                disabled={detail.isFetching || slots.isFetching}
                onClick={() => {
                  void detail.refetch()
                  void slots.refetch()
                }}
              >
                <RefreshCw
                  className={
                    detail.isFetching || slots.isFetching ? "animate-spin" : ""
                  }
                />
                刷新
              </Button>
            </div>
          </div>
        </SheetHeader>

        <div className="grid min-h-0 flex-1 overflow-y-auto xl:grid-cols-[minmax(0,1.6fr)_420px] xl:overflow-hidden">
          <section className="flex min-h-[430px] flex-col border-b bg-slate-950 xl:min-h-0 xl:border-r xl:border-b-0">
            <div className="flex items-center justify-between border-b border-white/10 px-4 py-2 text-xs text-slate-300">
              <span>
                {selectedSlot?.label ||
                  detail.data?.account_name ||
                  "账号浏览器"}
              </span>
              <span>
                {selectedSlot?.latency_ms != null
                  ? `${selectedSlot.latency_ms} ms`
                  : "等待浏览器状态"}
              </span>
            </div>
            {selectedSlot?.viewer_url ? (
              <iframe
                key={selectedSlot.viewer_url}
                src={selectedSlot.viewer_url}
                title={`${detail.data?.account_name || "互动账号"}实时浏览器`}
                className="min-h-[400px] flex-1 bg-slate-950"
                allow="clipboard-read; clipboard-write; fullscreen"
              />
            ) : (
              <div className="flex flex-1 items-center justify-center p-8 text-center text-slate-300">
                <div>
                  <ServerOff className="mx-auto size-10 opacity-60" />
                  <p className="mt-3 font-medium">暂无可嵌入的实时浏览器</p>
                  <p className="mt-1 max-w-md text-sm text-slate-400">
                    本机浏览器暂不提供嵌入画面；云端托管浏览器启动并绑定账号后会自动显示。
                  </p>
                </div>
              </div>
            )}
          </section>

          <aside className="min-h-0 bg-background xl:overflow-y-auto">
            <div className="space-y-4 p-4">
              {(detail.isError || slots.isError) && (
                <div
                  role="alert"
                  className="rounded-xl border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive"
                >
                  <p className="flex items-center gap-2 font-medium">
                    <CircleAlert className="size-4" />
                    实时监控数据加载失败
                  </p>
                  <p className="mt-1 leading-5">
                    {detail.isError
                      ? "互动步骤暂时无法读取；"
                      : "浏览器画面暂时无法读取；"}
                    请检查服务或托管浏览器状态后点击刷新。
                  </p>
                </div>
              )}
              <div className="rounded-xl border bg-muted/25 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-xs text-muted-foreground">目标视频</p>
                    {detail.data ? (
                      <a
                        href={detail.data.target_video_url}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-1 block truncate font-mono text-sm font-medium text-primary hover:underline"
                      >
                        {detail.data.aweme_id}
                      </a>
                    ) : (
                      <p className="mt-1 text-sm text-muted-foreground">
                        正在读取…
                      </p>
                    )}
                  </div>
                  {detail.data && (
                    <Badge variant="secondary">
                      {interactionTypeLabels[detail.data.interaction_type]}
                    </Badge>
                  )}
                </div>
                <div className="mt-3">
                  {detail.data ? (
                    <InteractionContentSummary
                      interactionType={detail.data.interaction_type}
                      targetCommentId={detail.data.target_comment_id}
                      targetCommentContent={detail.data.target_comment_content}
                      content={detail.data.content}
                      compact
                    />
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      正在读取互动内容…
                    </p>
                  )}
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  账号：{detail.data?.account_name || "读取中"}
                </p>
              </div>

              <div>
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h3 className="flex items-center gap-2 font-medium">
                      <Route className="size-4 text-primary" />
                      执行链路
                    </h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      每秒刷新任务状态和浏览器操作步骤
                    </p>
                  </div>
                  <Badge variant="outline">{events.length} 步</Badge>
                </div>
                <div className="sr-only" aria-live="polite" aria-atomic="true">
                  {latestEvent
                    ? `最新步骤：${eventLabel(latestEvent.event)}`
                    : "等待执行步骤"}
                </div>
                <div className="mt-4 space-y-3 border-l pl-4">
                  {events.map((event, index) => (
                    <article
                      key={event.id}
                      className="relative rounded-xl border bg-card p-3 shadow-sm before:absolute before:-left-[1.3rem] before:top-4 before:size-2 before:rounded-full before:bg-primary"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-sm font-medium">
                          {eventLabel(event.event)}
                        </p>
                        <span className="shrink-0 text-[11px] text-muted-foreground">
                          {index + 1}/{events.length}
                        </span>
                      </div>
                      {event.detail && (
                        <p className="mt-1 text-xs leading-5 text-muted-foreground">
                          {event.detail}
                        </p>
                      )}
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                        <InteractionStatusBadge status={event.to_status} />
                        {event.attempt_number > 0 && (
                          <span>第 {event.attempt_number} 次</span>
                        )}
                        <time>{formatDate(event.created_at)}</time>
                      </div>
                    </article>
                  ))}
                  {!events.length && (
                    <div className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
                      正在等待任务进入执行队列…
                    </div>
                  )}
                </div>
              </div>
            </div>
          </aside>
        </div>
      </SheetContent>
    </Sheet>
  )
}

function eventLabel(event: string) {
  return eventLabels[event] || event.replace(/_/g, " ")
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value))
}
