import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  ChevronRight,
  Copy,
  Download,
  ExternalLink,
  Inbox,
  Languages,
  ListFilter,
  MessageCircle,
  PlaySquare,
  RotateCcw,
  Search,
  SearchX,
} from "lucide-react"
import { Fragment, useCallback, useMemo, useRef, useState } from "react"

import {
  type CrawlTaskPublic,
  type DouyinAwemePublic,
  type DouyinMediaAssetPublic,
  DouyinService,
  DouyinTagsService,
  type DouyinWorkPublic,
  OpenAPI,
} from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import { Pager } from "@/components/Common/Pager"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { RowContextMenu } from "@/components/Common/RowContextMenu"
import { TableColumnMenu } from "@/components/Common/TableColumnMenu"
import { TimeAgo } from "@/components/Common/TimeAgo"
import { AwemeActions } from "@/components/Douyin/AwemeActions"
import { CoverPlayTrigger } from "@/components/Douyin/CoverPlayTrigger"
import { InteractionComposerDialog } from "@/components/Douyin/InteractionComposerDialog"
import { SourceBadge } from "@/components/Douyin/SourceSelect"
import { SubtitleDialog } from "@/components/Douyin/SubtitlePanel"
import { VideoPreviewDialog } from "@/components/Douyin/VideoPreviewDialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
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
import useCustomToast from "@/hooks/useCustomToast"
import { useHighlightedRows } from "@/hooks/useHighlightedRows"
import { useSmartPolling } from "@/hooks/useSmartPolling"
import { type TableColumnDef, useTableColumns } from "@/hooks/useTableColumns"
import { useVirtualRows, VIRTUALIZE_THRESHOLD } from "@/hooks/useVirtualRows"
import { getAccessToken } from "@/lib/auth-token"
import { formatDateTime, formatUnix } from "@/lib/time"
import { cn } from "@/lib/utils"
import { getDouyinVideoUrl, handleError } from "@/utils"

const pageSize = 20
type SortValue =
  | "published_at:desc"
  | "published_at:asc"
  | "liked_count:desc"
  | "comment_count:desc"
  | "collected_count:desc"
  | "persisted_comment_count:desc"
/** 媒体 / 字幕流水线状态的中文名：PipelineView 与行展开详情（报告 A5）共用 */
const PIPELINE_STATUS_LABELS: Record<string, string> = {
  queued: "等待",
  downloading: "下载中",
  downloaded: "已完成",
  temporary: "仅字幕",
  pending: "等待",
  running: "处理中",
  completed: "已完成",
  failed: "失败",
}

