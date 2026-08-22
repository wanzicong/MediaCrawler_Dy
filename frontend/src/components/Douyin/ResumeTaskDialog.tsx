import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { RotateCcw } from "lucide-react"
import { useState } from "react"

import {
  type CrawlTaskPublic,
  DouyinAccountsService,
  DouyinService,
} from "@/client"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
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

export function ResumeTaskDialog({ task }: { task: CrawlTaskPublic }) {
  const [open, setOpen] = useState(false)
  const [resumeCrawl, setResumeCrawl] = useState(task.can_resume_crawl)
  const [resumeMedia, setResumeMedia] = useState(task.can_resume_media)
  const [cookies, setCookies] = useState("")
  const [taskInterval, setTaskInterval] = useState("")
  const [accountChoice, setAccountChoice] = useState("original")
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const cookieTask = task.request.login_type === "cookie"
  const accountsQuery = useQuery({
    queryKey: ["douyin-accounts"],
    queryFn: () => DouyinAccountsService.listAccounts({ limit: 100 }),
    enabled: open && resumeCrawl,
  })
  const availableAccounts = (accountsQuery.data?.data ?? []).filter((account) =>
    ["ready", "busy"].includes(account.status),
  )
  const mutation = useMutation({
    mutationFn: () =>
      DouyinService.resumeTask({
        taskId: task.id,
        requestBody: {
          resume_crawl: resumeCrawl,
          resume_media: resumeMedia,
          task_interval_seconds: taskInterval.trim()
            ? Number(taskInterval)
            : undefined,
          cookies:
            (resumeCrawl || resumeMedia) &&
            accountChoice === "original" &&
            cookies.trim()
              ? cookies.trim()
              : undefined,
          account_id:
            resumeCrawl && accountChoice !== "original"
              ? accountChoice
              : undefined,
        },
      }),
    onSuccess: async (resumedTask) => {
      queryClient.setQueryData(["douyin-task", task.id], resumedTask)
      showSuccessToast("恢复请求已受理，后台正在从断点继续")
      setOpen(false)
      setCookies("")
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["douyin-task", task.id] }),
        queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] }),
        queryClient.invalidateQueries({ queryKey: ["douyin-media", task.id] }),
        queryClient.invalidateQueries({
          queryKey: ["douyin-media-summary", task.id],
        }),
      ])
    },
    onError: handleError.bind(showErrorToast),
  })

  const openChanged = (next: boolean) => {
    setOpen(next)
    if (next) {
      setResumeCrawl(task.can_resume_crawl)
      setResumeMedia(task.can_resume_media)
      setCookies("")
      setTaskInterval(
        task.request.task_interval_seconds == null
          ? ""
          : String(task.request.task_interval_seconds),
      )
      setAccountChoice("original")
    }
  }

  return (
    <Dialog open={open} onOpenChange={openChanged}>
      <DialogTrigger asChild>
        <Button>
          <RotateCcw />
          继续任务
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>从断点继续任务</DialogTitle>
          <DialogDescription>
            已保存的作品、视频和字幕不会删除；完成项会自动跳过，只处理未完成或中断项。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <ResumeScope
            id="resume-crawl"
            checked={resumeCrawl}
            disabled={!task.can_resume_crawl}
            title="继续爬取"
            description="从已保存的页码、游标或目标位置继续，并补齐中断页的评论。"
            onChange={setResumeCrawl}
          />
          <ResumeScope
            id="resume-media"
            checked={resumeMedia}
            disabled={!task.can_resume_media}
            title="继续视频下载和字幕"
            description="跳过已完成文件，恢复缺失或失败的下载与远程字幕任务。"
            onChange={setResumeMedia}
          />

          {resumeCrawl && (
            <div className="space-y-2">
              <Label htmlFor="resume-account">恢复执行账号</Label>
              <Select value={accountChoice} onValueChange={setAccountChoice}>
                <SelectTrigger id="resume-account" className="w-full">
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
              <p className="text-xs text-muted-foreground">
                原账号异常、停用或需要重新登录时，可改用其他可用账号；选择后会同步更新任务的执行账号。
              </p>
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
          )}

          {(resumeCrawl || resumeMedia) &&
            cookieTask &&
            accountChoice === "original" && (
              <div className="space-y-2">
                <Label htmlFor="resume-cookies">临时登录凭据（可选）</Label>
                <Textarea
                  id="resume-cookies"
                  value={cookies}
                  autoComplete="off"
                  placeholder="sessionid=...；爬取留空将复用浏览器登录状态，媒体下载会直接重试"
                  onChange={(event) => setCookies(event.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  登录凭据只用于本次恢复，任务受理后自动清除。
                </p>
              </div>
            )}

          {(resumeCrawl || resumeMedia) && (
            <div className="space-y-2">
              <Label htmlFor="resume-task-interval">
                恢复后的任务间隔（秒）
              </Label>
              <Input
                id="resume-task-interval"
                type="number"
                min={0}
                max={3600}
                step={1}
                value={taskInterval}
                placeholder="沿用原任务配置"
                onChange={(event) => setTaskInterval(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                留空沿用原任务配置；填 0 表示恢复后不额外等待下一任务。
              </p>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || (!resumeCrawl && !resumeMedia)}
          >
            {mutation.isPending ? "恢复中…" : "确认继续"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ResumeScope({
  id,
  checked,
  disabled,
  title,
  description,
  onChange,
}: {
  id: string
  checked: boolean
  disabled: boolean
  title: string
  description: string
  onChange: (checked: boolean) => void
}) {
  return (
    <div className="flex items-start gap-3 rounded-lg border p-3">
      <Checkbox
        id={id}
        checked={checked}
        disabled={disabled}
        onCheckedChange={(value) => onChange(value === true)}
      />
      <div className="space-y-1">
        <Label htmlFor={id}>{title}</Label>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
    </div>
  )
}
