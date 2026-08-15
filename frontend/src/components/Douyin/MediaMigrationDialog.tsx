import { useMutation, useQueryClient } from "@tanstack/react-query"
import { CloudUpload } from "lucide-react"
import { useState } from "react"

import { DouyinService } from "@/client"
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

export function MediaMigrationDialog({
  taskId,
  eligibleCount,
  assetIds,
  compact = false,
}: {
  taskId: string
  eligibleCount: number
  assetIds?: string[]
  compact?: boolean
}) {
  const [open, setOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const mutation = useMutation({
    mutationFn: () =>
      DouyinService.migrateMediaToMinio({
        taskId,
        requestBody: { asset_ids: assetIds ?? [] },
      }),
    onSuccess: async (result) => {
      showSuccessToast(`已提交 ${result.queued} 个视频迁移任务`)
      setOpen(false)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["douyin-media", taskId] }),
        queryClient.invalidateQueries({
          queryKey: ["douyin-media-summary", taskId],
        }),
      ])
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {compact ? (
          <Button variant="ghost" size="icon-sm" aria-label="重试上传到云端">
            <CloudUpload />
          </Button>
        ) : (
          <Button variant="outline" size="sm" disabled={eligibleCount < 1}>
            <CloudUpload />
            上传本地视频到云端（{eligibleCount}）
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>上传本地视频到云端</DialogTitle>
          <DialogDescription>
            将处理 {eligibleCount} 个视频。完整回读校验通过后才会删除本地文件。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 rounded-lg border bg-muted/30 p-4 text-sm">
          <p>1. 上传本地视频，并保留原文件。</p>
          <p>2. 从云端完整回读视频，核对文件完整性。</p>
          <p>3. 校验通过后切换为云端存储，再删除本地文件。</p>
          <p className="text-muted-foreground">
            上传、校验或存储切换失败时，本地文件不会被删除，可稍后重试。
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? "提交中…" : "确认上传并迁移"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
