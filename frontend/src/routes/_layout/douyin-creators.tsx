import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  CloudDownload,
  Download,
  Film,
  FolderPlus,
  History,
  ListFilter,
  LoaderCircle,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  UserRoundSearch,
  Users,
} from "lucide-react"
import {
  type FormEvent,
  type ReactNode,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"

import {
  type ApiError,
  DouyinAccountsService,
  type DouyinCreatorPublic,
  type DouyinCreatorStatus,
  DouyinCreatorsService,
} from "@/client"
import { BulkActionBar } from "@/components/Common/BulkActionBar"
import { confirmDialog } from "@/components/Common/confirm-dialog"
import { EmptyState } from "@/components/Common/EmptyState"
import { FilterChips } from "@/components/Common/FilterChips"
import { FilterPresetBar } from "@/components/Common/FilterPresetBar"
import {
  LoadModeToggle,
  usePersistentLoadMode,
} from "@/components/Common/LoadModeToggle"
import { Pager } from "@/components/Common/Pager"
import { PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { RefreshIndicator } from "@/components/Common/RefreshIndicator"
import { ScrollLoader } from "@/components/Common/ScrollLoader"
import { TimeAgo } from "@/components/Common/TimeAgo"
import {
  type ListViewMode,
  usePersistentViewMode,
  ViewModeToggle,
} from "@/components/Common/ViewModeToggle"
import { AssignCategoryDialog } from "@/components/Douyin/AssignCategoryDialog"
import {
  allCategoriesValue,
  CategorySelect,
  categoryDisplayName,
  useCategoryCatalog,
} from "@/components/Douyin/CategorySelect"
import { CreatorAvatar } from "@/components/Douyin/CreatorAvatar"
import { creatorNameLabel } from "@/components/Douyin/presentation"
import {
  allTracksValue,
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
  DialogFooter,
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
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import { useHighlightedRows } from "@/hooks/useHighlightedRows"
import { useListFeed } from "@/hooks/useListFeed"
import { useVirtualRows, VIRTUALIZE_THRESHOLD } from "@/hooks/useVirtualRows"
import { downloadCsv } from "@/lib/csv"
// 报告 O4：筛选上 URL，用这两个纯函数做「去默认值 / 安全取值」
import {
  compactSearch,
  readEnumParam,
  readStringParam,
} from "@/lib/search-params"
import { formatDateTime } from "@/lib/time"
import { cn } from "@/lib/utils"
import { handleError } from "@/utils"

// 报告 O4：状态 / 启用状态 / 排序都是枚举，白名单用于挡住手改 URL 传进来的脏值
const CREATOR_STATUS_VALUES = [
  "all",
  "unprocessed",
  "active",
  "crawled",
  "failed",
] as const
const CREATOR_ENABLED_VALUES = ["all", "true", "false"] as const
const CREATOR_SORT_VALUES = [
  "last_crawled_at:desc",
  "created_at:desc",
  "nickname:asc",
  "task_count:desc",
  "aweme_count:desc",
  "status:asc",
] as const
// 排序默认值：等于它就不写进 URL，保证未筛选时地址栏就是 /douyin-creators
const defaultCreatorSort = "last_crawled_at:desc"
/** 达人列表每批拉取条数：滚动加载时按批续拉，分页模式下即每页条数 */
const creatorPageSize = 60
/** 「刷新达人信息」每批同步多少个主页（后端单批上限 200，这里留出余量） */
const creatorSyncBatchSize = 100

type CreatorSortValue = (typeof CREATOR_SORT_VALUES)[number]

// 报告 O4：URL 查询参数类型。属性一律声明为可选（`?`）——
// 写成 `x: T | undefined` 时属性键是必填的，TanStack Router 会据此要求
// 所有 <Link to="/douyin-creators"> 显式传 search，navigate 也会报缺属性。
type CreatorSearch = {
  q?: string
  track?: string
  /** 内容分类筛选（大类会自动带出它的全部子类） */
  category?: string
  // 允许 "all"：state 的默认值就是 "all"，navigate 时会把该值原样写回
  status?: DouyinCreatorStatus | "all"
  enabled?: "all" | "true" | "false"
  sort?: CreatorSortValue
}

export const Route = createFileRoute("/_layout/douyin-creators")({
  // 报告 O4：筛选上 URL —— 刷新 / 深链 / 分享链接都能还原搜索、赛道、状态、启用状态、排序
  validateSearch: (search: Record<string, unknown>): CreatorSearch => ({
    q: readStringParam(search, "q"),
    track: readStringParam(search, "track"),
    category: readStringParam(search, "category"),
    status: readEnumParam(search, "status", CREATOR_STATUS_VALUES),
    enabled: readEnumParam(search, "enabled", CREATOR_ENABLED_VALUES),
    sort: readEnumParam(search, "sort", CREATOR_SORT_VALUES),
  }),
  component: DouyinCreatorDirectory,
  head: () => ({ meta: [{ title: "达人列表 - 灵感采集台" }] }),
})

// 已知截断：接口按 limit 截断返回，界面仅展示前 N 位达人（文案已提示）。
// 后续应改为服务端分页（响应中的 count 已是全量，可直接做分页游标 / offset）。
const statusLabels: Record<DouyinCreatorStatus, string> = {
  unprocessed: "未爬取",
  active: "进行中",
  crawled: "已爬取",
  failed: "需要重试",
}

// 卡片视图的响应式网格。虚拟滚动按「一行 N 个」切块，N 必须与这里的断点一致，
// 否则窄屏会多出空列、宽屏会白占一行。
const creatorCardGridClass =
  "grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"

// 与上面的 Tailwind 断点一一对应（sm 640 / xl 1280 / 2xl 1536）
const creatorGridBreakpoints = [
  { query: "(min-width: 1536px)", columns: 4 },
  { query: "(min-width: 1280px)", columns: 3 },
  { query: "(min-width: 640px)", columns: 2 },
] as const

/** 当前视口下卡片网格的列数，供虚拟滚动决定每行放几位达人 */
function useCreatorGridColumns() {
  const [columns, setColumns] = useState(1)
  useEffect(() => {
    const lists = creatorGridBreakpoints.map((item) =>
      window.matchMedia(item.query),
    )
    const update = () =>
      setColumns(
        creatorGridBreakpoints.find((_, index) => lists[index].matches)
          ?.columns ?? 1,
      )
    update()
    for (const list of lists) list.addEventListener("change", update)
    return () => {
      for (const list of lists) list.removeEventListener("change", update)
    }
  }, [])
  return columns
}

function DouyinCreatorDirectory() {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  // 报告 O4：初值从 URL 取，于是刷新 / 深链 / 分享链接都能还原筛选
  const urlSearch = Route.useSearch()
  const navigate = Route.useNavigate()
  const [trackId, setTrackId] = useState(urlSearch.track ?? allTracksValue)
  const [search, setSearch] = useState(urlSearch.q ?? "")
  const [categoryId, setCategoryId] = useState(
    urlSearch.category ?? allCategoriesValue,
  )
  // 输入框即时回显，查询用延迟值，避免每次按键都触发一次列表请求
  const deferredSearch = useDeferredValue(search)
  const [status, setStatus] = useState<DouyinCreatorStatus | "all">(
    urlSearch.status ?? "all",
  )
  const [enabled, setEnabled] = useState<"all" | "true" | "false">(
    urlSearch.enabled ?? "all",
  )
  // 排序刻意保持 string：Select 的 onValueChange 给的是 string，收窄成字面量联合会让 setSort 报类型错
  const [sort, setSort] = useState<string>(urlSearch.sort ?? defaultCreatorSort)
  // 报告 O4：筛选变化时把已生效的筛选写回 URL。
  // 依赖只放筛选 state 与 navigate —— 不能放 urlSearch 对象，否则每次导航都触发本 effect 造成死循环。
  // 用 replace: true 是刻意取舍：刷新 / 分享 / 深链 / 收藏都能还原筛选，
  // 而浏览器「后退」回到上一个页面而不是上一条筛选；不用 replace 的话改十次筛选
  // 就要按十次后退才能离开本页。
  useEffect(() => {
    void navigate({
      to: "/douyin-creators",
      replace: true,
      search: compactSearch(
        {
          q: search.trim() || undefined,
          track: trackId === allTracksValue ? undefined : trackId,
          category: categoryId === allCategoriesValue ? undefined : categoryId,
          status,
          enabled,
          // state 刻意保持 string（Select 的 onValueChange 回传 string），
          // 这里收窄到排序白名单联合类型，与 CreatorSearch.sort 对齐
          sort: sort as CreatorSortValue,
        },
        { status: "all", enabled: "all", sort: defaultCreatorSort },
      ),
    })
  }, [search, trackId, categoryId, status, enabled, sort, navigate])
  // 报告 A14：自动刷新开关，控制列表轮询间隔（默认保持原有 10 秒轮询）
  // 用 Set 存储选中项，把 O(n) 的 includes 判断换成 O(1) 的 has
  const [selected, setSelected] = useState<Set<string>>(new Set())
  // 批量归类弹窗的开关：归类对象是「当前选中的达人」
  const [assignCategoryOpen, setAssignCategoryOpen] = useState(false)
  const [viewMode, setViewMode] = usePersistentViewMode("douyin-creators-view")
  const tracksQuery = useTrackCatalog()
  // 内容分类目录：筛选下拉与 chips 文案共用同一份缓存
  const categoriesQuery = useCategoryCatalog()
  const selectedTrack = tracksQuery.data?.data.find(
    (track) => track.id === trackId,
  )
  const [sortBy, sortOrder] = sort.split(":") as [
    (
      | "nickname"
      | "status"
      | "task_count"
      | "aweme_count"
      | "last_crawled_at"
      | "created_at"
      | "follower_count"
      | "aweme_total_count"
      | "profile_synced_at"
    ),
    "asc" | "desc",
  ]
  // 加载方式：默认滚动加载（达人可能有成百上千位，翻页体验差）
  const [loadMode, changeLoadMode] = usePersistentLoadMode(
    "douyin-creators-load-mode",
  )
  const [page, setPage] = useState(0)
  const creatorsFeed = useListFeed<DouyinCreatorPublic>({
    queryKey: [
      "douyin-creators",
      trackId,
      categoryId,
      deferredSearch,
      status,
      enabled,
      sort,
    ],
    pageSize: creatorPageSize,
    mode: loadMode,
    page,
    fetchPage: (skip, limit) =>
      DouyinCreatorsService.listCreators({
        trackId: trackId && trackId !== allTracksValue ? trackId : undefined,
        categoryId: categoryId === allCategoriesValue ? undefined : categoryId,
        search: deferredSearch.trim() || undefined,
        status: status === "all" ? undefined : status,
        enabled: enabled === "all" ? undefined : enabled === "true",
        sortBy,
        sortOrder,
        skip,
        limit,
      }),
    getKey: (item) => item.id,
    // 达人是静态资产，不做轮询：需要在达人目录里点「刷新」或重进页面
  })
  // 概览统计与主列表拉的是同一份达人数据（仅筛选条件不同），属于重复请求。
  // 暂不删除：指标口径依赖全量 limit:500 的样本，与分页列表的口径不同。
  // 已加 staleTime 降低重复拉取频率；后续应改由后端提供聚合统计接口。
  const overviewQuery = useQuery({
    queryKey: ["douyin-creators-overview", trackId, enabled],
    queryFn: () =>
      DouyinCreatorsService.listCreators({
        trackId: trackId && trackId !== allTracksValue ? trackId : undefined,
        enabled: enabled === "all" ? undefined : enabled === "true",
        limit: 500,
      }),
    placeholderData: (previous) => previous,
    staleTime: 30_000,
  })
  const creators = creatorsFeed.rows
  const allRows = overviewQuery.data?.data ?? []
  // 报告 A6：轮询刷新后，状态或最近爬取时间发生变化的达人卡片短暂高亮
  const highlighted = useHighlightedRows(
    creators,
    (item) => item.id,
    (item) => `${item.status}:${item.last_crawled_at ?? ""}`,
  )
  const metrics = useMemo(
    () => ({
      total: overviewQuery.data?.count ?? 0,
      unprocessed: allRows.filter((item) => item.status === "unprocessed")
        .length,
      active: allRows.filter((item) => item.status === "active").length,
      crawled: allRows.filter((item) => item.status === "crawled").length,
      failed: allRows.filter((item) => item.status === "failed").length,
    }),
    [allRows, overviewQuery.data?.count],
  )
  // 「本页全选」只覆盖当前页的可勾选达人（占位达人无真实标识，无法建任务，排除在外）
  const selectableIds = useMemo(
    () =>
      creators.filter((item) => !item.is_placeholder).map((item) => item.id),
    [creators],
  )
  const allSelected =
    selectableIds.length > 0 && selectableIds.every((id) => selected.has(id))
  // 报告 O19：一次加载 200 位达人，超过阈值后只渲染可视区。
  // 三种视图渲染的都是 CreatorCard，所以按「一行 N 个」切成组，对组做行级虚拟滚动——
  // 组内仍是原来的响应式网格，布局不变；短列表完全走原路径。
  const scrollRef = useRef<HTMLDivElement>(null)
  const gridColumns = useCreatorGridColumns()
  const columnsPerRow = viewMode === "cards" ? gridColumns : 1
  const creatorGroups = useMemo(() => {
    const groups: DouyinCreatorPublic[][] = []
    for (let index = 0; index < creators.length; index += columnsPerRow) {
      groups.push(creators.slice(index, index + columnsPerRow))
    }
    return groups
  }, [creators, columnsPerRow])
  const virtualize = creators.length > VIRTUALIZE_THRESHOLD
  const virtualizer = useVirtualRows({
    count: creatorGroups.length,
    scrollRef,
    // 估算值只影响未测量前的滚动条长度，挂载后由 measureElement 校正
    estimateSize: viewMode === "cards" ? 200 : 96,
    enabled: virtualize,
  })
  const { virtualItems, totalSize } = virtualizer
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["douyin-creators"] }),
      queryClient.invalidateQueries({
        queryKey: ["douyin-creators-overview"],
      }),
    ])
  }
  const historySync = useMutation({
    mutationFn: () => DouyinCreatorsService.syncHistoricalCreators(),
    onSuccess: async (result) => {
      showSuccessToast(
        `已扫描 ${result.task_count} 个任务，新增 ${result.created_count} 位达人、${result.binding_count} 个绑定`,
      )
      await invalidate()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  // 「刷新达人信息」：分批同步主页基础信息（粉丝数 / 作品数 / 签名 / 头像等），
  // 只补从未同步过的达人；每批同步完更新进度，直到没有待补的为止。
  const [profileSyncProgress, setProfileSyncProgress] = useState<{
    synced: number
    failed: number
    remaining: number
  } | null>(null)
  const profileSync = useMutation({
    mutationFn: async () => {
      let synced = 0
      let failed = 0
      let remaining = 0
      setProfileSyncProgress({ synced, failed, remaining })
      // 硬上限兜底：避免后端异常时前端无限循环
      for (let round = 0; round < 60; round += 1) {
        const result = await DouyinCreatorsService.syncCreatorProfiles({
          requestBody: {
            creator_ids: [],
            limit: creatorSyncBatchSize,
            only_missing: true,
          },
        })
        synced += result.synced_count
        failed += result.failed_count
        remaining = result.remaining_count
        setProfileSyncProgress({ synced, failed, remaining })
        if (
          remaining === 0 ||
          result.synced_count + result.failed_count === 0
        ) {
          break
        }
      }
      return { synced, failed }
    },
    onSuccess: async ({ synced, failed }) => {
      showSuccessToast(
        failed
          ? `已同步 ${synced} 位达人信息，${failed} 位失败（可稍后重试）`
          : `已同步 ${synced} 位达人的主页信息`,
      )
      setProfileSyncProgress(null)
      await invalidate()
    },
    onError: (error) => {
      setProfileSyncProgress(null)
      handleError.call(showErrorToast, error as ApiError)
    },
  })
  const awemeSync = useMutation({
    mutationFn: () => DouyinCreatorsService.syncCreatorsFromAwemes(),
    onSuccess: async (result) => {
      showSuccessToast(
        `已聚合 ${result.total_count} 位达人，导入 ${result.created_count} 位（已存在 ${result.existing_count} 位）`,
      )
      await invalidate()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const toggle = useMutation({
    mutationFn: (item: DouyinCreatorPublic) =>
      DouyinCreatorsService.editCreator({
        creatorId: item.id,
        requestBody: { enabled: !item.enabled },
      }),
    onSuccess: invalidate,
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const remove = useMutation({
    mutationFn: (id: string) =>
      DouyinCreatorsService.deleteCreator({ creatorId: id }),
    onSuccess: async () => {
      showSuccessToast("达人已删除，历史任务和作品未受影响")
      await invalidate()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const bulkRemove = useMutation({
    mutationFn: (ids: string[]) =>
      DouyinCreatorsService.bulkDeleteCreators({ requestBody: { ids } }),
    onSuccess: async () => {
      showSuccessToast(`已删除 ${selected.size} 位达人，历史数据已保留`)
      setSelected(new Set())
      await invalidate()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  // 空结果是不是被筛选条件缩掉的：决定空态给「清除筛选」还是「同步历史任务」
  const narrowedByFilter =
    Boolean(search.trim()) ||
    status !== "all" ||
    enabled !== "all" ||
    categoryId !== allCategoriesValue
  const clearFilters = () => {
    setSearch("")
    setTrackId(allTracksValue)
    setCategoryId(allCategoriesValue)
    setStatus("all")
    setEnabled("all")
    setSelected(new Set())
  }
  // 原路径与虚拟路径共用同一份卡片渲染，避免两处 props 漂移
  const renderCreator = (creator: DouyinCreatorPublic) => (
    <CreatorCard
      key={creator.id}
      creator={creator}
      viewMode={viewMode}
      highlighted={highlighted.has(creator.id)}
      selected={selected.has(creator.id)}
      onToggleSelect={(checked) =>
        setSelected((current) => {
          const next = new Set(current)
          if (checked) next.add(creator.id)
          else next.delete(creator.id)
          return next
        })
      }
      onToggle={toggle.mutate}
      onRemove={remove.mutate}
      onSaved={invalidate}
    />
  )
  const listWrapperClass =
    viewMode === "cards"
      ? creatorCardGridClass
      : viewMode === "rows"
        ? "space-y-2"
        : "overflow-hidden rounded-xl border"
  // 虚拟滚动时每组内部的排布：卡片铺网格，横条 / 表格每组只有一位达人，只需补组间距
  const virtualGroupClass =
    viewMode === "cards"
      ? cn(creatorCardGridClass, "pb-3")
      : viewMode === "rows"
        ? "pb-2"
        : "border-b last:border-b-0"

  return (
    <div className="page-stack">
      <PageHero
        compact
        title="达人列表"
        actions={
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            <span className="mr-1 whitespace-nowrap text-xs text-muted-foreground">
              总数 <strong className="text-foreground">{metrics.total}</strong>{" "}
              · 未爬取{" "}
              <strong className="text-foreground">{metrics.unprocessed}</strong>{" "}
              · 进行中{" "}
              <strong className="text-foreground">{metrics.active}</strong> ·
              已爬取{" "}
              <strong className="text-foreground">{metrics.crawled}</strong> ·
              重试 <strong className="text-foreground">{metrics.failed}</strong>
            </span>
            <Button
              size="sm"
              variant="outline"
              disabled={awemeSync.isPending}
              onClick={async () => {
                // 报告 O15：改用统一确认框
                const ok = await confirmDialog({
                  title: "从历史作品同步达人名单？",
                  description:
                    "带真实标识的新作品直接导入正式达人，仅含脱敏数据的历史作品导入为“待补全”占位达人。",
                  confirmText: "开始同步",
                })
                if (!ok) return
                awemeSync.mutate()
              }}
            >
              <CloudDownload
                className={awemeSync.isPending ? "animate-spin" : ""}
              />
              从历史作品同步
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={historySync.isPending}
              onClick={() => historySync.mutate()}
            >
              <History
                className={historySync.isPending ? "animate-spin" : ""}
              />
              同步历史任务
            </Button>
            {/* 报告 A12：导出当前页 / 已选中的达人明细（全量导出走后端流式接口） */}
            <Button
              size="sm"
              variant="outline"
              disabled={!creators.length}
              onClick={() => {
                const rows = selected.size
                  ? creators.filter((item) => selected.has(item.id))
                  : creators
                downloadCsv("达人列表", rows, [
                  { header: "达人 ID", value: (row) => row.id },
                  { header: "昵称", value: (row) => row.nickname },
                  { header: "作品数", value: (row) => row.aweme_count },
                  { header: "任务数", value: (row) => row.task_count },
                  { header: "状态", value: (row) => statusLabels[row.status] },
                  {
                    header: "启用状态",
                    value: (row) => (row.enabled ? "已启用" : "已停用"),
                  },
                  {
                    header: "最近爬取时间",
                    value: (row) =>
                      formatDateTime(row.last_crawled_at, {
                        fallback: "从未",
                      }),
                  },
                ])
              }}
            >
              <Download />
              导出{selected.size ? "选中" : "本页"}
            </Button>
            <CreateCreatorsDialog
              initialTrackId={trackId}
              onCreated={invalidate}
            />
          </div>
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-64 flex-[2]">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索达人昵称或备注"
              aria-label="搜索达人昵称或备注"
              className="h-9 pl-9"
            />
          </div>
          <TrackSelect
            value={trackId}
            onValueChange={(value) => {
              setTrackId(value)
              setSelected(new Set())
            }}
            ariaLabel="按赛道筛选达人"
            includeAll
            allowDisabled
            className="h-9 min-w-40 flex-1"
          />
          {/* 内容分类筛选：选大类会自动带出它全部子类归类的达人 */}
          <CategorySelect
            value={categoryId}
            onValueChange={(value) => {
              setCategoryId(value)
              setSelected(new Set())
              setPage(0)
            }}
            includeAll
            ariaLabel="按内容分类筛选达人"
            className="h-9 min-w-36"
          />
          <Select
            value={status}
            onValueChange={(value) => setStatus(value as typeof status)}
          >
            <SelectTrigger className="h-9 min-w-32" aria-label="筛选达人状态">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部状态</SelectItem>
              {Object.entries(statusLabels).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={enabled}
            onValueChange={(value) => setEnabled(value as typeof enabled)}
          >
            <SelectTrigger
              className="h-9 min-w-36"
              aria-label="筛选达人启用状态"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部启用状态</SelectItem>
              <SelectItem value="true">已启用</SelectItem>
              <SelectItem value="false">已停用</SelectItem>
            </SelectContent>
          </Select>
          <Select value={sort} onValueChange={(value) => setSort(value)}>
            <SelectTrigger className="h-9 min-w-36" aria-label="达人排序方式">
              <ListFilter />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="last_crawled_at:desc">最近爬取</SelectItem>
              <SelectItem value="profile_synced_at:desc">
                最近更新信息
              </SelectItem>
              <SelectItem value="follower_count:desc">粉丝最多</SelectItem>
              <SelectItem value="aweme_total_count:desc">
                主页作品最多
              </SelectItem>
              <SelectItem value="created_at:desc">最近创建</SelectItem>
              <SelectItem value="nickname:asc">昵称 A-Z</SelectItem>
              <SelectItem value="task_count:desc">关联任务最多</SelectItem>
              <SelectItem value="aweme_count:desc">作品最多</SelectItem>
              <SelectItem value="status:asc">优先处理状态</SelectItem>
            </SelectContent>
          </Select>
          <div className="flex items-center gap-1.5 whitespace-nowrap text-xs text-muted-foreground">
            <Checkbox
              checked={allSelected}
              disabled={!selectableIds.length}
              // 报告·通病 7：全选只覆盖当前页，标签里点明范围与条数，避免误解为跨页全选
              aria-label={`全选本页（共 ${selectableIds.length} 条）`}
              onCheckedChange={(checked) =>
                // 语义为「本页全选」：只增删当前页的可勾选达人，不做跨页全选
                setSelected((current) => {
                  const next = new Set(current)
                  for (const id of selectableIds) {
                    if (checked === true) next.add(id)
                    else next.delete(id)
                  }
                  return next
                })
              }
            />
            本页全选
          </div>
          <span className="whitespace-nowrap text-xs text-muted-foreground">
            已选 {selected.size} 位 · 本页可选 {selectableIds.length} 位
          </span>
          <ViewModeToggle value={viewMode} onChange={setViewMode} />
          <LoadModeToggle value={loadMode} onChange={changeLoadMode} />
          {/* 刷新达人信息：批量补全主页基础信息（粉丝数 / 作品数 / 头像 / 抖音号） */}
          <Button
            size="sm"
            variant="outline"
            className="h-8 gap-1.5 text-xs"
            disabled={profileSync.isPending || Boolean(profileSyncProgress)}
            onClick={() => profileSync.mutate()}
            title="从抖音主页同步粉丝数、作品数、签名、头像等基础信息"
          >
            <RefreshCw
              className={profileSync.isPending ? "animate-spin" : "size-3.5"}
            />
            {profileSyncProgress
              ? `同步中 ${profileSyncProgress.synced}${
                  profileSyncProgress.remaining
                    ? ` / +${profileSyncProgress.remaining}`
                    : ""
                }`
              : "刷新达人信息"}
          </Button>
          {/* 刷新指示器：本页不再轮询，需要时手动刷新 */}
          <RefreshIndicator
            updatedAt={creatorsFeed.dataUpdatedAt}
            refreshing={creatorsFeed.isFetching}
            onRefresh={() => void creatorsFeed.refetch()}
          />
        </div>
        {/* 报告 A2：把已生效的筛选可视化成可移除的 chips */}
        <FilterChips
          className="mt-2"
          chips={[
            search.trim() && {
              key: "q",
              label: "搜索",
              value: search.trim(),
              onRemove: () => setSearch(""),
            },
            trackId !== allTracksValue && {
              key: "track",
              label: "赛道",
              value: selectedTrack?.name ?? "已选赛道",
              onRemove: () => {
                setTrackId(allTracksValue)
                setSelected(new Set())
              },
            },
            categoryId !== allCategoriesValue && {
              key: "category",
              label: "分类",
              value: categoryDisplayName(
                categoriesQuery.data?.data ?? [],
                categoryId,
              ),
              onRemove: () => {
                setCategoryId(allCategoriesValue)
                setSelected(new Set())
              },
            },
            status !== "all" && {
              key: "status",
              label: "状态",
              value: statusLabels[status],
              onRemove: () => setStatus("all"),
            },
            enabled !== "all" && {
              key: "enabled",
              label: "启用状态",
              value: enabled === "true" ? "已启用" : "已停用",
              onRemove: () => setEnabled("all"),
            },
          ]}
          onClearAll={clearFilters}
        />
        {/* 报告 A10：筛选预设，本地持久化常用筛选组合 */}
        <FilterPresetBar
          className="mt-2"
          storageKey="douyin-creators-filter-presets"
          currentFilters={{ search, trackId, status, enabled, sort }}
          onApply={(filters) => {
            setSearch(filters.search)
            setTrackId(filters.trackId)
            setStatus(filters.status)
            setEnabled(filters.enabled)
            setSort(filters.sort)
            setSelected(new Set())
          }}
        />
      </PageHero>

      <Card>
        <CardContent className="space-y-4 p-3">
          {creatorsFeed.isError ? (
            <QueryErrorState
              title="达人列表读取失败"
              description="请检查服务连接后重试。"
              onRetry={() => void creatorsFeed.refetch()}
              retrying={creatorsFeed.isFetching}
            />
          ) : creatorsFeed.isLoading ? (
            // 报告 A4：首次加载改用骨架屏，排布与真实列表一致，数据到达时不再整块跳动
            <div
              className={
                viewMode === "cards" ? creatorCardGridClass : "space-y-2"
              }
            >
              {Array.from({ length: 8 }, (_, index) => (
                <Skeleton
                  key={`creators-skeleton-${index}`}
                  className={cn(
                    "w-full rounded-xl",
                    viewMode === "cards" ? "h-36" : "h-20",
                  )}
                />
              ))}
            </div>
          ) : creators.length ? (
            virtualize ? (
              // 报告 O19：超出阈值才走虚拟路径，短列表仍是原来的整段渲染
              <div
                className={cn(
                  viewMode === "table" && "overflow-hidden rounded-xl border",
                )}
              >
                <div ref={scrollRef} className="max-h-[70vh] overflow-auto">
                  <div style={{ height: totalSize, position: "relative" }}>
                    {virtualItems.map((virtualRow) => (
                      <div
                        key={creatorGroups[virtualRow.index][0].id}
                        data-index={virtualRow.index}
                        ref={virtualizer.measureElement}
                        className={virtualGroupClass}
                        style={{
                          position: "absolute",
                          top: 0,
                          left: 0,
                          width: "100%",
                          transform: `translateY(${virtualRow.start}px)`,
                        }}
                      >
                        {creatorGroups[virtualRow.index].map(renderCreator)}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className={listWrapperClass}>
                {creators.map(renderCreator)}
              </div>
            )
          ) : narrowedByFilter ? (
            <EmptyState
              icon={Users}
              title="没有符合筛选条件的达人"
              description="换个关键词，或放宽状态、启用条件；也可以清除筛选查看全部达人。"
              action={
                <Button size="sm" variant="outline" onClick={clearFilters}>
                  清除筛选
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon={Users}
              title="当前赛道还没有达人"
              description="粘贴抖音主页链接可直接添加达人，也可以先同步历史任务或历史作品里已经采集到的达人。"
              action={
                <Button
                  size="sm"
                  disabled={historySync.isPending}
                  onClick={() => historySync.mutate()}
                >
                  <History
                    className={historySync.isPending ? "animate-spin" : ""}
                  />
                  同步历史任务
                </Button>
              }
            />
          )}
          {/* 滚动加载：滚到底自动续拉；分页模式由下面的分页器接管 */}
          {loadMode === "scroll" && creators.length > 0 && (
            <ScrollLoader
              loadedCount={creators.length}
              total={creatorsFeed.total}
              hasMore={creatorsFeed.hasMore}
              isFetching={creatorsFeed.isFetchingMore}
              onLoadMore={creatorsFeed.loadMore}
            />
          )}
          {loadMode === "paged" && (
            <Pager
              page={page}
              pageSize={creatorPageSize}
              total={creatorsFeed.total}
              totalLabel={(total) => `共 ${total} 位达人`}
              onPageChange={(next) => {
                setPage(next)
                setSelected(new Set())
              }}
              showJumper
            />
          )}
        </CardContent>
      </Card>

      {/* 报告 A3：依赖选中项的批量操作统一收进底部批量操作栏 */}
      <BulkActionBar
        count={selected.size}
        label={`已选 ${selected.size} 位达人`}
        onClear={() => setSelected(new Set())}
        actions={
          <>
            <BatchCreatorTaskDialog
              creatorIds={[...selected]}
              trackId={trackId}
              trackName={selectedTrack?.name ?? "当前赛道"}
              onCreated={() => {
                setSelected(new Set())
                void invalidate()
              }}
            />
            <Button
              size="sm"
              variant="destructive"
              disabled={bulkRemove.isPending}
              onClick={async () => {
                // 报告 O15：改用统一确认框
                const ok = await confirmDialog({
                  title: `删除选中的 ${selected.size} 位达人？`,
                  description: "历史任务和作品不会被删除。",
                  confirmText: "删除",
                  variant: "destructive",
                })
                if (!ok) return
                bulkRemove.mutate([...selected])
              }}
            >
              <Trash2 />
              批量删除
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setAssignCategoryOpen(true)}
            >
              <FolderPlus />
              归类到分类
            </Button>
          </>
        }
      />
      <AssignCategoryDialog
        open={assignCategoryOpen}
        onOpenChange={setAssignCategoryOpen}
        creatorIds={[...selected]}
        onDone={showSuccessToast}
        onError={showErrorToast}
      />
    </div>
  )
}

function CreatorCard({
  creator,
  viewMode,
  highlighted,
  selected,
  onToggleSelect,
  onToggle,
  onRemove,
  onSaved,
}: {
  creator: DouyinCreatorPublic
  viewMode: ListViewMode
  highlighted: boolean
  selected: boolean
  onToggleSelect: (checked: boolean) => void
  onToggle: (item: DouyinCreatorPublic) => void
  onRemove: (id: string) => void
  onSaved: () => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  return (
    <Card
      className={cn(
        viewMode === "table"
          ? "rounded-none border-0 border-b shadow-none last:border-b-0"
          : "transition hover:shadow-md",
        // 报告 A6：状态 / 最近爬取时间变化的达人卡片闪一下
        highlighted && "row-highlight",
      )}
    >
      <CardContent
        className={
          viewMode === "cards" ? "p-4" : "flex flex-wrap items-center gap-3 p-3"
        }
      >
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <Checkbox
            checked={selected}
            disabled={creator.is_placeholder}
            aria-label={`选择达人 ${creatorNameLabel(creator)}`}
            className="mt-2"
            onCheckedChange={(checked) => onToggleSelect(checked === true)}
          />
          <CreatorAvatar
            name={creator.nickname}
            seed={creator.creator_hash}
            src={creator.avatar_url || undefined}
            className="size-12"
            initialClassName="text-base"
          />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p
                className="truncate font-medium"
                title={creatorNameLabel(creator)}
              >
                {creatorNameLabel(creator)}
              </p>
              {!creator.enabled && <Badge variant="secondary">已停用</Badge>}
              {creator.is_placeholder && (
                <Badge
                  variant="outline"
                  className="border-amber-400/60 bg-amber-50 text-amber-700"
                >
                  待补全
                </Badge>
              )}
              <CreatorStatusBadge status={creator.status} />
            </div>
            {creator.is_placeholder && (
              <p className="mt-0.5 truncate text-xs text-muted-foreground">
                脱敏身份 · 补全主页链接后可创建任务
              </p>
            )}
            <p className="mt-1 text-xs text-muted-foreground">
              {creator.task_count} 个任务 · {creator.aweme_count} 个作品
              {/* 报告 A16：时间点用相对时间展示，与「最近爬取」排序项对应 */}
              {" · 最近爬取 "}
              <TimeAgo value={creator.last_crawled_at} neverText="从未" />
            </p>
            {/* 主页基础信息：由「刷新达人信息」同步回填 */}
            <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
              {creator.profile_synced_at ? (
                <>
                  <span>粉丝 {compactCount(creator.follower_count)}</span>
                  <span>获赞 {compactCount(creator.total_favorited)}</span>
                  <span>
                    主页作品 {compactCount(creator.aweme_total_count)}
                  </span>
                  {creator.unique_id && <span>抖音号 {creator.unique_id}</span>}
                  {creator.ip_location && <span>{creator.ip_location}</span>}
                  <span>
                    更新于 <TimeAgo value={creator.profile_synced_at} />
                  </span>
                </>
              ) : (
                <span className="text-amber-600">
                  {creator.profile_error
                    ? `主页信息同步失败：${creator.profile_error}`
                    : "主页信息未同步（点上方「刷新达人信息」补全）"}
                </span>
              )}
            </p>
            {creator.signature && (
              <p className="mt-1 line-clamp-2 text-[10px] text-muted-foreground">
                {creator.signature}
              </p>
            )}
            {creator.notes && (
              <p className="mt-1 line-clamp-2 text-[10px] text-muted-foreground">
                {creator.notes}
              </p>
            )}
          </div>
        </div>
        <div
          className={`flex flex-wrap justify-end gap-1 ${
            viewMode === "cards" ? "mt-3" : "ml-auto"
          }`}
        >
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2"
            aria-label={`编辑达人 ${creatorNameLabel(creator)}`}
            onClick={() => setEditing(true)}
          >
            <Pencil /> {creator.is_placeholder ? "补全" : "编辑"}
          </Button>
          <Button size="sm" variant="outline" asChild>
            <Link
              to="/douyin-creators/$creatorId"
              params={{ creatorId: creator.id }}
              aria-label={`查看达人详情 ${creatorNameLabel(creator)}`}
            >
              <UserRoundSearch />
              详情
            </Link>
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2"
            onClick={() => onToggle(creator)}
          >
            {creator.enabled ? "停用" : "启用"}
          </Button>
          <Button size="sm" variant="outline" asChild>
            <Link
              to="/douyin-library"
              search={{
                track: undefined,
                source: undefined,
                q: undefined,
                task: undefined,
                creator: creator.creator_hash,
                tag: undefined,
                storage: undefined,
                subtitle: undefined,
                sort: undefined,
              }}
              aria-label={`查看 ${creator.nickname || "该达人"} 的作品`}
            >
              <Film />
              作品
            </Link>
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-destructive"
            aria-label={`删除达人 ${creatorNameLabel(creator)}`}
            onClick={async () => {
              // 报告 O15：改用统一确认框
              const ok = await confirmDialog({
                title: `删除达人“${creatorNameLabel(creator)}”？`,
                description: "历史任务和作品不会被删除。",
                confirmText: "删除",
                variant: "destructive",
              })
              if (!ok) return
              onRemove(creator.id)
            }}
          >
            <Trash2 />
          </Button>
        </div>
      </CardContent>
      {editing && (
        <EditCreatorDialog
          item={creator}
          open
          onOpenChange={(open) => !open && setEditing(false)}
          onSaved={async () => {
            setEditing(false)
            await onSaved()
          }}
        />
      )}
    </Card>
  )
}

function CreatorStatusBadge({ status }: { status: DouyinCreatorStatus }) {
  return (
    <Badge
      variant={
        status === "failed"
          ? "destructive"
          : status === "crawled"
            ? "default"
            : "outline"
      }
    >
      {status === "active" && <LoaderCircle className="animate-spin" />}
      {statusLabels[status]}
    </Badge>
  )
}

function CreateCreatorsDialog({
  onCreated,
  initialTrackId,
}: {
  onCreated: () => Promise<void>
  initialTrackId: string
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState("")
  const [notes, setNotes] = useState("")
  const [trackId, setTrackId] = useState(
    initialTrackId === allTracksValue ? "" : initialTrackId,
  )
  useEffect(() => {
    if (!open) return
    setTrackId(initialTrackId === allTracksValue ? "" : initialTrackId)
  }, [initialTrackId, open])
  const mutation = useMutation({
    mutationFn: () =>
      DouyinCreatorsService.bulkCreateCreators({
        requestBody: {
          creators: parseCreatorTargets(value),
          notes,
          track_id: trackId,
        },
      }),
    onSuccess: async (result) => {
      showSuccessToast(
        `新增 ${result.created_count} 位，已存在 ${result.existing_count} 位`,
      )
      setValue("")
      setNotes("")
      setOpen(false)
      await onCreated()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!trackId || trackId === allTracksValue)
      return showErrorToast("请选择达人所属赛道")
    if (!parseCreatorTargets(value).length)
      return showErrorToast("请填写至少一位达人")
    mutation.mutate()
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus />
          添加达人
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit} className="space-y-5">
          <DialogHeader>
            <DialogTitle>批量添加达人</DialogTitle>
            <DialogDescription>
              每行或逗号分隔一位达人，支持粘贴主页链接或平台达人标识；
              已存在的达人会保持原归属不动。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label>所属赛道</Label>
            <TrackSelect
              value={trackId}
              onValueChange={setTrackId}
              enabled={open}
            />
            <p className="text-xs text-muted-foreground">
              新达人会直接归入所选赛道，后续任务和内容筛选会沿用该归属。
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="creator-values">达人主页链接或平台达人标识</Label>
            <Textarea
              id="creator-values"
              value={value}
              rows={8}
              placeholder={
                "https://www.douyin.com/user/MS4wLjABAAAA…\nMS4wLjABAAAAa2jK7…"
              }
              onChange={(event) => setValue(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="creator-notes">统一备注（可选）</Label>
            <Input
              id="creator-notes"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
            >
              取消
            </Button>
            <Button type="submit" disabled={mutation.isPending || !trackId}>
              保存达人
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function BatchCreatorTaskDialog({
  creatorIds,
  trackId,
  trackName,
  onCreated,
}: {
  creatorIds: string[]
  trackId: string
  trackName: string
  onCreated: () => void
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [open, setOpen] = useState(false)
  const [maxAwemes, setMaxAwemes] = useState(10)
  const [fetchComments, setFetchComments] = useState(true)
  const [maxComments, setMaxComments] = useState(10)
  const [delayLevel, setDelayLevel] = useState<
    "fast" | "steady" | "ultra_steady"
  >("steady")
  const [taskInterval, setTaskInterval] = useState("")
  const [accountChoice, setAccountChoice] = useState("adhoc")
  const [accountStrategy, setAccountStrategy] = useState<
    "least_loaded" | "round_robin" | "weighted_round_robin"
  >("least_loaded")
  const accounts = useQuery({
    queryKey: ["douyin-accounts"],
    queryFn: () => DouyinAccountsService.listAccounts({ limit: 100 }),
    enabled: open,
  })
  const pools = useQuery({
    queryKey: ["douyin-account-pools"],
    queryFn: () => DouyinAccountsService.listPools(),
    enabled: open,
  })
  const mutation = useMutation({
    mutationFn: () => {
      const requestBody: Parameters<
        typeof DouyinCreatorsService.createCreatorTasks
      >[0]["requestBody"] = {
        creator_ids: creatorIds,
        track_id: trackId,
        max_awemes: maxAwemes,
        fetch_comments: fetchComments,
        max_comments_per_aweme: maxComments,
        request_delay_level: delayLevel,
        ...(taskInterval.trim()
          ? { task_interval_seconds: Number(taskInterval) }
          : {}),
        download_media: false,
        translate_subtitles: false,
        media_processing_mode: "none",
      }
      if (accountChoice.startsWith("account:"))
        requestBody.account_id = accountChoice.slice(8)
      if (accountChoice.startsWith("pool:")) {
        requestBody.account_pool_id = accountChoice.slice(5)
        requestBody.account_strategy = accountStrategy
      }
      return DouyinCreatorsService.createCreatorTasks({ requestBody })
    },
    onSuccess: (result) => {
      showSuccessToast(`已创建 ${result.count} 个达人任务`)
      setOpen(false)
      onCreated()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="secondary" disabled={!creatorIds.length}>
          <Play />
          批量创建任务
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>从 {creatorIds.length} 位达人创建任务</DialogTitle>
          <DialogDescription>
            每位达人独立一个任务，便于逐人看结果；一次最多创建 20 个。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2 rounded-xl border bg-muted/30 p-3">
          <p className="text-xs font-medium text-muted-foreground">所属赛道</p>
          {trackId === allTracksValue ? (
            <p className="text-sm font-medium text-destructive">
              请先在上方按赛道筛选达人，再创建批量任务
            </p>
          ) : (
            <>
              <p className="text-sm font-medium">{trackName}</p>
              <p className="text-xs text-muted-foreground">
                已选达人会在该赛道内创建任务，不允许跨赛道混合运行。
              </p>
            </>
          )}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="执行账号">
            <Select value={accountChoice} onValueChange={setAccountChoice}>
              <SelectTrigger aria-label="执行账号">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="adhoc">临时浏览器登录</SelectItem>
                {(accounts.data?.data ?? [])
                  .filter(
                    (item) =>
                      item.enabled && ["ready", "busy"].includes(item.status),
                  )
                  .map((item) => (
                    <SelectItem key={item.id} value={`account:${item.id}`}>
                      账号 · {item.name}
                    </SelectItem>
                  ))}
                {(pools.data?.data ?? [])
                  .filter((item) => item.enabled)
                  .map((item) => (
                    <SelectItem key={item.id} value={`pool:${item.id}`}>
                      账号池 · {item.name}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </Field>
          {accountChoice.startsWith("pool:") && (
            <Field label="账号池调度策略">
              <Select
                value={accountStrategy}
                onValueChange={(value) =>
                  setAccountStrategy(value as typeof accountStrategy)
                }
              >
                <SelectTrigger aria-label="账号池调度策略">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="least_loaded">最少负载</SelectItem>
                  <SelectItem value="round_robin">顺序轮询</SelectItem>
                  <SelectItem value="weighted_round_robin">加权轮询</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          )}
          <Field label="每任务最大作品">
            <Input
              type="number"
              min={1}
              max={1000}
              value={maxAwemes}
              onChange={(event) => setMaxAwemes(Number(event.target.value))}
            />
          </Field>
          <Field label="每作品最大评论">
            <Input
              type="number"
              min={1}
              max={1000}
              disabled={!fetchComments}
              value={maxComments}
              onChange={(event) => setMaxComments(Number(event.target.value))}
            />
          </Field>
          <Field label="风控节奏">
            <Select
              value={delayLevel}
              onValueChange={(value) =>
                setDelayLevel(value as typeof delayLevel)
              }
            >
              <SelectTrigger aria-label="风控节奏">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="fast">快 · 1–2 秒随机</SelectItem>
                <SelectItem value="steady">稳 · 3–6 秒随机</SelectItem>
                <SelectItem value="ultra_steady">
                  超级稳 · 6–12 秒随机
                </SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label="任务完成后间隔（秒）">
            <Input
              type="number"
              min={0}
              max={3600}
              step={1}
              value={taskInterval}
              onChange={(event) => setTaskInterval(event.target.value)}
              placeholder="跟随请求风控节奏"
            />
          </Field>
        </div>
        <div className="space-y-3 rounded-xl border p-4">
          <Check
            checked={fetchComments}
            label="抓取评论"
            onChange={setFetchComments}
          />
          <p className="rounded-lg border border-blue-200/70 bg-blue-50/60 p-3 text-xs leading-5 text-blue-950 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-100">
            本次只创建达人采集任务。作品产出后，请到任务中心的“下载与字幕”页签创建关联处理任务。
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button
            disabled={
              mutation.isPending ||
              !creatorIds.length ||
              creatorIds.length > 20 ||
              !trackId ||
              trackId === allTracksValue
            }
            onClick={() => mutation.mutate()}
          >
            确认创建并运行
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function EditCreatorDialog({
  item,
  open,
  onOpenChange,
  onSaved,
}: {
  item: DouyinCreatorPublic
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => Promise<void>
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [nickname, setNickname] = useState(item.nickname)
  const [notes, setNotes] = useState(item.notes)
  const [enabled, setEnabled] = useState(item.enabled)
  const [trackId, setTrackId] = useState(item.track_id)
  const [completionUid, setCompletionUid] = useState("")
  useEffect(() => {
    if (open) {
      setNickname(item.nickname)
      setNotes(item.notes)
      setEnabled(item.enabled)
      setTrackId(item.track_id)
      setCompletionUid("")
    }
  }, [item, open])
  const mutation = useMutation({
    mutationFn: () =>
      DouyinCreatorsService.editCreator({
        creatorId: item.id,
        requestBody: {
          nickname,
          notes,
          enabled,
          track_id: trackId && trackId !== item.track_id ? trackId : null,
          ...(item.is_placeholder && completionUid.trim()
            ? { sec_uid: completionUid.trim() }
            : {}),
        },
      }),
    onSuccess: async () => {
      showSuccessToast(
        item.is_placeholder && completionUid.trim()
          ? "补全成功，该达人已可创建任务"
          : "达人信息已更新",
      )
      onOpenChange(false)
      await onSaved()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (item.is_placeholder && !completionUid.trim())
      return showErrorToast("请填写该达人的主页链接或平台达人标识完成补全")
    mutation.mutate()
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>
              {item.is_placeholder ? "补全达人" : "编辑达人"}
            </DialogTitle>
            <DialogDescription>
              {item.is_placeholder
                ? "该达人来自历史采集作品，粘贴主页链接完成补全后即可创建任务；昵称与备注可一并调整。"
                : "调整昵称、备注、启用状态与赛道归属；历史任务仍保留原赛道。"}
            </DialogDescription>
          </DialogHeader>
          {item.is_placeholder && (
            <div className="space-y-2">
              <Label htmlFor="edit-creator-completion">
                补全主页链接或平台达人标识
              </Label>
              <Input
                id="edit-creator-completion"
                value={completionUid}
                placeholder="https://www.douyin.com/user/MS4wLjABAAAA…"
                onChange={(event) => setCompletionUid(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                系统会校验链接与历史采集数据的脱敏身份一致，避免补全到错误的人。
              </p>
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="edit-creator-nickname">昵称</Label>
            <Input
              id="edit-creator-nickname"
              value={nickname}
              onChange={(event) => setNickname(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="edit-creator-notes">备注</Label>
            <Textarea
              id="edit-creator-notes"
              rows={3}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label>所属赛道</Label>
            <TrackSelect
              value={trackId}
              onValueChange={setTrackId}
              enabled={open}
              autoSelectDefault={false}
              ariaLabel={`选择“${creatorNameLabel(item)}”的所属赛道`}
            />
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Checkbox
              id="edit-creator-enabled"
              checked={enabled}
              onCheckedChange={(checked) => setEnabled(checked === true)}
            />
            <Label htmlFor="edit-creator-enabled">启用该达人</Label>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              取消
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending
                ? "保存中…"
                : item.is_placeholder
                  ? "补全并保存"
                  : "保存修改"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      {children}
    </div>
  )
}

function Check({
  checked,
  disabled,
  label,
  onChange,
}: {
  checked: boolean
  disabled?: boolean
  label: string
  onChange: (checked: boolean) => void
}) {
  return (
    <div className="flex items-center gap-2">
      <Checkbox
        checked={checked}
        disabled={disabled}
        // Label 是并列文本、没有 htmlFor，补 aria-label 保证有可读名称
        aria-label={label}
        onCheckedChange={(value) => onChange(value === true)}
      />
      <Label className="font-normal">{label}</Label>
    </div>
  )
}

/** 主页指标压缩展示：1.2万 / 358万 之类，避免长数字撑开行 */
function compactCount(value: number): string {
  if (!value) return "0"
  if (value < 10000) return String(value)
  if (value < 100000000) {
    return `${(value / 10000).toFixed(1).replace(/\.0$/, "")}万`
  }
  return `${(value / 100000000).toFixed(1).replace(/\.0$/, "")}亿`
}

function parseCreatorTargets(value: string) {
  return value
    .split(/[\n,，]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}
