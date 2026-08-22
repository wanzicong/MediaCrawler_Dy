import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { MessageCircle } from "lucide-react"
import { type ReactNode, useEffect, useMemo, useState } from "react"

import {
  DouyinAccountsService,
  type DouyinBatchCommentCreate,
  type DouyinBatchCommentMode,
  type DouyinBatchCommentPublic,
  DouyinInteractionsService,
  type DouyinWorkPublic,
} from "@/client"
import { Alert, AlertDescription } from "@/components/ui/alert"
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
import { Input } from "@/components/ui/input"
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

type DelayUnit = "seconds" | "minutes" | "hours"
type DelayMode = "fixed" | "random"

const delayMultipliers: Record<DelayUnit, number> = {
  seconds: 1,
  minutes: 60,
  hours: 3600,
}

const delayUnitLabels: Record<DelayUnit, string> = {
  seconds: "秒",
  minutes: "分钟",
  hours: "小时",
}

export function BatchCommentDialog({
  selectedWorks,
  onCreated,
  children,
}: {
  selectedWorks: DouyinWorkPublic[]
  onCreated?: (result: DouyinBatchCommentPublic) => void
  children?: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const [accountChoice, setAccountChoice] = useState("")
  const [mode, setMode] = useState<DouyinBatchCommentMode>("one_per_video")
  const [commentsText, setCommentsText] = useState("")
  const [delayMode, setDelayMode] = useState<DelayMode>("fixed")
  const [delayUnit, setDelayUnit] = useState<DelayUnit>("minutes")
  const [delayMin, setDelayMin] = useState("1")
  const [delayMax, setDelayMax] = useState("5")
  const [accountStrategy, setAccountStrategy] = useState<
    "least_loaded" | "round_robin" | "weighted_round_robin"
  >("least_loaded")
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()

  const accounts = useQuery({
    queryKey: ["douyin-accounts"],
    queryFn: () => DouyinAccountsService.listAccounts({ limit: 100 }),
    enabled: open,
  })
  const pools = useQuery({
    queryKey: ["douyin-account-pools"],
    queryFn: () => DouyinAccountsService.listPools(),
    enabled: open,
  })
  const options = useMemo(() => {
    const accountOptions = (accounts.data?.data ?? [])
      .filter((item) => item.enabled)
      .map((item) => ({
        value: `account:${item.id}`,
        label: `账号 · ${item.name}${item.is_logged_in ? " · 已登录" : " · 未登录"}`,
      }))
    const poolOptions = (pools.data?.data ?? [])
      .filter((item) => item.enabled)
      .map((item) => ({
        value: `pool:${item.id}`,
        label: `账号池 · ${item.name}（${item.accounts.length} 个账号）`,
      }))
    return [...accountOptions, ...poolOptions]
  }, [accounts.data?.data, pools.data?.data])

  useEffect(() => {
    if (open && !accountChoice && options.length) {
      setAccountChoice(options[0].value)
    }
  }, [accountChoice, open, options])

  const comments = useMemo(
    () =>
      commentsText
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean),
    [commentsText],
  )
  const plannedCount =
    mode === "one_per_video"
      ? selectedWorks.length
      : selectedWorks.length * comments.length
  const selectedPool = accountChoice.startsWith("pool:")
  const invalidDelayRange =
    delayMode === "random" && Number(delayMax || 0) < Number(delayMin || 0)

  const createBatch = useMutation({
    mutationFn: () => {
      const requestBody: DouyinBatchCommentCreate = {
        targets: selectedWorks.map((work) => ({
          task_id: work.aweme.task_id,
          aweme_id: work.aweme.aweme_id,
        })),
        comments,
        mode,
        account_id: accountChoice.startsWith("account:")
          ? accountChoice.slice("account:".length)
          : undefined,
        account_pool_id: selectedPool
          ? accountChoice.slice("pool:".length)
          : undefined,
        account_strategy: selectedPool ? accountStrategy : undefined,
        delay_min_seconds: Number(delayMin || 0) * delayMultipliers[delayUnit],
        delay_max_seconds:
          Number(
            delayMode === "fixed" ? delayMin || 0 : delayMax || delayMin || 0,
          ) * delayMultipliers[delayUnit],
      }
      return DouyinInteractionsService.createBatchComments({ requestBody })
    },
    onSuccess: async (result) => {
      showSuccessToast(result.message)
      setOpen(false)
      setCommentsText("")
      setAccountChoice("")
      onCreated?.(result)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["douyin-interactions"] }),
        queryClient.invalidateQueries({
          queryKey: ["douyin-task-interactions"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["douyin-interaction-quota"],
        }),
      ])
    },
    onError: handleError.bind(showErrorToast),
  })

  const submitDisabled =
    !selectedWorks.length ||
    !accountChoice ||
    !comments.length ||
    plannedCount > 500 ||
    invalidDelayRange ||
    createBatch.isPending

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {children ?? (
          <Button disabled={!selectedWorks.length}>
            <MessageCircle />
            批量发送评论
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>批量发送评论</DialogTitle>
          <DialogDescription>
            已选择 {selectedWorks.length}{" "}
            个视频。每条评论会生成独立任务，发送中、排队和失败状态可在“互动任务”中逐条查看。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-2">
          <div className="rounded-xl border bg-muted/25 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">目标视频 {selectedWorks.length}</Badge>
              <Badge variant={plannedCount > 500 ? "destructive" : "outline"}>
                将创建 {plannedCount} 条任务
              </Badge>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              最多一次创建 500 条。单条评论不能超过 2200 个字符。
            </p>
          </div>

          <div className="space-y-2">
            <Label>发送账号或账号池</Label>
            <Select value={accountChoice} onValueChange={setAccountChoice}>
              <SelectTrigger>
                <SelectValue placeholder="选择账号或账号池" />
              </SelectTrigger>
              <SelectContent>
                {options.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {!options.length && !accounts.isLoading && !pools.isLoading && (
              <p className="text-sm text-destructive">
                没有可用的账号或账号池，请先完成账号登录。
              </p>
            )}
          </div>

          {selectedPool && (
            <div className="space-y-2">
              <Label>账号池调度策略</Label>
              <Select
                value={accountStrategy}
                onValueChange={(value) =>
                  setAccountStrategy(value as typeof accountStrategy)
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="least_loaded">最少负载优先</SelectItem>
                  <SelectItem value="round_robin">轮询</SelectItem>
                  <SelectItem value="weighted_round_robin">加权轮询</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="space-y-2">
            <Label>评论分配方式</Label>
            <Select
              value={mode}
              onValueChange={(value) =>
                setMode(value as DouyinBatchCommentMode)
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="one_per_video">
                  每个视频一条，评论列表按顺序循环
                </SelectItem>
                <SelectItem value="all_per_video">
                  每个视频依次发送全部评论
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="batch-comment-content">评论内容</Label>
              <span className="text-xs text-muted-foreground">
                一行一条 · 已识别 {comments.length} 条
              </span>
            </div>
            <Textarea
              id="batch-comment-content"
              value={commentsText}
              onChange={(event) => setCommentsText(event.target.value)}
              placeholder={
                "输入评论内容，一行一条\n例如：\n这个观点很有启发\n已收藏，后面继续学习"
              }
              rows={7}
              maxLength={20_000}
            />
          </div>

          <div className="space-y-3 rounded-xl border p-4">
            <div className="space-y-2">
              <Label>任务之间的发送间隔</Label>
              <Select
                value={delayMode}
                onValueChange={(value) => setDelayMode(value as DelayMode)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="fixed">固定间隔</SelectItem>
                  <SelectItem value="random">随机区间</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
              <div className="space-y-2">
                <Label htmlFor="batch-comment-delay-min">
                  {delayMode === "fixed" ? "间隔" : "最短间隔"}
                </Label>
                <Input
                  id="batch-comment-delay-min"
                  type="number"
                  min="0"
                  step="1"
                  value={delayMin}
                  onChange={(event) => setDelayMin(event.target.value)}
                />
              </div>
              {delayMode === "random" ? (
                <div className="space-y-2">
                  <Label htmlFor="batch-comment-delay-max">最长间隔</Label>
                  <Input
                    id="batch-comment-delay-max"
                    type="number"
                    min="0"
                    step="1"
                    value={delayMax}
                    onChange={(event) => setDelayMax(event.target.value)}
                  />
                </div>
              ) : (
                <div className="hidden sm:block" />
              )}
              <div className="space-y-2">
                <Label>单位</Label>
                <Select
                  value={delayUnit}
                  onValueChange={(value) => setDelayUnit(value as DelayUnit)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(delayUnitLabels).map(([value, label]) => (
                      <SelectItem key={value} value={value}>
                        {label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              第一条会立即进入队列，后续任务按这里的固定间隔或随机区间计划发送；设置为
              0 秒即可连续排队。
            </p>
          </div>

          {invalidDelayRange && (
            <Alert variant="destructive">
              <AlertDescription>最长间隔不能小于最短间隔。</AlertDescription>
            </Alert>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button
            disabled={submitDisabled}
            onClick={() => createBatch.mutate()}
          >
            {createBatch.isPending
              ? "创建中…"
              : `创建 ${plannedCount} 条评论任务`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
