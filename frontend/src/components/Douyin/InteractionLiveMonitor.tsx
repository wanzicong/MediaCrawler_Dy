import {
  CircleAlert,
  ExternalLink,
  Hourglass,
  MonitorPlay,
  RefreshCw,
  Route,
  ServerOff,
} from "lucide-react"
import { useMemo, useRef } from "react"

import { DouyinAccountsService, DouyinInteractionsService } from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
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
import { Skeleton } from "@/components/ui/skeleton"
import { useSmartPolling } from "@/hooks/useSmartPolling"
import { useVirtualRows, VIRTUALIZE_THRESHOLD } from "@/hooks/useVirtualRows"
import { formatTimeOnly } from "@/lib/time"

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
  const detail = useSmartPolling(
    ["douyin-interaction-live", interactionId],
    () =>
      DouyinInteractionsService.getInteraction({
        interactionId: interactionId!,
      }),
    {
      enabled: open && Boolean(interactionId),
      // 只有任务仍在执行（排队/运行）时才需要 1 秒级实时刷新，进入终态立即停止轮询
      isActive: (data) => data.status === "running" || data.status === "queued",
      activeInterval: 1_000,
      idleInterval: false,
    },
  )
  // 槽位轮询服务于「互动执行中」的浏览器画面，因此跟随互动状态决定是否继续
  const interactionStatus = detail.data?.status
  const slots = useSmartPolling(
    ["douyin-browser-monitor"],
    () => DouyinAccountsService.listBrowserSlots(),
    {
      enabled: open,
      // 互动详情尚未返回时保守保持轮询，避免错过浏览器上线；终态后浏览器画面不再变化，无需空转
      isActive: () =>
        interactionStatus === undefined ||
        interactionStatus === "running" ||
        interactionStatus === "queued",
      activeInterval: 2_000,
      idleInterval: false,
    },
  )
  const selectedSlot = useMemo(() => {
    const accountId = detail.data?.account_id
    const accountName = detail.data?.account_name
    return slots.data?.data.find(
      (slot) =>
        (accountId && slot.occupied_account_id === accountId) ||
        (accountName && slot.occupied_account_name === accountName),
    )
  }, [detail.data?.account_id, detail.data?.account_name, slots.data?.data])
  // 事件列表直接作为渲染数据源，memo 化以保持引用稳定，避免整棵树重复 diff
  const events = useMemo(() => detail.data?.events ?? [], [detail.data?.events])
  const latestEvent = useMemo(
    () => (events.length ? events[events.length - 1] : undefined),
    [events],
  )
  // 执行步骤是单页无上限的长列表（长链路可达上百步），超过阈值时启用虚拟滚动；
  // 短链路仍走原来的全量渲染路径，行为不变（报告 O19）
  const stepsScrollerRef = useRef<HTMLDivElement>(null)
  const stepsVirtualEnabled = events.length > VIRTUALIZE_THRESHOLD
  const stepsVirtualizer = useVirtualRows({
    count: events.length,
    scrollRef: stepsScrollerRef,
    estimateSize: 120,
    enabled: stepsVirtualEnabled,
  })
  const { virtualItems, totalSize } = stepsVirtualizer
  // 首帧滚动容器还没有高度，虚拟器会返回空列表；此处回退成全量渲染，避免闪空
  const stepsVirtualized = virtualItems.length > 0
  const paddingTop = stepsVirtualized ? virtualItems[0].start : 0
  const paddingBottom = stepsVirtualized
    ? totalSize - virtualItems[virtualItems.length - 1].end
    : 0
  const renderedEvents = stepsVirtualized
    ? virtualItems.map((item) => ({
        event: events[item.index],
        index: item.index,
      }))
    : events.map((event, index) => ({ event, index }))

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[96vw] gap-0 p-0 sm:max-w-[96vw] xl:w-[86vw] xl:max-w-[1500px]">
        <SheetHeader className="border-b px-5 py-4 pr-12">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <SheetTitle className="flex items-center gap-2">
                  <MonitorPlay
                    className="size-5 text-primary"
                    aria-hidden="true"
                  />
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
                    <ExternalLink aria-hidden="true" />
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
                    <MonitorPlay aria-hidden="true" />
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
                  aria-hidden="true"
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
                  <ServerOff
                    className="mx-auto size-10 opacity-60"
                    aria-hidden="true"
                  />
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
                    <CircleAlert className="size-4" aria-hidden="true" />
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
                      // 加载态用骨架屏占位，避免数据到达时内容跳动
                      <Skeleton className="mt-2 h-5 w-32" />
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
                    <div className="space-y-2">
                      <Skeleton className="h-4 w-4/5" />
                      <Skeleton className="h-4 w-3/5" />
                    </div>
                  )}
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  账号：
                  {detail.data?.account_name || (
                    <Skeleton className="inline-block h-3.5 w-20 align-middle" />
                  )}
                </p>
              </div>

              <div>
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h3 className="flex items-center gap-2 font-medium">
                      <Route
                        className="size-4 text-primary"
                        aria-hidden="true"
                      />
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
                {/* 长链路（步骤数超过阈值）走虚拟滚动，只渲染可视区；短链路仍全量渲染 */}
                <div
                  ref={stepsScrollerRef}
                  className={
                    stepsVirtualEnabled
                      ? "mt-4 max-h-[70vh] overflow-y-auto pl-1"
                      : "mt-4"
                  }
                >
                  {!events.length && (
                    <EmptyState
                      compact
                      className="rounded-xl border border-dashed"
                      icon={Hourglass}
                      title="还没有执行步骤"
                      description="任务进入执行队列后，这里会按秒刷新每一步浏览器操作；也可以手动刷新查看最新进度。"
                      action={
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={detail.isFetching}
                          onClick={() => void detail.refetch()}
                        >
                          <RefreshCw aria-hidden="true" />
                          刷新状态
                        </Button>
                      }
                    />
                  )}
                  {events.length > 0 && (
                    <div className="relative border-l pl-4">
                      {paddingTop > 0 && (
                        <div
                          style={{ height: paddingTop }}
                          aria-hidden="true"
                        />
                      )}
                      {renderedEvents.map(({ event, index }) => (
                        <div
                          key={event.id}
                          data-index={stepsVirtualized ? index : undefined}
                          ref={
                            stepsVirtualized
                              ? stepsVirtualizer.measureElement
                              : undefined
                          }
                          className="pb-3"
                        >
                          <article className="relative rounded-xl border bg-card p-3 shadow-sm before:absolute before:-left-[1.3rem] before:top-4 before:size-2 before:rounded-full before:bg-primary">
                            <div className="flex items-start justify-between gap-2">
                              <p className="text-sm font-medium">
                                {eventLabel(event.event)}
                              </p>
                              <span className="shrink-0 text-[10px] text-muted-foreground">
                                {index + 1}/{events.length}
                              </span>
                            </div>
                            {event.detail && (
                              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                                {event.detail}
                              </p>
                            )}
                            <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                              <InteractionStatusBadge
                                status={event.to_status}
                              />
                              {event.attempt_number > 0 && (
                                <span>第 {event.attempt_number} 次</span>
                              )}
                              <time>{formatTimeOnly(event.created_at)}</time>
                            </div>
                          </article>
                        </div>
                      ))}
                      {paddingBottom > 0 && (
                        <div
                          style={{ height: paddingBottom }}
                          aria-hidden="true"
                        />
                      )}
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
