import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  ExternalLink,
  MessagesSquare,
  MonitorPlay,
  RefreshCw,
} from "lucide-react"
import { useState } from "react"

import {
  type DouyinInteractionPublic,
  DouyinInteractionsService,
} from "@/client"
import { InteractionLiveMonitor } from "@/components/Douyin/InteractionLiveMonitor"
import {
  InteractionStatusBadge,
  interactionTypeLabels,
} from "@/components/Douyin/InteractionStatusBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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

export function TaskInteractionsPanel({ taskId }: { taskId: string }) {
  const [monitorId, setMonitorId] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const query = useQuery({
    queryKey: ["douyin-task-interactions", taskId],
    queryFn: () =>
      DouyinInteractionsService.listInteractions({ taskId, limit: 10 }),
    refetchInterval: (result) =>
      result.state.data?.data.some((item) =>
        ["queued", "running"].includes(item.status),
      )
        ? 2_000
        : 5_000,
  })
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["douyin-task-interactions", taskId],
      }),
      queryClient.invalidateQueries({ queryKey: ["douyin-interactions"] }),
      queryClient.invalidateQueries({
        queryKey: ["douyin-interaction-quota"],
      }),
    ])
  }
  const confirm = useMutation({
    mutationFn: (id: string) =>
      DouyinInteractionsService.confirmInteraction({ interactionId: id }),
    onSuccess: async () => {
      showSuccessToast("互动任务已进入发送队列")
      await refresh()
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
      await refresh()
    },
    onError: handleError.bind(showErrorToast),
  })
  const cancel = useMutation({
    mutationFn: (id: string) =>
      DouyinInteractionsService.cancelInteraction({ interactionId: id }),
    onSuccess: refresh,
    onError: handleError.bind(showErrorToast),
  })
  const rows = query.data?.data ?? []

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-3">
        <div>
          <CardTitle className="flex items-center gap-2">
            <MessagesSquare className="size-5" />
            互动任务
          </CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">
            评论、回复和作者私信均需要人工确认，并通过托管账号的 CDP
            浏览器执行。
          </p>
        </div>
        <Button variant="outline" size="sm" asChild>
          <Link to="/douyin-interactions">查看全部</Link>
        </Button>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto rounded-xl border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>类型</TableHead>
                <TableHead>内容</TableHead>
                <TableHead>账号</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>时间</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length ? (
                rows.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell>
                      <p>{interactionTypeLabels[item.interaction_type]}</p>
                      <a
                        href={item.target_video_url}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-1 inline-flex items-center gap-1 font-mono text-xs text-primary hover:underline"
                      >
                        {item.aweme_id}
                        <ExternalLink className="size-3" />
                      </a>
                    </TableCell>
                    <TableCell className="max-w-sm">
                      <p className="line-clamp-2">{item.content_preview}</p>
                      {item.error && (
                        <p className="mt-1 line-clamp-2 text-xs text-destructive">
                          {item.error}
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
                            onClick={() => {
                              if (
                                item.status !== "needs_review" ||
                                window.confirm(
                                  "请先到抖音页面确认这条内容没有发送成功。确认未发送并重试吗？",
                                )
                              ) {
                                retry.mutate(item)
                              }
                            }}
                          >
                            <RefreshCw />
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
                    className="h-28 text-center text-muted-foreground"
                  >
                    {query.isLoading
                      ? "加载互动任务..."
                      : "暂无互动任务，可从视频或评论操作中创建"}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>
      <InteractionLiveMonitor
        interactionId={monitorId}
        open={Boolean(monitorId)}
        onOpenChange={(open) => !open && setMonitorId(null)}
      />
    </Card>
  )
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value))
}
