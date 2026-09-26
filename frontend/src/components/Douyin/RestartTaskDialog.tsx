import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"

import {
  type CrawlTaskPublic,
  DouyinAccountsService,
  DouyinService,
} from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
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

/**
 * 「从头重启」弹窗：清空断点重新采集，并允许换用其他可用账号。
 *
 * 原执行账号被停用、删除或转入异常后，任务快照里的账号已经不能再用；
 * 此时如果只确认一下就直接重启，用户只会反复看到「账号不可用」，
 * 所以这里和断点续爬一样给出账号切换入口，并在原账号失效时默认选中可用账号。
 */
export function RestartTaskDialog({
  task,
  open,
  onOpenChange,
}: {
  task: CrawlTaskPublic
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [accountChoice, setAccountChoice] = useState("original")
  const [cookies, setCookies] = useState("")
  /** 只在本次打开时自动换一次账号，避免覆盖用户的手动选择 */
  const [autoPicked, setAutoPicked] = useState(false)
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const cookieTask = task.request.login_type === "cookie"
  const accountsQuery = useQuery({
    queryKey: ["douyin-accounts"],
    queryFn: () => DouyinAccountsService.listAccounts({ limit: 100 }),
    enabled: open,
  })
  const availableAccounts = (accountsQuery.data?.data ?? []).filter((account) =>
    ["ready", "busy"].includes(account.status),
  )
  // 任务绑定过账号、但该账号已不在可用列表里：重启必然会失败，先替用户选好可用账号
  const originalUnavailable =
    task.account_id !== null &&
    !availableAccounts.some((account) => account.id === task.account_id)
  useEffect(() => {
    if (!open || autoPicked || !originalUnavailable) return
    if (accountsQuery.isLoading) return
    setAutoPicked(true)
    const [first] = availableAccounts
    if (first) setAccountChoice(first.id)
  }, [
    accountsQuery.isLoading,
    autoPicked,
    availableAccounts,
    open,
    originalUnavailable,
  ])

  const mutation = useMutation({
    mutationFn: () =>
      DouyinService.restartTask({
        taskId: task.id,
        requestBody: {
          account_id: accountChoice === "original" ? undefined : accountChoice,
          cookies:
            accountChoice === "original" && cookies.trim()
              ? cookies.trim()
              : undefined,
        },
      }),
    onSuccess: async () => {
      showSuccessToast("任务已清空断点并从头重新入队")
      onOpenChange(false)
      setCookies("")
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] }),
        queryClient.invalidateQueries({ queryKey: ["douyin-task", task.id] }),
      ])
    },
    onError: handleError.bind(showErrorToast),
  })

  const openChanged = (next: boolean) => {
    onOpenChange(next)
    if (next) {
      setCookies("")
      setAutoPicked(false)
      setAccountChoice("original")
    }
  }
  /**
   * 原账号已不可用、又没有替代账号时直接拦住提交：
   * 否则这次重启注定失败（原账号根本选不出来），只会白白浪费一次点击。
   */
  const blockedByAccount = originalUnavailable && accountChoice === "original"

  return (
    <Dialog open={open} onOpenChange={openChanged}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>从头重启任务</DialogTitle>
          <DialogDescription>
            已保存的作品、视频和字幕会保留，但断点会被清空，本任务从头重新采集。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="restart-account">重启执行账号</Label>
            <Select value={accountChoice} onValueChange={setAccountChoice}>
              <SelectTrigger id="restart-account" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="original">
                  {task.account_name
                    ? `沿用原账号 · ${task.account_name}`
                    : task.account_pool_name
                      ? `沿用原账号池 · ${task.account_pool_name}`
                      : "沿用原任务登录方式"}
                </SelectItem>
                {availableAccounts.map((account) => (
                  <SelectItem key={account.id} value={account.id}>
                    改用账号 · {account.name}
                    {account.status === "busy" ? "（繁忙时自动排队）" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {originalUnavailable && (
              <p className="text-xs text-destructive">
                原执行账号已停用、删除或转为异常状态，无法再用于采集；
                {availableAccounts.length
                  ? "已默认改用下面选中的可用账号。"
                  : "当前没有可用账号，请先到「账号管理」恢复或新增账号。"}
              </p>
            )}
            {accountsQuery.isError && (
              <div className="flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
                <span>可用账号读取失败，请重试后再选择。</span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={accountsQuery.isFetching}
                  onClick={() => void accountsQuery.refetch()}
                >
                  重试
                </Button>
              </div>
            )}
          </div>

          {cookieTask && accountChoice === "original" && (
            <div className="space-y-2">
              <Label htmlFor="restart-cookies">临时登录凭据（可选）</Label>
              <Textarea
                id="restart-cookies"
                value={cookies}
                autoComplete="off"
                placeholder="sessionid=...；留空将复用浏览器登录状态"
                onChange={(event) => setCookies(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                登录凭据只用于本次重启，任务受理后自动清除。
              </p>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => openChanged(false)}>
            取消
          </Button>
          <Button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || blockedByAccount}
            title={
              blockedByAccount
                ? "原执行账号不可用，请先选择其他可用账号"
                : undefined
            }
          >
            {mutation.isPending ? "重启中…" : "确认重启"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
