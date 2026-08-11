import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Heart,
  LoaderCircle,
  MessageCircle,
  Share2,
} from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import {
  type DouyinMediaAssetPublic,
  DouyinService,
  type DouyinWorkPublic,
  OpenAPI,
} from "@/client"
import { Button } from "@/components/ui/button"

export const Route = createFileRoute("/_layout/douyin_/$taskId/feed")({
  component: ImmersiveFeed,
  validateSearch: (search: Record<string, unknown>) => ({
    start: typeof search.start === "string" ? search.start : undefined,
  }),
  head: () => ({ meta: [{ title: "沉浸播放 - 灵感采集台" }] }),
})

function ImmersiveFeed() {
  const { taskId } = Route.useParams()
  const { start } = Route.useSearch()
  const [index, setIndex] = useState(0)
  const touchStart = useRef<number | null>(null)
  const wheelLocked = useRef(false)
  const works = useQuery({
    queryKey: ["douyin-feed", taskId],
    queryFn: () =>
      DouyinService.listWorks({
        taskId,
        downloadStatus: "downloaded",
        sortBy: "published_at",
        sortOrder: "desc",
        limit: 100,
      }),
  })
  const rows = useMemo(
    () =>
      (works.data?.data ?? []).filter(
        (row): row is DouyinWorkPublic & { media: DouyinMediaAssetPublic } =>
          Boolean(row.media?.download_available),
      ),
    [works.data?.data],
  )
  const move = useCallback(
    (direction: number) => {
      setIndex((current) =>
        Math.max(0, Math.min(rows.length - 1, current + direction)),
      )
    },
    [rows.length],
  )

  useEffect(() => {
    const awemeId = start?.startsWith("video-") ? start.slice(6) : undefined
    if (!awemeId) return
    const requestedIndex = rows.findIndex(
      (row) => row.aweme.aweme_id === awemeId,
    )
    if (requestedIndex >= 0) setIndex(requestedIndex)
  }, [rows, start])

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (["ArrowDown", "PageDown", "j"].includes(event.key)) move(1)
      if (["ArrowUp", "PageUp", "k"].includes(event.key)) move(-1)
    }
    window.addEventListener("keydown", handleKey)
    return () => window.removeEventListener("keydown", handleKey)
  }, [move])

  const current = rows[index]
  return (
    <div
      className="fixed inset-0 z-50 overflow-hidden bg-[#050507] text-white"
      onWheel={(event) => {
        if (wheelLocked.current || Math.abs(event.deltaY) < 20) return
        wheelLocked.current = true
        move(event.deltaY > 0 ? 1 : -1)
        window.setTimeout(() => {
          wheelLocked.current = false
        }, 450)
      }}
      onTouchStart={(event) => {
        touchStart.current = event.touches[0]?.clientY ?? null
      }}
      onTouchEnd={(event) => {
        if (touchStart.current === null) return
        const distance =
          touchStart.current - (event.changedTouches[0]?.clientY ?? 0)
        if (Math.abs(distance) > 50) move(distance > 0 ? 1 : -1)
        touchStart.current = null
      }}
    >
      <div className="absolute left-4 top-4 z-20 flex items-center gap-3">
        <Button
          variant="secondary"
          size="icon"
          className="rounded-full bg-black/50 text-white backdrop-blur hover:bg-black/70"
          asChild
        >
          <Link
            to="/douyin/$taskId"
            params={{ taskId }}
            aria-label="退出沉浸播放"
          >
            <ArrowLeft />
          </Link>
        </Button>
        <div className="rounded-full bg-black/45 px-4 py-2 text-sm backdrop-blur">
          {rows.length ? `${index + 1} / ${rows.length}` : "沉浸播放"}
        </div>
      </div>

      {works.isLoading ? (
        <div className="flex h-full items-center justify-center gap-2 text-white/70">
          <LoaderCircle className="animate-spin" />
          加载视频列表…
        </div>
      ) : !current ? (
        <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
          <p className="text-xl font-medium">没有可播放的视频</p>
          <p className="text-sm text-white/60">
            请先完成视频下载，或检查筛选后的媒体状态。
          </p>
          <Button variant="secondary" asChild>
            <Link to="/douyin/$taskId" params={{ taskId }}>
              返回任务
            </Link>
          </Button>
        </div>
      ) : (
        <FeedSlide key={current.media.id} taskId={taskId} work={current} />
      )}

      {rows.length > 1 && (
        <div className="absolute right-4 top-1/2 z-20 flex -translate-y-1/2 flex-col gap-2">
          <Button
            variant="secondary"
            size="icon"
            className="rounded-full bg-black/45 text-white backdrop-blur"
            disabled={index === 0}
            onClick={() => move(-1)}
            aria-label="上一个视频"
          >
            <ArrowUp />
          </Button>
          <Button
            variant="secondary"
            size="icon"
            className="rounded-full bg-black/45 text-white backdrop-blur"
            disabled={index + 1 >= rows.length}
            onClick={() => move(1)}
            aria-label="下一个视频"
          >
            <ArrowDown />
          </Button>
        </div>
      )}
      <p className="absolute bottom-3 left-1/2 z-20 -translate-x-1/2 text-xs text-white/40">
        滚轮、↑↓、J/K 或上下滑动切换视频
      </p>
    </div>
  )
}

