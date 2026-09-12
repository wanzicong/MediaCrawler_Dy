import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  Captions,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  ExternalLink,
  FileDown,
  FileSpreadsheet,
  Inbox,
  Languages,
  LayoutGrid,
  List,
  ListFilter,
  LoaderCircle,
  MessageCircle,
  PlaySquare,
  RotateCcw,
  Search,
  SearchX,
  Table2,
} from "lucide-react"
import { Fragment, memo, useCallback, useMemo, useRef, useState } from "react"

import {
  type CrawlTaskPublic,
  type DouyinAwemePublic,
  type DouyinMediaAssetPublic,
  DouyinService,
  type DouyinTagRefPublic,
  DouyinTagsService,
  type DouyinWorkPublic,
  OpenAPI,
} from "@/client"
import { BulkActionBar } from "@/components/Common/BulkActionBar"
import { confirmDialog } from "@/components/Common/confirm-dialog"
import { EmptyState } from "@/components/Common/EmptyState"
import { FilterChips } from "@/components/Common/FilterChips"
import { FilterPresetBar } from "@/components/Common/FilterPresetBar"
import { Pager } from "@/components/Common/Pager"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { RefreshIndicator } from "@/components/Common/RefreshIndicator"
import { RowContextMenu } from "@/components/Common/RowContextMenu"
import { TableColumnMenu } from "@/components/Common/TableColumnMenu"
import { TimeAgo } from "@/components/Common/TimeAgo"
import { AwemeActions } from "@/components/Douyin/AwemeActions"
import { BatchCommentDialog } from "@/components/Douyin/BatchCommentDialog"
import { InteractionComposerDialog } from "@/components/Douyin/InteractionComposerDialog"
import { MediaMigrationDialog } from "@/components/Douyin/MediaMigrationDialog"
import { ProcessMediaDialog } from "@/components/Douyin/ProcessMediaDialog"
import { SourceBadge } from "@/components/Douyin/SourceSelect"
import { VideoPreviewDialog } from "@/components/Douyin/VideoPreviewDialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useCustomToast from "@/hooks/useCustomToast"
import { useHighlightedRows } from "@/hooks/useHighlightedRows"
import { type TableColumnDef, useTableColumns } from "@/hooks/useTableColumns"
import { useVirtualRows, VIRTUALIZE_THRESHOLD } from "@/hooks/useVirtualRows"
import { getAccessToken } from "@/lib/auth-token"
import { downloadCsv } from "@/lib/csv"
import { formatDateTime, formatUnix } from "@/lib/time"
import { cn } from "@/lib/utils"
import { getDouyinVideoUrl, handleError } from "@/utils"

const pageSize = 20
/** 批量补采评论时的并发上限，避免一次性向后端打满请求 */
const COMMENT_RECRAWL_CONCURRENCY = 5
type SortValue =
  | "published_at:desc"
  | "published_at:asc"
  | "liked_count:desc"
  | "comment_count:desc"
  | "collected_count:desc"
  | "persisted_comment_count:desc"
type WorkView = "table" | "rows" | "cards"
/** 视频 / 字幕状态的中文名，筛选下拉与筛选 chips（报告 A2）共用同一套文案 */
const DOWNLOAD_STATUS_LABELS: Record<string, string> = {
  downloaded: "视频已完成",
  downloading: "视频下载中",
  failed: "视频失败",
}
const SUBTITLE_STATUS_LABELS: Record<string, string> = {
  completed: "字幕已完成",
  running: "字幕处理中",
  failed: "字幕失败",
}
/** 媒体 / 字幕流水线状态的中文名：PipelineView、行展开详情（报告 A5）与 CSV 导出（报告 A12）共用 */
const PIPELINE_STATUS_LABELS: Record<string, string> = {
  queued: "等待",
  downloading: "下载中",
  downloaded: "已完成",
  pending: "等待",
  running: "处理中",
  completed: "已完成",
  failed: "失败",
}

// 报告 A1：列可见性 —— 作品表格视图（7 列）的列清单，与表头一一对应。
// 必须是模块级常量：放进组件内每次 render 都会新建，hook 里的隐藏状态会被反复重置。
const WORKS_TABLE_COLUMNS = [
  // 复选框选择列有独立表头，不允许隐藏，否则用户没法勾选
  { key: "select", title: "选择", alwaysVisible: true },
  { key: "work", title: "作品" },
  { key: "published", title: "发布时间" },
  { key: "interactions", title: "互动数据" },
  { key: "comments", title: "已保存评论" },
  { key: "media", title: "视频 / 存储" },
  { key: "subtitle", title: "字幕" },
] as const satisfies readonly TableColumnDef[]

