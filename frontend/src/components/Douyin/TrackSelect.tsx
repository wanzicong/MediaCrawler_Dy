import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { RefreshCw, Target } from "lucide-react"
import { useEffect } from "react"

import { type DouyinTrackPublic, DouyinTracksService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { cn } from "@/lib/utils"

export const allTracksValue = "all"

type TrackOption = DouyinTrackPublic & { is_default?: boolean }

export function useTrackCatalog(enabled = true) {
  return useQuery({
    queryKey: ["douyin-track-options"],
    queryFn: () => DouyinTracksService.listTracks({ limit: 200 }),
    enabled,
    retry: false,
    staleTime: 30_000,
  })
}

export function defaultTrackId(tracks: TrackOption[]) {
  return (
    tracks.find((track) => track.is_default)?.id ??
    tracks.find((track) => track.enabled)?.id ??
    ""
  )
}

export function TrackSelect({
  value,
  onValueChange,
  includeAll = false,
  enabled = true,
  autoSelectDefault = true,
  allowDisabled = false,
  ariaLabel = "选择所属赛道",
  className,
}: {
  value: string
  onValueChange: (value: string) => void
  includeAll?: boolean
  enabled?: boolean
  autoSelectDefault?: boolean
  allowDisabled?: boolean
  ariaLabel?: string
  className?: string
}) {
  const tracksQuery = useTrackCatalog(enabled)
  const tracks = (tracksQuery.data?.data ?? []) as TrackOption[]
  // 列表筛选使用的“全部赛道”不是可写归属。复用筛选值打开创建弹窗时，
  // 将它视为空值并自动选择默认赛道，避免下拉框首屏显示空白。
  const normalizedValue = !includeAll && value === allTracksValue ? "" : value

  useEffect(() => {
    if (
      !enabled ||
      !autoSelectDefault ||
      normalizedValue ||
      tracks.length === 0
    )
      return
    onValueChange(defaultTrackId(tracks))
  }, [autoSelectDefault, enabled, normalizedValue, onValueChange, tracks])

  if (tracksQuery.isError || (!tracksQuery.isLoading && tracks.length === 0)) {
    return (
      <div className={cn("flex w-full items-center gap-2", className)}>
        <div
          role="alert"
          className="flex h-10 min-w-0 flex-1 items-center rounded-md border border-destructive/35 bg-destructive/5 px-3 text-sm text-destructive"
        >
          {tracksQuery.isError ? "赛道加载失败" : "暂无可用赛道"}
        </div>
        <Button
          type="button"
          size="icon"
          variant="outline"
          aria-label="重新加载赛道"
          disabled={tracksQuery.isFetching}
          onClick={() => void tracksQuery.refetch()}
        >
          <RefreshCw className={tracksQuery.isFetching ? "animate-spin" : ""} />
        </Button>
      </div>
    )
  }

  return (
    <Select
      value={normalizedValue}
      onValueChange={onValueChange}
      disabled={!enabled || tracksQuery.isLoading || tracksQuery.isError}
    >
      <SelectTrigger
        className={cn("min-h-10 w-full", className)}
        aria-label={ariaLabel}
      >
        <Target aria-hidden="true" />
        <SelectValue
          placeholder={
            tracksQuery.isError
              ? "赛道加载失败"
              : tracksQuery.isLoading
                ? "正在加载赛道…"
                : "选择所属赛道"
          }
        />
      </SelectTrigger>
      <SelectContent>
        {includeAll && <SelectItem value={allTracksValue}>全部赛道</SelectItem>}
        {tracks.map((track) => (
          <SelectItem
            key={track.id}
            value={track.id}
            disabled={!allowDisabled && !track.enabled}
          >
            {track.name}
            {track.is_default ? "（默认）" : ""}
            {!track.enabled ? "（已停用）" : ""}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export function TrackBadge({
  trackId,
  trackName,
  isDefault = false,
  className,
}: {
  trackId?: string | null
  trackName?: string | null
  isDefault?: boolean
  className?: string
}) {
  if (!trackId || !trackName) return null
  return (
    <Badge
      variant="outline"
      className={cn("min-h-6 max-w-full gap-1.5 font-normal", className)}
      asChild
    >
      <Link
        to="/douyin-tracks/$trackId"
        params={{ trackId }}
        title={`查看赛道：${trackName}`}
      >
        <Target className="size-3" aria-hidden="true" />
        <span className="truncate">{trackName}</span>
        {isDefault && <span className="text-muted-foreground">· 默认</span>}
      </Link>
    </Badge>
  )
}
