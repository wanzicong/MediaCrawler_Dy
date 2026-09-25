import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Film } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { DouyinService, DouyinTracksService } from "@/client"
import {
  createMediaProcessConfig,
  type MediaProcessConfig,
  MediaProcessFields,
  type MediaProcessSource,
  mediaProcessRequestBody,
} from "@/components/Douyin/MediaProcessFields"
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
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

export function ProcessMediaDialog({
  task,
  triggerLabel = "创建下载任务",
  triggerVariant = "default",
}: {
  task: MediaProcessSource
  triggerLabel?: string
  triggerVariant?: React.ComponentProps<typeof Button>["variant"]
}) {
  const [open, setOpen] = useState(false)
  const [config, setConfig] = useState<MediaProcessConfig>(() =>
    createMediaProcessConfig(task),
  )
  // 任务详情页每 2 秒轮询一次，task / 赛道默认值都会换新对象；
  // 只在每次打开弹窗后应用一次默认值，否则会把用户刚勾的选项重置掉。
  const defaultsApplied = useRef(false)
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const trackQuery = useQuery({
    queryKey: ["douyin-track", task.track_id],
    queryFn: () => DouyinTracksService.getTrack({ trackId: task.track_id }),
    enabled: open,
  })
  useEffect(() => {
    if (!open) {
      defaultsApplied.current = false
      return
    }
    if (defaultsApplied.current || !trackQuery.data) return
    defaultsApplied.current = true
    const defaults = trackQuery.data.default_task_config
    setConfig((current) => ({
      ...current,
      storage: defaults.media_storage ?? current.storage,
      translate: defaults.translate_subtitles ?? false,
      subtitleOnly: false,
      language: defaults.transcription_language ?? current.language,
    }))
  }, [open, trackQuery.data])
  const mutation = useMutation({
    mutationFn: () =>
      DouyinService.processMedia({
        taskId: task.id,
        requestBody: mediaProcessRequestBody(config),
      }),
    onSuccess: async () => {
      showSuccessToast("批量媒体处理已启动")
      setOpen(false)
      setConfig(createMediaProcessConfig(task))
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
      setConfig(createMediaProcessConfig(task))
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

        <MediaProcessFields config={config} onChange={setConfig} />

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
