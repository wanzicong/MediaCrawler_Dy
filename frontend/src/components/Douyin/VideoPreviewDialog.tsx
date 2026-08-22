import {
  Captions,
  Heart,
  LoaderCircle,
  MessageCircle,
  Play,
  Share2,
  Star,
} from "lucide-react"
import { useEffect, useState } from "react"

import {
  type DouyinAwemePublic,
  type DouyinMediaAssetPublic,
  OpenAPI,
} from "@/client"
import { SubtitlePanel } from "@/components/Douyin/SubtitlePanel"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

export function VideoPreviewDialog({
  taskId,
  asset,
  aweme,
  sourceUrl,
}: {
  taskId: string
  asset?: DouyinMediaAssetPublic | null
  aweme?: DouyinAwemePublic
  sourceUrl?: string | null
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
    const cleanSourceUrl = sourceUrl?.trim()
    if (!asset?.download_available) {
      setPreviewUrl(cleanSourceUrl || null)
      setError(cleanSourceUrl ? null : "没有可播放的视频资源")
      return () => controller.abort()
    }

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
  }, [asset?.download_available, asset?.id, open, sourceUrl, taskId])

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
            作品 {asset?.aweme_id || aweme?.aweme_id || "未知作品"} ·{" "}
            {asset
              ? asset.storage_backend === "minio"
                ? "云端存储"
                : "本地服务器"
              : "作品源地址"}
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
                srcLang={asset?.subtitle?.language || "zh"}
                label="任务字幕"
                default
              />
              当前浏览器不支持视频播放。
            </video>
          )}
        </div>
        <Tabs defaultValue="video" className="w-full">
          <TabsList>
            <TabsTrigger value="video">视频信息</TabsTrigger>
            {asset && (
              <TabsTrigger value="subtitle">
                <Captions />
                字幕信息
              </TabsTrigger>
            )}
          </TabsList>
          <TabsContent value="video">
            <div className="space-y-2 text-sm">
              {aweme && (
                <>
                  <p className="font-medium leading-6">
                    {aweme.title || aweme.aweme_id}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {aweme.nickname || "匿名创作者"} · 发布{" "}
                    {formatUnix(aweme.create_time)}
                    {aweme.source_keyword && ` · 来源 ${aweme.source_keyword}`}
                  </p>
                  <div className="flex flex-wrap items-center gap-4 text-xs">
                    <InlineStat
                      icon={Heart}
                      label="点赞"
                      value={aweme.liked_count}
                    />
                    <InlineStat
                      icon={MessageCircle}
                      label="评论"
                      value={aweme.comment_count}
                    />
                    <InlineStat
                      icon={Star}
                      label="收藏"
                      value={aweme.collected_count}
                    />
                    <InlineStat
                      icon={Share2}
                      label="分享"
                      value={aweme.share_count}
                    />
                  </div>
                </>
              )}
              {asset ? (
                <p className="text-xs text-muted-foreground">
                  文件 {formatFileSize(asset.file_size)} · {asset.mime_type} ·
                  {asset.storage_backend === "minio"
                    ? " 云端存储"
                    : " 本地服务器"}
                  {asset.completed_at &&
                    ` · 下载完成 ${formatDateTime(asset.completed_at)}`}
                </p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  当前使用作品自带的视频源地址播放；下载完成后会自动优先使用已下载文件。
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                {asset
                  ? "播放器按需读取视频片段；关闭窗口会停止读取，短时播放权限将在数分钟内自动失效。"
                  : "源地址的可用性取决于抖音资源权限与有效期。"}
              </p>
            </div>
          </TabsContent>
          {asset && (
            <TabsContent value="subtitle">
              <SubtitlePanel asset={asset} />
            </TabsContent>
          )}
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}

function InlineStat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Heart
  label: string
  value: number
}) {
  return (
    <span className="flex items-center gap-1">
      <Icon aria-hidden="true" className="size-3.5 text-muted-foreground" />
      <span className="font-semibold tabular-nums">{compact(value)}</span>
      <span className="text-muted-foreground">{label}</span>
    </span>
  )
}

function captionSource(asset?: DouyinMediaAssetPublic | null): string {
  const text = asset?.subtitle?.full_text.trim()
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

function compact(value: number) {
  return new Intl.NumberFormat("zh-CN", { notation: "compact" }).format(value)
}

function formatUnix(value: number | null) {
  if (!value) return "未知"
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium" }).format(
    new Date(value * 1_000),
  )
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value))
}

function formatFileSize(value: number) {
  if (!value) return "0 B"
  const units = ["B", "KB", "MB", "GB"]
  let size = value
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size.toFixed(1)} ${units[unit]}`
}
