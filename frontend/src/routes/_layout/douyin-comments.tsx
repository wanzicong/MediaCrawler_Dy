import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  ExternalLink,
  FileSpreadsheet,
  ImageIcon,
  ListPlus,
  MessageSquare,
  Search,
  SlidersHorizontal,
  User,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import {
  type CrawlTaskPublic,
  type DouyinCommentLibraryItemPublic,
  DouyinService,
  OpenAPI,
} from "@/client"
import { BulkActionBar } from "@/components/Common/BulkActionBar"
import { confirmDialog } from "@/components/Common/confirm-dialog"
import { EmptyState } from "@/components/Common/EmptyState"
import { FilterChips } from "@/components/Common/FilterChips"
import { FilterPresetBar } from "@/components/Common/FilterPresetBar"
import { Pager } from "@/components/Common/Pager"
import { FilterPanel, PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { RefreshIndicator } from "@/components/Common/RefreshIndicator"
import {
  RowContextMenu,
  type RowMenuItem,
} from "@/components/Common/RowContextMenu"
import { TableColumnMenu } from "@/components/Common/TableColumnMenu"
import { TimeAgo } from "@/components/Common/TimeAgo"
import {
  usePersistentViewMode,
  ViewModeToggle,
} from "@/components/Common/ViewModeToggle"
import { InteractionComposerDialog } from "@/components/Douyin/InteractionComposerDialog"
import {
  allSourcesValue,
  parseSourceSelection,
  SourceBadge,
  SourceSelect,
  useSourceCatalog,
} from "@/components/Douyin/SourceSelect"
import {
  allTracksValue,
  TrackBadge,
  TrackSelect,
  useTrackCatalog,
} from "@/components/Douyin/TrackSelect"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import useCustomToast from "@/hooks/useCustomToast"
import { useHighlightedRows } from "@/hooks/useHighlightedRows"
import { type TableColumnDef, useTableColumns } from "@/hooks/useTableColumns"
import { getAccessToken } from "@/lib/auth-token"
import { type CsvColumn, downloadCsv } from "@/lib/csv"
import {
  compactSearch,
  readEnumParam,
  readStringParam,
} from "@/lib/search-params"
import { formatDateTime, formatUnix } from "@/lib/time"
import { cn } from "@/lib/utils"
import { getDouyinVideoUrl } from "@/utils"

// 报告 O4：筛选上 URL —— 枚举白名单（挡住手改 URL 的脏值）
const COMMENT_TYPE_VALUES = ["all", "top_level", "reply"] as const
const PICTURE_FILTER_VALUES = ["all", "yes", "no"] as const
const COMMENT_SORT_VALUES = [
  "published_at:desc",
  "published_at:asc",
  "like_count:desc",
  "sub_comment_count:desc",
  "fetched_at:desc",
] as const

// 报告 O4：URL 查询参数的结构（全部可选，未筛选时不出现在地址栏）
type CommentSearch = {
  track?: string
  source?: string
  content?: string
  q?: string
  task?: string
  aweme?: string
  creator?: string
  keyword?: string
  type?: CommentType
  pics?: PictureFilter
  minLikes?: string
  maxLikes?: string
  from?: string
  to?: string
  sort?: SortValue
}

export const Route = createFileRoute("/_layout/douyin-comments")({
  // 报告 O4：筛选上 URL —— 刷新 / 分享 / 收藏 / 深链都能还原已应用的筛选条件
  validateSearch: (search: Record<string, unknown>): CommentSearch => ({
    track: readStringParam(search, "track"),
    source: readStringParam(search, "source"),
    content: readStringParam(search, "content"),
    q: readStringParam(search, "q"),
    task: readStringParam(search, "task"),
    aweme: readStringParam(search, "aweme"),
    creator: readStringParam(search, "creator"),
    keyword: readStringParam(search, "keyword"),
    type: readEnumParam(search, "type", COMMENT_TYPE_VALUES),
    pics: readEnumParam(search, "pics", PICTURE_FILTER_VALUES),
    minLikes: readStringParam(search, "minLikes"),
    maxLikes: readStringParam(search, "maxLikes"),
    from: readStringParam(search, "from"),
    to: readStringParam(search, "to"),
    sort: readEnumParam(search, "sort", COMMENT_SORT_VALUES),
  }),
  component: DouyinCommentManagement,
  head: () => ({ meta: [{ title: "评论管理 - 灵感采集台" }] }),
})

const pageSize = 50

type CommentType = "all" | "top_level" | "reply"
type PictureFilter = "all" | "yes" | "no"
type SortValue =
  | "published_at:desc"
  | "published_at:asc"
  | "like_count:desc"
  | "sub_comment_count:desc"
  | "fetched_at:desc"

type Filters = {
  trackId: string
  sourceValue: string
  commentContent: string
  search: string
  taskId: string
  awemeId: string
  videoCreator: string
  sourceKeyword: string
  commentType: CommentType
  hasPictures: PictureFilter
  minLikes: string
  maxLikes: string
  publishedFrom: string
  publishedTo: string
  sort: SortValue
}

const initialFilters: Filters = {
  trackId: allTracksValue,
  sourceValue: allSourcesValue,
  commentContent: "",
  search: "",
  taskId: "all",
  awemeId: "",
  videoCreator: "",
  sourceKeyword: "",
  commentType: "all",
  hasPictures: "all",
  minLikes: "",
  maxLikes: "",
  publishedFrom: "",
  publishedTo: "",
  sort: "published_at:desc",
}

/**
 * 报告 O4：把 URL 查询参数还原成「已应用」的筛选状态。
 * 只有「已应用」这一组进 URL，草稿态不写 —— 刷新后还原的是用户真正生效的筛选。
 */
function filtersFromSearch(search: CommentSearch): Filters {
  return {
    ...initialFilters,
    trackId: search.track ?? initialFilters.trackId,
    sourceValue: search.source ?? initialFilters.sourceValue,
    commentContent: search.content ?? initialFilters.commentContent,
    search: search.q ?? initialFilters.search,
    taskId: search.task ?? initialFilters.taskId,
    awemeId: search.aweme ?? initialFilters.awemeId,
    videoCreator: search.creator ?? initialFilters.videoCreator,
    sourceKeyword: search.keyword ?? initialFilters.sourceKeyword,
    commentType: search.type ?? initialFilters.commentType,
    hasPictures: search.pics ?? initialFilters.hasPictures,
    minLikes: search.minLikes ?? initialFilters.minLikes,
    maxLikes: search.maxLikes ?? initialFilters.maxLikes,
    publishedFrom: search.from ?? initialFilters.publishedFrom,
    publishedTo: search.to ?? initialFilters.publishedTo,
    sort: search.sort ?? initialFilters.sort,
  }
}

// 排序值的中文名映射（报告 A2：chips 里展示用）
const sortLabels: Record<SortValue, string> = {
  "published_at:desc": "评论时间从新到旧",
  "published_at:asc": "评论时间从旧到新",
  "like_count:desc": "点赞数最多",
  "sub_comment_count:desc": "回复数最多",
  "fetched_at:desc": "最近采集",
}

// 报告 A1：列可见性 —— 评论明细表的列清单。
// 必须是模块级稳定常量，放进组件里每次渲染都会新建，导致用户勾选的状态被重置。
const COMMENT_COLUMNS = [
  { key: "select", title: "选择", alwaysVisible: true },
  // 赛道与来源拆成两列：赛道在前，来源在后（原先合并成「赛道 / 来源」一列）
  { key: "track", title: "赛道" },
  { key: "source", title: "来源" },
  { key: "title", title: "视频标题" },
  { key: "content", title: "评论内容" },
  { key: "time", title: "评论时间" },
  // 操作列冻结在右侧，藏掉用户就没法回复 / 打开视频，永远可见
  { key: "actions", title: "操作", alwaysVisible: true },
] as const satisfies readonly TableColumnDef[]

function DouyinCommentManagement() {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  // 报告 O4：初值来自 URL，于是深链 / 刷新能还原已应用的筛选
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  // 草稿态与已应用态都从 URL 起步，进入页面时面板里显示的就是当前生效的筛选
  const [draft, setDraft] = useState<Filters>(() => filtersFromSearch(search))
  const [filters, setFilters] = useState<Filters>(() =>
    filtersFromSearch(search),
  )
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [exporting, setExporting] = useState(false)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [viewMode, changeViewMode] = usePersistentViewMode(
    "douyin-comments-view",
  )
  const [sortBy, sortOrder] = filters.sort.split(":") as [
    "published_at" | "like_count" | "sub_comment_count" | "fetched_at",
    "asc" | "desc",
  ]
  // 报告 A1：列可见性 —— 评论明细表（仅 table 视图）可自行勾选要显示哪几列
  const { isVisible, visibleCount, menuProps } = useTableColumns({
    storageKey: "douyin-comments-columns",
    columns: COMMENT_COLUMNS,
  })

  const tasks = useQuery({
    queryKey: ["douyin-comment-tasks", filters.trackId, filters.sourceValue],
    queryFn: () =>
      DouyinService.listTasks({
        trackId:
          filters.trackId && filters.trackId !== allTracksValue
            ? filters.trackId
            : undefined,
        ...parseSourceSelection(filters.sourceValue),
        limit: 100,
      }),
    staleTime: 30_000,
  })
  const comments = useQuery({
    queryKey: ["douyin-comment-library", filters, page],
    queryFn: () =>
      DouyinService.listCommentLibrary({
        trackId:
          filters.trackId && filters.trackId !== allTracksValue
            ? filters.trackId
            : undefined,
        commentContent: optional(filters.commentContent),
        search: optional(filters.search),
        taskId: filters.taskId === "all" ? undefined : filters.taskId,
        awemeId: optional(filters.awemeId),
        videoCreator: optional(filters.videoCreator),
        sourceKeyword: optional(filters.sourceKeyword),
        ...parseSourceSelection(filters.sourceValue),
        commentType: filters.commentType,
        hasPictures: filters.hasPictures,
        minLikes: optionalNumber(filters.minLikes),
        maxLikes: optionalNumber(filters.maxLikes),
        publishedFrom: dateTimestamp(filters.publishedFrom),
        publishedTo: dateTimestamp(filters.publishedTo, true),
        sortBy,
        sortOrder,
        skip: page * pageSize,
        limit: pageSize,
      }),
    placeholderData: (previous) => previous,
  })
  const rows = useMemo(() => {
    const seen = new Set<string>()
    return (comments.data?.data ?? []).filter((item) => {
      const commentId = item.comment.comment_id
      if (seen.has(commentId)) return false
      seen.add(commentId)
      return true
    })
  }, [comments.data?.data])
  const summary = comments.data?.summary
  // 报告 A6：轮询刷新后点赞数 / 回复数发生变化的行短暂高亮，避免「无声刷新」
  const highlighted = useHighlightedRows(
    rows,
    (item) => item.comment.id,
    (item) => `${item.comment.like_count}:${item.comment.sub_comment_count}`,
  )
  // 报告 A5：行展开一次只开一行，展开后可见评论全文与详细信息
  const [expandedId, setExpandedId] = useState<string | null>(null)
  // 任务下拉的选项数组每次 render 都会重建引用，包 useMemo 避免下游无谓重渲染
  const taskOptions = useMemo(() => tasks.data?.data ?? [], [tasks.data?.data])
  // 本页可见 id 同样是每轮 render 重建的映射，且被全选逻辑依赖，保持引用稳定
  const visibleIds = useMemo(() => rows.map((item) => item.comment.id), [rows])
  const allVisibleSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selected.has(id))
  const activeFilterCount = countActiveFilters(filters)
  // 报告 A2：chips 要把筛选值翻译成中文展示值；赛道 / 来源名复用下拉的目录查询（同一 queryKey 命中缓存）
  const { data: trackCatalog } = useTrackCatalog()
  const trackName =
    trackCatalog?.data?.find((track) => track.id === filters.trackId)?.name ??
    filters.trackId
  const { data: sourceCatalog } = useSourceCatalog(filters.trackId)
  const sourceName = useMemo(() => {
    if (filters.sourceValue === allSourcesValue) return ""
    const [sourceType, sourceId] = filters.sourceValue.split(":")
    return (
      sourceCatalog?.data?.find(
        (option) => option.id === sourceId && option.source_type === sourceType,
      )?.name ?? "已选来源"
    )
  }, [sourceCatalog?.data, filters.sourceValue])
  const appliedTaskLabel = useMemo(() => {
    if (filters.taskId === "all") return ""
    const task = taskOptions.find((item) => item.id === filters.taskId)
    return task ? taskLabel(task) : shortId(filters.taskId)
  }, [taskOptions, filters.taskId])

  const applyFilters = () => {
    if (
      optionalNumber(draft.minLikes) !== undefined &&
      optionalNumber(draft.maxLikes) !== undefined &&
      Number(draft.minLikes) > Number(draft.maxLikes)
    ) {
      showErrorToast("最小点赞数不能大于最大点赞数")
      return
    }
    if (
      draft.publishedFrom &&
      draft.publishedTo &&
      draft.publishedFrom > draft.publishedTo
    ) {
      showErrorToast("评论开始日期不能晚于结束日期")
      return
    }
    setFilters(draft)
    setPage(0)
    setSelected(new Set())
  }

  const resetFilters = () => {
    const reset = { ...initialFilters, trackId: filters.trackId }
    setDraft(reset)
    setFilters(reset)
    setPage(0)
    setSelected(new Set())
  }

  // 报告 A2：移除单个 chip 时草稿与已应用条件同步改，filters 变化即触发列表重新查询
  const applyFilterPatch = (patch: Partial<Filters>) => {
    setDraft((current) => ({ ...current, ...patch }))
    setFilters((current) => ({ ...current, ...patch }))
    setPage(0)
    setSelected(new Set())
  }

  // 报告 O4：筛选上 URL —— 只写「已应用」的 filters，草稿值不写，刷新后还原的是真正生效的条件。
  // 依赖里只放 filters 与 navigate，不放 search 对象，避免「改 URL → 重渲染 → 再写 URL」的死循环。
  useEffect(() => {
    void navigate({
      to: "/douyin-comments",
      // 关键：用 replace 而不是 push。否则每改一次筛选就多一条浏览器历史，
      // 用户按十次后退才能离开本页。代价是「后退」回到上一个页面而不是上一条筛选，
      // 换来的是刷新、分享、深链、收藏都生效 —— 这是有意的取舍。
      replace: true,
      search: compactSearch(
        {
          track:
            filters.trackId === allTracksValue ? undefined : filters.trackId,
          source:
            filters.sourceValue === allSourcesValue
              ? undefined
              : filters.sourceValue,
          content: filters.commentContent.trim() || undefined,
          q: filters.search.trim() || undefined,
          task: filters.taskId === "all" ? undefined : filters.taskId,
          aweme: filters.awemeId.trim() || undefined,
          creator: filters.videoCreator.trim() || undefined,
          keyword: filters.sourceKeyword.trim() || undefined,
          type: filters.commentType,
          pics: filters.hasPictures,
          minLikes: filters.minLikes.trim() || undefined,
          maxLikes: filters.maxLikes.trim() || undefined,
          from: filters.publishedFrom || undefined,
          to: filters.publishedTo || undefined,
          sort: filters.sort,
        },
        // 等于默认值的键不写进 URL，未筛选时地址栏保持干净的 /douyin-comments
        { type: "all", pics: "all", sort: "published_at:desc" },
      ),
    })
  }, [filters, navigate])

  // 报告 A2：清除全部筛选条件，回到初始状态
  const clearAllFilters = () => {
    setDraft(initialFilters)
    setFilters(initialFilters)
    setPage(0)
    setSelected(new Set())
  }

  const exportSelected = async () => {
    if (!selected.size) return
    setExporting(true)
    try {
      await downloadSelectedComments([...selected])
      showSuccessToast(`已导出 ${selected.size} 条评论`)
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : "评论导出失败")
    } finally {
      setExporting(false)
    }
  }

  // 报告 A12：CSV 只导出「已选中 / 当前页」这类小数据量，全量导出仍需走上面的后端接口
  const exportCsv = () => {
    const picked = selected.size
      ? rows.filter((item) => selected.has(item.comment.id))
      : rows
    if (!picked.length) {
      showErrorToast(
        selected.size
          ? "已选评论不在当前页，请切换到所在页后再导出 CSV"
          : "当前页没有可导出的评论",
      )
      return
    }
    downloadCsv(
      selected.size ? "评论导出-已选" : "评论导出-当前页",
      picked,
      commentCsvColumns,
    )
    showSuccessToast(`已导出 ${picked.length} 条评论（CSV）`)
  }

  return (
    <div className="page-stack">
      <PageHero
        compact
        title="评论管理"
        actions={
          // 报告 A14：刷新指示器（上次更新时间 + 手动刷新），替换原有的裸刷新按钮
          <RefreshIndicator
            updatedAt={comments.dataUpdatedAt}
            refreshing={comments.isFetching}
            onRefresh={() => void comments.refetch()}
          />
        }
      >
        <p className="text-xs text-muted-foreground">
          命中{" "}
          <strong className="text-foreground">
            {compact(summary?.matched_count ?? 0)}
          </strong>{" "}
          · 主评论{" "}
          <strong className="text-foreground">
            {compact(summary?.top_level_count ?? 0)}
          </strong>{" "}
          · 回复{" "}
          <strong className="text-foreground">
            {compact(summary?.reply_count ?? 0)}
          </strong>{" "}
          · 带图{" "}
          <strong className="text-foreground">
            {compact(summary?.picture_count ?? 0)}
          </strong>
        </p>
      </PageHero>

      <FilterPanel className="space-y-2 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <TrackSelect
            value={filters.trackId}
            onValueChange={(value) => {
              const next = {
                ...draft,
                trackId: value,
                sourceValue: allSourcesValue,
                taskId: "all",
              }
              setDraft(next)
              setFilters({
                ...filters,
                trackId: value,
                sourceValue: allSourcesValue,
                taskId: "all",
              })
              setPage(0)
              setSelected(new Set())
            }}
            includeAll
            allowDisabled
            className="h-9 min-w-44"
            ariaLabel="按赛道筛选评论"
          />
          <SourceSelect
            trackId={filters.trackId}
            value={draft.sourceValue}
            onValueChange={(value) =>
              setDraft({ ...draft, sourceValue: value, taskId: "all" })
            }
            className="h-9 min-w-48"
            ariaLabel="按关键词或作者筛选评论"
          />
          <div className="relative min-w-64 flex-1">
            <Search
              aria-hidden="true"
              className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              value={draft.commentContent}
              onChange={(event) =>
                setDraft({ ...draft, commentContent: event.target.value })
              }
              onKeyDown={(event) => event.key === "Enter" && applyFilters()}
              placeholder="搜索评论内容"
              aria-label="搜索评论内容"
              className="h-9 pl-9"
            />
          </div>
          <Button
            size="sm"
            variant="outline"
            className="h-9"
            onClick={() => setFiltersOpen((current) => !current)}
            aria-expanded={filtersOpen}
          >
            <SlidersHorizontal /> 更多筛选
            {activeFilterCount > 0 && (
              <Badge variant="secondary">{activeFilterCount}</Badge>
            )}
            <ChevronDown
              aria-hidden="true"
              className={filtersOpen ? "rotate-180" : ""}
            />
          </Button>
          <Button size="sm" className="h-9" onClick={applyFilters}>
            <Search />
            查询
          </Button>
        </div>
        {/* 报告 A10：筛选预设，套用 / 保存当前已应用的筛选条件 */}
        <FilterPresetBar
          storageKey="douyin-comments-filter-presets"
          currentFilters={filters}
          onApply={(next) => {
            const merged = { ...initialFilters, ...next }
            setDraft(merged)
            setFilters(merged)
            setPage(0)
            setSelected(new Set())
          }}
        />
        {/* 报告 A2：筛选 chips，展示的是已应用（applied）的筛选条件，可单个移除或全部清除 */}
        <FilterChips
          chips={[
            filters.trackId !== allTracksValue && {
              key: "track",
              label: "赛道",
              value: trackName,
              onRemove: () =>
                applyFilterPatch({
                  trackId: allTracksValue,
                  sourceValue: allSourcesValue,
                  taskId: "all",
                }),
            },
            filters.sourceValue !== allSourcesValue && {
              key: "source",
              label: "来源",
              value: sourceName,
              onRemove: () =>
                applyFilterPatch({ sourceValue: allSourcesValue }),
            },
            filters.commentContent.trim()
              ? {
                  key: "content",
                  label: "评论正文",
                  value: filters.commentContent.trim(),
                  onRemove: () => applyFilterPatch({ commentContent: "" }),
                }
              : false,
            filters.search.trim()
              ? {
                  key: "search",
                  label: "全文",
                  value: filters.search.trim(),
                  onRemove: () => applyFilterPatch({ search: "" }),
                }
              : false,
            filters.taskId !== "all" && {
              key: "task",
              label: "所属任务",
              value: appliedTaskLabel,
              onRemove: () => applyFilterPatch({ taskId: "all" }),
            },
            filters.awemeId.trim()
              ? {
                  key: "aweme",
                  label: "作品号",
                  value: filters.awemeId.trim(),
                  onRemove: () => applyFilterPatch({ awemeId: "" }),
                }
              : false,
            filters.videoCreator.trim()
              ? {
                  key: "creator",
                  label: "视频作者",
                  value: filters.videoCreator.trim(),
                  onRemove: () => applyFilterPatch({ videoCreator: "" }),
                }
              : false,
            filters.sourceKeyword.trim()
              ? {
                  key: "keyword",
                  label: "来源关键词",
                  value: filters.sourceKeyword.trim(),
                  onRemove: () => applyFilterPatch({ sourceKeyword: "" }),
                }
              : false,
            filters.commentType !== "all" && {
              key: "type",
              label: "评论层级",
              value:
                filters.commentType === "top_level" ? "仅主评论" : "仅回复",
              onRemove: () => applyFilterPatch({ commentType: "all" }),
            },
            filters.hasPictures !== "all" && {
              key: "pictures",
              label: "评论图片",
              value: filters.hasPictures === "yes" ? "仅带图" : "仅无图",
              onRemove: () => applyFilterPatch({ hasPictures: "all" }),
            },
            filters.minLikes.trim() || filters.maxLikes.trim()
              ? {
                  key: "likes",
                  label: "点赞区间",
                  value: `${filters.minLikes.trim() || "不限"} ~ ${
                    filters.maxLikes.trim() || "不限"
                  }`,
                  onRemove: () =>
                    applyFilterPatch({ minLikes: "", maxLikes: "" }),
                }
              : false,
            filters.publishedFrom || filters.publishedTo
              ? {
                  key: "published",
                  label: "评论日期",
                  value: `${filters.publishedFrom || "不限"} ~ ${
                    filters.publishedTo || "不限"
                  }`,
                  onRemove: () =>
                    applyFilterPatch({ publishedFrom: "", publishedTo: "" }),
                }
              : false,
            filters.sort !== initialFilters.sort && {
              key: "sort",
              label: "排序",
              value: sortLabels[filters.sort],
              onRemove: () => applyFilterPatch({ sort: initialFilters.sort }),
            },
          ]}
          onClearAll={clearAllFilters}
        />
        {filtersOpen && (
          <>
            <div className="grid gap-3 border-t pt-3 md:grid-cols-2 xl:grid-cols-4">
              <Field label="全文搜索" className="xl:col-span-2">
                <div className="relative">
                  <Search
                    aria-hidden="true"
                    className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                  />
                  <Input
                    value={draft.search}
                    onChange={(event) =>
                      setDraft({ ...draft, search: event.target.value })
                    }
                    onKeyDown={(event) =>
                      event.key === "Enter" && applyFilters()
                    }
                    placeholder="评论内容、评论人、评论号、视频标题或作品号"
                    aria-label="全文搜索评论"
                    className="pl-9"
                  />
                </div>
              </Field>
              <Field label="所属任务">
                <Select
                  value={draft.taskId}
                  onValueChange={(value) =>
                    setDraft({ ...draft, taskId: value })
                  }
                >
                  <SelectTrigger className="w-full" aria-label="筛选所属任务">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部任务</SelectItem>
                    {taskOptions.map((task) => (
                      <SelectItem key={task.id} value={task.id}>
                        {taskLabel(task)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="作品号">
                <Input
                  value={draft.awemeId}
                  onChange={(event) =>
                    setDraft({ ...draft, awemeId: event.target.value })
                  }
                  placeholder="支持部分匹配"
                  aria-label="筛选作品号"
                />
              </Field>
              <Field label="视频作者">
                <Input
                  value={draft.videoCreator}
                  onChange={(event) =>
                    setDraft({ ...draft, videoCreator: event.target.value })
                  }
                  placeholder="输入作者昵称"
                  aria-label="筛选视频作者"
                />
              </Field>
              <Field label="来源关键词">
                <Input
                  value={draft.sourceKeyword}
                  onChange={(event) =>
                    setDraft({ ...draft, sourceKeyword: event.target.value })
                  }
                  placeholder="任务命中的关键词"
                  aria-label="筛选来源关键词"
                />
              </Field>
              <Field label="评论层级">
                <Select
                  value={draft.commentType}
                  onValueChange={(value) =>
                    setDraft({ ...draft, commentType: value as CommentType })
                  }
                >
                  <SelectTrigger className="w-full" aria-label="筛选评论层级">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部层级</SelectItem>
                    <SelectItem value="top_level">仅主评论</SelectItem>
                    <SelectItem value="reply">仅回复</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              <Field label="评论图片">
                <Select
                  value={draft.hasPictures}
                  onValueChange={(value) =>
                    setDraft({ ...draft, hasPictures: value as PictureFilter })
                  }
                >
                  <SelectTrigger className="w-full" aria-label="筛选评论图片">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">不限</SelectItem>
                    <SelectItem value="yes">仅带图</SelectItem>
                    <SelectItem value="no">仅无图</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              <Field label="点赞区间">
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    min={0}
                    value={draft.minLikes}
                    onChange={(event) =>
                      setDraft({ ...draft, minLikes: event.target.value })
                    }
                    placeholder="最低"
                    aria-label="最低点赞数"
                  />
                  <span className="text-muted-foreground">—</span>
                  <Input
                    type="number"
                    min={0}
                    value={draft.maxLikes}
                    onChange={(event) =>
                      setDraft({ ...draft, maxLikes: event.target.value })
                    }
                    placeholder="最高"
                    aria-label="最高点赞数"
                  />
                </div>
              </Field>
              <Field label="评论日期">
                <div className="flex items-center gap-2">
                  <Input
                    type="date"
                    value={draft.publishedFrom}
                    onChange={(event) =>
                      setDraft({ ...draft, publishedFrom: event.target.value })
                    }
                    aria-label="评论开始日期"
                  />
                  <span className="text-muted-foreground">—</span>
                  <Input
                    type="date"
                    value={draft.publishedTo}
                    onChange={(event) =>
                      setDraft({ ...draft, publishedTo: event.target.value })
                    }
                    aria-label="评论结束日期"
                  />
                </div>
              </Field>
              <Field label="排序方式">
                <Select
                  value={draft.sort}
                  onValueChange={(value) =>
                    setDraft({ ...draft, sort: value as SortValue })
                  }
                >
                  <SelectTrigger className="w-full" aria-label="选择排序方式">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="published_at:desc">
                      评论时间从新到旧
                    </SelectItem>
                    <SelectItem value="published_at:asc">
                      评论时间从旧到新
                    </SelectItem>
                    <SelectItem value="like_count:desc">点赞数最多</SelectItem>
                    <SelectItem value="sub_comment_count:desc">
                      回复数最多
                    </SelectItem>
                    <SelectItem value="fetched_at:desc">最近采集</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
            </div>
            <div className="flex flex-wrap justify-end gap-2 border-t pt-4">
              <Button variant="outline" onClick={resetFilters}>
                重置条件
              </Button>
              <Button onClick={applyFilters}>
                <Search />
                查询评论
              </Button>
            </div>
          </>
        )}
      </FilterPanel>

      <Card>
        <CardContent className="p-0">
          <div className="flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-center">
            <div>
              <p className="font-medium">评论明细</p>
              <p className="text-xs text-muted-foreground">
                共 {comments.data?.count ?? 0} 条 · 已选择 {selected.size} 条
              </p>
            </div>
            <div className="flex flex-wrap gap-2 sm:ml-auto">
              {/* 报告 A1：列可见性菜单，只在 table 视图有意义（cards / rows 不是表格） */}
              {viewMode === "table" && <TableColumnMenu {...menuProps} />}
              <ViewModeToggle
                value={viewMode}
                onChange={changeViewMode}
                label="切换评论展示方式"
              />
              <CommentExportDialog filters={filters} />
              {/* 报告 A12：CSV 导出（有选中导出选中，否则导出本页） */}
              <Button
                size="sm"
                variant="outline"
                disabled={!rows.length}
                onClick={exportCsv}
              >
                <FileSpreadsheet />
                导出 CSV
              </Button>
            </div>
          </div>
          {comments.isError ? (
            // 接口失败必须单独成态：混进空态会让用户误以为「筛选没有结果」
            <div className="p-4">
              <QueryErrorState
                title="评论列表加载失败"
                description={
                  comments.error instanceof Error && comments.error.message
                    ? comments.error.message
                    : "未能获取评论列表，请检查网络或稍后重试。"
                }
                onRetry={() => comments.refetch()}
                retrying={comments.isFetching}
              />
            </div>
          ) : rows.length && viewMode !== "table" ? (
            <div
              className={
                viewMode === "cards"
                  ? "grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3"
                  : "space-y-2 p-4"
              }
            >
              {rows.map((item) => (
                <CommentPreviewCard
                  key={item.comment.id}
                  item={item}
                  compact={viewMode === "rows"}
                  highlighted={highlighted.has(item.comment.id)}
                  checked={selected.has(item.comment.id)}
                  onCheckedChange={(checked) =>
                    setSelected((current) => {
                      const next = new Set(current)
                      if (checked) next.add(item.comment.id)
                      else next.delete(item.comment.id)
                      return next
                    })
                  }
                />
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table className="min-w-[1000px]">
                <TableHeader>
                  <TableRow>
                    {isVisible("select") && (
                      <TableHead className="w-10">
                        {/* 通病 7：表头全选只覆盖当前页，标签里把「本页」和条数写明确 */}
                        <Checkbox
                          checked={allVisibleSelected}
                          aria-label={`全选本页（共 ${visibleIds.length} 条）`}
                          onCheckedChange={(checked) => {
                            setSelected((current) => {
                              const next = new Set(current)
                              for (const id of visibleIds) {
                                if (checked) next.add(id)
                                else next.delete(id)
                              }
                              return next
                            })
                          }}
                        />
                      </TableHead>
                    )}
                    {/* 报告 A1：表头与单元格都要包 isVisible，漏一处列就会整体错位 */}
                    {isVisible("track") && (
                      <TableHead className="min-w-28">赛道</TableHead>
                    )}
                    {isVisible("source") && (
                      <TableHead className="min-w-48">来源</TableHead>
                    )}
                    {isVisible("title") && (
                      <TableHead className="min-w-56">视频标题</TableHead>
                    )}
                    {isVisible("content") && (
                      <TableHead className="min-w-80">评论内容</TableHead>
                    )}
                    {isVisible("time") && (
                      <TableHead className="min-w-36">评论时间</TableHead>
                    )}
                    {/* 报告 A8：操作列冻结在右侧，横向滚动时始终可见 */}
                    {isVisible("actions") && (
                      <TableHead className="sticky right-0 z-10 bg-background/95 text-right backdrop-blur">
                        操作
                      </TableHead>
                    )}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.length ? (
                    rows.map((item) => (
                      <CommentRow
                        key={item.comment.id}
                        item={item}
                        checked={selected.has(item.comment.id)}
                        highlighted={highlighted.has(item.comment.id)}
                        expanded={expandedId === item.comment.id}
                        isVisible={isVisible}
                        visibleCount={visibleCount}
                        onToggleExpand={() =>
                          setExpandedId((current) =>
                            current === item.comment.id
                              ? null
                              : item.comment.id,
                          )
                        }
                        onCheckedChange={(checked) =>
                          setSelected((current) => {
                            const next = new Set(current)
                            if (checked) next.add(item.comment.id)
                            else next.delete(item.comment.id)
                            return next
                          })
                        }
                      />
                    ))
                  ) : comments.isLoading ? (
                    // 报告 O8：加载态改用骨架屏，保留表格结构，数据到达时不会整块跳动
                    Array.from({ length: 6 }, (_, rowIndex) => (
                      <TableRow
                        key={`comments-skeleton-${rowIndex}`}
                        className="hover:bg-transparent"
                      >
                        {/* 报告 A1：骨架屏单元格数跟随可见列数，隐藏列后不会多出占位列 */}
                        {Array.from(
                          { length: visibleCount },
                          (_, cellIndex) => (
                            <TableCell
                              key={`comments-skeleton-cell-${cellIndex}`}
                            >
                              <Skeleton className="h-4 w-full" />
                            </TableCell>
                          ),
                        )}
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      {/* 报告 A1：空态列数跟随可见列，隐藏列后不会只占一半宽度 */}
                      <TableCell colSpan={visibleCount} className="p-0">
                        {activeFilterCount > 0 ? (
                          // 有筛选条件却没结果：行动按钮是「清除筛选」，
                          // 引导用户退出死胡同，而不是让他自己猜是哪里筛掉了
                          <EmptyState
                            compact
                            icon={MessageSquare}
                            title="没有符合当前条件的评论"
                            description="当前筛选条件下没有命中评论，可以放宽关键词、日期或点赞区间后再试。"
                            action={
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={clearAllFilters}
                              >
                                清除筛选条件
                              </Button>
                            }
                          />
                        ) : (
                          // 真的一条评论都没有：此时「重置筛选」毫无意义，
                          // 改为把人引到抖音任务，评论要等互动抓取完成后才会汇总到这里
                          <EmptyState
                            compact
                            icon={MessageSquare}
                            title="还没有评论数据"
                            description="评论会在抖音任务的互动抓取完成后汇总到这里，先创建一个采集任务吧。"
                            action={
                              <Button
                                size="sm"
                                onClick={() => void navigate({ to: "/douyin" })}
                              >
                                去创建采集任务
                              </Button>
                            }
                          />
                        )}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
          <Pager
            page={page}
            pageSize={pageSize}
            total={comments.data?.count ?? 0}
            onPageChange={setPage}
            showJumper
            className="border-t p-4"
          />
        </CardContent>
      </Card>

      {/* 报告 A3：批量操作栏，依赖选中项的批量按钮统一收进这里（不依赖选中项的按钮留在原处） */}
      <BulkActionBar
        count={selected.size}
        onClear={() => setSelected(new Set())}
        actions={
          <Button
            size="sm"
            variant="outline"
            disabled={exporting}
            onClick={exportSelected}
          >
            {exporting ? "正在导出…" : `导出已选（${selected.size}）`}
          </Button>
        }
      />
    </div>
  )
}

function CommentRow({
  item,
  checked,
  highlighted,
  expanded,
  isVisible,
  visibleCount,
  onCheckedChange,
  onToggleExpand,
}: {
  item: DouyinCommentLibraryItemPublic
  checked: boolean
  highlighted: boolean
  expanded: boolean
  // 报告 A1：列可见性由父组件统一持有，这里只负责按开关渲染单元格
  isVisible: (key: string) => boolean
  visibleCount: number
  onCheckedChange: (checked: boolean) => void
  onToggleExpand: () => void
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const { comment, aweme } = item
  const copyContent = async () => {
    try {
      await navigator.clipboard.writeText(comment.content || "")
      showSuccessToast("评论内容已复制")
    } catch {
      showErrorToast("复制失败，请手动选择文本复制")
    }
  }
  const copyCommentId = async () => {
    try {
      await navigator.clipboard.writeText(comment.comment_id)
      showSuccessToast("评论 ID 已复制")
    } catch {
      showErrorToast("复制失败，请手动选择文本复制")
    }
  }
  // 报告 A7：低频操作从操作列挪到右键菜单，操作列只保留回复与打开视频
  const menuItems: RowMenuItem[] = [
    { label: "复制评论 ID", icon: Copy, onSelect: () => void copyCommentId() },
    {
      label: "打开评论所在视频",
      icon: ExternalLink,
      onSelect: () =>
        window.open(
          getDouyinVideoUrl(aweme.aweme_id),
          "_blank",
          "noopener,noreferrer",
        ),
    },
    {
      label: "查看作者主页",
      icon: User,
      disabled: !comment.sec_uid,
      onSelect: () =>
        window.open(
          douyinUserUrl(comment.sec_uid),
          "_blank",
          "noopener,noreferrer",
        ),
    },
    {
      separatorBefore: true,
      label: "加入导出",
      icon: ListPlus,
      disabled: checked,
      onSelect: () => {
        onCheckedChange(true)
        showSuccessToast("已加入导出列表")
      },
    },
  ]
  return (
    <>
      <RowContextMenu
        label={`评论 ${shortId(comment.comment_id)}`}
        items={menuItems}
      >
        <TableRow
          data-state={checked ? "selected" : undefined}
          className={cn(highlighted && "row-highlight")}
        >
          {/* 报告 A1：每个单元格都要跟表头同步包 isVisible */}
          {isVisible("select") && (
            <TableCell>
              <Checkbox
                checked={checked}
                aria-label={`选择评论 ${comment.comment_id}`}
                onCheckedChange={(value) => onCheckedChange(Boolean(value))}
              />
            </TableCell>
          )}
          {isVisible("track") && (
            <TableCell className="align-top">
              <TrackBadge
                trackId={item.track_id}
                trackName={item.track_name}
                className="max-w-40"
              />
            </TableCell>
          )}
          {/* 报告 A1：来源单独成列，表头与单元格都要包 isVisible */}
          {isVisible("source") && (
            <TableCell className="align-top">
              <SourceBadge
                sourceType={aweme.source_type}
                sourceName={aweme.source_name}
                sourceLabel={aweme.source_label}
                className="max-w-48"
              />
              <p
                className="mt-1.5 line-clamp-2 text-xs text-muted-foreground"
                title={aweme.source_keyword || item.task_title}
              >
                {aweme.source_label ||
                  `[任务] ${item.task_title || "指定作品"}`}
              </p>
            </TableCell>
          )}
          {isVisible("title") && (
            <TableCell className="align-top">
              <Tooltip>
                <TooltipTrigger asChild>
                  <p className="line-clamp-2 cursor-default text-sm font-normal leading-5">
                    {aweme.title || aweme.aweme_id}
                  </p>
                </TooltipTrigger>
                <TooltipContent className="max-w-sm">
                  {aweme.title || aweme.aweme_id}
                </TooltipContent>
              </Tooltip>
            </TableCell>
          )}
          {isVisible("content") && (
            <TableCell className="align-top">
              <div className="flex items-start gap-1.5">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <p className="line-clamp-3 flex-1 cursor-default whitespace-pre-wrap break-words text-sm leading-6">
                      {comment.content || "（无文本内容）"}
                    </p>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-md whitespace-pre-wrap break-words">
                    {comment.content || "（无文本内容）"}
                  </TooltipContent>
                </Tooltip>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label="复制评论内容"
                  disabled={!comment.content}
                  onClick={copyContent}
                >
                  <Copy />
                </Button>
                {/* 报告 A5：展开行查看全文与详细信息 */}
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label={expanded ? "收起评论详情" : "展开评论详情"}
                  aria-expanded={expanded}
                  onClick={onToggleExpand}
                >
                  <ChevronRight
                    aria-hidden="true"
                    className={cn(
                      "transition-transform",
                      expanded && "rotate-90",
                    )}
                  />
                </Button>
              </div>
            </TableCell>
          )}
          {isVisible("time") && (
            <TableCell className="whitespace-nowrap align-top text-xs text-muted-foreground">
              {/* 报告 A16：时间点改为相对时间，悬停可见绝对时间（create_time 是秒级时间戳） */}
              <TimeAgo
                value={comment.create_time ? comment.create_time * 1000 : null}
                neverText="未知"
              />
            </TableCell>
          )}
          {/* 报告 A8：操作列冻结在右侧 */}
          {isVisible("actions") && (
            <TableCell className="sticky right-0 bg-background/95 align-top text-right backdrop-blur">
              <div className="flex justify-end gap-1">
                <InteractionComposerDialog
                  taskId={comment.task_id}
                  aweme={aweme}
                  interactionType="comment_reply"
                  targetComment={comment}
                  compact
                />
                <Button size="icon-sm" variant="ghost" asChild>
                  <a
                    href={getDouyinVideoUrl(aweme.aweme_id)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <ExternalLink />
                  </a>
                </Button>
              </div>
            </TableCell>
          )}
        </TableRow>
      </RowContextMenu>
      {/* 报告 A5：展开行显示评论详情，列表里的原文是截断的，这里看全文 */}
      {expanded && (
        <TableRow className="bg-muted/30 hover:bg-muted/30">
          {/* 报告 A1：展开行横跨所有可见列，隐藏列后 colSpan 必须跟着变，否则会错位 */}
          <TableCell colSpan={visibleCount} className="whitespace-normal p-4">
            <div className="space-y-2">
              <p className="whitespace-pre-wrap break-words text-sm leading-6">
                {comment.content || "（无文本内容）"}
              </p>
              <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
                <span>评论 ID：{comment.comment_id}</span>
                <span>评论人：{comment.nickname || "匿名用户"}</span>
                <span>点赞 {comment.like_count}</span>
                <span>回复 {comment.sub_comment_count}</span>
                <span>
                  评论时间：
                  {formatUnix(comment.create_time, { fallback: "未知" })}
                </span>
                <span>采集时间：{formatDateTime(comment.fetched_at)}</span>
                <span>作品号：{aweme.aweme_id}</span>
                <span>
                  所属任务：{item.task_title || shortId(comment.task_id)}
                </span>
                {comment.pictures && <span>含图片</span>}
              </div>
            </div>
          </TableCell>
        </TableRow>
      )}
    </>
  )
}

function CommentPreviewCard({
  item,
  checked,
  highlighted,
  compact: compactLayout,
  onCheckedChange,
}: {
  item: DouyinCommentLibraryItemPublic
  checked: boolean
  highlighted: boolean
  compact: boolean
  onCheckedChange: (checked: boolean) => void
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const { comment, aweme } = item
  const isReply = !["", "0"].includes(comment.parent_comment_id)
  const copyContent = async () => {
    try {
      await navigator.clipboard.writeText(comment.content || "")
      showSuccessToast("评论内容已复制")
    } catch {
      showErrorToast("复制失败，请手动选择文本复制")
    }
  }
  return (
    <Card
      data-state={checked ? "selected" : undefined}
      className={cn("gap-0 py-0", highlighted && "row-highlight")}
    >
      <CardContent
        className={
          compactLayout
            ? "flex flex-col gap-3 p-3 lg:flex-row lg:items-center"
            : "space-y-3 p-4"
        }
      >
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center">
            <Checkbox
              checked={checked}
              aria-label={`选择评论 ${comment.comment_id}`}
              onCheckedChange={(value) => onCheckedChange(Boolean(value))}
            />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <TrackBadge
                trackId={item.track_id}
                trackName={item.track_name}
                className="max-w-40"
              />
              <SourceBadge
                sourceType={aweme.source_type}
                sourceName={aweme.source_name}
                sourceLabel={aweme.source_label}
                className="max-w-48"
              />
            </div>
            <p
              className="mt-1 line-clamp-2 text-sm font-normal"
              title={aweme.title || aweme.aweme_id}
            >
              {aweme.title || aweme.aweme_id}
            </p>
          </div>
        </div>
        <div className={compactLayout ? "min-w-0 flex-[1.5]" : ""}>
          <p className="line-clamp-3 whitespace-pre-wrap break-words text-sm leading-6">
            {comment.content || "（无文本内容）"}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <Badge variant={isReply ? "secondary" : "outline"}>
              {isReply ? "回复" : "主评论"}
            </Badge>
            {comment.pictures && (
              <Badge variant="outline">
                <ImageIcon aria-hidden="true" /> 带图
              </Badge>
            )}
            {/* 报告 A16：时间点改为相对时间 */}
            <TimeAgo
              value={comment.create_time ? comment.create_time * 1000 : null}
              neverText="未知"
            />
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-1">
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="复制评论内容"
            disabled={!comment.content}
            onClick={copyContent}
          >
            <Copy />
          </Button>
          <InteractionComposerDialog
            taskId={comment.task_id}
            aweme={aweme}
            interactionType="comment_reply"
            targetComment={comment}
            compact
          />
          <Button size="icon-sm" variant="ghost" asChild>
            <a
              href={getDouyinVideoUrl(aweme.aweme_id)}
              target="_blank"
              rel="noreferrer"
              aria-label="在抖音中打开视频"
            >
              <ExternalLink />
            </a>
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

const commentExportFields: Array<{
  key: string
  label: string
  value: (item: DouyinCommentLibraryItemPublic) => string
}> = [
  {
    key: "content",
    label: "评论内容",
    value: (item) => item.comment.content || "",
  },
  {
    key: "nickname",
    label: "评论人",
    value: (item) => item.comment.nickname || "匿名用户",
  },
  {
    key: "level",
    label: "评论层级",
    value: (item) =>
      ["", "0"].includes(item.comment.parent_comment_id) ? "主评论" : "回复",
  },
  {
    key: "like_count",
    label: "点赞数",
    value: (item) => String(item.comment.like_count),
  },
  {
    key: "create_time",
    label: "评论时间",
    value: (item) => formatUnix(item.comment.create_time, { fallback: "未知" }),
  },
  {
    key: "aweme_title",
    label: "视频标题",
    value: (item) => item.aweme.title || item.aweme.aweme_id,
  },
  {
    key: "aweme_id",
    label: "作品号",
    value: (item) => item.aweme.aweme_id,
  },
  {
    key: "aweme_url",
    label: "视频链接",
    value: (item) =>
      item.aweme.aweme_url || getDouyinVideoUrl(item.aweme.aweme_id),
  },
  {
    key: "aweme_nickname",
    label: "视频作者",
    value: (item) => item.aweme.nickname || "匿名作者",
  },
  {
    key: "source_keyword",
    label: "来源关键词",
    value: (item) => item.aweme.source_label || item.aweme.source_keyword || "",
  },
]

/**
 * CSV 导出列。
 *
 * 报告 A12 原本只导「内容摘要（截断 80 字）」，用户明确要求导出**完整评论**，
 * 因此这里改成整段内容，并补上作品链接与评论层级。
 */
const commentCsvColumns: CsvColumn<DouyinCommentLibraryItemPublic>[] = [
  { header: "评论 ID", value: (item) => item.comment.comment_id },
  {
    header: "评论内容",
    value: (item) => (item.comment.content || "").replace(/\s+/g, " ").trim(),
  },
  { header: "评论人", value: (item) => item.comment.nickname || "匿名用户" },
  {
    header: "评论层级",
    value: (item) =>
      ["", "0"].includes(item.comment.parent_comment_id) ? "主评论" : "回复",
  },
  { header: "点赞数", value: (item) => item.comment.like_count },
  { header: "回复数", value: (item) => item.comment.sub_comment_count },
  {
    header: "评论时间",
    value: (item) => formatUnix(item.comment.create_time, { fallback: "未知" }),
  },
  { header: "作品号", value: (item) => item.aweme.aweme_id },
  {
    header: "视频链接",
    value: (item) =>
      item.aweme.aweme_url || getDouyinVideoUrl(item.aweme.aweme_id),
  },
  {
    header: "视频标题",
    value: (item) => item.aweme.title || item.aweme.aweme_id,
  },
]

function CommentExportDialog({ filters }: { filters: Filters }) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [open, setOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [progress, setProgress] = useState<{
    loaded: number
    total: number
  } | null>(null)
  // 取消标记用 ref：翻页循环每轮读的都是最新值，不受 state 异步更新影响
  const abortedRef = useRef(false)
  // 确认框是独立 portal，弹它会被 Radix 当成「点击弹窗外」而关掉本弹窗，
  // 且关闭事件可能晚于「继续导出」的确认返回 —— 曾因此出现「刚确认就提示已取消」。
  // 置位期间（确认到导出结束）忽略关闭事件，只有显式点「取消导出」才中断。
  const suppressCloseAbortRef = useRef(false)
  const [sortBy, sortOrder] = filters.sort.split(":") as [
    "published_at" | "like_count" | "sub_comment_count" | "fetched_at",
    "asc" | "desc",
  ]
  const exportTxt = async () => {
    setExporting(true)
    abortedRef.current = false
    setProgress(null)
    try {
      const request = {
        trackId:
          filters.trackId && filters.trackId !== allTracksValue
            ? filters.trackId
            : undefined,
        commentContent: optional(filters.commentContent),
        search: optional(filters.search),
        taskId: filters.taskId === "all" ? undefined : filters.taskId,
        awemeId: optional(filters.awemeId),
        videoCreator: optional(filters.videoCreator),
        sourceKeyword: optional(filters.sourceKeyword),
        ...parseSourceSelection(filters.sourceValue),
        commentType: filters.commentType,
        hasPictures: filters.hasPictures,
        minLikes: optionalNumber(filters.minLikes),
        maxLikes: optionalNumber(filters.maxLikes),
        publishedFrom: dateTimestamp(filters.publishedFrom),
        publishedTo: dateTimestamp(filters.publishedTo, true),
        sortBy,
        sortOrder,
        limit: 100 as const,
      }
      const first = await DouyinService.listCommentLibrary({
        ...request,
        skip: 0,
      })
      const total = first.count ?? 0
      // 报告 O15：改用统一确认框（确认后继续走下面的翻页导出流程）
      if (total > 1000) {
        suppressCloseAbortRef.current = true
        const confirmed = await confirmDialog({
          title: "命中条数较多，确认继续导出？",
          description: `当前筛选条件命中 ${total} 条评论，导出可能需要较长时间。导出会包含全部命中数据，不设条数上限。`,
          confirmText: "继续导出",
        })
        if (!confirmed) {
          suppressCloseAbortRef.current = false
          return
        }
        // 确认框关闭时本弹窗可能已被连带关闭：显式恢复，避免被当成取消
        abortedRef.current = false
        setOpen(true)
      }
      const items = [...(first.data ?? [])]
      setProgress({ loaded: items.length, total })
      while (items.length < total) {
        // 用户在弹窗里点取消/关闭后，立即停止后续串行翻页
        if (abortedRef.current) {
          showErrorToast("已取消导出")
          return
        }
        const page = await DouyinService.listCommentLibrary({
          ...request,
          skip: items.length,
        })
        if (!page.data?.length) break
        items.push(...page.data)
        setProgress({ loaded: items.length, total })
        // 每轮让出一次事件循环：请求本身会 await，这里再补一次确保进度文案能渲染出来
        await new Promise((resolve) => setTimeout(resolve, 0))
      }
      if (!items.length) {
        showErrorToast("当前筛选结果没有评论可导出")
        return
      }
      const lines = [
        `导出时间\t${new Date().toLocaleString("zh-CN")}`,
        `筛选摘要\t${activeFilterSummary(filters)}`,
        "",
        commentExportFields.map((field) => field.label).join("\t"),
        ...items.map((item) =>
          commentExportFields
            .map((field) => txtCell(field.value(item)))
            .join("\t"),
        ),
      ]
      const content = `\uFEFF${lines.join("\r\n")}\r\n`
      const url = URL.createObjectURL(
        new Blob([content], {
          type: "text/plain;charset=utf-8",
        }),
      )
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = `douyin-comments-${Date.now()}.txt`
      anchor.click()
      URL.revokeObjectURL(url)
      showSuccessToast(`已按筛选条件导出 ${items.length} 条评论`)
      setOpen(false)
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : "评论导出失败")
    } finally {
      suppressCloseAbortRef.current = false
      setExporting(false)
      setProgress(null)
    }
  }

  const cancelExport = () => {
    abortedRef.current = true
    setOpen(false)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        // 导出中关闭弹窗视为取消（避免后台继续串行翻页）；
        // 确认框引起的「连带关闭」不算取消，否则刚确认就会提示「已取消导出」。
        if (!next && !suppressCloseAbortRef.current) abortedRef.current = true
        setOpen(next)
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <Download />
          导出筛选结果
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>导出筛选结果</DialogTitle>
          <DialogDescription>
            导出当前全部筛选结果为
            TXT，仅包含评论、用户、视频、关键词和时间等关键字段；超过 1000
            条时会再次确认，命中多少条就导出多少条，不设上限。
          </DialogDescription>
        </DialogHeader>
        <p className="rounded-lg bg-muted/50 p-3 text-sm text-muted-foreground">
          导出字段：{commentExportFields.map((field) => field.label).join("、")}
        </p>
        {exporting && (
          <p className="text-sm text-muted-foreground" aria-live="polite">
            {progress && progress.total > 0
              ? `正在导出 ${progress.loaded} / ${progress.total} 条…`
              : "正在读取筛选结果…"}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={cancelExport}>
            {exporting ? "取消导出" : "取消"}
          </Button>
          <Button onClick={exportTxt} disabled={exporting}>
            <Download />
            {exporting ? "正在导出…" : "确认导出 TXT"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function txtCell(value: string) {
  return value.replace(/[\t\r\n]+/g, " ").trim()
}

function Field({
  label,
  children,
  className,
}: {
  label: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={className}>
      <Label className="mb-2 block text-xs text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  )
}

function optional(value: string) {
  return value.trim() || undefined
}

function countActiveFilters(filters: Filters) {
  return [
    filters.commentContent,
    filters.search,
    filters.taskId !== "all" ? filters.taskId : "",
    filters.sourceValue !== allSourcesValue ? filters.sourceValue : "",
    filters.awemeId,
    filters.videoCreator,
    filters.sourceKeyword,
    filters.commentType !== "all" ? filters.commentType : "",
    filters.hasPictures !== "all" ? filters.hasPictures : "",
    filters.minLikes,
    filters.maxLikes,
    filters.publishedFrom,
    filters.publishedTo,
    filters.sort !== initialFilters.sort ? filters.sort : "",
  ].filter(Boolean).length
}

function activeFilterSummary(filters: Filters) {
  const labels = [
    filters.commentContent && `正文“${filters.commentContent}”`,
    filters.search && `全文“${filters.search}”`,
    filters.taskId !== "all" && "指定任务",
    filters.sourceValue !== allSourcesValue && "指定关键词/作者",
    filters.videoCreator && `作者“${filters.videoCreator}”`,
    filters.sourceKeyword && `关键词“${filters.sourceKeyword}”`,
    filters.commentType !== "all" &&
      (filters.commentType === "top_level" ? "仅主评论" : "仅回复"),
    filters.hasPictures !== "all" &&
      (filters.hasPictures === "yes" ? "仅带图" : "仅无图"),
  ].filter(Boolean)
  return labels.slice(0, 4).join(" · ") || "已应用高级筛选条件"
}

function optionalNumber(value: string) {
  if (!value.trim()) return undefined
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

function dateTimestamp(value: string, endOfDay = false) {
  if (!value) return undefined
  const suffix = endOfDay ? "T23:59:59" : "T00:00:00"
  return Math.floor(new Date(`${value}${suffix}`).getTime() / 1_000)
}

function taskLabel(task: CrawlTaskPublic) {
  const keywords = task.request.keywords
  const target =
    Array.isArray(keywords) && keywords.length
      ? keywords.join("、")
      : shortId(task.id)
  return `${target} · ${formatDateTime(task.created_at)}`
}

function shortId(value: string) {
  return value.slice(0, 8)
}

/** 报告 A7：评论作者主页地址（sec_uid 形如 MS4wLjAB…） */
function douyinUserUrl(secUid: string) {
  return `https://www.douyin.com/user/${encodeURIComponent(secUid)}`
}

// 模块级单例：`new Intl.*` 单次毫秒级，放进渲染路径会随列表长度线性放大。
const COMPACT_FORMATTER = new Intl.NumberFormat("zh-CN", {
  notation: "compact",
})

function compact(value: number) {
  return COMPACT_FORMATTER.format(value)
}

async function downloadSelectedComments(commentIds: string[]) {
  const token = getAccessToken()
  const response = await fetch(
    `${browserApiBase()}/api/v1/douyin/comments/export`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ comment_ids: commentIds }),
    },
  )
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string
    } | null
    throw new Error(payload?.detail || `评论导出失败 (${response.status})`)
  }
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement("a")
  anchor.href = url
  const disposition = response.headers.get("Content-Disposition") || ""
  const match =
    disposition.match(/filename\*=UTF-8''([^;]+)/i) ||
    disposition.match(/filename="?([^";]+)"?/i)
  anchor.download = match
    ? decodeURIComponent(match[1])
    : "douyin-selected-comments.txt"
  anchor.click()
  URL.revokeObjectURL(url)
}

function browserApiBase() {
  if (import.meta.env.DEV) return window.location.origin
  return new URL(OpenAPI.BASE || window.location.origin, window.location.origin)
    .toString()
    .replace(/\/$/, "")
}
