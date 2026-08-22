import { Link } from "@tanstack/react-router"
import {
  Captions,
  ExternalLink,
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
}: {
  taskId: string
  asset?: DouyinMediaAssetPublic | null
  aweme?: DouyinAwemePublic
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

    if (!asset?.download_available) {
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
  }, [asset?.download_available, asset?.id, open, taskId])

  const unavailable = open && !asset?.download_available

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={asset?.download_available ? "预览视频" : "视频尚未下载"}
          title={asset?.download_available ? "预览视频" : "视频尚未下载"}
        >
          <Play />
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>视频预览</DialogTitle>
          <DialogDescription>
            作品 {asset?.aweme_id || aweme?.aweme_id || "未知作品"} ·{" "}
            {asset?.download_available
              ? asset.storage_backend === "minio"
                ? "云端存储"
                : "本地服务器"
              : "尚未下载"}
          </DialogDescription>
        </DialogHeader>
        <div className="relative flex aspect-video items-center justify-center overflow-hidden rounded-lg bg-black">
          {!previewUrl && !error && !unavailable && (
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
          {unavailable && (
            <div className="flex max-w-lg flex-col items-center gap-3 px-8 text-center text-white">
              <p className="text-base font-medium">视频尚未下载</p>
              <p className="text-sm leading-6 text-white/65">
                采集任务只保存作品信息和临时下载地址；临时地址不是稳定播放流。请先创建下载任务，下载完成后再播放。
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                <Button variant="secondary" size="sm" asChild>
                  <Link to="/douyin/$taskId" params={{ taskId }}>
                    去创建下载任务
                  </Link>
                </Button>
                {aweme?.aweme_url && (
                  <Button variant="secondary" size="sm" asChild>
                    <a href={aweme.aweme_url} target="_blank" rel="noreferrer">
                      <ExternalLink />
                      在抖音中打开
                    </a>
                  </Button>
                )}
              </div>
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
              {asset?.download_available ? (
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
                  当前作品尚未形成可播放媒体资产；请先在任务或资源库中创建下载任务。
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                {asset?.download_available
                  ? "播放器按需读取视频片段；关闭窗口会停止读取，短时播放权限将在数分钟内自动失效。"
                  : "为避免临时地址过期、防盗链或重定向导致误报，系统不会直接播放采集源地址。"}
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
