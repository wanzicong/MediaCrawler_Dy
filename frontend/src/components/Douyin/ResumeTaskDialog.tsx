import { useMutation, useQueryClient } from "@tanstack/react-query"
import { RotateCcw } from "lucide-react"
import { useState } from "react"

import { type CrawlTaskPublic, DouyinService } from "@/client"
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
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

export function ResumeTaskDialog({ task }: { task: CrawlTaskPublic }) {
  const [open, setOpen] = useState(false)
  const [resumeCrawl, setResumeCrawl] = useState(task.can_resume_crawl)
  const [resumeMedia, setResumeMedia] = useState(task.can_resume_media)
  const [cookies, setCookies] = useState("")
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const cookieTask = task.request.login_type === "cookie"
  const mutation = useMutation({
    mutationFn: () =>
      DouyinService.resumeTask({
        taskId: task.id,
        requestBody: {
          resume_crawl: resumeCrawl,
          resume_media: resumeMedia,
          cookies:
            (resumeCrawl || resumeMedia) && cookies.trim()
              ? cookies.trim()
              : undefined,
        },
      }),
    onSuccess: async () => {
      showSuccessToast("任务已从断点继续")
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

          {(resumeCrawl || resumeMedia) && cookieTask && (
            <div className="space-y-2">
              <Label htmlFor="resume-cookies">Cookie（可选）</Label>
              <Textarea
                id="resume-cookies"
                value={cookies}
                autoComplete="off"
                placeholder="sessionid=...；爬取留空将复用 CDP 登录态，媒体下载会直接重试"
                onChange={(event) => setCookies(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Cookie 只用于本次恢复，不会保存到数据库或返回给前端。
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
