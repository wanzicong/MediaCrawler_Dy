import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowDown, ArrowLeft, ArrowUp, LoaderCircle } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { DouyinService, type DouyinWorkPublic } from "@/client"
import { parseSourceSelection } from "@/components/Douyin/SourceSelect"
import { Button } from "@/components/ui/button"
import { FeedSlide } from "@/routes/_layout/douyin_.$taskId.feed"
import type { LibraryFeedSearch } from "@/routes/_layout/douyin-library"

const sortValues = new Set<NonNullable<LibraryFeedSearch["sort"]>>([
  "downloaded_at:desc",
  "published_at:desc",
  "published_at:asc",
  "liked_count:desc",
  "comment_count:desc",
  "collected_count:desc",
  "persisted_comment_count:desc",
  "file_size:desc",
])

export const Route = createFileRoute("/_layout/douyin-library/feed")({
  validateSearch: (search: Record<string, unknown>): LibraryFeedSearch => ({
    start: typeof search.start === "string" ? search.start : undefined,
    track: typeof search.track === "string" ? search.track : undefined,
    source: typeof search.source === "string" ? search.source : undefined,
    q: typeof search.q === "string" ? search.q : undefined,
    task: typeof search.task === "string" ? search.task : undefined,
    creator: typeof search.creator === "string" ? search.creator : undefined,
    tag: typeof search.tag === "string" ? search.tag : undefined,
    storage: ["all", "local", "minio"].includes(String(search.storage))
      ? (search.storage as LibraryFeedSearch["storage"])
      : undefined,
    subtitle: ["all", "pending", "running", "completed", "failed"].includes(
      String(search.subtitle),
    )
      ? (search.subtitle as LibraryFeedSearch["subtitle"])
      : undefined,
    sort:
      typeof search.sort === "string" &&
      sortValues.has(search.sort as NonNullable<LibraryFeedSearch["sort"]>)
        ? (search.sort as LibraryFeedSearch["sort"])
        : undefined,
  }),
  component: LibraryImmersiveFeed,
  head: () => ({ meta: [{ title: "资源库沉浸播放 - Douyin Crawler" }] }),
})

function LibraryImmersiveFeed() {
  const filters = Route.useSearch()
  const [index, setIndex] = useState(0)
  const touchStart = useRef<number | null>(null)
  const wheelLocked = useRef(false)
  const [sortBy, sortOrder] = (filters.sort ?? "downloaded_at:desc").split(
    ":",
  ) as [
    (
      | "downloaded_at"
      | "published_at"
      | "liked_count"
      | "comment_count"
      | "collected_count"
      | "persisted_comment_count"
      | "file_size"
    ),
    "asc" | "desc",
  ]
  const works = useQuery({
    queryKey: ["douyin-library-feed", filters],
    queryFn: () =>
      DouyinService.listLibraryWorks({
        trackId: filters.track,
        ...parseSourceSelection(filters.source ?? "all"),
        search: filters.q,
        taskId: filters.task,
        creatorHash: filters.creator,
        tagId: filters.tag,
        storageBackend: filters.storage ?? "all",
        subtitleStatus: filters.subtitle ?? "all",
        sortBy,
        sortOrder,
        limit: 100,
      }),
  })
  const rows = useMemo(() => {
    const seen = new Set<string>()
    return (works.data?.data ?? []).filter((row): row is DouyinWorkPublic => {
      if (!row.media?.download_available) {
        return false
      }
      const awemeId = row.aweme.aweme_id
      if (seen.has(awemeId)) return false
      seen.add(awemeId)
      return true
    })
  }, [works.data?.data])
  const move = useCallback(
    (direction: number) => {
      setIndex((current) =>
        Math.max(0, Math.min(rows.length - 1, current + direction)),
      )
    },
    [rows.length],
  )

  useEffect(() => {
    const awemeId = filters.start?.startsWith("video-")
      ? filters.start.slice(6)
      : undefined
    if (!awemeId) return
    const requestedIndex = rows.findIndex(
      (row) => row.aweme.aweme_id === awemeId,
    )
    if (requestedIndex >= 0) setIndex(requestedIndex)
  }, [filters.start, rows])

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (["ArrowDown", "PageDown", "j"].includes(event.key)) move(1)
      if (["ArrowUp", "PageUp", "k"].includes(event.key)) move(-1)
    }
    window.addEventListener("keydown", handleKey)
    return () => window.removeEventListener("keydown", handleKey)
  }, [move])

  const { start: _start, ...backSearch } = filters
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
            to="/douyin-library"
            search={backSearch}
            aria-label="退出沉浸播放"
          >
            <ArrowLeft />
          </Link>
        </Button>
        <div className="rounded-full bg-black/45 px-4 py-2 text-sm backdrop-blur">
          {rows.length ? `${index + 1} / ${rows.length}` : "资源库沉浸播放"}
        </div>
      </div>

      {works.isLoading ? (
        <div className="flex h-full items-center justify-center gap-2 text-white/70">
          <LoaderCircle className="animate-spin" />
          加载筛选后的视频…
        </div>
      ) : !current ? (
        <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
          <p className="text-xl font-medium">没有可播放的视频</p>
          <p className="text-sm text-white/60">
            请返回资源库调整筛选条件，或先为作品创建下载任务。
          </p>
          <Button variant="secondary" asChild>
            <Link to="/douyin-library" search={backSearch}>
              返回视频资源库
            </Link>
          </Button>
        </div>
      ) : (
        <FeedSlide key={current.aweme.aweme_id} work={current} />
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
        当前筛选最多加载 100 条 · 滚轮、↑↓、J/K 或上下滑动切换
      </p>
    </div>
  )
}
