import { useQuery } from "@tanstack/react-query"
import { Tags, UserRound } from "lucide-react"

import {
  DouyinService,
  type DouyinSourceOptionPublic,
  type DouyinSourceType,
} from "@/client"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

export const allSourcesValue = "all"

export function useSourceCatalog(trackId: string) {
  // 赛道是可选的收窄条件：未选具体赛道（空值或「全部赛道」）时不再禁用请求，
  // 改为跨赛道汇总当前用户的全部关键词/作者来源；queryKey 仍带 trackId，
  // 切换赛道会重新取数。
  const scopedTrackId = trackId && trackId !== "all" ? trackId : undefined
  return useQuery({
    queryKey: ["douyin-source-options", trackId],
    queryFn: () => DouyinService.listSourceOptions({ trackId: scopedTrackId }),
    retry: false,
    staleTime: 30_000,
  })
}

export function sourceSelectionValue(
  sourceType: DouyinSourceType,
  sourceId: string,
) {
  return `${sourceType}:${sourceId}`
}

export function parseSourceSelection(value: string) {
  if (!value || value === allSourcesValue) return {}
  const separator = value.indexOf(":")
  if (separator < 1) return {}
  const sourceType = value.slice(0, separator) as DouyinSourceType
  const sourceId = value.slice(separator + 1)
  if (!sourceId || !["keyword", "creator"].includes(sourceType)) return {}
  return { sourceType, sourceId }
}

export function SourceSelect({
  trackId,
  value,
  onValueChange,
  className,
  ariaLabel = "按关键词或作者筛选",
}: {
  trackId: string
  value: string
  onValueChange: (value: string) => void
  className?: string
  ariaLabel?: string
}) {
  const query = useSourceCatalog(trackId)
  const options = query.data?.data ?? []
  // 只在真实的不可用状态（加载中/加载失败）禁用；赛道不再是前提条件。
  const disabled = query.isLoading || query.isError
  return (
    <Select value={value} onValueChange={onValueChange} disabled={disabled}>
      <SelectTrigger className={className} aria-label={ariaLabel}>
        <SelectValue
          placeholder={
            query.isError
              ? "来源加载失败"
              : query.isLoading
                ? "正在加载来源…"
                : "全部关键词/作者"
          }
        />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={allSourcesValue}>全部关键词/作者</SelectItem>
        {options.map((option) => (
          <SourceOption
            key={`${option.source_type}:${option.id}`}
            option={option}
          />
        ))}
      </SelectContent>
    </Select>
  )
}

export function SourceBadge({
  sourceType,
  sourceName,
  sourceLabel,
  className,
}: {
  sourceType?: DouyinSourceType | null
  sourceName?: string | null
  sourceLabel?: string | null
  className?: string
}) {
  if (!sourceLabel && !sourceName) return null
  const text = sourceLabel || sourceName || "未标注来源"
  const label =
    sourceType === "creator"
      ? "作者"
      : sourceType === "keyword"
        ? "关键词"
        : "来源"
  return (
    <Badge variant="outline" className={className} title={text}>
      {label}：{text.replace(/^(关键词|作者)：/, "")}
    </Badge>
  )
}

function SourceOption({ option }: { option: DouyinSourceOptionPublic }) {
  const Icon = option.source_type === "keyword" ? Tags : UserRound
  const prefix = option.source_type === "keyword" ? "关键词" : "作者"
  return (
    <SelectItem value={sourceSelectionValue(option.source_type, option.id)}>
      <span className="flex min-w-0 items-center gap-1.5">
        <Icon className="size-3.5 shrink-0" aria-hidden="true" />
        <span className="truncate">{option.name}</span>
        <span className="shrink-0 text-muted-foreground">
          （{prefix} · {option.usage_count}）
        </span>
      </span>
    </SelectItem>
  )
}
