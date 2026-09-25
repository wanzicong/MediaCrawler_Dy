import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Download, Film } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import {
  type DouyinMediaBatchProcessResult,
  type DouyinMediaTaskPublic,
  DouyinService,
  DouyinTracksService,
} from "@/client"
import {
  createMediaProcessConfig,
  type MediaProcessConfig,
  MediaProcessFields,
  mediaProcessRequestBody,
} from "@/components/Douyin/MediaProcessFields"
import { shortTaskReference } from "@/components/Douyin/TaskIdentity"
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

/** 批量入口只依赖这几个字段：来源任务、赛道与可下载作品数 */
export type BatchMediaSource = Pick<
  DouyinMediaTaskPublic,
  | "source_task_id"
  | "track_id"
  | "track_name"
  | "eligible_count"
  | "source_request"
>

function toProcessSource(task: BatchMediaSource) {
  return {
    id: task.source_task_id,
    track_id: task.track_id,
    aweme_count: task.eligible_count,
    request: task.source_request ?? {},
  }
}

/**
 * 批量下载与字幕：一次配置，应用到多个来源任务。
 *
 * 配置表单与单任务弹窗共用（``MediaProcessFields``），提交走
 * ``POST /douyin/media-tasks/process``；某个任务状态冲突时只跳过它，
 * 结果里会逐条给出跳过原因。
 */
export function BatchProcessMediaDialog({
  tasks,
  triggerLabel = "批量下载与字幕",
  triggerVariant = "default",
  onDone,
}: {
  tasks: BatchMediaSource[]
  triggerLabel?: string
  triggerVariant?: React.ComponentProps<typeof Button>["variant"]
  onDone?: () => void
}) {
  const [open, setOpen] = useState(false)
  const first = tasks[0]
  const [config, setConfig] = useState<MediaProcessConfig>(() =>
    first
      ? createMediaProcessConfig(toProcessSource(first))
      : {
          storage: "default",
          translate: false,
          subtitleOnly: false,
          forceRetranslate: false,
          language: "auto",
          cookies: "",
        },
  )
  const [result, setResult] = useState<DouyinMediaBatchProcessResult | null>(
    null,
  )
  // 批量任务可能来自多个赛道：沿用第一个任务的赛道默认配置，且每次打开只应用一次
  const defaultsApplied = useRef(false)
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const trackQuery = useQuery({
    queryKey: ["douyin-track", first?.track_id],
    queryFn: () => DouyinTracksService.getTrack({ trackId: first.track_id }),
    enabled: open && Boolean(first),
  })
  useEffect(() => {
    if (!open) {
      defaultsApplied.current = false
      return
    }
    if (defaultsApplied.current || !trackQuery.data || !first) return
    defaultsApplied.current = true
    const defaults = trackQuery.data.default_task_config
    setConfig((current) => ({
      ...current,
      storage: defaults.media_storage ?? current.storage,
      translate: defaults.translate_subtitles ?? false,
      subtitleOnly: false,
      language: defaults.transcription_language ?? current.language,
    }))
  }, [open, first, trackQuery.data])
  const mutation = useMutation({
    mutationFn: () =>
      DouyinService.processMediaTasks({
        requestBody: {
          ...mediaProcessRequestBody(config),
          task_ids: tasks.map((task) => task.source_task_id),
        },
      }),
    onSuccess: async (data) => {
      setResult(data)
      showSuccessToast(
        data.skipped_count
          ? `已提交 ${data.accepted_count} 个任务，${data.skipped_count} 个被跳过`
          : `已提交 ${data.accepted_count} 个任务的下载与字幕`,
      )
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["douyin-media-tasks"] }),
        queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] }),
        ...tasks.map((task) =>
          queryClient.invalidateQueries({
            queryKey: ["douyin-media", task.source_task_id],
          }),
        ),
        ...tasks.map((task) =>
          queryClient.invalidateQueries({
            queryKey: ["douyin-media-summary", task.source_task_id],
          }),
        ),
      ])
    },
    onError: handleError.bind(showErrorToast),
  })
  const closeAndReset = () => {
    setOpen(false)
    setResult(null)
    if (first) setConfig(createMediaProcessConfig(toProcessSource(first)))
    onDone?.()
  }
  const skipped = result?.items.filter((item) => !item.accepted) ?? []
  const titleOf = (taskId: string) => {
    const matched = tasks.find((task) => task.source_task_id === taskId)
    return matched
      ? `${shortTaskReference(matched.source_task_id)}（${matched.track_name}）`
      : shortTaskReference(taskId)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && mutation.isPending) return
        if (!next) closeAndReset()
        else setOpen(true)
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant={triggerVariant}>
          <Film />
          {triggerLabel}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>批量下载视频与生成字幕</DialogTitle>
          <DialogDescription>
            同一套配置会应用到选中的 {tasks.length} 个任务（合计{" "}
            {tasks.reduce((total, task) => total + task.eligible_count, 0)}{" "}
            个作品），不会重新爬取；已完成项目默认跳过。
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <div className="space-y-3 py-2 text-sm">
            <p>
              <Download className="mr-1 inline size-4" />
              已受理 <strong>{result.accepted_count}</strong> 个任务
              {result.skipped_count
                ? `，跳过 ${result.skipped_count} 个（原因见下）`
                : "，可在列表里查看下载与字幕进度。"}
            </p>
            {skipped.length > 0 && (
              <ul className="max-h-64 space-y-1 overflow-y-auto rounded-lg border p-3 text-xs text-muted-foreground">
                {skipped.map((item) => (
                  <li key={item.task_id}>
                    {titleOf(item.task_id)}：{item.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <>
            <div className="rounded-lg border bg-muted/40 p-3 text-xs text-muted-foreground">
              <p className="font-medium text-foreground">本次包含的任务</p>
              <ul className="mt-1 space-y-0.5">
                {tasks.slice(0, 8).map((task) => (
                  <li key={task.source_task_id}>
                    {shortTaskReference(task.source_task_id)} ·{" "}
                    {task.track_name} · {task.eligible_count} 个作品
                  </li>
                ))}
                {tasks.length > 8 && <li>…… 其余 {tasks.length - 8} 个任务</li>}
              </ul>
            </div>
            <MediaProcessFields config={config} onChange={setConfig} />
          </>
        )}

        <DialogFooter>
          {result ? (
            <Button onClick={closeAndReset}>完成</Button>
          ) : (
            <>
              <Button
                variant="outline"
                disabled={mutation.isPending}
                onClick={closeAndReset}
              >
                取消
              </Button>
              <Button
                onClick={() => mutation.mutate()}
                disabled={mutation.isPending || tasks.length === 0}
              >
                {mutation.isPending
                  ? "提交中…"
                  : `开始批量处理（${tasks.length}）`}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
