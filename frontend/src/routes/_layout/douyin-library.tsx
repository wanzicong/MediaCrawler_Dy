import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  Outlet,
  useRouterState,
} from "@tanstack/react-router"
import {
  Captions,
  ChevronDown,
  Copy,
  Database,
  Download,
  ExternalLink,
  Film,
  FilterX,
  Heart,
  Languages,
  ListFilter,
  MessageCircle,
  Play,
  PlaySquare,
  RotateCcw,
  Search,
  Share2,
  Star,
  UploadCloud,
} from "lucide-react"
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react"

import {
  type CrawlTaskPublic,
  type DouyinMediaAssetPublic,
  DouyinService,
  DouyinTagsService,
  type DouyinWorkPublic,
} from "@/client"
import { BulkActionBar } from "@/components/Common/BulkActionBar"
import { confirmDialog } from "@/components/Common/confirm-dialog"
import { EmptyState } from "@/components/Common/EmptyState"
import { FilterChips } from "@/components/Common/FilterChips"
import { FilterPresetBar } from "@/components/Common/FilterPresetBar"
import { Pager } from "@/components/Common/Pager"
import { PageHero } from "@/components/Common/PageShell"
import { RefreshIndicator } from "@/components/Common/RefreshIndicator"
import { RowContextMenu } from "@/components/Common/RowContextMenu"
import { TableColumnMenu } from "@/components/Common/TableColumnMenu"
import { TimeAgo } from "@/components/Common/TimeAgo"
import {
  type ListViewMode,
  usePersistentViewMode,
  ViewModeToggle,
} from "@/components/Common/ViewModeToggle"
import { AwemeActions } from "@/components/Douyin/AwemeActions"
import { BatchCommentDialog } from "@/components/Douyin/BatchCommentDialog"
import { CoverPlayTrigger } from "@/components/Douyin/CoverPlayTrigger"
import {
  allSourcesValue,
  parseSourceSelection,
  SourceBadge,
  SourceSelect,
  sourceSelectionValue,
  useSourceCatalog,
} from "@/components/Douyin/SourceSelect"
import { SubtitlePanel } from "@/components/Douyin/SubtitlePanel"
import {
  allTracksValue,
  TrackBadge,
  TrackSelect,
  useTrackCatalog,
} from "@/components/Douyin/TrackSelect"
import { downloadMedia } from "@/components/Douyin/UnifiedWorksPanel"
import {
  VideoPreviewDialog,
  videoPreviewTriggerLabel,
} from "@/components/Douyin/VideoPreviewDialog"
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
} from "@/components/ui/dialog"
import { DropdownMenuItem } from "@/components/ui/dropdown-menu"
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
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import useCustomToast from "@/hooks/useCustomToast"
import { useHighlightedRows } from "@/hooks/useHighlightedRows"
import { useSmartPolling } from "@/hooks/useSmartPolling"
import { type TableColumnDef, useTableColumns } from "@/hooks/useTableColumns"
import { useVirtualRows } from "@/hooks/useVirtualRows"
import { downloadCsv } from "@/lib/csv"
// 报告 O4：筛选上 URL 所需的纯函数
import {
  compactSearch,
  readEnumParam,
  readStringParam,
} from "@/lib/search-params"
import { getDouyinVideoUrl, handleError } from "@/utils"

const pageSize = 32

/**
 * 表格视图的虚拟滚动阈值与行高估算。
 *
 * 单页 32 行、每行上百个 DOM 节点，整页铺满时开发模式下一次重渲染要一两秒；
 * 超过阈值就只渲染可视区的行（任务详情表用的是同一套做法）。
 */
const LIBRARY_VIRTUALIZE_THRESHOLD = 12
const LIBRARY_ROW_ESTIMATE_SIZE = 64
const activeStatuses = new Set([
  "queued",
  "running",
  "waiting_login",
  "processing_media",
])

type SortValue =
  | "downloaded_at:desc"
  | "published_at:desc"
  | "published_at:asc"
  | "liked_count:desc"
  | "comment_count:desc"
  | "collected_count:desc"
  | "persisted_comment_count:desc"
  | "file_size:desc"

// 报告 O4：筛选上 URL —— 枚举白名单（validateSearch 用它挡住手改 URL 的脏值）
const SORT_VALUES: readonly SortValue[] = [
  "downloaded_at:desc",
  "published_at:desc",
  "published_at:asc",
  "liked_count:desc",
  "comment_count:desc",
  "collected_count:desc",
  "persisted_comment_count:desc",
  "file_size:desc",
]

const STORAGE_BACKEND_VALUES = ["all", "local", "minio"] as const

const SUBTITLE_STATUS_VALUES = [
  "all",
  "pending",
  "running",
  "completed",
  "failed",
] as const

const DOWNLOAD_STATUS_VALUES = [
  "all",
  "missing",
  "queued",
  "downloading",
  "downloaded",
  "failed",
] as const

// 报告 A2：存储后端与下载状态的中文展示名（chips 里不直接显示原始 key）
const storageBackendLabels: Record<"local" | "minio", string> = {
  local: "本地",
  minio: "云端 MinIO",
}

const downloadStatusLabels: Record<string, string> = {
  missing: "未下载",
  downloaded: "已下载",
  queued: "排队中",
  downloading: "下载中",
  failed: "下载失败",
}

// 报告 A1：列可见性 —— VideoTable 的列清单。
// 必须是模块级稳定常量：放进组件里每次渲染都会新建数组，hook 的状态会被反复重置。
// key 用英文短名进本地存储，title 用表头中文原文；操作列与选择列不允许隐藏。
const LIBRARY_COLUMNS = [
  { key: "select", title: "选择", alwaysVisible: true },
  { key: "work", title: "作品" },
  { key: "creator", title: "创作者" },
  { key: "track", title: "赛道" },
  { key: "source", title: "来源" },
  { key: "liked", title: "点赞" },
  { key: "comment", title: "评论" },
  { key: "persisted", title: "已存评论" },
  { key: "published", title: "发布时间" },
  { key: "download", title: "下载" },
  { key: "subtitle", title: "字幕" },
  { key: "actions", title: "操作", alwaysVisible: true },
] as const satisfies readonly TableColumnDef[]

// 报告 O4：字段一律写成「可选属性」`x?: T`，而不是 `x: T | undefined`。
// 后者里键是**必填**的，TanStack Router 会据此要求所有指向本路由的
// <Link> / navigate 都必须传完整 search；可选属性才允许省略。
// 本类型被 douyin-library.feed.tsx 复用（那边只读不写），改成可选同样兼容。
export type LibraryFeedSearch = {
  start?: string
  track?: string
  source?: string
  q?: string
  task?: string
  creator?: string
  tag?: string
  storage?: "all" | "local" | "minio"
  subtitle?: "all" | "pending" | "running" | "completed" | "failed"
  /** 报告 O4：下载状态筛选（新增，此前未进 URL） */
  download?:
    | "all"
    | "missing"
    | "queued"
    | "downloading"
    | "downloaded"
    | "failed"
  sort?: SortValue
  /** 报告 O4：分页（新增，此前未进 URL） */
  page?: number
}