export function UnifiedWorksPanel({
  task,
  active,
}: {
  task: CrawlTaskPublic
  active: boolean
}) {
  const taskId = task.id
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [page, setPage] = useState(0)
  const [search, setSearch] = useState("")
  const [sort, setSort] = useState<SortValue>("published_at:desc")
  const [downloadStatus, setDownloadStatus] = useState("all")
  const [subtitleStatus, setSubtitleStatus] = useState("all")
  const [tagId, setTagId] = useState("all")
  // 用 Set 代替数组：行内复选框判定从 O(n) includes 降为 O(1) has，勾选不再随页大小劣化
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  // 报告 A5：表格视图中已展开详情的作品 ID
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const [view, setView] = useState<WorkView>("table")
  const [subtitleFormat, setSubtitleFormat] = useState<"srt" | "vtt" | "txt">(
    "srt",
  )
  const [recrawlProgress, setRecrawlProgress] = useState({
    created: 0,
    total: 0,
  })
  const [sortBy, sortOrder] = sort.split(":") as [
    (
      | "published_at"
      | "liked_count"
      | "comment_count"
      | "collected_count"
      | "persisted_comment_count"
    ),
    "asc" | "desc",
  ]
  const worksQuery = useQuery({
    queryKey: [
      "douyin-works",
      taskId,
      page,
      search,
      sort,
      downloadStatus,
      subtitleStatus,
      tagId,
    ],
    queryFn: () =>
      DouyinService.listWorks({
        taskId,
        search: search.trim() || undefined,
        downloadStatus: downloadStatus === "all" ? undefined : downloadStatus,
        subtitleStatus: subtitleStatus === "all" ? undefined : subtitleStatus,
        tagId: tagId === "all" ? undefined : tagId,
        sortBy,
        sortOrder,
        skip: page * pageSize,
        limit: pageSize,
      }),
    placeholderData: (previous) => previous,
    refetchInterval: active ? 2_000 : 5_000,
  })
  const tagsQuery = useQuery({
    queryKey: ["douyin-works-tags", taskId],
    queryFn: () =>
      DouyinTagsService.listTags({
        taskId,
        sortBy: "aweme_count",
        sortOrder: "desc",
        limit: 500,
      }),
    staleTime: 30_000,
  })
  const summaryQuery = useQuery({
    queryKey: ["douyin-media-summary", taskId],
    queryFn: () => DouyinService.getMediaSummary({ taskId }),
    refetchInterval: active ? 2_000 : 5_000,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["douyin-works", taskId] }),
      queryClient.invalidateQueries({ queryKey: ["douyin-media", taskId] }),
      queryClient.invalidateQueries({
        queryKey: ["douyin-media-summary", taskId],
      }),
      // 标签下拉里的作品计数随作品状态变化，漏掉它会出现「筛选下拉数量不刷新」
      queryClient.invalidateQueries({
        queryKey: ["douyin-works-tags", taskId],
      }),
    ])
  }
  const retry = useMutation({
    mutationFn: (assetIds: string[]) =>
      DouyinService.retryMedia({
        taskId,
        requestBody: {
          asset_ids: assetIds,
          retry_downloads: true,
          retry_subtitles: true,
        },
      }),
    onSuccess: async () => {
      showSuccessToast("失败项已重新排队")
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const retranslate = useMutation({
    mutationFn: (assetId: string) =>
      DouyinService.retranslateMedia({ taskId, assetId }),
    onSuccess: async () => {
      showSuccessToast("字幕已重新提交到远程服务")
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const recrawlComments = useMutation({
    mutationFn: async (awemeIds: string[]) => {
      // 原来是串行 for 逐条 await，选满一页要排队等 20 次请求；改成每批最多 5 个并发，
      // 并把已完成数量回写进度，用户能看到「已创建 N / M」而不是无反馈的等待。
      setRecrawlProgress({ created: 0, total: awemeIds.length })
      let created = 0
      for (
        let index = 0;
        index < awemeIds.length;
        index += COMMENT_RECRAWL_CONCURRENCY
      ) {
        const batch = awemeIds.slice(index, index + COMMENT_RECRAWL_CONCURRENCY)
        await Promise.all(
          batch.map((awemeId) =>
            DouyinService.recrawlAwemeComments({
              taskId,
              awemeId,
              requestBody: {
                fetch_sub_comments: Boolean(task.request.fetch_sub_comments),
                max_comments_per_aweme: Number(
                  task.request.max_comments_per_aweme ?? 10,
                ),
                request_delay_level:
                  task.request.request_delay_level === "ultra_steady"
                    ? "ultra_steady"
                    : "steady",
                account_id: task.account_id ?? undefined,
              },
            }),
          ),
        )
        created += batch.length
        setRecrawlProgress({ created, total: awemeIds.length })
      }
      return created
    },
    onSuccess: async (created) => {
      showSuccessToast(`已为 ${created} 个视频创建评论补采任务`)
      setSelected(new Set())
      setRecrawlProgress({ created: 0, total: 0 })
      await queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] })
    },
    onError: handleError.bind(showErrorToast),
  })
  // `?? []` 每次渲染都会新建数组，直接作为依赖会让下游 memo 全部失效，先兜住引用
  const rows = useMemo(() => worksQuery.data?.data ?? [], [worksQuery.data])
  // 报告 A6：轮询刷新后，下载 / 字幕 / 媒体状态发生变化的作品行短暂高亮（首次加载不闪）
  const highlighted = useHighlightedRows(
    rows,
    (row) => row.aweme.aweme_id,
    (row) =>
      `${row.media?.status ?? "-"}:${row.media?.subtitle?.status ?? "-"}:${row.media?.migration_status ?? "-"}`,
  )
  // 报告 A1：列可见性 —— 表头、正常行、展开行 colSpan、空态 colSpan 与加载骨架
  // 共用同一份状态，所以只在父组件里取一次往下传，避免各处各建导致列数不一致。
  const { isVisible, visibleCount, menuProps } = useTableColumns({
    storageKey: "unified-works-panel-columns",
    columns: WORKS_TABLE_COLUMNS,
  })
  const pageIds = useMemo(() => rows.map((row) => row.aweme.aweme_id), [rows])
  const allPageSelected =
    pageIds.length > 0 && pageIds.every((id) => selected.has(id))
  const selectedWorks = useMemo(
    () => rows.filter((row) => selected.has(row.aweme.aweme_id)),
    [rows, selected],
  )
  const somePageSelected = selectedWorks.length > 0 && !allPageSelected
  const selectedAssets = useMemo(
    () =>
      rows
        .filter((row) => selected.has(row.aweme.aweme_id) && row.media)
        .map((row) => row.media as DouyinMediaAssetPublic),
    [rows, selected],
  )
  const selectedIds = useMemo(() => Array.from(selected), [selected])
  const togglePageSelection = useCallback(
    (checked: boolean) => {
      setSelected((current) => {
        const next = new Set(current)
        for (const id of pageIds) {
          if (checked) next.add(id)
          else next.delete(id)
        }
        return next
      })
    },
    [pageIds],
  )
  // 行组件用 memo 包裹，回调若每次渲染都换引用会让 memo 失效：
  // showErrorToast / mutate 这类每次渲染新建的值，分别用 ref 与解构固定依赖。
  const errorToastRef = useRef(showErrorToast)
  errorToastRef.current = showErrorToast
  const toggleSelection = useCallback((awemeId: string, checked: boolean) => {
    setSelected((current) => {
      const next = new Set(current)
      if (checked) next.add(awemeId)
      else next.delete(awemeId)
      return next
    })
  }, [])
  // 报告 A5：切换表格行的「作品详情」展开
  const toggleExpanded = useCallback((awemeId: string) => {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(awemeId)) next.delete(awemeId)
      else next.add(awemeId)
      return next
    })
  }, [])
  // 报告 A7：右键菜单里的「复制作品 ID」
  const copyAwemeId = useCallback(
    async (awemeId: string) => {
      try {
        await navigator.clipboard.writeText(awemeId)
        showSuccessToast("作品 ID 已复制")
      } catch {
        showErrorToast("复制失败，请手动选择文本复制")
      }
    },
    [showErrorToast, showSuccessToast],
  )
  const handleDownload = useCallback(
    (asset: DouyinMediaAssetPublic) =>
      downloadMedia(taskId, asset, errorToastRef.current),
    [taskId],
  )
  const { mutate: retryMutate } = retry
  const handleRetry = useCallback(
    (assetId: string) => retryMutate([assetId]),
    [retryMutate],
  )
  const { mutate: retranslateMutate } = retranslate
  const handleRetranslate = useCallback(
    (assetId: string) => retranslateMutate(assetId),
    [retranslateMutate],
  )
  const failedAssets = useMemo(
    () =>
      rows
        .map((row) => row.media)
        .filter((asset): asset is DouyinMediaAssetPublic =>
          Boolean(
            asset &&
              (asset.status === "failed" ||
                asset.subtitle?.status === "failed"),
          ),
        )
        .map((asset) => asset.id),
    [rows],
  )
  const summary = summaryQuery.data
  const lastMediaActivity = useMemo(
    () =>
      rows.reduce<string | null>((latest, row) => {
        const updatedAt = row.media?.updated_at
        if (!updatedAt) return latest
        return !latest || new Date(updatedAt) > new Date(latest)
          ? updatedAt
          : latest
      }, null),
    [rows],
  )
  // 首屏按钮的显隐依赖它，避免每次勾选/翻页都整页遍历
  const hasDownloadableRows = useMemo(
    () => rows.some((row) => row.media?.download_available),
    [rows],
  )
  const selectedAssetIds = useMemo(
    () => selectedAssets.map((asset) => asset.id),
    [selectedAssets],
  )
  const hasMigratableSelection = useMemo(
    () =>
      selectedAssets.some(
        (asset) =>
          asset.storage_backend === "local" && asset.download_available,
      ),
    [selectedAssets],
  )
  // 报告 A2：筛选 chips 里的标签用中文名展示，标签列表还没到位时退化为 id
  const selectedTagName = useMemo(() => {
    const tag = (tagsQuery.data?.data ?? []).find((item) => item.id === tagId)
    return tag ? `#${tag.name}` : tagId
  }, [tagsQuery.data, tagId])
  // 报告 A2：改筛选后统一回到第 1 页并清空勾选，避免留下跨筛选的选中项
  const resetPageAndSelection = useCallback(() => {
    setPage(0)
    setSelected(new Set())
  }, [])
  // 报告 A4/O8：空态要区分「真的没采到数据」和「被筛选条件筛空」，行动按钮据此切换
  const hasActiveFilters =
    Boolean(search) ||
    downloadStatus !== "all" ||
    subtitleStatus !== "all" ||
    tagId !== "all"
  const clearFilters = useCallback(() => {
    setSearch("")
    setDownloadStatus("all")
    setSubtitleStatus("all")
    setTagId("all")
    resetPageAndSelection()
  }, [resetPageAndSelection])

  // 报告 O19：作品列表虚拟滚动（只渲染可视区 + 上下缓冲行）。
  // 本页单页上限由 pageSize（20）决定，远低于 VIRTUALIZE_THRESHOLD，
  // 所以当前恒走原路径、零行为变化；单页量级上调后自动生效。
  // 行展开（A5）会让行高不定，固定行高撑不出正确总高，展开时回退到整表渲染。
  const scrollRef = useRef<HTMLDivElement>(null)
  const virtualizeRows = rows.length > VIRTUALIZE_THRESHOLD
  const virtualizeActive = virtualizeRows && expanded.size === 0
  const virtualizer = useVirtualRows({
    count: rows.length,
    scrollRef,
    // 作品行含 80px 封面 + 速览操作，实测行高约 132px
    estimateSize: 132,
    enabled: virtualizeActive,
  })
  const { virtualItems, totalSize } = virtualizer
  const paddingTop =
    virtualizeActive && virtualItems.length ? virtualItems[0].start : 0
  const paddingBottom =
    virtualizeActive && virtualItems.length
      ? totalSize - virtualItems[virtualItems.length - 1].end
      : 0
  const visibleRows = virtualizeActive
    ? virtualItems.map((item) => rows[item.index])
    : rows

  const exportSelection = async (kind: "comments" | "subtitles") => {
    if (!selectedIds.length) {
      showErrorToast("请先选择至少一个作品")
      return
    }
    try {
      await downloadExport(
        taskId,
        kind,
        kind === "comments"
          ? { aweme_ids: selectedIds }
          : { aweme_ids: selectedIds, format: subtitleFormat },
      )
      showSuccessToast(kind === "comments" ? "评论 TXT 已导出" : "字幕已导出")
    } catch (reason) {
      showErrorToast(reason instanceof Error ? reason.message : "导出失败")
    }
  }

  // 三个视图共用同一份空态，只有加载骨架各不相同
  const emptyWorksState = (
    <EmptyWorksState
      isError={worksQuery.isError}
      hasFilters={hasActiveFilters}
      onClearFilters={clearFilters}
      onRetry={() => worksQuery.refetch()}
      retrying={worksQuery.isFetching}
    />
  )

  return (
    <Card className="overflow-hidden">
      <CardHeader className="border-b bg-muted/20">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <p className="text-sm font-medium text-primary">统一内容工作区</p>
            <CardTitle className="mt-1">作品、下载与字幕</CardTitle>
            <p className="mt-2 text-sm text-muted-foreground">
              一条作品记录同时展示发布时间、互动、已保存评论、视频存储和字幕状态。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {(summary?.local_downloaded ?? 0) > 0 && (
              <MediaMigrationDialog
                taskId={taskId}
                eligibleCount={summary?.local_downloaded ?? 0}
              />
            )}
            {!active &&
              task.checkpoint_phase !== "crawl" &&
              task.aweme_count > 0 && <ProcessMediaDialog task={task} />}
            {hasDownloadableRows && (
              <Button variant="outline" asChild>
                <Link
                  to="/douyin/$taskId/feed"
                  params={{ taskId }}
                  search={{ start: undefined }}
                >
                  <PlaySquare />
                  沉浸播放
                </Link>
              </Button>
            )}
            {/* 报告 A14：刷新指示器替换原来的裸刷新按钮，顺带给出「几秒前更新」 */}
            <RefreshIndicator
              updatedAt={worksQuery.dataUpdatedAt}
              refreshing={worksQuery.isFetching}
              onRefresh={() => void invalidate()}
            />
          </div>
        </div>
        {summary && task.status === "processing_media" && (
          <output className="mt-4 flex items-start gap-3 rounded-xl border border-cyan-500/30 bg-cyan-500/5 p-4">
            <LoaderCircle
              aria-hidden="true"
              className="mt-0.5 size-5 shrink-0 animate-spin text-cyan-600"
            />
            <div className="space-y-1">
              <p className="text-sm font-medium">
                {task.resume_count > 0
                  ? `第 ${task.resume_count} 次恢复正在处理媒体`
                  : "正在处理视频与字幕"}
              </p>
              <p className="text-xs leading-5 text-muted-foreground">
                下载中 {summary.downloading} 条，排队 {summary.queued}{" "}
                条，临时字幕 {summary.temporary} 条，下载失败{" "}
                {summary.download_failed} 条
                {lastMediaActivity
                  ? `；最近进度更新：${formatDateTime(lastMediaActivity)}`
                  : ""}
                。页面每 2 秒自动刷新，无需重复提交。
              </p>
            </div>
          </output>
        )}
        {summary && (
          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
            <Summary label="作品" value={task.aweme_count} />
            <Summary
              label="下载完成 / 仅字幕"
              value={`${summary.downloaded} / ${summary.temporary}`}
            />
            <Summary
              label="下载中 / 排队"
              value={`${summary.downloading} / ${summary.queued}`}
            />
            <Summary label="视频失败" value={summary.download_failed} />
            <Summary
              label="字幕完成 / 失败"
              value={`${summary.subtitle_completed} / ${summary.subtitle_failed}`}
            />
            <Summary
              label="本地 / 云端"
              value={`${summary.local_downloaded} / ${summary.minio_downloaded}`}
            />
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-4 p-4 md:p-6">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
          <div className="relative min-w-64 flex-1">
            <Search
              aria-hidden="true"
              className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              value={search}
              aria-label="搜索标题、作者或作品号"
              onChange={(event) => {
                setSearch(event.target.value)
                setPage(0)
                setSelected(new Set())
              }}
              placeholder="搜索标题、作者或作品号"
              className="pl-9"
            />
          </div>
          <Select
            value={sort}
            onValueChange={(value) => {
              setSort(value as SortValue)
              setPage(0)
              setSelected(new Set())
            }}
          >
            <SelectTrigger className="w-full xl:w-48" aria-label="排序方式">
              <ListFilter />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="published_at:desc">最新发布</SelectItem>
              <SelectItem value="published_at:asc">最早发布</SelectItem>
              <SelectItem value="liked_count:desc">点赞最多</SelectItem>
              <SelectItem value="comment_count:desc">评论最多</SelectItem>
              <SelectItem value="collected_count:desc">收藏最多</SelectItem>
              <SelectItem value="persisted_comment_count:desc">
                已保存评论最多
              </SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={downloadStatus}
            onValueChange={(value) => {
              setDownloadStatus(value)
              setPage(0)
              setSelected(new Set())
            }}
          >
            <SelectTrigger
              className="w-full xl:w-40"
              aria-label="按视频下载状态筛选"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部视频状态</SelectItem>
              <SelectItem value="downloaded">视频已完成</SelectItem>
              <SelectItem value="downloading">视频下载中</SelectItem>
              <SelectItem value="failed">视频失败</SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={subtitleStatus}
            onValueChange={(value) => {
              setSubtitleStatus(value)
              setPage(0)
              setSelected(new Set())
            }}
          >
            <SelectTrigger
              className="w-full xl:w-40"
              aria-label="按字幕状态筛选"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部字幕状态</SelectItem>
              <SelectItem value="completed">字幕已完成</SelectItem>
              <SelectItem value="running">字幕处理中</SelectItem>
              <SelectItem value="failed">字幕失败</SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={tagId}
            onValueChange={(value) => {
              setTagId(value)
              setPage(0)
              setSelected(new Set())
            }}
          >
            <SelectTrigger className="w-full xl:w-44" aria-label="按标签筛选">
              <SelectValue placeholder="全部标签" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部标签</SelectItem>
              {(tagsQuery.data?.data ?? []).map((tag) => (
                <SelectItem key={tag.id} value={tag.id}>
                  #{tag.name}（{tag.aweme_count}）
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* 报告 A2：筛选 chips —— 把当前生效的筛选条件可视化，可逐个 × 掉 */}
        <FilterChips
          chips={[
            Boolean(search) && {
              key: "search",
              label: "搜索",
              value: search,
              onRemove: () => {
                setSearch("")
                resetPageAndSelection()
              },
            },
            downloadStatus !== "all" && {
              key: "downloadStatus",
              label: "视频状态",
              value: DOWNLOAD_STATUS_LABELS[downloadStatus] ?? downloadStatus,
              onRemove: () => {
                setDownloadStatus("all")
                resetPageAndSelection()
              },
            },
            subtitleStatus !== "all" && {
              key: "subtitleStatus",
              label: "字幕状态",
              value: SUBTITLE_STATUS_LABELS[subtitleStatus] ?? subtitleStatus,
              onRemove: () => {
                setSubtitleStatus("all")
                resetPageAndSelection()
              },
            },
            tagId !== "all" && {
              key: "tagId",
              label: "标签",
              value: selectedTagName,
              onRemove: () => {
                setTagId("all")
                resetPageAndSelection()
              },
            },
          ]}
          onClearAll={clearFilters}
        />

        {/* 报告 A10：筛选预设 —— 把常用筛选组合存到本地，下次一键套用 */}
        <FilterPresetBar
          storageKey="unified-works-panel-filter-presets"
          currentFilters={{ search, downloadStatus, subtitleStatus, tagId }}
          onApply={(next) => {
            setSearch(next.search)
            setDownloadStatus(next.downloadStatus)
            setSubtitleStatus(next.subtitleStatus)
            setTagId(next.tagId)
            resetPageAndSelection()
          }}
        />

        <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-muted/20 p-3">
          <div className="mr-1 flex items-center gap-2">
            <Checkbox
              id={`select-task-page-${taskId}`}
              aria-label={`全选本页（共 ${rows.length} 条）`}
              checked={
                allPageSelected
                  ? true
                  : somePageSelected
                    ? "indeterminate"
                    : false
              }
              disabled={!rows.length}
              onCheckedChange={(checked) =>
                togglePageSelection(checked === true)
              }
            />
            <label
              htmlFor={`select-task-page-${taskId}`}
              className="cursor-pointer whitespace-nowrap text-sm text-muted-foreground"
            >
              {selectedWorks.length
                ? `已选 ${selectedWorks.length} 项（本页）`
                : `全选本页（共 ${rows.length} 条）`}
            </label>
          </div>
          {/* 报告 A3：依赖选中项的批量按钮已移到底部 BulkActionBar，这里只留不依赖选中的操作 */}
          {failedAssets.length > 0 && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => retry.mutate(failedAssets)}
              disabled={retry.isPending}
            >
              <RotateCcw />
              重试本页失败项
            </Button>
          )}
          {/* 报告 A12：导出当前页 / 已选中的作品明细（全量导出需后端流式接口，本次不做） */}
          <Button
            size="sm"
            variant="outline"
            className="ml-auto"
            disabled={!rows.length}
            onClick={() => {
              const exportRows = selectedWorks.length ? selectedWorks : rows
              downloadCsv("作品列表", exportRows, [
                { header: "作品 ID", value: (row) => row.aweme.aweme_id },
                { header: "标题", value: (row) => row.aweme.title },
                { header: "作者", value: (row) => row.aweme.nickname },
                {
                  header: "发布时间",
                  value: (row) =>
                    formatDateTime(unixSecondsToDate(row.aweme.create_time)),
                },
                { header: "点赞", value: (row) => row.aweme.liked_count },
                { header: "评论", value: (row) => row.aweme.comment_count },
                { header: "收藏", value: (row) => row.aweme.collected_count },
                { header: "分享", value: (row) => row.aweme.share_count },
                {
                  header: "已保存评论",
                  value: (row) => row.persisted_comment_count,
                },
                {
                  header: "视频状态",
                  value: (row) =>
                    row.media
                      ? (PIPELINE_STATUS_LABELS[row.media.status] ??
                        row.media.status)
                      : "未创建下载任务",
                },
                {
                  header: "存储位置",
                  value: (row) =>
                    row.media
                      ? row.media.storage_backend === "minio"
                        ? "云端"
                        : "本地"
                      : "",
                },
                {
                  header: "字幕状态",
                  value: (row) =>
                    row.media?.subtitle
                      ? (PIPELINE_STATUS_LABELS[row.media.subtitle.status] ??
                        row.media.subtitle.status)
                      : "未生成字幕",
                },
                {
                  header: "抖音链接",
                  value: (row) => getDouyinVideoUrl(row.aweme.aweme_id),
                },
              ])
            }}
          >
            <FileSpreadsheet />
            导出{selectedWorks.length ? "选中" : "本页"}
          </Button>
        </div>

        <Tabs
          value={view}
          onValueChange={(value) => setView(value as WorkView)}
          className="gap-4"
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted-foreground">
              当前结果 {worksQuery.data?.count ?? 0} 条
            </p>
            <TabsList
              aria-label="选择作品展示方式"
              className="h-10 w-full p-1 sm:w-auto"
            >
              <TabsTrigger value="table" className="px-3 sm:px-4">
                <Table2 aria-hidden="true" />
                表格
              </TabsTrigger>
              <TabsTrigger value="rows" className="px-3 sm:px-4">
                <List aria-hidden="true" />
                横条
              </TabsTrigger>
              <TabsTrigger value="cards" className="px-3 sm:px-4">
                <LayoutGrid aria-hidden="true" />
                卡片
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="table" className="mt-0">
            {/* 报告 A1：列可见性入口，只作用于表格视图（横条 / 卡片不是表格） */}
            <div className="mb-3 flex justify-end">
              <TableColumnMenu {...menuProps} />
            </div>
            {/* 报告 O19：虚拟滚动需要滚动容器，超阈值时才限制高度；
                未启用时保持原来的 overflow-x-auto，短列表零行为变化 */}
            <div
              ref={scrollRef}
              className={cn(
                "rounded-xl border",
                virtualizeRows
                  ? "max-h-[70vh] overflow-auto"
                  : "overflow-x-auto",
              )}
            >
              {/* 报告 通病21：列多，给表格一个最小宽度兜底，窄屏靠横向滚动而不是挤列 */}
              <Table className="min-w-[900px]">
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-14">
                      <Checkbox
                        aria-label={`全选本页（共 ${rows.length} 条）`}
                        checked={
                          allPageSelected
                            ? true
                            : somePageSelected
                              ? "indeterminate"
                              : false
                        }
                        onCheckedChange={(checked) =>
                          togglePageSelection(checked === true)
                        }
                      />
                    </TableHead>
                    {isVisible("work") && <TableHead>作品</TableHead>}
                    {isVisible("published") && (
                      <TableHead className="hidden lg:table-cell">
                        发布时间
                      </TableHead>
                    )}
                    {isVisible("interactions") && (
                      <TableHead className="hidden xl:table-cell">
                        互动数据
                      </TableHead>
                    )}
                    {isVisible("comments") && <TableHead>已保存评论</TableHead>}
                    {isVisible("media") && <TableHead>视频 / 存储</TableHead>}
                    {/* 报告 A8：最后一列（操作列）横向滚动时冻结在右侧 */}
                    {isVisible("subtitle") && (
                      <TableHead className="sticky right-0 z-10 bg-background/95 backdrop-blur">
                        字幕
                      </TableHead>
                    )}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.length ? (
                    <>
                      {/* 报告 O19：上下占位行撑出滚动高度，中间只渲染可视区。
                          占位行没有单元格与内容，本身不产生可读文本；
                          biome 视 <tr> 为可交互元素，禁止在其上写 aria-hidden / role。 */}
                      {virtualizeActive && (
                        <tr style={{ height: paddingTop }} />
                      )}
                      {visibleRows.map((row) => {
                        const aweme = row.aweme
                        const asset = row.media
                        const isExpanded = expanded.has(aweme.aweme_id)
                        return (
                          <Fragment key={aweme.id}>
                            {/* 报告 A7：低频操作沉到右键菜单，操作区只留高频按钮 */}
                            <RowContextMenu
                              label={aweme.title || aweme.aweme_id}
                              items={[
                                {
                                  label: "复制作品 ID",
                                  icon: Copy,
                                  onSelect: () =>
                                    void copyAwemeId(aweme.aweme_id),
                                },
                                {
                                  label: "打开抖音页",
                                  icon: ExternalLink,
                                  onSelect: () =>
                                    window.open(
                                      getDouyinVideoUrl(aweme.aweme_id),
                                      "_blank",
                                      "noopener,noreferrer",
                                    ),
                                },
                                {
                                  separatorBefore: true,
                                  label: "下载视频",
                                  icon: Download,
                                  disabled: !asset?.download_available,
                                  onSelect: () => {
                                    if (asset) handleDownload(asset)
                                  },
                                },
                                {
                                  label: "重试失败处理",
                                  icon: RotateCcw,
                                  disabled:
                                    !asset ||
                                    (asset.status !== "failed" &&
                                      asset.subtitle?.status !== "failed"),
                                  onSelect: () => {
                                    if (asset) handleRetry(asset.id)
                                  },
                                },
                                {
                                  label: "重新翻译字幕",
                                  icon: Languages,
                                  disabled: !asset?.download_available,
                                  onSelect: () => {
                                    if (asset) handleRetranslate(asset.id)
                                  },
                                },
                              ]}
                            >
                              <TableRow
                                className={cn(
                                  "align-top",
                                  // 报告 A6：轮询后状态变化的行短暂高亮
                                  highlighted.has(aweme.aweme_id) &&
                                    "row-highlight",
                                )}
                              >
                                <TableCell>
                                  <div className="flex flex-col items-center gap-1">
                                    <Checkbox
                                      aria-label={`选择作品：${aweme.title || aweme.aweme_id}`}
                                      checked={selected.has(aweme.aweme_id)}
                                      onCheckedChange={(checked) =>
                                        toggleSelection(
                                          aweme.aweme_id,
                                          checked === true,
                                        )
                                      }
                                    />
                                    {/* 报告 A5：展开 / 收起该行的作品详情 */}
                                    <Button
                                      size="icon-sm"
                                      variant="ghost"
                                      aria-label={
                                        isExpanded
                                          ? "收起作品详情"
                                          : "展开作品详情"
                                      }
                                      aria-expanded={isExpanded}
                                      onClick={() =>
                                        toggleExpanded(aweme.aweme_id)
                                      }
                                    >
                                      <ChevronRight
                                        className={cn(
                                          "transition-transform",
                                          isExpanded && "rotate-90",
                                        )}
                                      />
                                    </Button>
                                  </div>
                                </TableCell>
                                {isVisible("work") && (
                                  <TableCell className="min-w-80 max-w-lg">
                                    <div className="flex gap-3">
                                      {aweme.cover_url ? (
                                        <img
                                          src={aweme.cover_url}
                                          alt=""
                                          loading="lazy"
                                          className="h-20 w-14 shrink-0 rounded-lg object-cover"
                                        />
                                      ) : (
                                        <div className="h-20 w-14 shrink-0 rounded-lg bg-muted" />
                                      )}
                                      <div className="min-w-0">
                                        <p className="line-clamp-2 font-medium">
                                          {aweme.title || aweme.aweme_id}
                                        </p>
                                        <p className="mt-1 text-sm text-muted-foreground">
                                          {aweme.nickname || "匿名作者"}
                                        </p>
                                        <SourceBadge
                                          sourceType={aweme.source_type}
                                          sourceLabel={aweme.source_label}
                                          className="mt-2"
                                        />
                                        <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                                          {aweme.aweme_id}
                                        </p>
                                        {(row.tags?.length ?? 0) > 0 && (
                                          <div className="mt-2 flex flex-wrap gap-1">
                                            {(row.tags ?? [])
                                              .slice(0, 4)
                                              .map((tag) => (
                                                <Badge
                                                  key={tag.id}
                                                  variant="outline"
                                                >
                                                  #{tag.name}
                                                </Badge>
                                              ))}
                                          </div>
                                        )}
                                        <WorkQuickActions
                                          taskId={taskId}
                                          aweme={aweme}
                                          asset={asset}
                                          active={active}
                                          onDownload={handleDownload}
                                          onRetry={handleRetry}
                                          onRetranslate={handleRetranslate}
                                        />
                                      </div>
                                    </div>
                                  </TableCell>
                                )}
                                {isVisible("published") && (
                                  <TableCell className="hidden min-w-36 whitespace-nowrap lg:table-cell">
                                    {/* 报告 A16：时间点改用相对时间，悬停看绝对时间 */}
                                    <p>
                                      <TimeAgo
                                        value={unixSecondsToDate(
                                          aweme.create_time,
                                        )}
                                      />
                                    </p>
                                    <p className="mt-1 text-xs text-muted-foreground">
                                      抓取 <TimeAgo value={aweme.fetched_at} />
                                    </p>
                                  </TableCell>
                                )}
                                {isVisible("interactions") && (
                                  <TableCell className="hidden min-w-40 text-sm xl:table-cell">
                                    <div className="grid grid-cols-2 gap-x-3 gap-y-1">
                                      <span>
                                        赞 {compact(aweme.liked_count)}
                                      </span>
                                      <span>
                                        评 {compact(aweme.comment_count)}
                                      </span>
                                      <span>
                                        藏 {compact(aweme.collected_count)}
                                      </span>
                                      <span>
                                        转 {compact(aweme.share_count)}
                                      </span>
                                    </div>
                                  </TableCell>
                                )}
                                {isVisible("comments") && (
                                  <TableCell>
                                    <CommentsDialog
                                      taskId={taskId}
                                      aweme={aweme}
                                      count={row.persisted_comment_count}
                                      active={active}
                                    />
                                  </TableCell>
                                )}
                                {isVisible("media") && (
                                  <TableCell className="min-w-48">
                                    {asset ? (
                                      <PipelineView
                                        label={
                                          asset.storage_backend === "minio"
                                            ? "云端"
                                            : "本地"
                                        }
                                        status={asset.status}
                                        progress={asset.progress}
                                        error={asset.error}
                                        detail={`已尝试 ${asset.attempt_count} 次 · 更新于 ${formatDateTime(asset.updated_at)}`}
                                      />
                                    ) : (
                                      <span className="text-xs text-muted-foreground">
                                        未创建下载任务
                                      </span>
                                    )}
                                  </TableCell>
                                )}
                                {/* 报告 A8：最后一列（操作列）横向滚动时冻结在右侧 */}
                                {isVisible("subtitle") && (
                                  <TableCell className="sticky right-0 min-w-48 bg-background/95 backdrop-blur">
                                    {asset?.subtitle ? (
                                      <PipelineView
                                        label={
                                          asset.subtitle.language || "远程字幕"
                                        }
                                        status={asset.subtitle.status}
                                        progress={asset.subtitle.progress}
                                        error={asset.subtitle.error}
                                      />
                                    ) : (
                                      <span className="text-xs text-muted-foreground">
                                        未生成字幕
                                      </span>
                                    )}
                                  </TableCell>
                                )}
                              </TableRow>
                            </RowContextMenu>
                            {/* 报告 A5：展开行显示作品详情（媒体 / 字幕 / 评论汇总） */}
                            {isExpanded && (
                              <TableRow className="bg-muted/20 hover:bg-muted/20">
                                <TableCell
                                  colSpan={visibleCount}
                                  className="whitespace-normal"
                                >
                                  <WorkDetailDetails row={row} />
                                </TableCell>
                              </TableRow>
                            )}
                          </Fragment>
                        )
                      })}
                      {virtualizeActive && (
                        <tr style={{ height: paddingBottom }} />
                      )}
                    </>
                  ) : worksQuery.isLoading ? (
                    // 报告 A4：加载态改用骨架屏并保留列结构，避免内容跳动
                    <WorkTableSkeleton isVisible={isVisible} />
                  ) : (
                    <TableRow>
                      <TableCell colSpan={visibleCount}>
                        {emptyWorksState}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          </TabsContent>

          <TabsContent value="rows" className="mt-0">
            <ul aria-label="作品横条列表" className="space-y-3">
              {rows.length ? (
                rows.map((row) => (
                  <WorkRowItem
                    key={row.aweme.id}
                    taskId={taskId}
                    row={row}
                    active={active}
                    checked={selected.has(row.aweme.aweme_id)}
                    onToggleSelection={toggleSelection}
                    onDownload={handleDownload}
                    onRetry={handleRetry}
                    onRetranslate={handleRetranslate}
                  />
                ))
              ) : worksQuery.isLoading ? (
                <WorkListSkeleton variant="rows" />
              ) : (
                emptyWorksState
              )}
            </ul>
          </TabsContent>

          <TabsContent value="cards" className="mt-0">
            <ul
              aria-label="作品卡片列表"
              className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"
            >
              {rows.length ? (
                rows.map((row) => (
                  <WorkCardItem
                    key={row.aweme.id}
                    taskId={taskId}
                    row={row}
                    active={active}
                    checked={selected.has(row.aweme.aweme_id)}
                    onToggleSelection={toggleSelection}
                    onDownload={handleDownload}
                    onRetry={handleRetry}
                    onRetranslate={handleRetranslate}
                  />
                ))
              ) : worksQuery.isLoading ? (
                <WorkListSkeleton variant="cards" />
              ) : (
                emptyWorksState
              )}
            </ul>
          </TabsContent>
        </Tabs>
        <Pager
          page={page}
          pageSize={pageSize}
          total={worksQuery.data?.count ?? 0}
          totalLabel={(total) => `共 ${total} 项`}
          onPageChange={(nextPage) => {
            setPage(nextPage)
            setSelected(new Set())
          }}
        />
      </CardContent>
      {/* 报告 A3：批量操作栏 —— 勾选后从底部浮出，操作随选中项出现 */}
      <BulkActionBar
        count={selected.size}
        onClear={() => setSelected(new Set())}
        actions={
          <>
            <BatchCommentDialog
              selectedWorks={selectedWorks}
              onCreated={() => setSelected(new Set())}
            >
              <Button size="sm" disabled={!selectedWorks.length}>
                <MessageCircle />
                批量发送评论
              </Button>
            </BatchCommentDialog>
            <Button
              size="sm"
              variant="outline"
              onClick={() => exportSelection("comments")}
            >
              <FileDown />
              导出评论 TXT
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={async () => {
                // 报告 O15：把 window.confirm 换成站内统一确认框；20 条以内直接提交，不打断用户
                if (selectedIds.length > 20) {
                  const ok = await confirmDialog({
                    title: `将为 ${selectedIds.length} 个视频分别创建评论补采任务，确认继续？`,
                    confirmText: "创建任务",
                  })
                  if (!ok) return
                }
                recrawlComments.mutate(selectedIds)
              }}
              disabled={recrawlComments.isPending}
            >
              <MessageCircle />
              {recrawlComments.isPending
                ? recrawlProgress.total > 0
                  ? `已创建 ${recrawlProgress.created} / ${recrawlProgress.total}`
                  : "正在创建…"
                : "批量补采评论"}
            </Button>
            <Select
              value={subtitleFormat}
              onValueChange={(value) =>
                setSubtitleFormat(value as "srt" | "vtt" | "txt")
              }
            >
              <SelectTrigger className="h-8 w-24" aria-label="字幕导出格式">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="srt">SRT</SelectItem>
                <SelectItem value="vtt">VTT</SelectItem>
                <SelectItem value="txt">TXT</SelectItem>
              </SelectContent>
            </Select>
            <Button
              size="sm"
              variant="outline"
              onClick={() => exportSelection("subtitles")}
            >
              <Captions />
              导出字幕
            </Button>
            {hasMigratableSelection && (
              <MediaMigrationDialog
                taskId={taskId}
                eligibleCount={selectedAssets.length}
                assetIds={selectedAssetIds}
                compact
              />
            )}
          </>
        }
      />
    </Card>
  )
}

type WorkItemProps = {
  taskId: string
  row: DouyinWorkPublic
  active: boolean
  checked: boolean
  /** 回传作品 ID 而不是在父级为每行生成闭包，行组件的 props 才能保持稳定 */
  onToggleSelection: (awemeId: string, checked: boolean) => void
  onDownload: (asset: DouyinMediaAssetPublic) => void
  onRetry: (assetId: string) => void
  onRetranslate: (assetId: string) => void
}

// 每行都会挂一批子组件（对话框 / 下拉菜单），用 memo 隔断父级勾选、翻页引起的整表重渲染
const WorkRowItem = memo(function WorkRowItem({
  taskId,
  row,
  active,
  checked,
  onToggleSelection,
  onDownload,
  onRetry,
  onRetranslate,
}: WorkItemProps) {
  const { aweme, media: asset } = row
  const title = aweme.title || aweme.aweme_id

  return (
    <li className="grid gap-5 rounded-2xl border bg-card p-4 shadow-xs transition-colors hover:border-primary/30 lg:grid-cols-[minmax(0,1.35fr)_minmax(26rem,1fr)]">
      <div className="flex min-w-0 gap-3">
        <Checkbox
          checked={checked}
          aria-label={`选择作品：${title}`}
          onCheckedChange={(value) =>
            onToggleSelection(aweme.aweme_id, value === true)
          }
        />
        <WorkCover aweme={aweme} className="h-28 w-20" />
        <div className="min-w-0 flex-1">
          <h3 className="line-clamp-2 font-semibold leading-6">{title}</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {aweme.nickname || "匿名作者"}
          </p>
          <SourceBadge
            sourceType={aweme.source_type}
            sourceLabel={aweme.source_label}
            className="mt-2"
          />
          <p className="mt-1 font-mono text-[11px] text-muted-foreground">
            {aweme.aweme_id}
          </p>
          <WorkTags tags={row.tags} />
          <WorkQuickActions
            taskId={taskId}
            aweme={aweme}
            asset={asset}
            active={active}
            onDownload={onDownload}
            onRetry={onRetry}
            onRetranslate={onRetranslate}
          />
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl bg-muted/25 p-3 text-sm">
          <p className="font-medium">互动与评论</p>
          <div className="mt-2 grid grid-cols-4 gap-2 text-xs text-muted-foreground">
            <span>赞 {compact(aweme.liked_count)}</span>
            <span>评 {compact(aweme.comment_count)}</span>
            <span>藏 {compact(aweme.collected_count)}</span>
            <span>转 {compact(aweme.share_count)}</span>
          </div>
          <div className="mt-3 flex items-center justify-between gap-3">
            <span className="text-xs text-muted-foreground">
              {/* 报告 A16：发布时间改用相对时间 */}
              发布 <TimeAgo value={unixSecondsToDate(aweme.create_time)} />
            </span>
            <CommentsDialog
              taskId={taskId}
              aweme={aweme}
              count={row.persisted_comment_count}
              active={active}
            />
          </div>
        </div>
        <WorkPipelineStatus asset={asset} />
      </div>
    </li>
  )
})

const WorkCardItem = memo(function WorkCardItem({
  taskId,
  row,
  active,
  checked,
  onToggleSelection,
  onDownload,
  onRetry,
  onRetranslate,
}: WorkItemProps) {
  const { aweme, media: asset } = row
  const title = aweme.title || aweme.aweme_id

  return (
    <li className="flex min-w-0 flex-col overflow-hidden rounded-xl border bg-card shadow-xs transition hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md">
      <div className="relative aspect-video overflow-hidden bg-muted">
        {aweme.cover_url ? (
          <img
            src={aweme.cover_url}
            alt=""
            loading="lazy"
            className="size-full object-cover"
          />
        ) : (
          <div className="size-full bg-muted" />
        )}
        <div className="absolute left-2 top-2 rounded-lg bg-background/90 p-1.5 shadow-sm backdrop-blur">
          <Checkbox
            checked={checked}
            aria-label={`选择作品：${title}`}
            onCheckedChange={(value) =>
              onToggleSelection(aweme.aweme_id, value === true)
            }
          />
        </div>
        <div className="absolute bottom-2 right-2 rounded-full bg-background/90 px-2 py-0.5 text-[11px] font-medium shadow-sm backdrop-blur">
          {/* 报告 A16：发布时间改用相对时间 */}
          <TimeAgo value={unixSecondsToDate(aweme.create_time)} />
        </div>
      </div>

      <div className="flex flex-1 flex-col p-3">
        <h3 className="line-clamp-2 min-h-10 text-sm font-semibold leading-5">
          {title}
        </h3>
        <p className="mt-0.5 truncate text-xs text-muted-foreground">
          {aweme.nickname || "匿名作者"}
        </p>
        <SourceBadge
          sourceType={aweme.source_type}
          sourceLabel={aweme.source_label}
          className="mt-2"
        />
        <WorkTags tags={row.tags} />
        <div className="mt-3 grid grid-cols-4 gap-1 rounded-lg bg-muted/25 p-2 text-center text-[11px]">
          <span>赞 {compact(aweme.liked_count)}</span>
          <span>评 {compact(aweme.comment_count)}</span>
          <span>藏 {compact(aweme.collected_count)}</span>
          <span>转 {compact(aweme.share_count)}</span>
        </div>
        <details className="group mt-2">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-md border-t pt-2 text-[11px] font-medium text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none [&::-webkit-details-marker]:hidden">
            <span>视频与字幕状态</span>
            <ChevronDown
              aria-hidden="true"
              className="size-3.5 transition group-open:rotate-180"
            />
          </summary>
          <div className="pt-2">
            <WorkPipelineStatus asset={asset} />
          </div>
        </details>
        <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t pt-3">
          <CommentsDialog
            taskId={taskId}
            aweme={aweme}
            count={row.persisted_comment_count}
            active={active}
          />
          <WorkQuickActions
            taskId={taskId}
            aweme={aweme}
            asset={asset}
            active={active}
            onDownload={onDownload}
            onRetry={onRetry}
            onRetranslate={onRetranslate}
          />
        </div>
      </div>
    </li>
  )
})

function WorkCover({
  aweme,
  className,
}: {
  aweme: DouyinAwemePublic
  className: string
}) {
  return aweme.cover_url ? (
    <img
      src={aweme.cover_url}
      alt=""
      loading="lazy"
      className={`${className} shrink-0 rounded-xl object-cover`}
    />
  ) : (
    <div className={`${className} shrink-0 rounded-xl bg-muted`} />
  )
}

function WorkTags({ tags }: { tags?: DouyinTagRefPublic[] }) {
  if (!tags?.length) return null
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {tags.slice(0, 4).map((tag) => (
        <Badge key={tag.id} variant="outline">
          #{tag.name}
        </Badge>
      ))}
    </div>
  )
}

function WorkQuickActions({
  taskId,
  aweme,
  asset,
  active,
  onDownload,
  onRetry,
  onRetranslate,
}: {
  taskId: string
  aweme: DouyinAwemePublic
  asset: DouyinMediaAssetPublic | null
  active: boolean
  onDownload: (asset: DouyinMediaAssetPublic) => void
  onRetry: (assetId: string) => void
  onRetranslate: (assetId: string) => void
}) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1">
      {(asset?.download_available || aweme.video_download_url) && (
        <VideoPreviewDialog taskId={taskId} asset={asset} aweme={aweme} />
      )}
      {/* 报告 O10：把高频的「下载视频」提到行内与「视频预览」并列，其余低频操作收进右侧「更多」菜单 */}
      {asset?.download_available && (
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label="下载视频"
          title="下载视频"
          onClick={() => onDownload(asset)}
        >
          <Download />
        </Button>
      )}
      <AwemeActions taskId={taskId} aweme={aweme} active={active}>
        {asset?.download_available && (
          <DropdownMenuItem asChild>
            <Link
              to="/douyin/$taskId/feed"
              params={{ taskId }}
              search={{ start: `video-${aweme.aweme_id}` }}
            >
              <PlaySquare />
              沉浸播放
            </Link>
          </DropdownMenuItem>
        )}
        {asset &&
          (asset.status === "failed" ||
            asset.subtitle?.status === "failed") && (
            <DropdownMenuItem onSelect={() => onRetry(asset.id)}>
              <RotateCcw />
              重试失败处理
            </DropdownMenuItem>
          )}
        {asset?.download_available && (
          <DropdownMenuItem onSelect={() => onRetranslate(asset.id)}>
            <Languages />
            重新翻译
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <a
            href={getDouyinVideoUrl(aweme.aweme_id)}
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLink />
            在抖音中打开视频
          </a>
        </DropdownMenuItem>
      </AwemeActions>
    </div>
  )
}

function WorkPipelineStatus({
  asset,
}: {
  asset: DouyinMediaAssetPublic | null
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div>
        {asset ? (
          <PipelineView
            label={asset.storage_backend === "minio" ? "云端" : "本地"}
            status={asset.status}
            progress={asset.progress}
            error={asset.error}
            detail={`已尝试 ${asset.attempt_count} 次 · 更新于 ${formatDateTime(asset.updated_at)}`}
          />
        ) : (
          <span className="text-xs text-muted-foreground">未创建下载任务</span>
        )}
      </div>
      <div>
        {asset?.subtitle ? (
          <PipelineView
            label={asset.subtitle.language || "远程字幕"}
            status={asset.subtitle.status}
            progress={asset.subtitle.progress}
            error={asset.subtitle.error}
          />
        ) : (
          <span className="text-xs text-muted-foreground">未生成字幕</span>
        )}
      </div>
    </div>
  )
}

/**
 * 报告 A5：表格行展开后的作品详情。
 * 只做只读汇总（媒体 / 字幕 / 评论），把整行放不下的字段铺开，不重复行内已有的操作按钮。
 */
function WorkDetailDetails({ row }: { row: DouyinWorkPublic }) {
  const { aweme, media: asset } = row
  return (
    <div className="space-y-2">
      <div className="grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <DetailItem label="作品 ID" value={aweme.aweme_id} mono />
        <DetailItem label="作者" value={aweme.nickname || "匿名作者"} />
        <DetailItem
          label="已保存评论"
          value={`${row.persisted_comment_count} 条`}
        />
        <DetailItem
          label="互动数据"
          value={`赞 ${compact(aweme.liked_count)} · 评 ${compact(aweme.comment_count)} · 藏 ${compact(aweme.collected_count)} · 转 ${compact(aweme.share_count)}`}
        />
        <DetailItem
          label="视频状态"
          value={
            asset
              ? `${PIPELINE_STATUS_LABELS[asset.status] ?? asset.status} · ${asset.storage_backend === "minio" ? "云端" : "本地"}`
              : "未创建下载任务"
          }
        />
        <DetailItem
          label="视频进度"
          value={
            asset
              ? `${asset.progress}% · 已尝试 ${asset.attempt_count} 次`
              : "—"
          }
        />
        <DetailItem
          label="字幕状态"
          value={
            asset?.subtitle
              ? `${asset.subtitle.language || "远程字幕"} · ${PIPELINE_STATUS_LABELS[asset.subtitle.status] ?? asset.subtitle.status} · ${asset.subtitle.progress}%`
              : "未生成字幕"
          }
        />
        <DetailItem
          label="最近更新"
          value={asset ? formatDateTime(asset.updated_at) : "—"}
        />
      </div>
      {asset?.error && (
        <p className="text-xs text-destructive">视频错误：{asset.error}</p>
      )}
      {asset?.subtitle?.error && (
        <p className="text-xs text-destructive">
          字幕错误：{asset.subtitle.error}
        </p>
      )}
    </div>
  )
}

function DetailItem({
  label,
  value,
  mono,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="rounded-lg border bg-background/60 p-2">
      <p className="text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-0.5 break-all font-medium",
          mono && "font-mono text-[11px]",
        )}
      >
        {value}
      </p>
    </div>
  )
}

