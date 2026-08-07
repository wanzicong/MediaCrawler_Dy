import { LoaderCircle, Play } from "lucide-react"
import { useEffect, useState } from "react"

import { type DouyinMediaAssetPublic, OpenAPI } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"

export function VideoPreviewDialog({
  taskId,
  asset,
}: {
  taskId: string
  asset: DouyinMediaAssetPublic
}) {
  const [open, setOpen] = useState(false)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      setPreviewUrl(null)
      setError(null)
      return
    }

    const controller = new AbortController()
    const apiBase = browserMediaApiBase()
    const previewPath = `/api/v1/douyin/tasks/${taskId}/media/${asset.id}`
    const establishSession = async () => {
      setPreviewUrl(null)
      setError(null)
      try {
        const token = localStorage.getItem("access_token")
        const response = await fetch(
          `${apiBase}${previewPath}/preview-session`,
          {
            method: "POST",
            credentials: "include",
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            signal: controller.signal,
          },
        )
        if (!response.ok) {
          const payload = (await response.json().catch(() => null)) as {
            detail?: string
          } | null
          throw new Error(
            payload?.detail || `视频预览初始化失败 (${response.status})`,
          )
        }
        setPreviewUrl(`${apiBase}${previewPath}/preview?v=${Date.now()}`)
      } catch (reason) {
        if (controller.signal.aborted) return
        setError(
          reason instanceof Error ? reason.message : "视频预览初始化失败",
        )
      }
    }
    void establishSession()
    return () => controller.abort()
  }, [asset.id, open, taskId])

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label="预览视频">
          <Play />
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>视频预览</DialogTitle>
          <DialogDescription>
            作品 {asset.aweme_id} ·
            {asset.storage_backend === "minio" ? " MinIO" : " 本地服务器"}
          </DialogDescription>
        </DialogHeader>
        <div className="relative flex aspect-video items-center justify-center overflow-hidden rounded-lg bg-black">
          {!previewUrl && !error && (
            <div className="flex items-center gap-2 text-sm text-white/70">
              <LoaderCircle className="animate-spin" />
              正在准备视频流…
            </div>
          )}
          {error && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/80">
              <p className="max-w-md px-6 text-center text-sm text-red-300">
                {error}
              </p>
            </div>
          )}
          {previewUrl && (
            <video
              key={previewUrl}
              className="h-full w-full"
              src={previewUrl}
              controls
              autoPlay
              playsInline
              preload="metadata"
              onError={() => setError("视频无法播放，请检查文件格式或存储服务")}
            >
              <track
                kind="captions"
                src={captionSource(asset)}
                srcLang={asset.subtitle?.language || "zh"}
                label="任务字幕"
                default
              />
              当前浏览器不支持视频播放。
            </video>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          播放器按需读取视频片段；关闭窗口会停止读取，短时播放权限将在数分钟内自动失效。
        </p>
      </DialogContent>
    </Dialog>
  )
}

function captionSource(asset: DouyinMediaAssetPublic): string {
  const text = asset.subtitle?.full_text.trim()
  const vtt = text
    ? `WEBVTT\n\n00:00:00.000 --> 99:59:59.000\n${text}\n`
    : "WEBVTT\n"
  return `data:text/vtt;charset=utf-8,${encodeURIComponent(vtt)}`
}

function browserMediaApiBase(): string {
  if (import.meta.env.DEV) return window.location.origin

  const configured = new URL(
    OpenAPI.BASE || window.location.origin,
    window.location.origin,
  )
  return configured.toString().replace(/\/$/, "")
}