// 报告 O4：URL 里的 page 是字符串，安全解析为 >= 0 的整数，脏值一律当第 0 页
function readPageParam(search: Record<string, unknown>): number {
  const raw = readStringParam(search, "page")
  const parsed = raw === undefined ? 0 : Number.parseInt(raw, 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0
}

export const Route = createFileRoute("/_layout/douyin-library")({
  // 报告 O4：筛选上 URL —— 刷新 / 分享 / 收藏 / 深链都能还原筛选条件。
  // 原有参数（track/source/q/task/creator/tag/storage/subtitle/sort）全部保留，
  // 本次新增 download（下载状态）与 page（分页），并把读取统一收敛到 @/lib/search-params。
  validateSearch: (search: Record<string, unknown>): LibraryFeedSearch => ({
    track: readStringParam(search, "track"),
    source: readStringParam(search, "source"),
    q: readStringParam(search, "q"),
    task: readStringParam(search, "task"),
    creator: readStringParam(search, "creator"),
    tag: readStringParam(search, "tag"),
    storage: readEnumParam(search, "storage", STORAGE_BACKEND_VALUES),
    subtitle: readEnumParam(search, "subtitle", SUBTITLE_STATUS_VALUES),
    download: readEnumParam(search, "download", DOWNLOAD_STATUS_VALUES),
    sort: readEnumParam(search, "sort", SORT_VALUES),
    page: readPageParam(search),
  }),
  component: DouyinVideoLibrary,
  head: () => ({ meta: [{ title: "视频资源库 - 灵感采集台" }] }),
})

function DouyinVideoLibrary() {
  const routeSearch = Route.useSearch()
  // 报告 O4：筛选状态写回 URL 用的 navigate
  const navigate = Route.useNavigate()
  const feedRouteActive = useRouterState({
    select: (state) => state.location.pathname.endsWith("/feed"),
  })
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  // 报告 O4：分页初值来自 URL，刷新 / 深链可还原
  const [page, setPage] = useState(routeSearch.page ?? 0)
  const [search, setSearch] = useState(routeSearch.q ?? "")
  const [trackId, setTrackId] = useState(routeSearch.track ?? allTracksValue)
  const [sourceValue, setSourceValue] = useState(
    routeSearch.source ?? allSourcesValue,
  )
  const [taskId, setTaskId] = useState(routeSearch.task ?? "all")
  const [creatorHash, setCreatorHash] = useState(routeSearch.creator ?? "all")
  const [tagId, setTagId] = useState(routeSearch.tag ?? "all")
  const [storageBackend, setStorageBackend] = useState<
    "all" | "local" | "minio"
  >(routeSearch.storage ?? "all")
  const [downloadStatus, setDownloadStatus] = useState<
    "all" | "missing" | "queued" | "downloading" | "downloaded" | "failed"
  >(routeSearch.download ?? "all")
  // 报告 O11：视图模式改用共享的持久化 hook（自带兜底，隐私模式下不再抛错崩溃）
  const [viewMode, changeViewMode] = usePersistentViewMode(
    "douyin-library-view",
  )
  // 报告 A1：列可见性 —— 只有表格视图是 <Table>，卡片 / 横条视图不接入。
  // 状态提到父组件是因为表格（VideoTable）与骨架屏（LibrarySkeleton）都要用同一份偏好，
  // 两边各自调 hook 会各持一份 state，勾选后另一边不重渲染。
  const { isVisible, visibleCount, menuProps } = useTableColumns({
    storageKey: "douyin-library-columns",
    columns: LIBRARY_COLUMNS,
  })
  const [subtitleStatus, setSubtitleStatus] = useState<
    "all" | "pending" | "running" | "completed" | "failed"
  >(routeSearch.subtitle ?? "all")
  const [sort, setSort] = useState<SortValue>(
    routeSearch.sort ?? "downloaded_at:desc",
  )
  const [sortBy, sortOrder] = sort.split(":") as [
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

  // 报告 O4：筛选上 URL（双向）—— 初值来自 URL，筛选变化时写回 URL。
  // 用 replace: true：不加的话用户每改一次筛选就多一条浏览器历史，按十次「后退」才离开本页。
  // 取舍：刷新 / 分享 / 深链 / 收藏都能还原筛选条件，但浏览器「后退」是回到上一个页面，
  // 而不是回到上一条筛选 —— 这是有意为之。
  // 依赖里只放筛选 state 与 navigate，不放 search 对象，避免「写 URL → search 变 → 再写」的死循环。
  useEffect(() => {
    // 沉浸播放子路由（/douyin-library/feed）有自己的 URL 参数，父路由不插手，否则会把用户踢出播放页
    if (feedRouteActive) return
    void navigate({
      to: "/douyin-library",
      replace: true,
      search: compactSearch(
        {
          q: search.trim() || undefined,
          track: trackId === allTracksValue ? undefined : trackId,
          source: sourceValue === allSourcesValue ? undefined : sourceValue,
          task: taskId === "all" ? undefined : taskId,
          creator: creatorHash === "all" ? undefined : creatorHash,
          tag: tagId === "all" ? undefined : tagId,
          storage: storageBackend,
          subtitle: subtitleStatus,
          download: downloadStatus,
          sort,
          page,
        },
        // 等于默认值的键不写进 URL：未筛选时地址栏保持干净的 /douyin-library
        {
          storage: "all",
          subtitle: "all",
          download: "all",
          sort: "downloaded_at:desc",
          page: 0,
        },
      ),
    })
  }, [
    search,
    trackId,
    sourceValue,
    taskId,
    creatorHash,
    tagId,
    storageBackend,
    subtitleStatus,
    downloadStatus,
    sort,
    page,
    feedRouteActive,
    navigate,
  ])

  const tasksQuery = useQuery({
    queryKey: ["douyin-library-tasks", trackId, sourceValue],
    queryFn: () =>
      DouyinService.listTasks({
        trackId: trackId && trackId !== allTracksValue ? trackId : undefined,
        ...parseSourceSelection(sourceValue),
        limit: 100,
      }),
    staleTime: 30_000,
  })
  const creatorsQuery = useQuery({
    queryKey: ["douyin-library-creators", trackId, taskId],
    queryFn: () =>
      DouyinService.listLibraryCreators({
        trackId: trackId && trackId !== allTracksValue ? trackId : undefined,
        taskId: taskId === "all" ? undefined : taskId,
      }),
    staleTime: 30_000,
  })
  const tagsQuery = useQuery({
    queryKey: ["douyin-library-tags", trackId, taskId],
    queryFn: () =>
      DouyinTagsService.listTags({
        trackId: trackId && trackId !== allTracksValue ? trackId : undefined,
        taskId: taskId === "all" ? undefined : taskId,
        sortBy: "aweme_count",
        sortOrder: "desc",
        limit: 500,
      }),
    staleTime: 30_000,
  })
  // 报告 A2：筛选 chips 需要把 track / source 的原始值翻译成中文名。
  // 这两个 hook 与 TrackSelect / SourceSelect 内部使用同一 queryKey，命中缓存，不会多发请求。
  const trackCatalogQuery = useTrackCatalog()
  const sourceCatalogQuery = useSourceCatalog(trackId)
  const worksQuery = useSmartPolling(
    [
      "douyin-library-works",
      page,
      trackId,
      sourceValue,
      search,
      taskId,
      creatorHash,
      tagId,
      storageBackend,
      subtitleStatus,
      downloadStatus,
      sort,
    ],
    () =>
      DouyinService.listLibraryWorks({
        trackId: trackId && trackId !== allTracksValue ? trackId : undefined,
        search: search.trim() || undefined,
        taskId: taskId === "all" ? undefined : taskId,
        creatorHash: creatorHash === "all" ? undefined : creatorHash,
        tagId: tagId === "all" ? undefined : tagId,
        ...parseSourceSelection(sourceValue),
        downloadStatus,
        storageBackend,
        subtitleStatus,
        sortBy,
        sortOrder,
        skip: page * pageSize,
        limit: pageSize,
      }),
    {
      // 只有列表里还存在队列中 / 下载中 / 转写中的作品时才轮询：
      // 此前是无条件 5 秒拉一次（单页 700KB+，含字幕全文与分段时间轴），
      // 每次刷新都要重渲染整屏卡片，是页面「时不时卡住、点了没反应」的主因。
      isActive: (data) =>
        data.data.some(
          (row) =>
            row.media?.status === "queued" ||
            row.media?.status === "downloading" ||
            row.media?.subtitle?.status === "pending" ||
            row.media?.subtitle?.status === "running",
        ),
      activeInterval: 5_000,
      placeholderData: (previous) => previous,
    },
  )
  const taskMap = useMemo(
    () => new Map((tasksQuery.data?.data ?? []).map((task) => [task.id, task])),
    [tasksQuery.data?.data],
  )
  const rows = useMemo(() => {
    const seen = new Set<string>()
    return (worksQuery.data?.data ?? []).filter((row) => {
      const awemeId = row.aweme.aweme_id
      if (seen.has(awemeId)) return false
      seen.add(awemeId)
      return true
    })
  }, [worksQuery.data?.data])
  const [selectedAwemeIds, setSelectedAwemeIds] = useState<string[]>([])
  // 报告 A6：轮询刷新后下载状态 / 媒体状态发生变化的作品在表格视图里闪一下
  // 指纹用「下载状态 + 媒体资产更新时间」，两者任一变化都会让指纹变化。
  // 只用于表格行：.row-highlight 动画以「底色渐隐到透明」收尾，卡片自身有底色，套用会闪成透明。
  const highlighted = useHighlightedRows(
    rows,
    (row) => row.aweme.id,
    (row) => `${row.media?.status ?? "none"}:${row.media?.updated_at ?? ""}`,
  )
  const selectedAwemeSet = useMemo(
    () => new Set(selectedAwemeIds),
    [selectedAwemeIds],
  )
  const pageAwemeIds = rows.map((row) => row.aweme.aweme_id)
  const selectedRows = rows.filter((row) =>
    selectedAwemeSet.has(row.aweme.aweme_id),
  )
  const allPageSelected =
    pageAwemeIds.length > 0 &&
    pageAwemeIds.every((awemeId) => selectedAwemeSet.has(awemeId))
  const somePageSelected = selectedRows.length > 0 && !allPageSelected
  const pageLocal = rows.filter(
    (row) => row.media?.storage_backend === "local",
  ).length
  const pageMinio = rows.filter(
    (row) => row.media?.storage_backend === "minio",
  ).length
  const pageUndownloaded = rows.filter((row) => !row.media).length
  const hasPlayableRows = rows.some((row) => row.media?.download_available)

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["douyin-library-works"] })
  }
  const retry = useMutation({
    mutationFn: ({ taskId, assetId }: { taskId: string; assetId: string }) =>
      DouyinService.retryMedia({
        taskId,
        requestBody: {
          asset_ids: [assetId],
          retry_downloads: true,
          retry_subtitles: true,
        },
      }),
    onSuccess: async () => {
      showSuccessToast("资源已重新排队")
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const retranslate = useMutation({
    mutationFn: ({ taskId, assetId }: { taskId: string; assetId: string }) =>
      DouyinService.retranslateMedia({ taskId, assetId }),
    onSuccess: async () => {
      showSuccessToast("字幕已提交到远程翻译服务")
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const recrawlComments = useMutation({
    mutationFn: async (selectedWorks: DouyinWorkPublic[]) => {
      const taskCache = new Map(taskMap)
      let created = 0
      for (const work of selectedWorks) {
        const sourceTaskId = work.aweme.task_id
        let sourceTask = taskCache.get(sourceTaskId)
        if (!sourceTask) {
          sourceTask = await DouyinService.getTask({ taskId: sourceTaskId })
          taskCache.set(sourceTaskId, sourceTask)
        }
        await DouyinService.recrawlAwemeComments({
          taskId: sourceTaskId,
          awemeId: work.aweme.aweme_id,
          requestBody: {
            fetch_sub_comments: Boolean(sourceTask.request.fetch_sub_comments),
            max_comments_per_aweme: Number(
              sourceTask.request.max_comments_per_aweme ?? 10,
            ),
            request_delay_level:
              sourceTask.request.request_delay_level === "ultra_steady"
                ? "ultra_steady"
                : "steady",
            account_id: sourceTask.account_id ?? undefined,
          },
        })
        created += 1
      }
      return created
    },
    onSuccess: async (created) => {
      showSuccessToast(`已为 ${created} 个视频创建评论采集任务`)
      setSelectedAwemeIds([])
      await Promise.all([
        // 任务页列表
        queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] }),
        // 本页顶部的任务下拉（queryKey 为 ["douyin-library-tasks", trackId, sourceValue]）——
        // 此前漏了这一个，导致批量补采后下拉框不刷新。
        queryClient.invalidateQueries({ queryKey: ["douyin-library-tasks"] }),
      ])
    },
    onError: handleError.bind(showErrorToast),
  })
  const migrationFilters = {
    search: search.trim() || undefined,
    track_id: trackId && trackId !== allTracksValue ? trackId : undefined,
    task_id: taskId === "all" ? undefined : taskId,
    creator_hash: creatorHash === "all" ? undefined : creatorHash,
    tag_id: tagId === "all" ? undefined : tagId,
    subtitle_status: subtitleStatus,
  }
  const migrateLibrary = useMutation({
    mutationFn: () =>
      DouyinService.migrateLibraryMediaToMinio({
        requestBody: migrationFilters,
      }),
    onSuccess: async (result) => {
      showSuccessToast(
        result.queued
          ? `已将 ${result.queued} 个本地视频加入云端上传队列`
          : result.message,
      )
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const [exportingSubtitles, setExportingSubtitles] = useState(false)
  const exportSubtitles = async () => {
    setExportingSubtitles(true)
    try {
      const loadPage = (skip: number) =>
        DouyinService.listLibraryWorks({
          trackId: trackId && trackId !== allTracksValue ? trackId : undefined,
          search: search.trim() || undefined,
          taskId: taskId === "all" ? undefined : taskId,
          creatorHash: creatorHash === "all" ? undefined : creatorHash,
          tagId: tagId === "all" ? undefined : tagId,
          ...parseSourceSelection(sourceValue),
          downloadStatus,
          storageBackend,
          subtitleStatus,
          sortBy,
          sortOrder,
          skip,
          limit: 100,
        })
      const firstPage = await loadPage(0)
      const total = firstPage.count ?? firstPage.data?.length ?? 0
      if (total > 1000) {
        // 报告 O15：改用统一确认框（导出属于可恢复操作，用默认样式）
        const ok = await confirmDialog({
          title: `当前筛选条件命中 ${total} 条作品，完整导出可能需要较长时间。`,
          description: "确认继续导出吗？",
          confirmText: "继续导出",
        })
        if (!ok) return
      }
      const works: DouyinWorkPublic[] = [...(firstPage.data ?? [])]
      while (works.length < total) {
        const nextPage = await loadPage(works.length)
        if (!nextPage.data?.length) break
        works.push(...nextPage.data)
      }
      const withSubtitle = works.filter((work) =>
        work.media?.subtitle?.full_text.trim(),
      )
      if (!withSubtitle.length) {
        showErrorToast("当前筛选结果中没有可导出的字幕")
        return
      }
      const exportedAt = new Date()
      const blocks = withSubtitle.map((work, index) => {
        const aweme = work.aweme
        const subtitle = work.media?.subtitle
        const meta = [
          `作品号：${aweme.aweme_id}`,
          `达人：${aweme.nickname || "匿名创作者"}`,
          `发布时间：${formatUnix(aweme.create_time)}`,
          subtitle?.language ? `字幕语言：${subtitle.language}` : "",
        ]
          .filter(Boolean)
          .join(" · ")
        return `【${index + 1}】${aweme.title || aweme.aweme_id}\n${meta}\n${subtitle?.full_text.trim()}`
      })
      const header = `抖音字幕导出（按当前筛选条件）\n导出时间：${formatDateTimeText(exportedAt)}\n筛选命中 ${total} 条作品，本次导出 ${withSubtitle.length} 条字幕`
      const content = `${header}\n\n${"=".repeat(56)}\n\n${blocks.join("\n\n")}\n`
      const url = URL.createObjectURL(
        new Blob([`\uFEFF${content}`], { type: "text/plain;charset=utf-8" }),
      )
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = `douyin-subtitles-${exportedAt.getFullYear()}${String(exportedAt.getMonth() + 1).padStart(2, "0")}${String(exportedAt.getDate()).padStart(2, "0")}-${String(exportedAt.getHours()).padStart(2, "0")}${String(exportedAt.getMinutes()).padStart(2, "0")}.txt`
      anchor.click()
      URL.revokeObjectURL(url)
      showSuccessToast(`已按筛选条件导出 ${withSubtitle.length} 条字幕`)
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : "字幕导出失败")
    } finally {
      setExportingSubtitles(false)
    }
  }
  // 报告 A12：CSV 导出只导「已选中 / 当前页」这类小数据量，全量导出需后端流式接口
  const exportWorksCsv = () => {
    const target = selectedRows.length ? selectedRows : rows
    if (!target.length) return
    downloadCsv(
      selectedRows.length ? "视频资源库-已选" : "视频资源库-当前页",
      target,
      [
        { header: "作品 ID", value: (row) => row.aweme.aweme_id },
        { header: "作者", value: (row) => row.aweme.nickname || "匿名创作者" },
        {
          header: "发布时间",
          value: (row) => formatUnix(row.aweme.create_time),
        },
        { header: "点赞", value: (row) => row.aweme.liked_count },
        { header: "评论", value: (row) => row.aweme.comment_count },
        { header: "收藏", value: (row) => row.aweme.collected_count },
        { header: "下载状态", value: (row) => downloadStateText(row) },
        { header: "存储后端", value: (row) => storageBackendText(row) },
      ],
    )
  }
  // 列表行做了 memo：这里的对象必须保持引用稳定，否则每次渲染都会新建一份、击穿 memo。
  const feedSearch: LibraryFeedSearch = useMemo(
    () => ({
      track: trackId && trackId !== allTracksValue ? trackId : undefined,
      source: sourceValue === allSourcesValue ? undefined : sourceValue,
      q: search.trim() || undefined,
      task: taskId === "all" ? undefined : taskId,
      creator: creatorHash === "all" ? undefined : creatorHash,
      tag: tagId === "all" ? undefined : tagId,
      storage: storageBackend,
      subtitle: subtitleStatus,
      sort,
    }),
    [
      creatorHash,
      search,
      sort,
      sourceValue,
      storageBackend,
      subtitleStatus,
      tagId,
      taskId,
      trackId,
    ],
  )

  const toggleSelection = useCallback((awemeId: string, checked: boolean) => {
    setSelectedAwemeIds((current) =>
      checked
        ? current.includes(awemeId)
          ? current
          : [...current, awemeId]
        : current.filter((id) => id !== awemeId),
    )
  }, [])
  const togglePageSelection = useCallback(
    (checked: boolean) => {
      setSelectedAwemeIds(checked ? pageAwemeIds : [])
    },
    [pageAwemeIds],
  )
  // 逐行回调统一收在这里并保持稳定引用：列表行 memo 之后，轮询刷新只有
  // 真正变化的行会重渲染，而不是整屏 32 行一起重画。
  const handleRetryAsset = useCallback(
    (taskId: string, asset: DouyinMediaAssetPublic) =>
      retry.mutate({ taskId, assetId: asset.id }),
    [retry.mutate],
  )
  const handleRetranslateAsset = useCallback(
    (taskId: string, asset: DouyinMediaAssetPublic) =>
      retranslate.mutate({ taskId, assetId: asset.id }),
    [retranslate.mutate],
  )
  const handleDownloadAsset = useCallback(
    (taskId: string, asset: DouyinMediaAssetPublic) =>
      downloadMedia(taskId, asset, showErrorToast),
    [showErrorToast],
  )
  const handleRecrawlComments = useCallback(
    (row: DouyinWorkPublic) => recrawlComments.mutate([row]),
    [recrawlComments.mutate],
  )

  if (feedRouteActive) return <Outlet />

  const resetPage = () => {
    setPage(0)
    setSelectedAwemeIds([])
  }
  // 报告 A2：筛选 chips —— 把已应用筛选的原始值翻译成中文展示名
  const trackChipName = (trackCatalogQuery.data?.data ?? []).find(
    (track) => track.id === trackId,
  )?.name
  const sourceChipName = (sourceCatalogQuery.data?.data ?? []).find(
    (option) =>
      sourceSelectionValue(option.source_type, option.id) === sourceValue,
  )?.name
  const selectedTask = (tasksQuery.data?.data ?? []).find(
    (task) => task.id === taskId,
  )
  const selectedCreator = (creatorsQuery.data?.data ?? []).find(
    (creator) => creator.creator_hash === creatorHash,
  )
  const selectedTag = (tagsQuery.data?.data ?? []).find(
    (tag) => tag.id === tagId,
  )
  // 报告 A2：一次性清除全部筛选（排序不是筛选条件，保留用户当前排序）
  const clearAllFilters = () => {
    setSearch("")
    setTrackId(allTracksValue)
    setSourceValue(allSourcesValue)
    setTaskId("all")
    setCreatorHash("all")
    setTagId("all")
    setStorageBackend("all")
    setDownloadStatus("all")
    setSubtitleStatus("all")
    resetPage()
  }
  // 报告 A4：区分「筛选无结果」与「库里确实还没有作品」——两者的空态引导完全不同。
  // 前者引导「清除筛选」，后者引导「先去采集」，所以要先知道当前是否带着筛选条件。
  const hasActiveFilters = Boolean(
    search.trim() ||
      trackId !== allTracksValue ||
      sourceValue !== allSourcesValue ||
      taskId !== "all" ||
      creatorHash !== "all" ||
      tagId !== "all" ||
      storageBackend !== "all" ||
      downloadStatus !== "all" ||
      subtitleStatus !== "all",
  )
  const filterChips = [
    search.trim()
      ? {
          key: "q",
          label: "搜索",
          value: search.trim(),
          onRemove: () => {
            setSearch("")
            resetPage()
          },
        }
      : false,
    trackId !== allTracksValue
      ? {
          key: "track",
          label: "赛道",
          value: trackChipName ?? trackId.slice(0, 8),
          onRemove: () => {
            setTrackId(allTracksValue)
            setSourceValue(allSourcesValue)
            setTaskId("all")
            setCreatorHash("all")
            setTagId("all")
            resetPage()
          },
        }
      : false,
    sourceValue !== allSourcesValue
      ? {
          key: "source",
          label: "来源",
          value: sourceChipName ?? sourceValue.slice(0, 16),
          onRemove: () => {
            setSourceValue(allSourcesValue)
            setTaskId("all")
            setCreatorHash("all")
            setTagId("all")
            resetPage()
          },
        }
      : false,
    taskId !== "all"
      ? {
          key: "task",
          label: "任务",
          value: selectedTask ? taskLabel(selectedTask) : taskId.slice(0, 8),
          onRemove: () => {
            setTaskId("all")
            setCreatorHash("all")
            setTagId("all")
            resetPage()
          },
        }
      : false,
    creatorHash !== "all"
      ? {
          key: "creator",
          label: "创作者",
          value: selectedCreator?.nickname || creatorHash.slice(0, 8),
          onRemove: () => {
            setCreatorHash("all")
            resetPage()
          },
        }
      : false,
    tagId !== "all"
      ? {
          key: "tag",
          label: "标签",
          value: selectedTag ? `#${selectedTag.name}` : tagId.slice(0, 8),
          onRemove: () => {
            setTagId("all")
            resetPage()
          },
        }
      : false,
    storageBackend !== "all"
      ? {
          key: "storage",
          label: "存储",
          value: storageBackendLabels[storageBackend],
          onRemove: () => {
            setStorageBackend("all")
            resetPage()
          },
        }
      : false,
    downloadStatus !== "all"
      ? {
          key: "download",
          label: "下载状态",
          value: downloadStatusLabels[downloadStatus] ?? downloadStatus,
          onRemove: () => {
            setDownloadStatus("all")
            resetPage()
          },
        }
      : false,
  ]
  return (
    <div className="page-stack">
      <PageHero
        compact
        title="视频资源库"
        actions={
          <div className="flex flex-wrap gap-1.5">
            {hasPlayableRows ? (
              <Button size="sm" asChild>
                <Link to="/douyin-library/feed" search={feedSearch}>
                  <PlaySquare />
                  沉浸播放
                </Link>
              </Button>
            ) : (
              <Button size="sm" disabled title="请先下载视频">
                <PlaySquare />
                下载后播放
              </Button>
            )}
            <Button
              size="sm"
              variant="secondary"
              disabled={
                migrateLibrary.isPending ||
                storageBackend === "minio" ||
                !(worksQuery.data?.count ?? 0)
              }
              onClick={async () => {
                // 报告 O15：改用统一确认框（迁移类操作可恢复，用默认样式）
                const ok = await confirmDialog({
                  title: "确认把当前筛选条件下的所有本地视频上传到云端？",
                  description: "只有完整上传并校验成功后才会删除本地文件。",
                  confirmText: "开始上传",
                })
                if (ok) migrateLibrary.mutate()
              }}
            >
              <UploadCloud />
              {migrateLibrary.isPending ? "正在加入队列…" : "本地视频转云端"}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={exportSubtitles}
              disabled={exportingSubtitles || !(worksQuery.data?.count ?? 0)}
            >
              <Captions />
              {exportingSubtitles ? "正在导出…" : "导出字幕"}
            </Button>
            {/* 报告 A12：CSV 导出（已选中优先，否则导出当前页） */}
            <Button
              size="sm"
              variant="secondary"
              onClick={exportWorksCsv}
              disabled={!rows.length}
              aria-label="导出 CSV"
            >
              <Download />
              导出 CSV
            </Button>
            {/* 报告 A14：刷新指示器（替代原「刷新资源」按钮） */}
            <RefreshIndicator
              updatedAt={worksQuery.dataUpdatedAt}
              refreshing={worksQuery.isFetching}
              onRefresh={() => void invalidate()}
            />
          </div>
        }
      >
        <p className="text-xs text-muted-foreground">
          匹配{" "}
          <strong className="text-foreground">
            {worksQuery.data?.count ?? 0}
          </strong>{" "}
          · 创作者{" "}
          <strong className="text-foreground">
            {creatorsQuery.data?.count ?? 0}
          </strong>{" "}
          · 本页本地 <strong className="text-foreground">{pageLocal}</strong> ·
          云端 <strong className="text-foreground">{pageMinio}</strong> · 未下载{" "}
          <strong className="text-foreground">{pageUndownloaded}</strong>
        </p>
      </PageHero>

      <Card>
        <CardContent className="space-y-2 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-64 flex-[2]">
              <Search
                aria-hidden="true"
                className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value)
                  resetPage()
                }}
                placeholder="搜索标题、描述、创作者或作品号"
                aria-label="搜索视频资源"
                className="h-9 pl-9"
              />
            </div>
            <TrackSelect
              value={trackId}
              onValueChange={(value) => {
                setTrackId(value)
                setSourceValue(allSourcesValue)
                setTaskId("all")
                setCreatorHash("all")
                setTagId("all")
                resetPage()
              }}
              includeAll
              allowDisabled
              ariaLabel="按赛道筛选视频资源"
              className="h-9 min-w-40 flex-1"
            />
            <SourceSelect
              trackId={trackId}
              value={sourceValue}
              onValueChange={(value) => {
                setSourceValue(value)
                setTaskId("all")
                setCreatorHash("all")
                setTagId("all")
                resetPage()
              }}
              className="h-9 min-w-48 flex-1"
              ariaLabel="按关键词或作者筛选视频资源"
            />
            <Select
              value={taskId}
              onValueChange={(value) => {
                setTaskId(value)
                setCreatorHash("all")
                setTagId("all")
                resetPage()
              }}
            >
              <SelectTrigger className="h-9 min-w-36" aria-label="筛选任务">
                <SelectValue placeholder="选择任务" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部任务</SelectItem>
                {(tasksQuery.data?.data ?? []).map((task) => (
                  <SelectItem key={task.id} value={task.id}>
                    {taskLabel(task)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={tagId}
              onValueChange={(value) => {
                setTagId(value)
                resetPage()
              }}
            >
              <SelectTrigger className="h-9 min-w-32" aria-label="筛选标签">
                <SelectValue placeholder="选择标签" />
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
            <Select
              value={creatorHash}
              onValueChange={(value) => {
                setCreatorHash(value)
                resetPage()
              }}
            >
              <SelectTrigger className="h-9 min-w-36" aria-label="筛选创作者">
                <SelectValue placeholder="选择创作者" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部创作者</SelectItem>
                {(creatorsQuery.data?.data ?? []).map((creator) => (
                  <SelectItem
                    key={creator.creator_hash}
                    value={creator.creator_hash}
                  >
                    {creator.nickname}（{creator.work_count}）
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={storageBackend}
              onValueChange={(value) => {
                setStorageBackend(value as "all" | "local" | "minio")
                resetPage()
              }}
            >
              <SelectTrigger className="h-9 min-w-32" aria-label="筛选存储后端">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部存储</SelectItem>
                <SelectItem value="local">本地服务器</SelectItem>
                <SelectItem value="minio">云端存储</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={subtitleStatus}
              onValueChange={(value) => {
                setSubtitleStatus(value as typeof subtitleStatus)
                resetPage()
              }}
            >
              <SelectTrigger className="h-9 min-w-32" aria-label="筛选字幕状态">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部字幕</SelectItem>
                <SelectItem value="completed">字幕完成</SelectItem>
                <SelectItem value="running">字幕处理中</SelectItem>
                <SelectItem value="pending">字幕等待中</SelectItem>
                <SelectItem value="failed">字幕失败</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-wrap items-center gap-2 border-t pt-2">
            <div className="flex flex-wrap items-center gap-2">
              {/* 报告 O11：换成共享的三视图切换组件 */}
              <ViewModeToggle
                value={viewMode}
                onChange={changeViewMode}
                label="切换视频展示方式"
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Select
                value={downloadStatus}
                onValueChange={(value) => {
                  setDownloadStatus(value as typeof downloadStatus)
                  resetPage()
                }}
              >
                <SelectTrigger className="h-9 w-36" aria-label="按下载状态筛选">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部状态</SelectItem>
                  <SelectItem value="missing">未下载</SelectItem>
                  <SelectItem value="downloaded">已下载</SelectItem>
                  <SelectItem value="queued">排队中</SelectItem>
                  <SelectItem value="downloading">下载中</SelectItem>
                  <SelectItem value="failed">下载失败</SelectItem>
                </SelectContent>
              </Select>
              <Select
                value={sort}
                onValueChange={(value) => {
                  setSort(value as SortValue)
                  resetPage()
                }}
              >
                <SelectTrigger className="h-9 w-44" aria-label="排序方式">
                  <ListFilter aria-hidden="true" />
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="downloaded_at:desc">最近下载</SelectItem>
                  <SelectItem value="published_at:desc">最新发布</SelectItem>
                  <SelectItem value="published_at:asc">最早发布</SelectItem>
                  <SelectItem value="liked_count:desc">点赞最多</SelectItem>
                  <SelectItem value="comment_count:desc">评论最多</SelectItem>
                  <SelectItem value="collected_count:desc">收藏最多</SelectItem>
                  <SelectItem value="persisted_comment_count:desc">
                    已保存评论最多
                  </SelectItem>
                  <SelectItem value="file_size:desc">文件最大</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="ml-auto flex items-center gap-2">
              <Checkbox
                id="select-library-page"
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
                htmlFor="select-library-page"
                className="cursor-pointer whitespace-nowrap text-xs"
              >
                {selectedRows.length
                  ? `已选择本页 ${selectedRows.length} 个视频`
                  : "选择本页视频"}
              </label>
              {/* 报告 A1：列可见性入口（卡片 / 横条视图不是表格，不显示） */}
              {viewMode === "table" && (
                <TableColumnMenu {...menuProps} className="ml-1" />
              )}
            </div>
          </div>
          {/* 报告 A2：已应用筛选 chips（可单点移除 / 一键清除） */}
          <FilterChips chips={filterChips} onClearAll={clearAllFilters} />
          {/* 报告 A10：筛选预设 */}
          <FilterPresetBar
            storageKey="douyin-library-filter-presets"
            currentFilters={{
              search,
              trackId,
              sourceValue,
              taskId,
              creatorHash,
              tagId,
              storageBackend,
              downloadStatus,
              subtitleStatus,
            }}
            onApply={(f) => {
              const next = f as {
                search: string
                trackId: string
                sourceValue: string
                taskId: string
                creatorHash: string
                tagId: string
                storageBackend: "all" | "local" | "minio"
                downloadStatus:
                  | "all"
                  | "missing"
                  | "queued"
                  | "downloading"
                  | "downloaded"
                  | "failed"
                subtitleStatus:
                  | "all"
                  | "pending"
                  | "running"
                  | "completed"
                  | "failed"
              }
              setSearch(next.search ?? "")
              setTrackId(next.trackId ?? allTracksValue)
              setSourceValue(next.sourceValue ?? allSourcesValue)
              setTaskId(next.taskId ?? "all")
              setCreatorHash(next.creatorHash ?? "all")
              setTagId(next.tagId ?? "all")
              setStorageBackend(next.storageBackend ?? "all")
              setDownloadStatus(next.downloadStatus ?? "all")
              setSubtitleStatus(next.subtitleStatus ?? "all")
              resetPage()
            }}
          />
        </CardContent>
      </Card>

      {!rows.length && worksQuery.isLoading ? (
        <LibrarySkeleton
          viewMode={viewMode}
          isVisible={isVisible}
          visibleCount={visibleCount}
        />
      ) : rows.length ? (
        viewMode === "cards" ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-5">
            {rows.map((row) => (
              <VideoCard
                key={row.aweme.id}
                row={row}
                task={taskMap.get(row.aweme.task_id)}
                onRetry={handleRetryAsset}
                onRetranslate={handleRetranslateAsset}
                onDownload={handleDownloadAsset}
                feedSearch={feedSearch}
                selected={selectedAwemeSet.has(row.aweme.aweme_id)}
                onSelectedChange={toggleSelection}
              />
            ))}
          </div>
        ) : viewMode === "rows" ? (
          <div className="space-y-2">
            {rows.map((row) => (
              <VideoRow
                key={row.aweme.id}
                row={row}
                task={taskMap.get(row.aweme.task_id)}
                onRetry={handleRetryAsset}
                onRetranslate={handleRetranslateAsset}
                onDownload={handleDownloadAsset}
                feedSearch={feedSearch}
                selected={selectedAwemeSet.has(row.aweme.aweme_id)}
                onSelectedChange={toggleSelection}
              />
            ))}
          </div>
        ) : (
          <VideoTable
            rows={rows}
            taskMap={taskMap}
            onRetry={handleRetryAsset}
            onRetranslate={handleRetranslateAsset}
            onDownload={handleDownloadAsset}
            feedSearch={feedSearch}
            selectedAwemeSet={selectedAwemeSet}
            allPageSelected={allPageSelected}
            somePageSelected={somePageSelected}
            onTogglePage={togglePageSelection}
            onToggleRow={toggleSelection}
            onRecrawlComments={handleRecrawlComments}
            highlightedIds={highlighted}
            isVisible={isVisible}
          />
        )
      ) : hasActiveFilters ? (
        /* 报告 A4：带着筛选条件却一条都没命中 —— 行动按钮指向「清除筛选」而不是「去采集」 */
        <EmptyState
          icon={FilterX}
          title="没有符合当前条件的视频作品"
          description="当前筛选条件下没有匹配的作品，放宽条件或清除筛选后即可看到库里的其他视频。"
          action={
            <Button size="sm" variant="outline" onClick={clearAllFilters}>
              清除筛选条件
            </Button>
          }
        />
      ) : (
        /* 报告 A4：库里确实还没有作品 —— 引导用户先去采集 */
        <EmptyState
          icon={Film}
          title="视频资源库还是空的"
          description="先在「抖音任务」里创建采集任务，采集到的视频会自动汇总到这里。"
          action={
            <Button size="sm" asChild>
              <Link to="/douyin">去创建采集任务</Link>
            </Button>
          }
        />
      )}

      {/* 报告 O1：改用共享分页器（支持页码跳转） */}
      <Pager
        page={page}
        pageSize={pageSize}
        total={worksQuery.data?.count ?? 0}
        onPageChange={(nextPage) => {
          setPage(nextPage)
          setSelectedAwemeIds([])
        }}
        showJumper
      />

      {/* 报告 A3：批量操作栏（依赖选中项的批量按钮从筛选栏搬到这里） */}
      <BulkActionBar
        count={selectedRows.length}
        onClear={() => setSelectedAwemeIds([])}
        actions={
          <>
            <Button
              size="sm"
              disabled={recrawlComments.isPending}
              onClick={async () => {
                // 报告 O15：改用统一确认框（选中的作品较多时才二次确认）
                if (selectedRows.length > 20) {
                  const ok = await confirmDialog({
                    title: `将为 ${selectedRows.length} 个视频分别创建评论采集任务，确认继续？`,
                    confirmText: "开始创建",
                  })
                  if (!ok) return
                }
                recrawlComments.mutate(selectedRows)
              }}
            >
              <MessageCircle />
              {recrawlComments.isPending ? "正在创建…" : "批量创建评论任务"}
            </Button>
            <BatchCommentDialog
              selectedWorks={selectedRows}
              onCreated={() => setSelectedAwemeIds([])}
            >
              <Button size="sm">
                <MessageCircle />
                批量发送评论
              </Button>
            </BatchCommentDialog>
          </>
        }
      />
    </div>
  )
}

function mediaStateLabel(row: DouyinWorkPublic) {
  const asset = row.media
  if (!asset) return "未下载"
  if (asset.status === "failed") return "下载失败"
  if (asset.status === "temporary") return "仅字幕（未保留视频）"
  if (asset.status !== "downloaded") return "下载中"
  return asset.storage_backend === "minio" ? "云端" : "本地"
}

// 报告 A12：CSV 里的「下载状态」列（与界面徽标文案区分开，表格里更易读）
function downloadStateText(row: DouyinWorkPublic) {
  const asset = row.media
  if (!asset) return "未下载"
  if (asset.status === "downloaded") return "已下载"
  if (asset.status === "failed") return "下载失败"
  if (asset.status === "queued") return "排队中"
  if (asset.status === "downloading") return "下载中"
  if (asset.status === "temporary") return "仅字幕"
  return asset.status
}

// 报告 A12：CSV 里的「存储后端」列
function storageBackendText(row: DouyinWorkPublic) {
  const backend = row.media?.storage_backend
  if (!backend) return "未下载"
  return storageBackendLabels[backend] ?? backend
}

function MediaStateBadge({
  row,
  onCover = false,
}: {
  row: DouyinWorkPublic
  onCover?: boolean
}) {
  const label = mediaStateLabel(row)
  if (onCover) {
    return (
      <Badge className="border-white/20 bg-black/35 text-white hover:bg-black/35">
        {label}
      </Badge>
    )
  }
  const variant =
    label === "未下载"
      ? "secondary"
      : label === "下载失败"
        ? "destructive"
        : "outline"
  return (
    <Badge variant={variant} className="shrink-0">
      {label}
    </Badge>
  )
}

function InlineStat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Heart
  label: string
  value: string
}) {
  return (
    <span className="flex items-center gap-1" title={label}>
      <Icon aria-hidden="true" className="size-3.5 text-muted-foreground" />
      <span className="font-semibold tabular-nums">{value}</span>
      <span className="sr-only">{label}</span>
    </span>
  )
}

function WorkActionButtons({
  row,
  task,
  retry,
  retranslate,
  onDownload,
  feedSearch,
  onPreview,
}: {
  row: DouyinWorkPublic
  task?: CrawlTaskPublic
  retry: (asset: DouyinMediaAssetPublic) => void
  retranslate: (asset: DouyinMediaAssetPublic) => void
  onDownload: (asset: DouyinMediaAssetPublic) => void
  feedSearch?: LibraryFeedSearch
  /**
   * 由所在行统一打开预览弹窗：整行只保留一个 VideoPreviewDialog 实例
   * （此前封面与操作列各挂一份，每行两个 Radix Dialog）。
   */
  onPreview: () => void
}) {
  const aweme = row.aweme
  const asset = row.media
  const active = task ? activeStatuses.has(task.status) : false
  // 报告 O10：字幕弹窗改为受控（原 SubtitleDialog 自持 open 状态，无法从「更多」菜单里打开）
  const [subtitleAsset, setSubtitleAsset] =
    useState<DouyinMediaAssetPublic | null>(null)
  const canPreview = Boolean(
    asset?.download_available || aweme.video_download_url,
  )
  const canRetry = Boolean(
    asset && (asset.status === "failed" || asset.subtitle?.status === "failed"),
  )
  return (
    <>
      {/* 报告 O10：只保留「预览」「下载」两个高频操作直接显示，其余收进「更多」菜单 */}
      {canPreview && (
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label={videoPreviewTriggerLabel(asset, aweme)}
          title={videoPreviewTriggerLabel(asset, aweme)}
          onClick={onPreview}
        >
          <Play />
        </Button>
      )}
      {asset?.download_available && (
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label="下载视频"
          onClick={() => onDownload(asset)}
        >
          <Download />
        </Button>
      )}
      {/* 复用 AwemeActions 的「更多」菜单渲染低频操作，避免同一行出现两个「更多」按钮 */}
      <AwemeActions taskId={aweme.task_id} aweme={aweme} active={active}>
        {asset && (
          <DropdownMenuItem onSelect={() => setSubtitleAsset(asset)}>
            <Captions />
            查看字幕
          </DropdownMenuItem>
        )}
        {asset?.download_available && (
          <DropdownMenuItem onSelect={() => retranslate(asset)}>
            <Languages />
            重新翻译字幕
          </DropdownMenuItem>
        )}
        {canRetry && asset && (
          <DropdownMenuItem onSelect={() => retry(asset)}>
            <RotateCcw />
            重试资源
          </DropdownMenuItem>
        )}
        <DropdownMenuItem asChild>
          <a
            href={getDouyinVideoUrl(aweme.aweme_id)}
            target="_blank"
            rel="noreferrer"
            aria-label="在抖音中打开视频"
          >
            <ExternalLink />
            在抖音中打开
          </a>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link
            to="/douyin/$taskId"
            params={{ taskId: aweme.task_id }}
            aria-label="进入任务"
          >
            <ExternalLink />
            进入任务
          </Link>
        </DropdownMenuItem>
        {asset?.download_available && feedSearch && (
          <DropdownMenuItem asChild>
            <Link
              to="/douyin-library/feed"
              search={{ ...feedSearch, start: `video-${aweme.aweme_id}` }}
              aria-label="沉浸播放"
            >
              <PlaySquare />
              沉浸播放
            </Link>
          </DropdownMenuItem>
        )}
      </AwemeActions>
      <Dialog
        open={subtitleAsset !== null}
        onOpenChange={(open) => {
          if (!open) setSubtitleAsset(null)
        }}
      >
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>字幕信息</DialogTitle>
            <DialogDescription>
              {aweme.title || aweme.aweme_id} · 作品{" "}
              {subtitleAsset?.aweme_id ?? aweme.aweme_id}
            </DialogDescription>
          </DialogHeader>
          {subtitleAsset && <SubtitlePanel asset={subtitleAsset} />}
        </DialogContent>
      </Dialog>
    </>
  )
}

export const VideoCard = memo(function VideoCard({
  row,
  task,
  onRetry,
  onRetranslate,
  onDownload,
  feedSearch,
  selected,
  onSelectedChange,
}: {
  row: DouyinWorkPublic
  task?: CrawlTaskPublic
  onRetry: (taskId: string, asset: DouyinMediaAssetPublic) => void
  onRetranslate: (taskId: string, asset: DouyinMediaAssetPublic) => void
  onDownload: (taskId: string, asset: DouyinMediaAssetPublic) => void
  feedSearch: LibraryFeedSearch
  selected: boolean
  onSelectedChange: (awemeId: string, checked: boolean) => void
}) {
  const aweme = row.aweme
  const asset = row.media
  const subtitle = asset?.subtitle
  const taskId = aweme.task_id
  const retry = useCallback(
    (target: DouyinMediaAssetPublic) => onRetry(taskId, target),
    [onRetry, taskId],
  )
  const retranslate = useCallback(
    (target: DouyinMediaAssetPublic) => onRetranslate(taskId, target),
    [onRetranslate, taskId],
  )
  const download = useCallback(
    (target: DouyinMediaAssetPublic) => onDownload(taskId, target),
    [onDownload, taskId],
  )
  const canPreview = Boolean(
    asset?.download_available || aweme.video_download_url,
  )
  const [previewOpen, setPreviewOpen] = useState(false)
  const openPreview = useCallback(() => setPreviewOpen(true), [])
  return (
    <>
      <Card className="group gap-0 overflow-hidden rounded-xl py-0 transition hover:-translate-y-0.5 hover:shadow-lg">
        <div className="relative aspect-video overflow-hidden bg-muted">
          <div className="absolute left-2 top-2 z-10 flex size-8 items-center justify-center rounded-md bg-background/90 shadow-sm backdrop-blur">
            <Checkbox
              aria-label={`选择视频 ${aweme.title || aweme.aweme_id}`}
              checked={selected}
              onCheckedChange={(checked) =>
                onSelectedChange(aweme.aweme_id, checked === true)
              }
            />
          </div>
          <CoverPlayTrigger
            taskId={aweme.task_id}
            aweme={aweme}
            asset={asset}
            onPlay={openPreview}
            imageClassName="h-full w-full object-cover transition duration-500 group-hover:scale-[1.03]"
            fallback={
              <div className="flex h-full items-center justify-center">
                <Film aria-hidden="true" className="size-12 opacity-25" />
              </div>
            }
            playIconClassName="size-5"
          />
          <div className="absolute inset-x-0 bottom-0 flex items-end justify-between bg-gradient-to-t from-black/75 to-transparent p-3 pt-10 text-white">
            {/* 报告 A16：发布时间改用相对时间（悬停看绝对时间），与表格视图一致 */}
            <span className="flex items-center gap-1 text-[11px]">
              发布
              <TimeAgo
                value={aweme.create_time ? aweme.create_time * 1000 : null}
                neverText="未知"
              />
            </span>
            <MediaStateBadge row={row} onCover />
          </div>
        </div>
        <CardContent className="space-y-2 p-2.5">
          <div>
            <h2 className="line-clamp-2 min-h-9 text-[13px] font-semibold leading-4.5">
              {aweme.title || aweme.aweme_id}
            </h2>
            <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
              <span className="truncate">{aweme.nickname || "匿名创作者"}</span>
              <SourceBadge
                sourceType={aweme.source_type}
                sourceName={aweme.source_name}
                sourceLabel={aweme.source_label}
                className="max-w-48 text-[10px]"
              />
            </div>
            {(row.tags?.length ?? 0) > 0 && (
              <div className="mt-1.5 flex min-h-5 flex-wrap gap-1">
                {(row.tags ?? []).slice(0, 2).map((tag) => (
                  <Badge key={tag.id} variant="outline" className="h-5 px-1.5">
                    #{tag.name}
                  </Badge>
                ))}
                {(row.tags?.length ?? 0) > 2 && (
                  <Badge variant="outline" className="h-5 px-1.5">
                    +{(row.tags?.length ?? 0) - 2}
                  </Badge>
                )}
              </div>
            )}
          </div>
          <div className="flex items-center justify-between rounded-lg bg-muted/45 px-2 py-1.5">
            <InlineStat
              icon={Heart}
              label="点赞"
              value={compact(aweme.liked_count)}
            />
            <InlineStat
              icon={MessageCircle}
              label="评论"
              value={compact(aweme.comment_count)}
            />
            <InlineStat
              icon={Star}
              label="收藏"
              value={compact(aweme.collected_count)}
            />
            <InlineStat
              icon={Share2}
              label="分享"
              value={compact(aweme.share_count)}
            />
            <InlineStat
              icon={Database}
              label="已存评论"
              value={compact(row.persisted_comment_count)}
            />
          </div>
          <details className="group">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-2 border-t pt-2 text-[11px] font-medium text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none [&::-webkit-details-marker]:hidden">
              <span>来源与处理状态</span>
              <ChevronDown
                aria-hidden="true"
                className="size-3.5 transition group-open:rotate-180"
              />
            </summary>
            <div className="flex min-w-0 flex-wrap items-center gap-1.5 pt-2">
              {task && (
                <TrackBadge
                  trackId={task.track_id}
                  trackName={task.track_name}
                  isDefault={task.track_is_default}
                  className="max-w-[45%]"
                />
              )}
              <Badge variant="outline" className="max-w-[58%] truncate">
                {task ? taskLabel(task) : "历史任务"}
              </Badge>
              <Badge variant="secondary" className="ml-auto shrink-0">
                {subtitle?.status === "completed" && (
                  <Captions aria-hidden="true" />
                )}
                {subtitleStatusLabel(subtitle?.status)}
              </Badge>
            </div>
          </details>
          <div className="flex flex-wrap items-center gap-1 border-t pt-2">
            <WorkActionButtons
              row={row}
              task={task}
              retry={retry}
              retranslate={retranslate}
              onDownload={download}
              feedSearch={feedSearch}
              onPreview={openPreview}
            />
          </div>
        </CardContent>
      </Card>
      {canPreview && (
        <VideoPreviewDialog
          taskId={taskId}
          asset={asset}
          aweme={aweme}
          open={previewOpen}
          onOpenChange={setPreviewOpen}
          hideTrigger
        />
      )}
    </>
  )
})

export const VideoRow = memo(function VideoRow({
  row,
  task,
  onRetry,
  onRetranslate,
  onDownload,
  feedSearch,
  selected,
  onSelectedChange,
}: {
  row: DouyinWorkPublic
  task?: CrawlTaskPublic
  onRetry: (taskId: string, asset: DouyinMediaAssetPublic) => void
  onRetranslate: (taskId: string, asset: DouyinMediaAssetPublic) => void
  onDownload: (taskId: string, asset: DouyinMediaAssetPublic) => void
  /** 报告 O12：横条视图也补齐「沉浸播放」入口 */
  feedSearch: LibraryFeedSearch
  selected: boolean
  onSelectedChange: (awemeId: string, checked: boolean) => void
}) {
  const aweme = row.aweme
  const title = aweme.title || aweme.aweme_id
  const taskId = aweme.task_id
  const retry = useCallback(
    (target: DouyinMediaAssetPublic) => onRetry(taskId, target),
    [onRetry, taskId],
  )
  const retranslate = useCallback(
    (target: DouyinMediaAssetPublic) => onRetranslate(taskId, target),
    [onRetranslate, taskId],
  )
  const download = useCallback(
    (target: DouyinMediaAssetPublic) => onDownload(taskId, target),
    [onDownload, taskId],
  )
  const canPreview = Boolean(
    row.media?.download_available || aweme.video_download_url,
  )
  const [previewOpen, setPreviewOpen] = useState(false)
  const openPreview = useCallback(() => setPreviewOpen(true), [])
  return (
    <>
      <Card>
        <CardContent className="flex items-center gap-3 p-3">
          <div className="flex size-9 shrink-0 items-center justify-center">
            <Checkbox
              aria-label={`选择视频 ${title}`}
              checked={selected}
              onCheckedChange={(checked) =>
                onSelectedChange(aweme.aweme_id, checked === true)
              }
            />
          </div>
          <div className="relative aspect-video w-28 shrink-0 overflow-hidden rounded-md bg-muted">
            <CoverPlayTrigger
              taskId={aweme.task_id}
              aweme={aweme}
              asset={row.media}
              onPlay={openPreview}
              imageClassName="h-full w-full object-cover"
              fallback={
                <div className="flex h-full items-center justify-center">
                  <Film aria-hidden="true" className="size-6 opacity-25" />
                </div>
              }
            />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h3 className="truncate text-sm font-medium" title={title}>
                {title}
              </h3>
              <MediaStateBadge row={row} />
            </div>
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              {aweme.nickname || "匿名创作者"} · 发布{" "}
              {formatUnix(aweme.create_time)}
              {aweme.source_label && ` · ${aweme.source_label}`}
            </p>
            <div className="mt-1.5 flex items-center gap-3">
              <InlineStat
                icon={Heart}
                label="点赞"
                value={compact(aweme.liked_count)}
              />
              <InlineStat
                icon={MessageCircle}
                label="评论"
                value={compact(aweme.comment_count)}
              />
              <InlineStat
                icon={Star}
                label="收藏"
                value={compact(aweme.collected_count)}
              />
              <InlineStat
                icon={Database}
                label="已存评论"
                value={compact(row.persisted_comment_count)}
              />
            </div>
          </div>
          <div className="hidden shrink-0 items-center gap-1.5 lg:flex">
            {task && (
              <TrackBadge
                trackId={task.track_id}
                trackName={task.track_name}
                isDefault={task.track_is_default}
                className="max-w-32"
              />
            )}
            <SourceBadge
              sourceType={aweme.source_type}
              sourceName={aweme.source_name}
              sourceLabel={aweme.source_label}
              className="max-w-48"
            />
            <Badge variant="secondary" className="shrink-0">
              {subtitleStatusLabel(row.media?.subtitle?.status)}
            </Badge>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <WorkActionButtons
              row={row}
              task={task}
              retry={retry}
              retranslate={retranslate}
              onDownload={download}
              feedSearch={feedSearch}
              onPreview={openPreview}
            />
          </div>
        </CardContent>
      </Card>
      {canPreview && (
        <VideoPreviewDialog
          taskId={taskId}
          asset={row.media}
          aweme={aweme}
          open={previewOpen}
          onOpenChange={setPreviewOpen}
          hideTrigger
        />
      )}
    </>
  )
})

/**
 * 报告 A4 / O8：首次加载骨架屏。
 *
 * 改造前这里是一行「正在加载视频资源…」文案，数据到达后整块 DOM 被替换，
 * 高度差会把下面的分页器顶得跳一下。骨架屏按当前视图模式铺设同构的占位块，
 * 表格视图保留完整表头与列宽，加载完成前后布局基本不动。
 */
function LibrarySkeleton({
  viewMode,
  isVisible,
  visibleCount,
}: {
  viewMode: ListViewMode
  /** 报告 A1：列可见性 */
  isVisible: (key: string) => boolean
  /** 报告 A1：当前可见列数（骨架屏占位行的 colSpan 要用它） */
  visibleCount: number
}) {
  if (viewMode === "cards") {
    return (
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-5">
        {Array.from({ length: 8 }, (_, index) => (
          <Skeleton
            key={`library-skeleton-card-${index}`}
            className="h-64 w-full rounded-xl"
          />
        ))}
      </div>
    )
  }
  if (viewMode === "rows") {
    return (
      <div className="space-y-2">
        {Array.from({ length: 8 }, (_, index) => (
          <Skeleton
            key={`library-skeleton-row-${index}`}
            className="h-24 w-full rounded-xl"
          />
        ))}
      </div>
    )
  }
  return (
    <Card className="overflow-hidden py-0">
      <CardContent className="p-0">
        <Table className="min-w-[900px]">
          <TableHeader>
            <TableRow>
              <TableHead className="w-12" />
              {/* 报告 A1：骨架屏表头要跟真实表格一样跟着列可见性走 */}
              {isVisible("work") && (
                <TableHead className="min-w-64">作品</TableHead>
              )}
              {isVisible("creator") && <TableHead>创作者</TableHead>}
              {isVisible("track") && <TableHead>赛道</TableHead>}
              {isVisible("source") && <TableHead>来源</TableHead>}
              {isVisible("liked") && (
                <TableHead className="text-right">点赞</TableHead>
              )}
              {isVisible("comment") && (
                <TableHead className="text-right">评论</TableHead>
              )}
              {isVisible("persisted") && (
                <TableHead className="text-right">已存评论</TableHead>
              )}
              {isVisible("published") && <TableHead>发布时间</TableHead>}
              {isVisible("download") && <TableHead>下载</TableHead>}
              {isVisible("subtitle") && <TableHead>字幕</TableHead>}
              <TableHead className="text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Array.from({ length: 8 }, (_, index) => (
              <TableRow key={`library-skeleton-table-${index}`}>
                {/* 报告 A1：colSpan 必须跟着可见列数走，写死数字会在隐藏列后错位 */}
                <TableCell colSpan={visibleCount}>
                  <Skeleton className="h-8 w-full" />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function VideoTable({
  rows,
  taskMap,
  onRetry,
  onRetranslate,
  onDownload,
  feedSearch,
  selectedAwemeSet,
  allPageSelected,
  somePageSelected,
  onTogglePage,
  onToggleRow,
  onRecrawlComments,
  highlightedIds,
  isVisible,
}: {
  rows: DouyinWorkPublic[]
  taskMap: Map<string, CrawlTaskPublic>
  onRetry: (taskId: string, asset: DouyinMediaAssetPublic) => void
  onRetranslate: (taskId: string, asset: DouyinMediaAssetPublic) => void
  onDownload: (taskId: string, asset: DouyinMediaAssetPublic) => void
  feedSearch: LibraryFeedSearch
  selectedAwemeSet: Set<string>
  allPageSelected: boolean
  somePageSelected: boolean
  onTogglePage: (checked: boolean) => void
  onToggleRow: (awemeId: string, checked: boolean) => void
  /** 报告 A7：单行「加入评论采集」 */
  onRecrawlComments: (row: DouyinWorkPublic) => void
  /** 报告 A6：轮询后数据变化的行 id */
  highlightedIds: Set<string>
  /** 报告 A1：列可见性（表头与每一行单元格都要用它包一层） */
  isVisible: (key: string) => boolean
}) {
  // 单页 32 行、每行上百个节点：整页渲染在开发模式下能飙到一两秒。
  // 这里沿用任务详情表的虚拟滚动做法，只渲染可视区的行。
  const scrollRef = useRef<HTMLDivElement>(null)
  const virtualizeActive = rows.length > LIBRARY_VIRTUALIZE_THRESHOLD
  const { virtualItems, totalSize } = useVirtualRows({
    count: rows.length,
    scrollRef,
    estimateSize: LIBRARY_ROW_ESTIMATE_SIZE,
    // 行高固定、滚动条由容器接管，上下各留 4 行足够避免快速滚动白屏；
    // 默认 10 行会渲染掉大半个列表，省不下来。
    overscan: 4,
    enabled: virtualizeActive,
  })
  const virtualRows = virtualizeActive
    ? virtualItems.map((item) => rows[item.index])
    : rows
  const paddingTop =
    virtualizeActive && virtualItems.length ? virtualItems[0].start : 0
  const paddingBottom =
    virtualizeActive && virtualItems.length
      ? totalSize - virtualItems[virtualItems.length - 1].end
      : 0
  return (
    <Card>
      <CardContent className="p-0">
        {/* 报告 A21：12 列在窄屏会被挤爆，给表格一个最小宽度，外层交给横向滚动而不是压缩列宽 */}
        <div
          ref={scrollRef}
          className={
            virtualizeActive ? "max-h-[70vh] overflow-auto" : "overflow-x-auto"
          }
        >
          <Table className="min-w-[900px]">
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">
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
                      onTogglePage(checked === true)
                    }
                  />
                </TableHead>
                {/* 报告 A1：表头与行内单元格必须成对包 isVisible，漏一处整列错位 */}
                {isVisible("work") && (
                  <TableHead className="min-w-64">作品</TableHead>
                )}
                {isVisible("creator") && <TableHead>创作者</TableHead>}
                {isVisible("track") && <TableHead>赛道</TableHead>}
                {isVisible("source") && <TableHead>来源</TableHead>}
                {isVisible("liked") && (
                  <TableHead className="text-right">点赞</TableHead>
                )}
                {isVisible("comment") && (
                  <TableHead className="text-right">评论</TableHead>
                )}
                {isVisible("persisted") && (
                  <TableHead className="text-right">已存评论</TableHead>
                )}
                {isVisible("published") && <TableHead>发布时间</TableHead>}
                {isVisible("download") && <TableHead>下载</TableHead>}
                {isVisible("subtitle") && <TableHead>字幕</TableHead>}
                {/* 报告 A8：操作列冻结在右侧 */}
                <TableHead className="sticky right-0 z-10 bg-background/95 text-right backdrop-blur">
                  操作
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {virtualizeActive && <tr style={{ height: paddingTop }} />}
              {virtualRows.map((row) => (
                <VideoTableRow
                  key={row.aweme.id}
                  row={row}
                  task={taskMap.get(row.aweme.task_id)}
                  onRetry={onRetry}
                  onRetranslate={onRetranslate}
                  onDownload={onDownload}
                  feedSearch={feedSearch}
                  selected={selectedAwemeSet.has(row.aweme.aweme_id)}
                  onToggleRow={onToggleRow}
                  onRecrawlComments={onRecrawlComments}
                  highlighted={highlightedIds.has(row.aweme.id)}
                  isVisible={isVisible}
                />
              ))}
              {virtualizeActive && <tr style={{ height: paddingBottom }} />}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

export const VideoTableRow = memo(function VideoTableRow({
  row,
  task,
  onRetry,
  onRetranslate,
  onDownload,
  feedSearch,
  selected,
  onToggleRow,
  onRecrawlComments,
  highlighted,
  isVisible,
}: {
  row: DouyinWorkPublic
  task?: CrawlTaskPublic
  onRetry: (taskId: string, asset: DouyinMediaAssetPublic) => void
  onRetranslate: (taskId: string, asset: DouyinMediaAssetPublic) => void
  onDownload: (taskId: string, asset: DouyinMediaAssetPublic) => void
  feedSearch: LibraryFeedSearch
  selected: boolean
  onToggleRow: (awemeId: string, checked: boolean) => void
  onRecrawlComments: (row: DouyinWorkPublic) => void
  highlighted: boolean
  /** 报告 A1：列可见性 */
  isVisible: (key: string) => boolean
}) {
  const aweme = row.aweme
  const asset = row.media
  const title = aweme.title || aweme.aweme_id
  const [, copyAwemeId] = useCopyToClipboard()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const canPreview = Boolean(
    asset?.download_available || aweme.video_download_url,
  )
  const canRetry = Boolean(
    asset && (asset.status === "failed" || asset.subtitle?.status === "failed"),
  )
  const taskId = aweme.task_id
  const retry = useCallback(
    (target: DouyinMediaAssetPublic) => onRetry(taskId, target),
    [onRetry, taskId],
  )
  const retranslate = useCallback(
    (target: DouyinMediaAssetPublic) => onRetranslate(taskId, target),
    [onRetranslate, taskId],
  )
  const download = useCallback(
    (target: DouyinMediaAssetPublic) => onDownload(taskId, target),
    [onDownload, taskId],
  )
  const [previewOpen, setPreviewOpen] = useState(false)
  const openPreview = useCallback(() => setPreviewOpen(true), [])
  return (
    <>
      <RowContextMenu
        label={title}
        items={[
          {
            label: "复制作品 ID",
            icon: Copy,
            onSelect: () => {
              void copyAwemeId(aweme.aweme_id).then((ok) => {
                if (ok) showSuccessToast("作品 ID 已复制")
                else showErrorToast("复制失败，请手动复制")
              })
            },
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
            // 整行只有一个预览弹窗实例，右键菜单直接开它
            label: "预览视频",
            icon: Play,
            disabled: !canPreview,
            onSelect: openPreview,
          },
          {
            label: "下载",
            icon: Download,
            disabled: !asset?.download_available,
            onSelect: () => {
              if (asset) download(asset)
            },
          },
          {
            separatorBefore: true,
            label: "重试",
            icon: RotateCcw,
            disabled: !canRetry,
            onSelect: () => {
              if (asset) retry(asset)
            },
          },
          {
            separatorBefore: true,
            label: "加入评论采集",
            icon: MessageCircle,
            onSelect: () => onRecrawlComments(row),
          },
        ]}
      >
        <TableRow className={highlighted ? "row-highlight" : undefined}>
          <TableCell>
            <Checkbox
              aria-label={`选择视频 ${title}`}
              checked={selected}
              onCheckedChange={(checked) =>
                onToggleRow(aweme.aweme_id, checked === true)
              }
            />
          </TableCell>
          {isVisible("work") && (
            <TableCell>
              <div className="flex items-center gap-2.5">
                <div className="relative aspect-video w-16 shrink-0 overflow-hidden rounded bg-muted">
                  <CoverPlayTrigger
                    taskId={aweme.task_id}
                    aweme={aweme}
                    asset={asset}
                    imageClassName="h-full w-full object-cover"
                    fallback={
                      <div className="flex h-full items-center justify-center">
                        <Film
                          aria-hidden="true"
                          className="size-5 opacity-25"
                        />
                      </div>
                    }
                  />
                </div>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="line-clamp-2 max-w-56 cursor-default text-sm font-medium leading-5">
                      {title}
                    </span>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-sm">{title}</TooltipContent>
                </Tooltip>
              </div>
            </TableCell>
          )}
          {isVisible("creator") && (
            <TableCell className="max-w-28 truncate text-xs">
              {aweme.nickname || "匿名创作者"}
            </TableCell>
          )}
          {isVisible("track") && (
            <TableCell>
              {task ? (
                <TrackBadge
                  trackId={task.track_id}
                  trackName={task.track_name}
                  isDefault={task.track_is_default}
                  className="max-w-32"
                />
              ) : (
                <span className="text-xs text-muted-foreground">-</span>
              )}
            </TableCell>
          )}
          {isVisible("source") && (
            <TableCell>
              <SourceBadge
                sourceType={aweme.source_type}
                sourceName={aweme.source_name}
                sourceLabel={aweme.source_label}
                className="max-w-48"
              />
            </TableCell>
          )}
          {isVisible("liked") && (
            <TableCell className="text-right tabular-nums">
              {compact(aweme.liked_count)}
            </TableCell>
          )}
          {isVisible("comment") && (
            <TableCell className="text-right tabular-nums">
              {compact(aweme.comment_count)}
            </TableCell>
          )}
          {isVisible("persisted") && (
            <TableCell className="text-right tabular-nums">
              {compact(row.persisted_comment_count)}
            </TableCell>
          )}
          {isVisible("published") && (
            <TableCell className="whitespace-nowrap text-xs">
              {/* 报告 A16：时间点用相对时间展示（悬停看绝对时间） */}
              <TimeAgo
                value={aweme.create_time ? aweme.create_time * 1000 : null}
                neverText="未知"
              />
            </TableCell>
          )}
          {isVisible("download") && (
            <TableCell>
              <MediaStateBadge row={row} />
            </TableCell>
          )}
          {isVisible("subtitle") && (
            <TableCell className="whitespace-nowrap text-xs">
              {subtitleStatusLabel(asset?.subtitle?.status)}
            </TableCell>
          )}
          {/* 报告 A8：操作列冻结在右侧 */}
          <TableCell className="sticky right-0 bg-background/95 backdrop-blur">
            {/* 报告 O12：表格视图与卡片/横条视图共用同一套操作入口 */}
            <div className="flex items-center justify-end gap-1">
              <WorkActionButtons
                row={row}
                task={task}
                retry={retry}
                retranslate={retranslate}
                onDownload={download}
                feedSearch={feedSearch}
                onPreview={openPreview}
              />
            </div>
          </TableCell>
        </TableRow>
      </RowContextMenu>
      {canPreview && (
        <VideoPreviewDialog
          taskId={taskId}
          asset={asset}
          aweme={aweme}
          open={previewOpen}
          onOpenChange={setPreviewOpen}
          hideTrigger
        />
      )}
    </>
  )
})

function taskLabel(task: CrawlTaskPublic) {
  const request = task.request as { keywords?: string[]; video_ids?: string[] }
  const target = request.keywords?.[0] || request.video_ids?.[0]
  return target
    ? `${task.crawl_type} · ${target}`
    : `${task.crawl_type} · ${task.id.slice(0, 8)}`
}

// 格式化器必须在模块级构造：`new Intl.*` 单次约毫秒级，放在渲染函数里
// 会在每次列表刷新时被调用成百上千次（每张卡片 5 个数字 + 时间），
// 直接把主线程堵住几百毫秒到一秒以上。
const DATE_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  dateStyle: "medium",
})
const DATE_TIME_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  dateStyle: "medium",
  timeStyle: "short",
})
const COMPACT_FORMATTER = new Intl.NumberFormat("zh-CN", {
  notation: "compact",
  maximumFractionDigits: 1,
})

function formatUnix(value: number | null) {
  if (!value) return "未知"
  return DATE_FORMATTER.format(new Date(value * 1_000))
}

function formatDateTimeText(value: Date) {
  return DATE_TIME_FORMATTER.format(value)
}

function subtitleStatusLabel(status: string | undefined) {
  const labels: Record<string, string> = {
    pending: "字幕排队",
    running: "字幕处理中",
    completed: "字幕完成",
    failed: "字幕失败",
  }
  return status ? (labels[status] ?? status) : "无字幕"
}

function compact(value: number) {
  return COMPACT_FORMATTER.format(value)
}
