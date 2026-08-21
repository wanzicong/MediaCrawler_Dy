import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { MessageCircle, MessagesSquare, MonitorPlay, Reply } from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import {
  DouyinAccountsService,
  type DouyinAwemePublic,
  type DouyinCommentPublic,
  type DouyinInteractionCreate,
  type DouyinInteractionPublic,
  DouyinInteractionsService,
  type DouyinInteractionType,
  DouyinService,
  DouyinTracksService,
} from "@/client"
import { InteractionLiveMonitor } from "@/components/Douyin/InteractionLiveMonitor"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

const labels: Record<
  DouyinInteractionType,
  { title: string; action: string; description: string }
> = {
  video_comment: {
    title: "评论视频",
    action: "评论",
    description: "评论将通过所选托管账号的专属浏览器发送。",
  },
  comment_reply: {
    title: "回复评论",
    action: "回复",
    description: "系统会在作品评论区定位这条评论，再通过专属浏览器发送回复。",
  },
  creator_message: {
    title: "私信作者",
    action: "私信",
    description:
      "作者标识只在执行时从作品详情临时解析，不会留存在内容数据或操作记录中。",
  },
}

export function InteractionComposerDialog({
  taskId,
  aweme,
  interactionType,
  targetComment,
  compact = false,
  controlledOpen,
  onControlledOpenChange,
  hideTrigger = false,
}: {
  taskId: string
  aweme: DouyinAwemePublic
  interactionType: DouyinInteractionType
  targetComment?: DouyinCommentPublic
  compact?: boolean
  controlledOpen?: boolean
  onControlledOpenChange?: (open: boolean) => void
  hideTrigger?: boolean
}) {
  const [internalOpen, setInternalOpen] = useState(false)
  const [accountId, setAccountId] = useState("")
  const [content, setContent] = useState("")
  const [prepared, setPrepared] = useState<DouyinInteractionPublic | null>(null)
  const [monitorInteractionId, setMonitorInteractionId] = useState<
    string | null
  >(null)
  const [monitorOpen, setMonitorOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const copy = labels[interactionType]
  const contentLimit = interactionType === "creator_message" ? 1000 : 2200
  const open = controlledOpen ?? internalOpen
  const setOpen = (value: boolean) => {
    setInternalOpen(value)
    onControlledOpenChange?.(value)
  }

  const accounts = useQuery({
    queryKey: ["douyin-accounts"],
    queryFn: () => DouyinAccountsService.listAccounts({ limit: 100 }),
    enabled: open,
  })
  const task = useQuery({
    queryKey: ["douyin-task", taskId],
    queryFn: () => DouyinService.getTask({ taskId }),
    enabled: open && interactionType !== "creator_message",
  })
  const trackId = task.data?.track_id
  const track = useQuery({
    queryKey: ["douyin-track", trackId],
    queryFn: () => DouyinTracksService.getTrack({ trackId: trackId ?? "" }),
    enabled: open && Boolean(trackId),
  })
  const replyTemplates = track.data?.reply_templates ?? []
  const quotas = useQuery({
    queryKey: ["douyin-interaction-quota"],
    queryFn: () => DouyinInteractionsService.listInteractionQuota(),
    enabled: open,
    refetchInterval: open ? 5_000 : false,
  })
  const quotaMap = useMemo(
    () => new Map((quotas.data ?? []).map((item) => [item.account_id, item])),
    [quotas.data],
  )
  const usableAccounts =
    accounts.data?.data.filter((account) => account.enabled) ?? []

  useEffect(() => {
    if (!accountId && usableAccounts.length) {
      const available = usableAccounts.find(
        (account) => quotaMap.get(account.id)?.available,
      )
      setAccountId((available ?? usableAccounts[0]).id)
    }
  }, [accountId, quotaMap, usableAccounts])

  const payload = (): DouyinInteractionCreate => ({
    task_id: taskId,
    aweme_id: aweme.aweme_id,
    account_id: accountId,
    interaction_type: interactionType,
    target_comment_id: targetComment?.comment_id,
    content: content.trim(),
  })

  const prepare = useMutation({
    mutationFn: async () => {
      const requestBody = payload()
      const checked = await DouyinInteractionsService.preflightInteraction({
        requestBody,
      })
      if (!checked.allowed) throw new Error(checked.message)
      return DouyinInteractionsService.prepareInteraction({ requestBody })
    },
    onSuccess: async (interaction) => {
      setPrepared(interaction)
      showSuccessToast("发送前检查通过，草稿已保存，请再次确认发送")
      await invalidateInteractions(queryClient, taskId)
    },
    onError: (error) => {
      if (error instanceof Error && !("body" in error)) {
        showErrorToast(error.message)
        return
      }
      handleError.call(showErrorToast, error as never)
    },
  })
  const confirm = useMutation({
    mutationFn: ({
      interactionId,
    }: {
      interactionId: string
      monitor: boolean
    }) => DouyinInteractionsService.confirmInteraction({ interactionId }),
    onSuccess: async (_, variables) => {
      showSuccessToast("互动任务已确认并进入浏览器执行队列")
      if (variables.monitor) {
        setMonitorInteractionId(variables.interactionId)
        setMonitorOpen(true)
      }
      resetAndClose()
      await invalidateInteractions(queryClient, taskId)
    },
    onError: handleError.bind(showErrorToast),
  })

  const resetAndClose = () => {
    setOpen(false)
    setContent("")
    setPrepared(null)
  }
  const selectedQuota = quotaMap.get(accountId)
  const Icon =
    interactionType === "creator_message"
      ? MessagesSquare
      : interactionType === "comment_reply"
        ? Reply
        : MessageCircle

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(value) => {
          setOpen(value)
          if (!value) {
            setContent("")
            setPrepared(null)
          }
        }}
      >
        {!hideTrigger && (
          <DialogTrigger asChild>
            <Button
              size="sm"
              variant={compact ? "ghost" : "outline"}
              className={compact ? "h-7 px-2 text-xs" : undefined}
              aria-label={copy.action}
            >
              <Icon />
              {copy.action}
            </Button>
          </DialogTrigger>
        )}
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{copy.title}</DialogTitle>
            <DialogDescription>{copy.description}</DialogDescription>
          </DialogHeader>

          <div className="space-y-5 py-2">
            <div className="rounded-xl border bg-muted/25 p-4">
              <p className="line-clamp-2 font-medium">
                {aweme.title || aweme.aweme_id}
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                {aweme.nickname || "匿名作者"} · {aweme.aweme_id}
              </p>
              {targetComment && (
                <div className="mt-3 rounded-lg bg-background p-3 text-sm">
                  <p className="text-xs text-muted-foreground">
                    回复 {targetComment.nickname || "匿名用户"}
                  </p>
                  <p className="mt-1 line-clamp-3">{targetComment.content}</p>
                </div>
              )}
            </div>

            <div className="space-y-2">
              <Label>发送账号</Label>
              <Select
                value={accountId}
                onValueChange={setAccountId}
                disabled={Boolean(prepared)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="选择一个已登录账号" />
                </SelectTrigger>
                <SelectContent>
                  {usableAccounts.map((account) => {
                    const quota = quotaMap.get(account.id)
                    return (
                      <SelectItem key={account.id} value={account.id}>
                        {account.name} ·{" "}
                        {quota?.available ? "可用" : "暂不可用"}
                      </SelectItem>
                    )
                  })}
                </SelectContent>
              </Select>
              {selectedQuota && (
                <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                  <Badge
                    variant={
                      selectedQuota.available ? "outline" : "destructive"
                    }
                  >
                    今日剩余 {selectedQuota.remaining_today}/
                    {selectedQuota.daily_limit}
                  </Badge>
                  <span>最小间隔 {selectedQuota.min_interval_seconds} 秒</span>
                </div>
              )}
              {!usableAccounts.length && !accounts.isLoading && (
                <p className="text-sm text-destructive">
                  没有可选账号，请先在账号池页面添加并登录账号。
                </p>
              )}
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor={`interaction-content-${interactionType}`}>
                  发送内容
                </Label>
                <span className="text-xs text-muted-foreground">
                  {content.length}/{contentLimit}
                </span>
              </div>
              {replyTemplates.length > 0 && (
                <Select
                  value=""
                  onValueChange={setContent}
                  disabled={Boolean(prepared)}
                >
                  <SelectTrigger aria-label="选择赛道回复话术">
                    <SelectValue placeholder="从当前赛道的话术库选择（可选）" />
                  </SelectTrigger>
                  <SelectContent>
                    {replyTemplates.map((template) => (
                      <SelectItem key={template} value={template}>
                        {template}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              <Textarea
                id={`interaction-content-${interactionType}`}
                value={content}
                maxLength={contentLimit}
                rows={6}
                disabled={Boolean(prepared)}
                placeholder={`输入要${copy.action}的内容`}
                onChange={(event) => setContent(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                内容会加密保存，不会写入应用日志。重复目标和内容在 24
                小时内会被拦截。
              </p>
            </div>

            {prepared && (
              <Alert>
                <MessageCircle />
                <AlertTitle>等待最终确认</AlertTitle>
                <AlertDescription>
                  草稿已经保存，但尚未发送。点击“确认并发送”后才会进入浏览器执行队列。
                </AlertDescription>
              </Alert>
            )}
          </div>

          <DialogFooter className="flex-wrap">
            <Button variant="outline" onClick={resetAndClose}>
              {prepared ? "稍后处理" : "取消"}
            </Button>
            {prepared ? (
              <>
                <Button
                  variant="outline"
                  disabled={confirm.isPending}
                  onClick={() =>
                    confirm.mutate({
                      interactionId: prepared.id,
                      monitor: true,
                    })
                  }
                >
                  <MonitorPlay />
                  发送并查看实时监控
                </Button>
                <Button
                  disabled={confirm.isPending}
                  onClick={() =>
                    confirm.mutate({
                      interactionId: prepared.id,
                      monitor: false,
                    })
                  }
                >
                  {confirm.isPending ? "确认中..." : "确认并发送"}
                </Button>
              </>
            ) : (
              <Button
                disabled={
                  prepare.isPending ||
                  !accountId ||
                  !content.trim() ||
                  selectedQuota?.available === false
                }
                onClick={() => prepare.mutate()}
              >
                {prepare.isPending ? "检查中..." : "发送前检查"}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <InteractionLiveMonitor
        interactionId={monitorInteractionId}
        open={monitorOpen}
        onOpenChange={setMonitorOpen}
      />
    </>
  )
}

async function invalidateInteractions(
  queryClient: ReturnType<typeof useQueryClient>,
  taskId: string,
) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["douyin-interactions"] }),
    queryClient.invalidateQueries({
      queryKey: ["douyin-task-interactions", taskId],
    }),
    queryClient.invalidateQueries({ queryKey: ["douyin-interaction-quota"] }),
  ])
}