/**
 * 报告 A4：表格加载骨架。保留 7 列的列结构（含断点隐藏与报告 A1 的列可见性），
 * 骨架块与真实行同高，数据到达时不会出现内容跳动。
 */
function WorkTableSkeleton({
  isVisible,
}: {
  isVisible: (key: string) => boolean
}) {
  // 与表头一一对应：复选框 / 作品 / 发布时间 / 互动数据 / 已保存评论 / 视频 / 字幕。
  // 报告 A1：列可见性必须同步到骨架，否则隐藏列后骨架会比表头多出一格。
  const cells = [
    { key: "select", className: "w-14" },
    { key: "work", className: "" },
    { key: "published", className: "hidden lg:table-cell" },
    { key: "interactions", className: "hidden xl:table-cell" },
    { key: "comments", className: "" },
    { key: "media", className: "" },
    { key: "subtitle", className: "" },
  ] as const
  return (
    <>
      {Array.from({ length: 5 }, (_, rowIndex) => (
        <TableRow
          key={`work-skeleton-${rowIndex}`}
          className="hover:bg-transparent"
        >
          {cells.map((cell, cellIndex) =>
            isVisible(cell.key) ? (
              <TableCell
                key={`work-skeleton-${rowIndex}-${cellIndex}`}
                className={cell.className}
              >
                <Skeleton
                  className={cellIndex === 0 ? "size-4" : "h-4 w-full"}
                />
              </TableCell>
            ) : null,
          )}
        </TableRow>
      ))}
    </>
  )
}

