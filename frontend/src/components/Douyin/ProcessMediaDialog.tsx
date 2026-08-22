import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Film } from "lucide-react"
import { useEffect, useState } from "react"

import {
  type CrawlTaskPublic,
  DouyinService,
  DouyinTracksService,
  type MediaStorageBackend,
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

type StorageChoice = MediaStorageBackend | "default"
type MediaSourceTask = Pick<
  CrawlTaskPublic,
  "id" | "track_id" | "aweme_count" | "request"
>

function taskStorage(task: MediaSourceTask): StorageChoice {
  const value = task.request.media_storage
  return value === "local" || value === "minio" ? value : "default"
}

function taskLanguage(task: MediaSourceTask): string {
  const value = task.request.transcription_language
  return typeof value === "string" && value.trim() ? value : "auto"
}

export function ProcessMediaDialog({
  task,
  triggerLabel = "创建下载任务",
  triggerVariant = "default",
}: {
  task: MediaSourceTask
  triggerLabel?: string
  triggerVariant?: React.ComponentProps<typeof Button>["variant"]
}) {
  const [open, setOpen] = useState(false)
  const [storage, setStorage] = useState<StorageChoice>(taskStorage(task))
  const [translate, setTranslate] = useState(false)
  const [subtitleOnly, setSubtitleOnly] = useState(false)
  const [forceRetranslate, setForceRetranslate] = useState(false)
  const [language, setLanguage] = useState(taskLanguage(task))
  const [cookies, setCookies] = useState("")
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const trackQuery = useQuery({
    queryKey: ["douyin-track", task.track_id],
    queryFn: () => DouyinTracksService.getTrack({ trackId: task.track_id }),
    enabled: open,
  })
  useEffect(() => {
    if (!open || !trackQuery.data) return
    const defaults = trackQuery.data.default_task_config
    setStorage(defaults.media_storage ?? taskStorage(task))
    setTranslate(defaults.translate_subtitles ?? false)
    setSubtitleOnly(false)
    setLanguage(defaults.transcription_language ?? taskLanguage(task))
  }, [open, task, trackQuery.data])
  const mutation = useMutation({
    mutationFn: () =>
      DouyinService.processMedia({
        taskId: task.id,
        requestBody: {
          media_storage: storage === "default" ? undefined : storage,
          translate_subtitles: translate,
          subtitle_only: translate && subtitleOnly,
          force_retranslate: translate && forceRetranslate,
          transcription_language: language.trim() || "auto",
          cookies: cookies.trim() || undefined,
        },
      }),
    onSuccess: async () => {
      showSuccessToast("批量媒体处理已启动")
      setOpen(false)
      setCookies("")
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["douyin-task", task.id] }),
        queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] }),
        queryClient.invalidateQueries({ queryKey: ["douyin-media-tasks"] }),
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
      setStorage(taskStorage(task))
      setTranslate(false)
      setSubtitleOnly(false)
      setForceRetranslate(false)
      setLanguage(taskLanguage(task))
      setCookies("")
    }
  }

  return (
    <Dialog open={open} onOpenChange={openChanged}>
      <DialogTrigger asChild>
        <Button size="sm" variant={triggerVariant}>
          <Film />
          {triggerLabel}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>下载视频与生成字幕</DialogTitle>
          <DialogDescription>
            不会重新爬取，将直接处理当前任务已保存的 {task.aweme_count}
            个作品。已完成项目默认跳过。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-2">
          <div className="space-y-2">
            <Label>新视频存储位置</Label>
            <Select
              value={storage}
              disabled={subtitleOnly}
              onValueChange={(value) => setStorage(value as StorageChoice)}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="default">跟随服务配置</SelectItem>
                <SelectItem value="local">本地服务器</SelectItem>
                <SelectItem value="minio">云端存储</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {subtitleOnly
                ? "仅字幕模式不会上传或保留新下载的视频。"
                : "已下载文件保留原位置；未下载或失败的记录按本次选择存储。"}
            </p>
          </div>

          <CheckField
            id="post-process-translate"
            checked={translate}
            label="调用远程 API 生成字幕"
            description="没有本地视频时会先下载视频，再提交远程字幕服务。"
            onChange={(checked) => {
              setTranslate(checked)
              if (!checked) {
                setSubtitleOnly(false)
                setForceRetranslate(false)
              }
            }}
          />
          <CheckField
            id="post-process-subtitle-only"
            checked={translate && subtitleOnly}
            disabled={!translate}
            label="仅生成字幕，不保留视频"
            description="已有下载文件直接使用；没有下载文件时临时下载，转写完成后自动删除，不上传本地或云端存储。"
            onChange={setSubtitleOnly}
          />
          <CheckField
            id="post-process-force-translate"
            checked={translate && forceRetranslate}
            disabled={!translate}
            label="强制重新翻译已有字幕"
            description="已完成字幕也会重新提交；未勾选时只处理缺失或失败的字幕。"
            onChange={setForceRetranslate}
          />

          {translate && (
            <div className="space-y-2">
              <Label htmlFor="post-process-language">视频语言</Label>
              <Input
                id="post-process-language"
                value={language}
                placeholder="auto、zh、en"
                onChange={(event) => setLanguage(event.target.value)}
              />
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="post-process-cookies">临时登录凭据（可选）</Label>
            <Textarea
              id="post-process-cookies"
              value={cookies}
              autoComplete="off"
              placeholder="sessionid=...；视频地址无需鉴权时可留空"
              onChange={(event) => setCookies(event.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              登录凭据只用于本次下载，任务受理后自动清除。
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? "启动中…" : "开始批量处理"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function CheckField({
  id,
  checked,
  disabled,
  label,
  description,
  onChange,
}: {
  id: string
  checked: boolean
  disabled?: boolean
  label: string
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
        <Label htmlFor={id}>{label}</Label>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
    </div>
  )
}
