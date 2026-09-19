import { useEffect, useState } from "react"

import {
  type DouyinAwemePublic,
  type DouyinMediaAssetPublic,
  OpenAPI,
} from "@/client"
import { getAccessToken } from "@/lib/auth-token"

/**
 * 视频播放源：把「已下载文件」与「采集地址在线转发」两条路径收敛成一份逻辑。
 *
 * 预览弹窗与视频详情页共用它，避免两处各写一遍取流与错误处理。
 * 浏览器不直接访问源地址：已下载走 `preview`，仅有采集地址走 `online-preview`，
 * 都由服务端补齐 Referer/UA 并支持 Range 分段。
 */
export type VideoPreviewSource = {
  /** 播放地址（已建立会话后才非空） */
  url: string | null
  /** 初始化失败原因 */
  error: string | null
  /** 正在建立会话 */
  loading: boolean
  /** 既没有已下载文件，也没有采集地址 */
  unavailable: boolean
  /** 取流方式：已下载文件 / 采集地址在线转发 */
  mode: "file" | "online"
}

export function useVideoPreviewSource({
  taskId,
  asset,
  aweme,
  enabled = true,
}: {
  taskId: string
  asset?: DouyinMediaAssetPublic | null
  aweme?: DouyinAwemePublic
  /** 弹窗场景传 open；详情页进入即取流 */
  enabled?: boolean
}): VideoPreviewSource {
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const downloadable = Boolean(asset?.download_available)
  const awemeId = aweme?.aweme_id
  const onlinePlayable =
    !downloadable && Boolean(awemeId && aweme?.video_download_url)
  const unavailable = !downloadable && !onlinePlayable

  useEffect(() => {
    if (!enabled || unavailable) {
      setUrl(null)
      setError(null)
      setLoading(false)
      return
    }

    const controller = new AbortController()
    const apiBase = browserMediaApiBase()
    const previewPath = downloadable
      ? `/api/v1/douyin/tasks/${taskId}/media/${asset?.id}`
      : `/api/v1/douyin/tasks/${taskId}/awemes/${awemeId}`
    const sessionUrl = `${previewPath}/${
      downloadable ? "preview-session" : "online-preview-session"
    }`
    const streamUrl = `${previewPath}/${
      downloadable ? "preview" : "online-preview"
    }`

    const establishSession = async () => {
      setUrl(null)
      setError(null)
      setLoading(true)
      try {
        const token = getAccessToken()
        const response = await fetch(`${apiBase}${sessionUrl}`, {
          method: "POST",
          credentials: "include",
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          signal: controller.signal,
        })
        if (!response.ok) {
          const payload = (await response.json().catch(() => null)) as {
            detail?: unknown
          } | null
          throw new Error(previewErrorMessage(payload?.detail, response.status))
        }
        setUrl(`${apiBase}${streamUrl}?v=${Date.now()}`)
      } catch (reason) {
        if (controller.signal.aborted) return
        setError(
          reason instanceof Error ? reason.message : "视频预览初始化失败",
        )
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void establishSession()
    return () => controller.abort()
  }, [asset?.id, awemeId, downloadable, enabled, taskId, unavailable])

  return {
    url,
    error,
    loading,
    unavailable,
    mode: downloadable ? "file" : "online",
  }
}

/** 开发环境走 Vite 代理（同源），生产走 OpenAPI.BASE。 */
function browserMediaApiBase(): string {
  if (import.meta.env.DEV) return window.location.origin
  const configured = new URL(
    OpenAPI.BASE || window.location.origin,
    window.location.origin,
  )
  return configured.toString().replace(/\/$/, "")
}

/**
 * 预览初始化失败的提示。
 *
 * FastAPI 的 422 把 `detail` 放成数组（每项是校验错误对象），
 * 直接当字符串用会渲染成 `[object Object]`，这里统一收敛成可读文案。
 */
function previewErrorMessage(detail: unknown, status: number): string {
  const fallback = `视频预览初始化失败 (${status})`
  if (typeof detail === "string" && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: unknown } | undefined
    if (typeof first?.msg === "string" && first.msg.trim()) return first.msg
  }
  if (detail && typeof detail === "object") {
    const message = (detail as { message?: unknown; detail?: unknown }).message
    if (typeof message === "string" && message.trim()) return message
  }
  return fallback
}

/**
 * 把任务字幕包成播放器可用的 VTT（data URL）。
 *
 * 字幕是整段文本、没有逐句时间轴，这里给一条覆盖全片的时间轴，
 * 播放时能直接开字幕，不假装有逐句对齐。
 */
export function subtitleTrackSource(
  asset?: DouyinMediaAssetPublic | null,
): string {
  const text = asset?.subtitle?.full_text.trim()
  const vtt = text
    ? `WEBVTT\n\n00:00:00.000 --> 99:59:59.000\n${text}\n`
    : "WEBVTT\n"
  return `data:text/vtt;charset=utf-8,${encodeURIComponent(vtt)}`
}