/** 报告 A4：横条 / 卡片视图的加载骨架，保持与真实条目一致的外框尺寸 */
function WorkListSkeleton({ variant }: { variant: "rows" | "cards" }) {
  const count = variant === "cards" ? 4 : 3
  return (
    <>
      {Array.from({ length: count }, (_, index) => (
        <li key={`work-list-skeleton-${index}`}>
          <Skeleton
            className={cn(
              "w-full",
              variant === "cards" ? "h-64 rounded-xl" : "h-32 rounded-2xl",
            )}
          />
        </li>
      ))}
    </>
  )
}

/**
 * 报告 A4 / O8：作品空态。
 * 以前只有「没有符合筛选条件的作品」一句话，用户既不知道是不是真的没数据，
 * 也不知道下一步做什么。这里区分「被筛选筛空」与「任务还没采到数据」，
 * 前者给「清除筛选」，后者给「刷新」。
 */
function EmptyWorksState({
  isError,
  hasFilters,
  onClearFilters,
  onRetry,
  retrying,
}: {
  isError: boolean
  /** 当前是否有生效的筛选条件（决定空态文案与行动按钮） */
  hasFilters: boolean
  onClearFilters: () => void
  onRetry: () => void
  retrying: boolean
}) {
  // 请求失败以前会被渲染成「没有符合筛选条件的作品」，用户既看不到原因也无法重试
  if (isError) {
    return (
      <QueryErrorState
        title="作品列表加载失败"
        description="无法获取该任务的作品数据，请检查网络连接后重试。"
        onRetry={onRetry}
        retrying={retrying}
        className="col-span-full rounded-xl"
      />
    )
  }
  return (
    <EmptyState
      className="col-span-full"
      icon={hasFilters ? SearchX : Inbox}
      title={hasFilters ? "没有符合筛选条件的作品" : "还没有作品数据"}
      description={
        hasFilters
          ? "当前筛选条件可能过窄，清除筛选即可看回全部作品。"
          : "任务开始采集后作品会陆续出现在这里；也可以点刷新看最新进度。"
      }
      action={
        hasFilters ? (
          <Button size="sm" variant="outline" onClick={onClearFilters}>
            清除筛选
          </Button>
        ) : (
          <Button
            size="sm"
            variant="outline"
            onClick={onRetry}
            disabled={retrying}
          >
            <RotateCcw />
            刷新
          </Button>
        )
      }
    />
  )
}