// 报告 A1：列可见性 —— 作品表格（6 列）的列清单，与表头一一对应。
// 必须是模块级常量：放进组件内每次 render 都会新建，hook 里的隐藏状态会被反复重置。
const WORKS_TABLE_COLUMNS = [
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
  // 报告 A5：表格中已展开详情的作品 ID
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
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
  const worksQuery = useSmartPolling(
    [
      "douyin-works",
      taskId,
      page,
      search,
      sort,
      downloadStatus,
      subtitleStatus,
      tagId,
    ],
    () =>
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
    {
      // 任务在跑、或本页还有排队/下载中/转写中的作品时才轮询；
      // 全都落地后停掉，避免空闲时每 5 秒重渲染整张作品表。
      isActive: (data) =>
        active ||
        data.data.some(
          (row) =>
            row.media?.status === "queued" ||
            row.media?.status === "downloading" ||
            row.media?.subtitle?.status === "pending" ||
            row.media?.subtitle?.status === "running",
        ),
      activeInterval: 2_000,
      placeholderData: (previous) => previous,
    },
  )
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
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["douyin-works", taskId] }),
      queryClient.invalidateQueries({ queryKey: ["douyin-media", taskId] }),
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
  // 实际列数 = 可见列 + 行首展开列 + 行尾操作列（后两者不参与列可见性配置）
  const rowColumnCount = visibleCount + 2
  // 高频回调固定引用：showErrorToast / mutate 每次渲染都会新建，用 ref 与解构稳定依赖
  const errorToastRef = useRef(showErrorToast)
  errorToastRef.current = showErrorToast
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
    setPage(0)
  }, [])

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
    // 紧凑行：48px 小封面 + 单行标题与元信息，实测行高约 66px
    estimateSize: 66,
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

  // 加载中 / 空数据 / 筛选无结果共用同一份空态
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

        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            当前结果 {worksQuery.data?.count ?? 0} 条
          </p>
          {/* 报告 A1：列可见性入口 */}
          <TableColumnMenu {...menuProps} />
        </div>

        {/* 报告 O19：虚拟滚动需要滚动容器，超阈值时才限制高度；
            未启用时保持原来的 overflow-x-auto，短列表零行为变化 */}
        <div
          ref={scrollRef}
          className={cn(
            "rounded-xl border",
            virtualizeRows ? "max-h-[70vh] overflow-auto" : "overflow-x-auto",
          )}
        >
          {/* 报告 通病21：列多，给表格一个最小宽度兜底，窄屏靠横向滚动而不是挤列 */}
          <Table className="min-w-[900px]">
            <TableHeader>
              <TableRow>
                {/* 行首是「展开作品详情」控制列，表头留空占位 */}
                <TableHead className="w-14" />
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
                {isVisible("subtitle") && <TableHead>字幕</TableHead>}
                {/* 报告 A8：播放 / 更多操作统一收在行尾，横向滚动时冻结在最右侧 */}
                <TableHead className="sticky right-0 z-10 bg-background/95 text-right backdrop-blur">
                  操作
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length ? (
                <>
                  {/* 报告 O19：上下占位行撑出滚动高度，中间只渲染可视区。
                          占位行没有单元格与内容，本身不产生可读文本；
                          biome 视 <tr> 为可交互元素，禁止在其上写 aria-hidden / role。 */}
                  {virtualizeActive && <tr style={{ height: paddingTop }} />}
                  {visibleRows.map((row) => {
                    const aweme = row.aweme
                    const asset = row.media
                    const tags = row.tags ?? []
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
                              onSelect: () => void copyAwemeId(aweme.aweme_id),
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
                              // 报告 A6：轮询后状态变化的行短暂高亮
                              highlighted.has(aweme.aweme_id) &&
                                "row-highlight",
                            )}
                          >
                            <TableCell className="w-14">
                              <div className="flex flex-col items-center gap-1">
                                {/* 报告 A5：展开 / 收起该行的作品详情 */}
                                <Button
                                  size="icon-sm"
                                  variant="ghost"
                                  aria-label={
                                    isExpanded ? "收起作品详情" : "展开作品详情"
                                  }
                                  aria-expanded={isExpanded}
                                  onClick={() => toggleExpanded(aweme.aweme_id)}
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
                                <div className="flex items-start gap-2.5">
                                  {/* 封面同样作为播放入口：可播放时点击即开预览弹窗 */}
                                  <CoverPlayTrigger
                                    taskId={aweme.task_id}
                                    aweme={aweme}
                                    asset={asset}
                                    imageClassName="h-12 w-9 shrink-0 rounded-md object-cover"
                                    buttonClassName="shrink-0"
                                    fallback={
                                      <div className="h-12 w-9 shrink-0 rounded-md bg-muted" />
                                    }
                                  />
                                  <div className="min-w-0 flex-1">
                                    <p className="line-clamp-1 text-sm font-medium">
                                      {aweme.title || aweme.aweme_id}
                                    </p>
                                    {/* 作者 / 作品号 / 来源 / 标签压成一行，避免多行文本把行高撑起来 */}
                                    <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                                      <span className="max-w-32 truncate">
                                        {aweme.nickname || "匿名作者"}
                                      </span>
                                      <span className="font-mono text-[10px]">
                                        {aweme.aweme_id}
                                      </span>
                                      <SourceBadge
                                        sourceType={aweme.source_type}
                                        sourceLabel={aweme.source_label}
                                        className="shrink-0"
                                      />
                                      {tags.slice(0, 2).map((tag) => (
                                        <span key={tag.id}>#{tag.name}</span>
                                      ))}
                                      {tags.length > 2 && (
                                        <span>+{tags.length - 2}</span>
                                      )}
                                    </p>
                                  </div>
                                </div>
                              </TableCell>
                            )}
                            {isVisible("published") && (
                              <TableCell className="hidden min-w-32 text-sm whitespace-nowrap lg:table-cell">
                                {/* 报告 A16：时间点改用相对时间，悬停看绝对时间 */}
                                <TimeAgo
                                  value={unixSecondsToDate(aweme.create_time)}
                                />
                              </TableCell>
                            )}
                            {isVisible("interactions") && (
                              <TableCell className="hidden min-w-36 text-xs xl:table-cell">
                                <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
                                  <span>赞 {compact(aweme.liked_count)}</span>
                                  <span>评 {compact(aweme.comment_count)}</span>
                                  <span>
                                    藏 {compact(aweme.collected_count)}
                                  </span>
                                  <span>转 {compact(aweme.share_count)}</span>
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
                                      asset.status === "temporary"
                                        ? "仅字幕（视频已删除）"
                                        : asset.storage_backend === "minio"
                                          ? "云端"
                                          : "本地"
                                    }
                                    status={asset.status}
                                    progress={asset.progress}
                                    error={asset.error}
                                    detail={`已尝试 ${asset.attempt_count} 次`}
                                  />
                                ) : (
                                  <span className="text-xs text-muted-foreground">
                                    未创建下载任务
                                  </span>
                                )}
                              </TableCell>
                            )}
                            {isVisible("subtitle") && (
                              <TableCell className="min-w-48">
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
                            {/* 报告 A8：播放 / 更多操作统一收在行尾并冻结在最右侧 */}
                            <TableCell className="sticky right-0 min-w-40 bg-background/95 backdrop-blur">
                              <div className="flex justify-end">
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
                            </TableCell>
                          </TableRow>
                        </RowContextMenu>
                        {/* 报告 A5：展开行显示作品详情（媒体 / 字幕 / 评论汇总） */}
                        {isExpanded && (
                          <TableRow className="bg-muted/20 hover:bg-muted/20">
                            <TableCell
                              colSpan={rowColumnCount}
                              className="whitespace-normal"
                            >
                              <WorkDetailDetails row={row} />
                            </TableCell>
                          </TableRow>
                        )}
                      </Fragment>
                    )
                  })}
                  {virtualizeActive && <tr style={{ height: paddingBottom }} />}
                </>
              ) : worksQuery.isLoading ? (
                // 报告 A4：加载态改用骨架屏并保留列结构，避免内容跳动
                <WorkTableSkeleton isVisible={isVisible} />
              ) : (
                <TableRow>
                  <TableCell colSpan={rowColumnCount}>
                    {emptyWorksState}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
        <Pager
          page={page}
          pageSize={pageSize}
          total={worksQuery.data?.count ?? 0}
          totalLabel={(total) => `共 ${total} 项`}
          onPageChange={setPage}
        />
      </CardContent>
    </Card>
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
    <div className="flex shrink-0 flex-wrap items-center gap-1">
      {(asset?.download_available || aweme.video_download_url) && (
        <VideoPreviewDialog taskId={taskId} asset={asset} aweme={aweme} />
      )}
      {/* 仅字幕任务没有可播放文件，但仍然要能直接查看字幕内容 */}
      {asset?.subtitle && (
        <SubtitleDialog asset={asset} title={aweme.title || aweme.aweme_id} />
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
              ? asset.status === "temporary"
                ? "仅字幕（视频已删除）"
                : `${PIPELINE_STATUS_LABELS[asset.status] ?? asset.status} · ${asset.storage_backend === "minio" ? "云端" : "本地"}`
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
          label="字幕段落"
          value={
            asset?.subtitle
              ? `${asset.subtitle.segments.length} 段 · ${asset.subtitle.full_text.length} 字`
              : "—"
          }
        />
        <DetailItem
          label="最近更新"
          value={asset ? formatDateTime(asset.updated_at) : "—"}
        />
        {/* 行内不再展示抓取时间，完整信息收进行展开详情 */}
        <DetailItem label="抓取时间" value={formatDateTime(aweme.fetched_at)} />
      </div>
      {asset?.error && (
        <p className="text-xs text-destructive">视频错误：{asset.error}</p>
      )}
      {asset?.subtitle?.error && (
        <p className="text-xs text-destructive">
          字幕错误：{asset.subtitle.error}
        </p>
      )}
      {asset?.subtitle?.full_text.trim() && (
        <div className="rounded-lg border bg-background/60 p-2 text-xs">
          <p className="text-muted-foreground">字幕文本</p>
          <p className="mt-0.5 line-clamp-4 whitespace-pre-wrap leading-5">
            {asset.subtitle.full_text}
          </p>
        </div>
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
          mono && "font-mono text-[10px]",
        )}
      >
        {value}
      </p>
    </div>
  )
}

/**
 * 报告 A4：表格加载骨架。保留 6 列的列结构（含断点隐藏与报告 A1 的列可见性），
 * 骨架块与真实行同高，数据到达时不会出现内容跳动。
 */
function WorkTableSkeleton({
  isVisible,
}: {
  isVisible: (key: string) => boolean
}) {
  // 与表头一一对应：展开控制 / 作品 / 发布时间 / 互动数据 / 已保存评论 / 视频 / 字幕 / 操作。
  // 报告 A1：列可见性必须同步到骨架，否则隐藏列后骨架会比表头多出一格。
  const cells = [
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
          <TableCell className="w-14">
            <Skeleton className="size-4" />
          </TableCell>
          {cells.map((cell, cellIndex) =>
            isVisible(cell.key) ? (
              <TableCell
                key={`work-skeleton-${rowIndex}-${cellIndex}`}
                className={cell.className}
              >
                <Skeleton className="h-4 w-full" />
              </TableCell>
            ) : null,
          )}
          <TableCell className="w-40">
            <Skeleton className="ml-auto h-4 w-24" />
          </TableCell>
        </TableRow>
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
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <Badge variant={status === "failed" ? "destructive" : "outline"}>
          {label} · {PIPELINE_STATUS_LABELS[status] ?? status}
        </Badge>
        <span className="text-[10px] text-muted-foreground">{progress}%</span>
      </div>
      <div className="h-1 overflow-hidden rounded-full bg-muted">
        <div
          className={
            status === "failed" ? "h-full bg-destructive" : "h-full bg-primary"
          }
          style={{ width: `${Math.max(0, Math.min(progress, 100))}%` }}
        />
      </div>
      {detail && <p className="text-[10px] text-muted-foreground">{detail}</p>}
      {error && (
        <p className="line-clamp-2 text-[10px] text-destructive">{error}</p>
      )}
    </div>
  )
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
// 模块级单例：渲染路径里每次 `new Intl.*` 都要几毫秒，列表长时开销会累加。
const COMPACT_FORMATTER = new Intl.NumberFormat("zh-CN", {
  notation: "compact",
  maximumFractionDigits: 1,
})

function compact(value: number) {
  return COMPACT_FORMATTER.format(value)
}
