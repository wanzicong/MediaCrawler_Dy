import { useQuery } from "@tanstack/react-query"
import { Tags, UserRound } from "lucide-react"
import { useMemo } from "react"

import {
  DouyinService,
  type DouyinSourceOptionPublic,
  type DouyinSourceType,
} from "@/client"
import { FilterSelect } from "@/components/Common/FilterSelect"
import { Badge } from "@/components/ui/badge"

export const allSourcesValue = "all"

export type SourceKind = "keyword" | "creator"

/** 拆开后的两个下拉各自的文案（关键词 / 博主） */
const SOURCE_KIND_COPY: Record<
  SourceKind,
  { label: string; all: string; loading: string; failed: string }
> = {
  keyword: {
    label: "关键词",
    all: "全部关键词",
    loading: "正在加载关键词…",
    failed: "关键词加载失败",
  },
  creator: {
    label: "博主",
    all: "全部博主",
    loading: "正在加载博主…",
    failed: "博主加载失败",
  },
}

export function useSourceCatalog(trackId: string) {
  // 赛道是可选的收窄条件：未选具体赛道（空值或「全部赛道」）时不再禁用请求，
  // 改为跨赛道汇总当前用户的全部关键词/作者来源；queryKey 仍带 trackId，
  // 切换赛道会重新取数。
  const scopedTrackId = trackId && trackId !== "all" ? trackId : undefined
  return useQuery({
    queryKey: ["douyin-source-options", trackId],
    queryFn: () => DouyinService.listSourceOptions({ trackId: scopedTrackId }),
    retry: false,
    // 来源目录只在赛道/关键词/达人发生变化时才变，放宽缓存避免切页面重拉
    staleTime: 300_000,
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
  // 只在真实的不可用状态（加载中/加载失败）禁用；赛道不再是前提条件。
  const disabled = query.isLoading || query.isError
  // 来源目录可能有 2000+ 条：选项数组必须跟着数据缓存，
  // 否则每次渲染都会重建整份选项（含图标元素），白白浪费主线程
  const options = useMemo(
    () => [
      { value: allSourcesValue, label: "全部关键词/作者" },
      ...(query.data?.data ?? []).map((option) => ({
        value: sourceSelectionValue(option.source_type, option.id),
        label: sourceOptionLabel(option),
        icon: <SourceOptionIcon option={option} />,
      })),
    ],
    [query.data?.data],
  )
  return (
    <FilterSelect
      value={value}
      onValueChange={onValueChange}
      options={options}
      disabled={disabled}
      className={className}
      ariaLabel={ariaLabel}
      placeholder={
        query.isError
          ? "来源加载失败"
          : query.isLoading
            ? "正在加载来源…"
            : "全部关键词/作者"
      }
    />
  )
}

/**
 * 单一来源类型的下拉（关键词 / 博主各一个）。
 *
 * 和合并版 ``SourceSelect`` 相比：选项只列本类型的来源，文案不再出现
 * 「各一半」的混合列表；取值格式与筛选参数完全一致（``keyword:id`` /
 * ``creator:id`` → ``source_type`` + ``source_id``），因此两个下拉可以共用
 * 同一份 state：选了一边，另一边自动回到「全部」。
 */
export function SourceTypeSelect({
  trackId,
  value,
  onValueChange,
  sourceType,
  className,
  ariaLabel,
}: {
  trackId: string
  value: string
  onValueChange: (value: string) => void
  sourceType: SourceKind
  className?: string
  ariaLabel?: string
}) {
  const query = useSourceCatalog(trackId)
  const copy = SOURCE_KIND_COPY[sourceType]
  const Icon = sourceType === "keyword" ? Tags : UserRound
  const disabled = query.isLoading || query.isError
  const options = useMemo(
    () => [
      { value: allSourcesValue, label: copy.all },
      ...(query.data?.data ?? [])
        .filter((option) => option.source_type === sourceType)
        .map((option) => ({
          value: sourceSelectionValue(option.source_type, option.id),
          label: `${option.name}（${option.usage_count} 个任务）`,
          icon: <Icon className="size-3.5 shrink-0" aria-hidden="true" />,
        })),
    ],
    [Icon, copy.all, query.data?.data, sourceType],
  )
  return (
    <FilterSelect
      value={value}
      onValueChange={onValueChange}
      options={options}
      disabled={disabled}
      className={className}
      ariaLabel={ariaLabel ?? `按${copy.label}筛选`}
      placeholder={
        query.isError ? copy.failed : query.isLoading ? copy.loading : copy.all
      }
    />
  )
}

/** 关键词来源下拉：只列关键词 */
export function KeywordSourceSelect(
  props: Omit<Parameters<typeof SourceTypeSelect>[0], "sourceType">,
) {
  return <SourceTypeSelect {...props} sourceType="keyword" />
}

/** 博主来源下拉：只列博主 */
export function CreatorSourceSelect(
  props: Omit<Parameters<typeof SourceTypeSelect>[0], "sourceType">,
) {
  return <SourceTypeSelect {...props} sourceType="creator" />
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

/** 合并版来源下拉的选项文案：关键词/作者前缀 + 使用次数 */
function sourceOptionLabel(option: DouyinSourceOptionPublic) {
  const prefix = option.source_type === "keyword" ? "关键词" : "作者"
  return `${option.name}（${prefix} · ${option.usage_count}）`
}

/** 选项行内的来源类型图标 */
function SourceOptionIcon({ option }: { option: DouyinSourceOptionPublic }) {
  const Icon = option.source_type === "keyword" ? Tags : UserRound
  return <Icon className="size-3.5 shrink-0" aria-hidden="true" />
}
