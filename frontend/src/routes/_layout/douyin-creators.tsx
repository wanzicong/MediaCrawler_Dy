import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  CloudDownload,
  Download,
  FolderPlus,
  History,
  ListFilter,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Users,
} from "lucide-react"
import {
  type FormEvent,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"

import {
  type ApiError,
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
import {
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
import { CreateTaskDialog } from "@/components/Douyin/CreateTaskDialog"
import {
  CreatorCard,
  creatorCardGridClass,
  statusLabels,
  useCreatorGridColumns,
} from "@/components/Douyin/CreatorCard"
import {
  allTracksValue,
  TrackSelect,
  useTrackCatalog,
} from "@/components/Douyin/TrackSelect"
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
// 主页详情拉取状态筛选：pending = 从未成功也没失败过，failed = 最近一次拉取失败
// （先成功、后失败的达人同时算已拉取与失败，两个视图都能看到它）
const CREATOR_DETAIL_VALUES = ["all", "synced", "pending", "failed"] as const
const creatorDetailLabels: Record<
  (typeof CREATOR_DETAIL_VALUES)[number],
  string
> = {
  all: "全部详情状态",
  synced: "已拉取详情",
  pending: "未拉取详情",
  failed: "拉取失败",
}
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
  /** 主页详情拉取状态：all / synced（已拉取）/ pending（未拉取）/ failed（拉取失败） */
  detail?: (typeof CREATOR_DETAIL_VALUES)[number]
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
    detail: readEnumParam(search, "detail", CREATOR_DETAIL_VALUES),
    sort: readEnumParam(search, "sort", CREATOR_SORT_VALUES),
  }),
  component: DouyinCreatorDirectory,
  head: () => ({ meta: [{ title: "达人列表 - 灵感采集台" }] }),
})

// 已知截断：接口按 limit 截断返回，界面仅展示前 N 位达人（文案已提示）。
// 后续应改为服务端分页（响应中的 count 已是全量，可直接做分页游标 / offset）。
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
  const [detail, setDetail] = useState<(typeof CREATOR_DETAIL_VALUES)[number]>(
    urlSearch.detail ?? "all",
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
          detail,
          // state 刻意保持 string（Select 的 onValueChange 回传 string），
          // 这里收窄到排序白名单联合类型，与 CreatorSearch.sort 对齐
          sort: sort as CreatorSortValue,
        },
        {
          status: "all",
          enabled: "all",
          detail: "all",
          sort: defaultCreatorSort,
        },
      ),
    })
  }, [search, trackId, categoryId, status, enabled, detail, sort, navigate])
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
      detail,
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
        profileStatus: detail === "all" ? undefined : detail,
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
  // 批量创建任务时带入的统一对话框需要稳定的预设达人数组（否则每次渲染都会重置弹窗状态）
  const selectedCreators = useMemo(
    () => creators.filter((item) => selected.has(item.id)),
    [creators, selected],
  )
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
  // 只在「分页」模式启用虚拟滚动：滚动加载模式下列表必须随内容一起变高，
  // 否则触底哨兵会被固定高度的内层滚动容器永久框在视口里 ——
  // IntersectionObserver 每完成一页就立刻再次触发，会把全量达人一次拉完
  // （实测 1269 位达人被 23 次连续请求拉光，页面同时卡死）。
  // 滚动加载因此与视频资源库的卡片视图保持一致：整页滚动 + 触底哨兵。
  const virtualize =
    loadMode === "paged" && creators.length > VIRTUALIZE_THRESHOLD
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
    detail !== "all" ||
    categoryId !== allCategoriesValue
  const clearFilters = () => {
    setSearch("")
    setTrackId(allTracksValue)
    setCategoryId(allCategoriesValue)
    setStatus("all")
    setEnabled("all")
    setDetail("all")
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
          {/* 详情拉取筛选：筛出待补主页信息的达人，或用「拉取失败」筛出需要重试的达人 */}
          <Select
            value={detail}
            onValueChange={(value) =>
              setDetail(value as (typeof CREATOR_DETAIL_VALUES)[number])
            }
          >
            <SelectTrigger
              className="h-9 min-w-36"
              aria-label="按主页详情拉取状态筛选达人"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CREATOR_DETAIL_VALUES.map((value) => (
                <SelectItem key={value} value={value}>
                  {creatorDetailLabels[value]}
                </SelectItem>
              ))}
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
            detail !== "all" && {
              key: "detail",
              label: "详情",
              value: creatorDetailLabels[detail],
              onRemove: () => setDetail("all"),
            },
          ]}
          onClearAll={clearFilters}
        />
        {/* 报告 A10：筛选预设，本地持久化常用筛选组合 */}
        <FilterPresetBar
          className="mt-2"
          storageKey="douyin-creators-filter-presets"
          currentFilters={{ search, trackId, status, enabled, detail, sort }}
          onApply={(filters) => {
            setSearch(filters.search)
            setTrackId(filters.trackId)
            setStatus(filters.status)
            setEnabled(filters.enabled)
            // 旧预设没有 detail 字段，回落到「全部」而不是 undefined
            setDetail(filters.detail ?? "all")
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
            {/* 与任务中心共用同一个创建任务对话框：账号、登录方式、并发、延迟档位、
                媒体处理等配置项完全一致，避免「从达人进来的任务」缺配置项而失败 */}
            <CreateTaskDialog
              initialTrackId={trackId === allTracksValue ? "" : trackId}
              initialCrawlType="creator"
              initialCreators={selectedCreators}
              triggerLabel="批量创建任务"
              triggerVariant="secondary"
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

function parseCreatorTargets(value: string) {
  return value
    .split(/[\n,，]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}