function FeedSlide({
  taskId,
  work,
}: {
  taskId: string
  work: DouyinWorkPublic & { media: DouyinMediaAssetPublic }
}) {
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState("")
  useEffect(() => {
    const controller = new AbortController()
    const establish = async () => {
      try {
        const token = localStorage.getItem("access_token")
        const path = `/api/v1/douyin/tasks/${taskId}/media/${work.media.id}`
        const response = await fetch(
          `${browserApiBase()}${path}/preview-session`,
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
            payload?.detail || `视频初始化失败 (${response.status})`,
          )
        }
        setUrl(`${browserApiBase()}${path}/preview?v=${Date.now()}`)
      } catch (reason) {
        if (!controller.signal.aborted)
          setError(reason instanceof Error ? reason.message : "视频初始化失败")
      }
    }
    void establish()
    return () => controller.abort()
  }, [taskId, work.media.id])
  const aweme = work.aweme
  return (
    <div className="relative mx-auto flex h-full max-w-[min(100vw,1200px)] items-center justify-center px-3 py-3 sm:px-16">
      <div className="relative h-full w-full overflow-hidden rounded-[1.75rem] bg-black shadow-2xl sm:w-auto sm:min-w-[min(70vw,520px)]">
        {!url && !error && (
          <div className="flex h-full items-center justify-center gap-2 text-white/60">
            <LoaderCircle className="animate-spin" />
            准备视频流…
          </div>
        )}
        {error && (
          <div className="flex h-full items-center justify-center px-8 text-center text-red-300">
            {error}
          </div>
        )}
        {url && (
          <video
            src={url}
            className="h-full w-full object-contain"
            autoPlay
            controls
            loop
            playsInline
            preload="metadata"
            onError={() => setError("视频无法播放，请检查媒体文件或对象存储")}
          >
            <track
              kind="captions"
              src={captionSource(work.media)}
              srcLang={work.media.subtitle?.language || "zh"}
              label="任务字幕"
              default
            />
          </video>
        )}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 via-black/35 to-transparent px-5 pb-14 pt-28">
          <p className="font-semibold">@{aweme.nickname || "匿名作者"}</p>
          <p className="mt-2 line-clamp-3 max-w-xl text-sm leading-6 text-white/90">
            {aweme.title || aweme.aweme_id}
          </p>
          <p className="mt-2 text-xs text-white/55">
            发布于 {formatUnix(aweme.create_time)} ·{" "}
            {work.media.storage_backend === "minio" ? "MinIO" : "本地服务器"}
          </p>
        </div>
        <div className="absolute bottom-20 right-4 flex flex-col items-center gap-5 text-xs">
          <Metric icon={Heart} value={aweme.liked_count} />
          <Metric icon={MessageCircle} value={work.persisted_comment_count} />
          <Metric icon={Share2} value={aweme.share_count} />
        </div>
      </div>
    </div>
  )
}

function Metric({ icon: Icon, value }: { icon: typeof Heart; value: number }) {
  return (
    <div className="flex flex-col items-center gap-1">
      <span className="rounded-full bg-black/45 p-3 backdrop-blur">
        <Icon className="size-5" />
      </span>
      <span>
        {new Intl.NumberFormat("zh-CN", { notation: "compact" }).format(value)}
      </span>
    </div>
  )
}
function captionSource(asset: DouyinMediaAssetPublic) {
  const text = asset.subtitle?.full_text.trim()
  return `data:text/vtt;charset=utf-8,${encodeURIComponent(text ? `WEBVTT\n\n00:00:00.000 --> 99:59:59.000\n${text}\n` : "WEBVTT\n")}`
}
function browserApiBase() {
  if (import.meta.env.DEV) return window.location.origin
  return new URL(OpenAPI.BASE || window.location.origin, window.location.origin)
    .toString()
    .replace(/\/$/, "")
}
function formatUnix(value: number | null) {
  return value
    ? new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(value * 1_000))
    : "未知"
}