function CommentsDialog({
  taskId,
  aweme,
  count,
  active,
}: {
  taskId: string
  aweme: DouyinAwemePublic
  count: number
  active: boolean
}) {
  const [open, setOpen] = useState(false)
  const [commentPage, setCommentPage] = useState(0)
  const [sort, setSort] = useState<"published_at" | "like_count">(
    "published_at",
  )
  const query = useQuery({
    queryKey: ["douyin-comments", taskId, aweme.aweme_id, sort, commentPage],
    queryFn: () =>
      DouyinService.listComments({
        taskId,
        awemeId: aweme.aweme_id,
        sortBy: sort,
        sortOrder: "desc",
        skip: commentPage * 100,
        limit: 100,
      }),
    enabled: open,
    refetchInterval: open && active ? 3_000 : false,
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <MessageCircle />
          {count} 条
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-hidden sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{aweme.title || aweme.aweme_id}</DialogTitle>
          <DialogDescription>已保存评论及评论发布时间</DialogDescription>
        </DialogHeader>
        <div className="flex justify-end">
          <Select
            value={sort}
            onValueChange={(value) => {
              setSort(value as "published_at" | "like_count")
              setCommentPage(0)
            }}
          >
            <SelectTrigger className="w-36" aria-label="评论排序方式">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="published_at">按时间</SelectItem>
              <SelectItem value="like_count">按点赞</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="max-h-[60vh] space-y-3 overflow-y-auto pr-2">
          {query.data?.data.length ? (
            query.data.data.map((comment) => (
              <div
                key={comment.id}
                className="rounded-xl border bg-muted/20 p-4"
              >
                <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
                  <span>{comment.nickname || "匿名"}</span>
                  <div className="flex items-center gap-2">
                    <span>
                      {formatUnix(comment.create_time)} · 赞{" "}
                      {comment.like_count}
                    </span>
                    <InteractionComposerDialog
                      taskId={taskId}
                      aweme={aweme}
                      interactionType="comment_reply"
                      targetComment={comment}
                      compact
                    />
                  </div>
                </div>
                <p className="mt-2 whitespace-pre-wrap text-sm leading-6">
                  {comment.content || "-"}
                </p>
              </div>
            ))
          ) : (
            <p className="py-12 text-center text-sm text-muted-foreground">
              {query.isLoading ? "加载评论…" : "暂无已保存评论"}
            </p>
          )}
        </div>
        {(query.data?.count ?? 0) > 100 && (
          <div className="flex items-center justify-end gap-2 border-t pt-3">
            <span className="mr-auto text-xs text-muted-foreground">
              第 {commentPage + 1} 页 · 共 {query.data?.count ?? 0} 条
            </span>
            <Button
              size="sm"
              variant="outline"
              disabled={commentPage === 0}
              onClick={() => setCommentPage((value) => value - 1)}
            >
              上一页
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={(commentPage + 1) * 100 >= (query.data?.count ?? 0)}
              onClick={() => setCommentPage((value) => value + 1)}
            >
              下一页
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function PipelineView({
  label,
  status,
  progress,
  error,
  detail,
}: {
  label: string
  status: string
  progress: number
  error: string | null
  detail?: string
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <Badge variant={status === "failed" ? "destructive" : "outline"}>
          {label} · {PIPELINE_STATUS_LABELS[status] ?? status}
        </Badge>
        <span className="text-xs text-muted-foreground">{progress}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className={
            status === "failed" ? "h-full bg-destructive" : "h-full bg-primary"
          }
          style={{ width: `${Math.max(0, Math.min(progress, 100))}%` }}
        />
      </div>
      {detail && <p className="text-xs text-muted-foreground">{detail}</p>}
      {error && (
        <p className="line-clamp-2 text-xs text-destructive">{error}</p>
      )}
    </div>
  )
}

function Summary({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-xl border bg-card p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
    </div>
  )
}

export async function downloadExport(
  taskId: string,
  kind: "comments" | "subtitles",
  body: object,
) {
  const token = getAccessToken()
  const response = await fetch(
    `${browserApiBase()}/api/v1/douyin/tasks/${taskId}/exports/${kind}`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    },
  )
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string
    } | null
    throw new Error(payload?.detail || `导出失败 (${response.status})`)
  }
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement("a")
  anchor.href = url
  const disposition = response.headers.get("Content-Disposition") || ""
  const match =
    disposition.match(/filename\*=UTF-8''([^;]+)/i) ||
    disposition.match(/filename="?([^";]+)"?/i)
  anchor.download = match ? decodeURIComponent(match[1]) : `douyin-${kind}`
  anchor.click()
  URL.revokeObjectURL(url)
}

export async function downloadMedia(
  taskId: string,
  asset: DouyinMediaAssetPublic,
  onError: (message: string) => void,
) {
  try {
    const token = getAccessToken()
    const response = await fetch(
      `${browserApiBase()}/api/v1/douyin/tasks/${taskId}/media/${asset.id}/file`,
      { headers: token ? { Authorization: `Bearer ${token}` } : undefined },
    )
    if (!response.ok) throw new Error(`视频下载失败 (${response.status})`)
    const url = URL.createObjectURL(await response.blob())
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = `douyin-${asset.aweme_id}.mp4`
    anchor.click()
    URL.revokeObjectURL(url)
  } catch (reason) {
    onError(reason instanceof Error ? reason.message : "视频下载失败")
  }
}

function browserApiBase() {
  if (import.meta.env.DEV) return window.location.origin
  return new URL(OpenAPI.BASE || window.location.origin, window.location.origin)
    .toString()
    .replace(/\/$/, "")
}
/** 报告 A16：后端 create_time 是秒级 Unix 时间戳，TimeAgo 内部按毫秒解析，这里统一换算 */
function unixSecondsToDate(value: number | null | undefined): Date | null {
  return value ? new Date(value * 1000) : null
}
function compact(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value)
}
