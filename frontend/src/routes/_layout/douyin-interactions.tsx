import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  Camera,
  Copy,
  ExternalLink,
  Eye,
  ImageOff,
  Inbox,
  MonitorPlay,
  MoreHorizontal,
  RotateCcw,
  ShieldCheck,
  XCircle,
  ZoomIn,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import {
  type DouyinInteractionEventPublic,
  type DouyinInteractionPublic,
  type DouyinInteractionStatus,
  DouyinInteractionsService,
  type DouyinInteractionType,
  OpenAPI,
} from "@/client"
import { confirmDialog } from "@/components/Common/confirm-dialog"
// 报告 A4/O8：空态统一用「图标 + 标题 + 说明 + 主行动按钮」
import { EmptyState } from "@/components/Common/EmptyState"
import { FilterChips } from "@/components/Common/FilterChips"
import { FilterPresetBar } from "@/components/Common/FilterPresetBar"
import { PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { RefreshIndicator } from "@/components/Common/RefreshIndicator"
import {
  RowContextMenu,
  type RowMenuItem,
} from "@/components/Common/RowContextMenu"
// 报告 A1：列可见性菜单
import { TableColumnMenu } from "@/components/Common/TableColumnMenu"
import { TimeAgo } from "@/components/Common/TimeAgo"
import { InteractionContentSummary } from "@/components/Douyin/InteractionContentSummary"
import { InteractionLiveMonitor } from "@/components/Douyin/InteractionLiveMonitor"
import {
  canShowInteractionRetry,
  InteractionStatusBadge,
  interactionTypeLabels,
  isInteractionRetryCandidateStatus,
} from "@/components/Douyin/InteractionStatusBadge"
import {
  allSourcesValue,
  parseSourceSelection,
  SourceBadge,
  SourceSelect,
  sourceSelectionValue,
  useSourceCatalog,
} from "@/components/Douyin/SourceSelect"
import {
  allTracksValue,
  TrackSelect,
  useTrackCatalog,
} from "@/components/Douyin/TrackSelect"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
// 报告 A4/O8：加载态改用骨架屏，保持已有结构不跳动
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import useCustomToast from "@/hooks/useCustomToast"
import { useHighlightedRows } from "@/hooks/useHighlightedRows"
// 报告 A1：手写 Table 的列可见性
import { type TableColumnDef, useTableColumns } from "@/hooks/useTableColumns"
// 报告 O19：长事件列表虚拟滚动
import { useVirtualRows, VIRTUALIZE_THRESHOLD } from "@/hooks/useVirtualRows"
// 报告 O4：筛选上 URL
import {
  compactSearch,
  readEnumParam,
  readStringParam,
} from "@/lib/search-params"
import { readStorage } from "@/lib/storage"
import { formatDateTime } from "@/lib/time"
import { cn } from "@/lib/utils"
import { getDouyinVideoUrl, handleError } from "@/utils"

/** 报告 O4：状态筛选的 URL 白名单，挡住手改 URL 传进来的脏值 */
const INTERACTION_STATUS_FILTER_VALUES = [
  "all",
  "pending_confirmation",
  "queued",
  "running",
  "succeeded",
  "failed",
  "blocked",
  "needs_review",
  "cancelled",
] as const

/** 报告 O4：互动类型筛选的 URL 白名单 */
const INTERACTION_TYPE_FILTER_VALUES = [
  "all",
  "video_comment",
  "comment_reply",
  "creator_message",
] as const

type StatusFilter = DouyinInteractionStatus | "all"
type TypeFilter = DouyinInteractionType | "all"

/**
 * 报告 O4：互动任务页面的 URL 筛选参数。
 * 所有属性都声明为**可选**：TS 里 `{ status: StatusFilter | undefined }` 的属性仍是必填的
 * （值可以是 undefined，但键必须存在），TanStack Router 据此要求跳转到本路由的
 * Link / navigate 必须携带 search，导致所有 `<Link to="/douyin-interactions">` 报
 * 「Property 'search' is missing」。写成 `status?: ...` 后 search 才变为可选。
 */
type InteractionSearch = {
  status?: StatusFilter
  type?: TypeFilter
  track?: string
  source?: string
}

export const Route = createFileRoute("/_layout/douyin-interactions")({
  // 报告 O4：筛选上 URL —— 刷新、分享链接、深链、收藏都能还原筛选条件
  validateSearch: (search: Record<string, unknown>): InteractionSearch => ({
    status: readEnumParam(search, "status", INTERACTION_STATUS_FILTER_VALUES),
    type: readEnumParam(search, "type", INTERACTION_TYPE_FILTER_VALUES),
    track: readStringParam(search, "track"),
    source: readStringParam(search, "source"),
  }),
  component: DouyinInteractionsPage,
  head: () => ({ meta: [{ title: "互动任务 - 灵感采集台" }] }),
})

/** 状态筛选的中文名（与状态徽标、筛选下拉的文案保持一致） */
const interactionStatusLabels: Record<DouyinInteractionStatus, string> = {
  pending_confirmation: "待确认",
  queued: "排队中",
  running: "发送中",
  succeeded: "已成功",
  failed: "失败",
  blocked: "已暂停",
  needs_review: "待人工核对",
  cancelled: "已取消",
}

/**
 * 批量重试的并发上限。
 * 原实现把全部候选一次性交给 Promise.allSettled，候选多时实测可发出 500 个并发请求，
 * 会打爆后端与浏览器连接池，这里分批推进，每批最多 5 个。
 */
const RETRY_BATCH_SIZE = 5

/**
 * 报告 A1：互动任务表的列清单（模块级常量，避免每次 render 重建导致偏好被重置）。
 * title 与表头文案保持一致；操作列冻结且不允许隐藏，藏掉用户就没法操作了。
 */
const INTERACTION_COLUMNS = [
  { key: "type", title: "类型 / 目标" },
  { key: "source", title: "来源" },
  { key: "content", title: "互动内容 / 目标内容" },
  { key: "account", title: "账号" },
  { key: "status", title: "状态" },
  { key: "updated", title: "更新时间" },
  { key: "actions", title: "操作", alwaysVisible: true },
] as const satisfies readonly TableColumnDef[]

function DouyinInteractionsPage() {
  // 报告 O4：筛选上 URL —— 初值来自 URL，于是刷新 / 深链能还原筛选
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(
    search.status ?? "all",
  )
  const [typeFilter, setTypeFilter] = useState<TypeFilter>(search.type ?? "all")
  const [trackId, setTrackId] = useState(search.track ?? allTracksValue)
  const [sourceValue, setSourceValue] = useState(
    search.source ?? allSourcesValue,
  )
  // detailId / monitorId 是弹窗状态，不属于筛选，不写进 URL
  const [detailId, setDetailId] = useState<string | null>(null)
  const [monitorId, setMonitorId] = useState<string | null>(null)
  // 批量重试的进度与中断标记
  const [retryAllProgress, setRetryAllProgress] = useState<{
    done: number
    total: number
  } | null>(null)
  const retryAllAbortRef = useRef(false)
  // 报告 A1：列可见性偏好存本地，表头与单元格据此显示 / 隐藏
  const { isVisible, visibleCount, menuProps } = useTableColumns({
    storageKey: "douyin-interactions-columns",
    columns: INTERACTION_COLUMNS,
  })
  // 报告 O4：筛选变化时写回 URL。
  // replace: true —— 不用 replace 的话，用户每改一次筛选就多一条浏览器历史，
  // 按十次「后退」才能离开这个页面。用 replace 后刷新、分享、深链、收藏都生效，
  // 但浏览器「后退」是回到上一个页面而不是上一条筛选，这是有意的取舍。
  // 依赖只放筛选 state 与 navigate，绝不能放 search 对象，否则会写入 → 重渲染 → 再写入的死循环。
  useEffect(() => {
    void navigate({
      to: "/douyin-interactions",
      replace: true,
      // 等于默认值的键由 compactSearch 丢掉，未筛选时地址栏就是 /douyin-interactions
      search: compactSearch(
        {
          status: statusFilter,
          type: typeFilter,
          track: trackId === allTracksValue ? undefined : trackId,
          source: sourceValue === allSourcesValue ? undefined : sourceValue,
        },
        { status: "all", type: "all" },
      ),
    })
  }, [statusFilter, typeFilter, trackId, sourceValue, navigate])
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const interactions = useQuery({
    queryKey: [
      "douyin-interactions",
      trackId,
      sourceValue,
      statusFilter,
      typeFilter,
    ],
    queryFn: () =>
      DouyinInteractionsService.listInteractions({
        trackId: trackId === allTracksValue ? undefined : trackId,
        ...parseSourceSelection(sourceValue),
        status: statusFilter === "all" ? undefined : statusFilter,
        interactionType: typeFilter === "all" ? undefined : typeFilter,
        // 已知的数据截断：此处硬编码 limit: 100 且列表没有分页，
        // 命中超过 100 条的筛选结果会被静默截断；后端是否支持服务端分页尚未确认，
        // 本次不改动翻页逻辑，仅在此标注以免误以为看到了全部数据。
        limit: 100,
      }),
    refetchInterval: (query) =>
      query.state.data?.data.some((item) =>
        ["queued", "running"].includes(item.status),
      )
        ? 2_000
        : false,
  })
  const detail = useQuery({
    queryKey: ["douyin-interaction-detail", detailId],
    queryFn: () =>
      DouyinInteractionsService.getInteraction({ interactionId: detailId! }),
    enabled: Boolean(detailId),
    refetchInterval: (query) =>
      query.state.data &&
      ["queued", "running"].includes(query.state.data.status)
        ? 2_000
        : false,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["douyin-interactions"] }),
      queryClient.invalidateQueries({
        queryKey: ["douyin-task-interactions"],
      }),
      queryClient.invalidateQueries({ queryKey: ["douyin-interaction-quota"] }),
      detailId
        ? queryClient.invalidateQueries({
            queryKey: ["douyin-interaction-detail", detailId],
          })
        : Promise.resolve(),
    ])
  }
  const confirm = useMutation({
    mutationFn: (id: string) =>
      DouyinInteractionsService.confirmInteraction({ interactionId: id }),
    onSuccess: async () => {
      showSuccessToast("互动任务已确认并进入发送队列")
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const retry = useMutation({
    mutationFn: (item: DouyinInteractionPublic) =>
      DouyinInteractionsService.retryInteraction({
        interactionId: item.id,
        requestBody: { confirm_not_sent: item.status === "needs_review" },
      }),
    onSuccess: async () => {
      showSuccessToast("互动任务已重新排队")
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const retryAll = useMutation({
    mutationFn: async () => {
      const all: DouyinInteractionPublic[] = []
      let skip = 0
      let total = 0
      do {
        const page = await DouyinInteractionsService.listInteractions({
          trackId: trackId === allTracksValue ? undefined : trackId,
          ...parseSourceSelection(sourceValue),
          skip,
          limit: 100,
        })
        all.push(...page.data)
        total = page.count
        skip += page.data.length
      } while (skip < total)

      const candidates = all.filter(canShowInteractionRetry)
      const unavailable = all.filter(
        (item) =>
          isInteractionRetryCandidateStatus(item.status) && !item.can_retry,
      )

      // 分批重试：每批最多 RETRY_BATCH_SIZE 个，批间检查中断标记，
      // 让用户可以中途叫停，同时把并发压在可控范围内。
      retryAllAbortRef.current = false
      setRetryAllProgress({ done: 0, total: candidates.length })
      const results: PromiseSettledResult<unknown>[] = []
      for (
        let index = 0;
        index < candidates.length;
        index += RETRY_BATCH_SIZE
      ) {
        if (retryAllAbortRef.current) break
        const batch = candidates.slice(index, index + RETRY_BATCH_SIZE)
        results.push(
          ...(await Promise.allSettled(
            batch.map((item) =>
              DouyinInteractionsService.retryInteraction({
                interactionId: item.id,
                requestBody: {
                  confirm_not_sent: item.status === "needs_review",
                },
              }),
            ),
          )),
        )
        setRetryAllProgress({ done: results.length, total: candidates.length })
        if (retryAllAbortRef.current) break
      }
      setRetryAllProgress(null)

      if (retryAllAbortRef.current) {
        throw new Error(
          `已取消批量重试：已完成 ${results.length}/${candidates.length} 条`,
        )
      }
      const failed = results.filter((result) => result.status === "rejected")
      if (failed.length || unavailable.length) {
        throw new Error(
          `已重新排队 ${results.length - failed.length} 条；${failed.length} 条请求失败，${unavailable.length} 条目标不可用或内容损坏，无法安全重试`,
        )
      }
      return candidates.length
    },
    onSuccess: async (count) => {
      showSuccessToast(`已将 ${count} 条可重试互动任务重新排队`)
      await invalidate()
    },
    onError: async (error) => {
      showErrorToast(error instanceof Error ? error.message : "批量重试失败")
      await invalidate()
    },
  })
  const cancel = useMutation({
    mutationFn: (id: string) =>
      DouyinInteractionsService.cancelInteraction({ interactionId: id }),
    onSuccess: invalidate,
    onError: handleError.bind(showErrorToast),
  })
  // 列表数据与派生判断缓存，避免每次 render 重复遍历（原实现每次 render 都跑 rows.some）
  const rows = useMemo(() => interactions.data?.data ?? [], [interactions.data])
  const hasRetryable = useMemo(() => rows.some(canShowInteractionRetry), [rows])
  // 报告 A6：轮询刷新后发生变化的行闪一下；指纹取「状态 + 更新时间」，两者都没动就不闪
  const highlighted = useHighlightedRows(
    rows,
    (row) => row.id,
    (row) => `${row.status}:${row.updated_at}`,
  )
  // 报告 A7：右键菜单的「复制互动 ID」复用统一的剪贴板 hook
  const [, copy] = useCopyToClipboard()
  const copyInteractionId = async (id: string) => {
    if (await copy(id)) showSuccessToast("已复制互动 ID")
  }
  // 报告 A7：把低频操作从操作列挪进右键菜单（操作列只留高频项，见 O10）
  const rowMenuItems = (item: DouyinInteractionPublic) => {
    const menu: RowMenuItem[] = [
      {
        label: "复制互动 ID",
        icon: Copy,
        onSelect: () => void copyInteractionId(item.id),
      },
      { label: "查看详情", icon: Eye, onSelect: () => setDetailId(item.id) },
      {
        label: "查看实时监控",
        icon: MonitorPlay,
        onSelect: () => setMonitorId(item.id),
      },
    ]
    if (canShowInteractionRetry(item)) {
      menu.push({
        separatorBefore: true,
        label: "重试",
        icon: RotateCcw,
        onSelect: () => void retryAfterReview(item, retry.mutate),
      })
    }
    if (item.can_cancel) {
      menu.push({
        separatorBefore: true,
        label: "取消任务",
        icon: XCircle,
        destructive: true,
        onSelect: () => cancel.mutate(item.id),
      })
    }
    return menu
  }
  // 截图数量徽标：事件列表可能很长，避免每次 render 重新 filter
  const screenshotCount = useMemo(
    () =>
      detail.data?.events.filter((event) => event.has_screenshot).length ?? 0,
    [detail.data],
  )
  // 报告 O19：详情弹窗的事件列表单页无上限（长任务可达数百条），此前一次性铺满 DOM。
  // 事件卡片高度差异很大（带截图的可到 400px 以上），所以走「测量式」虚拟滚动：
  // 每个卡片挂 measureElement，用真实高度回填，避免用固定估算高度导致卡片互相重叠。
  const events = useMemo(() => detail.data?.events ?? [], [detail.data])
  const eventsScrollRef = useRef<HTMLDivElement>(null)
  const virtualizeEvents = events.length > VIRTUALIZE_THRESHOLD
  const eventsVirtualizer = useVirtualRows({
    count: events.length,
    scrollRef: eventsScrollRef,
    estimateSize: 240,
    enabled: virtualizeEvents,
  })
  const { virtualItems: eventVirtualItems, totalSize: eventsTotalSize } =
    eventsVirtualizer
  // 报告 A2/O8：判断空态是不是「筛选筛空了」，据此决定主行动按钮是清筛选还是去建任务
  const hasActiveFilters =
    statusFilter !== "all" ||
    typeFilter !== "all" ||
    trackId !== allTracksValue ||
    sourceValue !== allSourcesValue
  // 报告 A2：筛选 chips 需要展示可读的名称而不是 id。
  // 这两个 query 的 key 与 TrackSelect / SourceSelect 内部一致，命中同一份缓存，不会多发请求。
  const trackCatalog = useTrackCatalog()
  const sourceCatalog = useSourceCatalog(trackId)
  const trackName = (trackCatalog.data?.data ?? []).find(
    (track) => track.id === trackId,
  )?.name
  const sourceName = (sourceCatalog.data?.data ?? []).find(
    (option) =>
      sourceSelectionValue(option.source_type, option.id) === sourceValue,
  )?.name
  // 报告 A2：一次性清空全部筛选状态（含关闭详情/实时监控浮层）
  const clearAllFilters = () => {
    setStatusFilter("all")
    setTypeFilter("all")
    setTrackId(allTracksValue)
    setSourceValue(allSourcesValue)
    setDetailId(null)
    setMonitorId(null)
  }

  // 报告 O19：事件卡片抽成一份渲染函数，虚拟滚动路径与短列表路径共用，
  // 保证两条路径的 DOM / 样式完全一致（key 用事件 id，不用 index）。
  const renderEventCard = (event: DouyinInteractionEventPublic) => {
    const item = detail.data
    if (!item) return null
    return (
      <div
        key={event.id}
        className="relative rounded-xl border bg-card p-3 shadow-sm before:absolute before:-left-[1.3rem] before:top-5 before:size-2 before:rounded-full before:bg-primary"
      >
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="text-sm font-medium">
              {interactionEventLabel(event.event)}
            </p>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <InteractionStatusBadge status={event.to_status} />
              {event.attempt_number > 0 && (
                <span>第 {event.attempt_number} 次执行</span>
              )}
              <span>{formatDateTime(event.created_at)}</span>
            </div>
          </div>
        </div>
        <a
          href={item.target_video_url || getDouyinVideoUrl(item.aweme_id)}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-flex items-center gap-1 text-xs text-primary hover:underline"
        >
          目标视频 {item.aweme_id}
          {/* 报告 通病20：链接已带文案，图标只是装饰 */}
          <ExternalLink className="size-3" aria-hidden="true" />
        </a>
        {event.detail && (
          <p className="mt-2 text-sm text-muted-foreground">{event.detail}</p>
        )}
        {event.has_screenshot && detailId && (
          <InteractionEvidence interactionId={detailId} event={event} />
        )}
      </div>
    )
  }

  return (
    <div className="page-stack">
      <PageHero
        compact
        title="互动任务"
        actions={
          <div className="flex flex-wrap gap-1.5">
            {/* 报告 A14：刷新指示器替换原「刷新」按钮，展示上次更新时间 */}
            <RefreshIndicator
              updatedAt={interactions.dataUpdatedAt}
              refreshing={interactions.isFetching}
              onRefresh={() => void interactions.refetch()}
            />
            <Button
              size="sm"
              variant="outline"
              disabled={retryAll.isPending || !hasRetryable}
              onClick={async () => {
                // 报告 O15：改用统一确认框（原来是 window.confirm）
                const ok = await confirmDialog({
                  title: "重试全部可重试项？",
                  description:
                    "将重新调度全部尚未成功且当前不在发送中的互动任务；发送中的任务不会重复提交。",
                  confirmText: "重试",
                })
                if (ok) retryAll.mutate()
              }}
            >
              <RotateCcw
                aria-hidden="true"
                className={retryAll.isPending ? "animate-spin" : undefined}
              />
              {retryAll.isPending
                ? retryAllProgress
                  ? `已重试 ${retryAllProgress.done} / ${retryAllProgress.total}`
                  : "正在重试全部"
                : "重试全部可重试项"}
            </Button>
            {retryAll.isPending && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  // 只置标记，当前批次跑完即停，避免把在途请求打断成半途状态
                  retryAllAbortRef.current = true
                }}
              >
                取消
              </Button>
            )}
          </div>
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <TrackSelect
            value={trackId}
            onValueChange={(value) => {
              setTrackId(value)
              setSourceValue(allSourcesValue)
              setDetailId(null)
              setMonitorId(null)
            }}
            includeAll
            allowDisabled
            autoSelectDefault={false}
            className="h-9 min-w-44"
            ariaLabel="按赛道筛选互动任务"
          />
          <SourceSelect
            trackId={trackId}
            value={sourceValue}
            onValueChange={setSourceValue}
            className="h-9 min-w-48"
            ariaLabel="按关键词或作者筛选互动任务"
          />
          <Select
            value={statusFilter}
            onValueChange={(value) => setStatusFilter(value as StatusFilter)}
          >
            <SelectTrigger className="h-9 w-40" aria-label="按互动任务状态筛选">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部状态</SelectItem>
              <SelectItem value="pending_confirmation">待确认</SelectItem>
              <SelectItem value="queued">排队中</SelectItem>
              <SelectItem value="running">发送中</SelectItem>
              <SelectItem value="succeeded">已成功</SelectItem>
              <SelectItem value="failed">失败</SelectItem>
              <SelectItem value="blocked">已暂停</SelectItem>
              <SelectItem value="needs_review">待人工核对</SelectItem>
              <SelectItem value="cancelled">已取消</SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={typeFilter}
            onValueChange={(value) => setTypeFilter(value as TypeFilter)}
          >
            <SelectTrigger className="h-9 w-40" aria-label="按互动类型筛选">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部类型</SelectItem>
              <SelectItem value="video_comment">视频评论</SelectItem>
              <SelectItem value="comment_reply">评论回复</SelectItem>
              <SelectItem value="creator_message">作者私信</SelectItem>
            </SelectContent>
          </Select>
          {/* 报告 A1：列可见性设置，放在筛选栏右端（ml-auto 推到行尾） */}
          <TableColumnMenu {...menuProps} className="ml-auto" />
        </div>
        <div className="mt-2 space-y-2">
          {/* 报告 A10：筛选预设，把高频筛选组合存到本地一键复用 */}
          <FilterPresetBar
            storageKey="douyin-interactions-filter-presets"
            currentFilters={{
              status: statusFilter,
              type: typeFilter,
              trackId,
              sourceValue,
            }}
            onApply={(filters) => {
              setStatusFilter(filters.status)
              setTypeFilter(filters.type)
              setTrackId(filters.trackId)
              setSourceValue(filters.sourceValue)
              setDetailId(null)
              setMonitorId(null)
            }}
          />
          {/* 报告 A2：筛选 chips，展示已应用的筛选并可单个移除 */}
          <FilterChips
            chips={[
              statusFilter !== "all" && {
                key: "status",
                label: "状态",
                value: interactionStatusLabels[statusFilter],
                onRemove: () => setStatusFilter("all"),
              },
              typeFilter !== "all" && {
                key: "type",
                label: "类型",
                value: interactionTypeLabels[typeFilter],
                onRemove: () => setTypeFilter("all"),
              },
              trackId !== allTracksValue && {
                key: "track",
                label: "赛道",
                value: trackName ?? trackId,
                // 赛道变化会重建来源选项，一并复位来源筛选
                onRemove: () => {
                  setTrackId(allTracksValue)
                  setSourceValue(allSourcesValue)
                },
              },
              sourceValue !== allSourcesValue && {
                key: "source",
                label: "来源",
                value: sourceName ?? "已选择的来源",
                onRemove: () => setSourceValue(allSourcesValue),
              },
            ]}
            onClearAll={clearAllFilters}
          />
        </div>
      </PageHero>

      <Card>
        <CardContent className="space-y-3 p-3">
          {interactions.isError ? (
            <QueryErrorState
              title="互动任务加载失败"
              description="无法获取互动任务列表，可能是网络或后端服务异常，请重试。"
              onRetry={() => interactions.refetch()}
              retrying={interactions.isFetching}
            />
          ) : (
            <div className="overflow-x-auto rounded-xl border">
              {/* 报告 通病21：7 列 + 冻结操作列，窄屏给出最小宽度避免列被压扁 */}
              <Table className="min-w-[960px]">
                <TableHeader>
                  <TableRow>
                    {/* 报告 A1：列可见性 —— 表头与下方每一行的单元格必须成对包裹，
                        漏一处就会整列错位 */}
                    {isVisible("type") && <TableHead>类型 / 目标</TableHead>}
                    {isVisible("source") && <TableHead>来源</TableHead>}
                    {isVisible("content") && (
                      <TableHead>互动内容 / 目标内容</TableHead>
                    )}
                    {isVisible("account") && <TableHead>账号</TableHead>}
                    {isVisible("status") && <TableHead>状态</TableHead>}
                    {isVisible("updated") && <TableHead>更新时间</TableHead>}
                    {/* 报告 A8：操作列冻结，横向滚动时始终可见 */}
                    {/* 报告 A1：操作列 alwaysVisible，不参与隐藏 */}
                    <TableHead className="sticky right-0 z-10 bg-background/95 text-right backdrop-blur">
                      操作
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.length ? (
                    rows.map((item) => (
                      // 报告 A7：行右键菜单，把低频操作从拥挤的操作列挪出去
                      <RowContextMenu
                        key={item.id}
                        label={item.id}
                        items={rowMenuItems(item)}
                      >
                        <TableRow
                          // 报告 A6：数据变化的行闪一下
                          className={cn(
                            highlighted.has(item.id) && "row-highlight",
                          )}
                        >
                          {/* 报告 A1：列可见性 —— 数据行的每个单元格都要与表头成对包裹 */}
                          {isVisible("type") && (
                            <TableCell>
                              <div className="flex flex-wrap items-center gap-2">
                                <p className="font-medium">
                                  {interactionTypeLabels[item.interaction_type]}
                                </p>
                                {item.batch_id && (
                                  <Badge variant="outline">
                                    批量 #{(item.sequence_index ?? 0) + 1}
                                  </Badge>
                                )}
                              </div>
                              <div className="mt-1 flex flex-wrap items-center gap-2">
                                <a
                                  href={
                                    item.target_video_url ||
                                    getDouyinVideoUrl(item.aweme_id)
                                  }
                                  target="_blank"
                                  rel="noreferrer"
                                  className="inline-flex items-center gap-1 font-mono text-xs text-primary hover:underline"
                                >
                                  视频 {item.aweme_id}
                                  {/* 报告 通病20：链接已带文案，图标只是装饰 */}
                                  <ExternalLink
                                    className="size-3"
                                    aria-hidden="true"
                                  />
                                </a>
                                <Link
                                  to="/douyin/$taskId"
                                  params={{ taskId: item.task_id }}
                                  className="text-xs text-muted-foreground hover:text-primary"
                                >
                                  查看采集任务
                                </Link>
                              </div>
                            </TableCell>
                          )}
                          {isVisible("source") && (
                            <TableCell>
                              <SourceBadge
                                sourceType={item.source_type}
                                sourceLabel={item.source_label}
                                className="max-w-52"
                              />
                            </TableCell>
                          )}
                          {isVisible("content") && (
                            <TableCell className="max-w-md">
                              <InteractionContentSummary
                                interactionType={item.interaction_type}
                                targetCommentId={item.target_comment_id}
                                targetCommentContent={
                                  item.target_comment_content
                                }
                                content={item.content_preview}
                                compact
                              />
                              {item.error && (
                                <p className="mt-1 line-clamp-2 text-xs text-destructive">
                                  {item.failure_code}: {item.error}
                                </p>
                              )}
                            </TableCell>
                          )}
                          {isVisible("account") && (
                            <TableCell>
                              {item.account_name || "账号已删除"}
                            </TableCell>
                          )}
                          {isVisible("status") && (
                            <TableCell>
                              <InteractionStatusBadge status={item.status} />
                            </TableCell>
                          )}
                          {isVisible("updated") && (
                            <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                              {/* 计划时间是未来时点，相对时间会显示成「刚刚」，这里保留绝对时间 */}
                              {item.scheduled_at && (
                                <p>计划 {formatDateTime(item.scheduled_at)}</p>
                              )}
                              {/* 报告 A16：时间点改用相对时间，悬停查看绝对时间 */}
                              <p>
                                更新 <TimeAgo value={item.updated_at} />
                              </p>
                            </TableCell>
                          )}
                          {/* 报告 A8：操作列冻结，横向滚动时始终可见 */}
                          <TableCell className="sticky right-0 bg-background/95 backdrop-blur">
                            <div className="flex justify-end gap-1">
                              {/* 报告 O10：操作列只留高频操作，其余收进「更多」菜单 */}
                              <Button
                                size="icon-sm"
                                variant="ghost"
                                aria-label="查看详情"
                                onClick={() => setDetailId(item.id)}
                              >
                                <Eye />
                              </Button>
                              {item.can_confirm && (
                                <Button
                                  size="sm"
                                  onClick={() => confirm.mutate(item.id)}
                                >
                                  确认发送
                                </Button>
                              )}
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <Button
                                    size="icon-sm"
                                    variant="ghost"
                                    aria-label="更多操作"
                                  >
                                    <MoreHorizontal />
                                  </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end">
                                  <DropdownMenuItem
                                    onSelect={() => setMonitorId(item.id)}
                                  >
                                    <MonitorPlay aria-hidden="true" />
                                    查看实时监控
                                  </DropdownMenuItem>
                                  {canShowInteractionRetry(item) && (
                                    <DropdownMenuItem
                                      onSelect={() =>
                                        void retryAfterReview(
                                          item,
                                          retry.mutate,
                                        )
                                      }
                                    >
                                      <RotateCcw aria-hidden="true" />
                                      重试
                                    </DropdownMenuItem>
                                  )}
                                  {item.can_cancel && (
                                    <DropdownMenuItem
                                      variant="destructive"
                                      onSelect={() => cancel.mutate(item.id)}
                                    >
                                      <XCircle aria-hidden="true" />
                                      取消任务
                                    </DropdownMenuItem>
                                  )}
                                </DropdownMenuContent>
                              </DropdownMenu>
                            </div>
                          </TableCell>
                        </TableRow>
                      </RowContextMenu>
                    ))
                  ) : interactions.isLoading ? (
                    // 报告 A4/O8：首次加载用骨架屏而不是「加载互动任务...」一行字，
                    // 行数与真实列表接近，数据到达时不会整页跳动。
                    Array.from({ length: 6 }, (_, index) => (
                      <TableRow key={`interactions-skeleton-${index}`}>
                        <TableCell colSpan={visibleCount} className="py-3">
                          <Skeleton className="h-9 w-full rounded-lg" />
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={visibleCount} className="p-0">
                        {/* 报告 A4/O8：空态给「图标 + 标题 + 说明 + 主行动按钮」，
                            筛没了就一键清除筛选，真的没数据就引导去创建互动任务 */}
                        <EmptyState
                          compact
                          icon={Inbox}
                          title={
                            hasActiveFilters
                              ? "没有符合当前条件的互动任务"
                              : "还没有互动任务"
                          }
                          description={
                            hasActiveFilters
                              ? "可以放宽赛道、来源、状态或类型的筛选条件后再试。"
                              : "互动任务会在采集到的视频或评论上创建，创建后这里会显示发送进度。"
                          }
                          action={
                            hasActiveFilters ? (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={clearAllFilters}
                              >
                                清除筛选条件
                              </Button>
                            ) : (
                              <Button size="sm" variant="outline" asChild>
                                <Link to="/douyin">去看采集任务</Link>
                              </Button>
                            )
                          }
                        />
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={Boolean(detailId)} onOpenChange={() => setDetailId(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>互动任务详情</DialogTitle>
            <DialogDescription>
              完整内容仅对任务所有者可见，不会写入应用日志。
            </DialogDescription>
          </DialogHeader>
          {detail.data ? (
            <div className="space-y-5">
              {detail.data.status === "needs_review" && (
                <Alert>
                  <ShieldCheck aria-hidden="true" />
                  <AlertTitle>需要人工检查</AlertTitle>
                  <AlertDescription>
                    请先打开抖音确认内容没有发送成功，再执行重试，以免重复发送。
                  </AlertDescription>
                </Alert>
              )}
              <div className="rounded-xl border bg-muted/25 p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="font-medium">
                    {interactionTypeLabels[detail.data.interaction_type]}
                  </p>
                  <InteractionStatusBadge status={detail.data.status} />
                </div>
                <div className="mt-3">
                  <InteractionContentSummary
                    interactionType={detail.data.interaction_type}
                    targetCommentId={detail.data.target_comment_id}
                    targetCommentContent={detail.data.target_comment_content}
                    content={detail.data.content}
                  />
                </div>
                <div className="mt-3 flex flex-wrap gap-2 border-t pt-3">
                  <Button variant="outline" size="sm" asChild>
                    <a
                      href={
                        detail.data.target_video_url ||
                        getDouyinVideoUrl(detail.data.aweme_id)
                      }
                      target="_blank"
                      rel="noreferrer"
                    >
                      <ExternalLink aria-hidden="true" />
                      打开抖音视频 {detail.data.aweme_id}
                    </a>
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setMonitorId(detail.data.id)}
                  >
                    <MonitorPlay aria-hidden="true" />
                    查看实时监控
                  </Button>
                </div>
              </div>
              <div>
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h3 className="font-medium">浏览器操作日志</h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      自动记录关键浏览器操作；截图仅任务所有者可查看。
                    </p>
                  </div>
                  <Badge variant="outline">
                    <Camera aria-hidden="true" />
                    {screenshotCount} 张截图
                  </Badge>
                </div>
                {/* 报告 O19：事件列表自带滚动容器，长任务只渲染可视区内的卡片；
                    事件数未超过阈值时（virtualizeEvents 为 false）完全走原来的
                    「逐条渲染 + space-y-4」路径，短列表零行为变化。
                    pl-2 是给时间轴圆点留的余量：滚动容器的 padding box 左边缘才是
                    裁剪边界，圆点（-left-[1.3rem]）会压在这条线上，不留余量会被切掉一半。 */}
                <div
                  ref={eventsScrollRef}
                  className="mt-4 max-h-[55vh] overflow-y-auto pl-2"
                >
                  <div className="border-l pr-1 pl-4">
                    {virtualizeEvents ? (
                      <div
                        style={{
                          height: eventsTotalSize,
                          position: "relative",
                        }}
                      >
                        {eventVirtualItems.map((virtualRow) => (
                          <div
                            key={events[virtualRow.index].id}
                            data-index={virtualRow.index}
                            ref={eventsVirtualizer.measureElement}
                            className="pb-4"
                            style={{
                              position: "absolute",
                              top: 0,
                              left: 0,
                              width: "100%",
                              transform: `translateY(${virtualRow.start}px)`,
                            }}
                          >
                            {renderEventCard(events[virtualRow.index])}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="space-y-4">
                        {events.map((event) => renderEventCard(event))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            // 报告 A4/O8：加载态用骨架屏，保持与详情内容接近的块状结构
            <div className="space-y-4">
              <span className="sr-only">正在加载互动任务详情</span>
              <Skeleton className="h-28 w-full rounded-xl" />
              <Skeleton className="h-10 w-2/3 rounded-lg" />
              <Skeleton className="h-20 w-full rounded-xl" />
              <Skeleton className="h-20 w-full rounded-xl" />
              <Skeleton className="h-20 w-full rounded-xl" />
            </div>
          )}
        </DialogContent>
      </Dialog>
      <InteractionLiveMonitor
        interactionId={monitorId}
        open={Boolean(monitorId)}
        onOpenChange={(open) => !open && setMonitorId(null)}
      />
    </div>
  )
}

async function retryAfterReview(
  item: DouyinInteractionPublic,
  retry: (item: DouyinInteractionPublic) => void,
) {
  // 报告 O15：改用统一确认框（原来是 window.confirm）
  if (item.status === "needs_review") {
    const ok = await confirmDialog({
      title: "确认这条内容没有发送成功？",
      description:
        "请先到抖音页面确认内容未发送成功再重试，以免重复发送相同内容。",
      confirmText: "重试",
    })
    if (!ok) return
  }
  retry(item)
}

const interactionEventLabels: Record<string, string> = {
  created: "已创建互动任务",
  confirmed: "用户已确认发送",
  retried: "用户已确认重试",
  started: "开始执行互动任务",
  succeeded: "互动任务执行成功",
  execution_failed: "互动任务执行失败",
  cancelled: "互动任务已取消",
  worker_cancelled: "执行进程被中断",
  service_restarted: "服务重启时恢复任务",
  browser_browser_connected: "连接账号浏览器",
  browser_login_verified: "验证账号登录状态",
  browser_video_opened: "打开目标视频",
  browser_comment_editor_ready: "打开评论输入框",
  browser_reply_target_found: "定位目标评论",
  browser_reply_editor_ready: "打开回复输入框",
  browser_creator_profile_opened: "打开作者主页",
  browser_message_editor_ready: "打开私信窗口",
  browser_content_filled: "填写互动内容",
  browser_submit_triggered: "触发发送",
  browser_platform_accepted: "平台确认接收",
  browser_execution_failed: "保留异常页面现场",
}

function interactionEventLabel(event: string) {
  return interactionEventLabels[event] || event.replace(/_/g, " ")
}

function InteractionEvidence({
  interactionId,
  event,
}: {
  interactionId: string
  event: DouyinInteractionEventPublic
}) {
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)
  // 是否已滚动进入视口；只有进入视口才发起截图请求
  const [visible, setVisible] = useState(false)

  // 懒加载：原实现每个事件一挂载就立刻 fetch + createObjectURL，一次展开详情
  // 有几十个事件时会瞬间产生 50+ 并发请求，同时占用大量 blob 内存。
  // 这里改为滚动进入视口（提前 200px）才加载，离开视口的判断由浏览器代理。
  useEffect(() => {
    if (!event.has_screenshot) return
    const node = containerRef.current
    if (!node) return
    if (typeof IntersectionObserver === "undefined") {
      setVisible(true)
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true)
          observer.disconnect()
        }
      },
      { rootMargin: "200px" },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [event.has_screenshot])

  useEffect(() => {
    if (!event.has_screenshot || !visible) return
    const controller = new AbortController()
    let objectUrl: string | null = null
    const load = async () => {
      try {
        const token = readStorage("access_token")
        const response = await fetch(
          `${interactionApiBase()}/api/v1/douyin/interactions/${interactionId}/events/${event.id}/screenshot`,
          {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            signal: controller.signal,
          },
        )
        if (!response.ok) throw new Error(`截图加载失败 (${response.status})`)
        objectUrl = URL.createObjectURL(await response.blob())
        setImageUrl(objectUrl)
      } catch (reason) {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "截图加载失败")
        }
      }
    }
    void load()
    // 卸载（或依赖变化）时中断请求并回收已创建的 objectURL，懒加载后仍需保证不泄漏
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [visible, event.has_screenshot, event.id, interactionId])

  return (
    <div ref={containerRef} className="mt-3">
      {error ? (
        <div className="flex h-24 items-center justify-center gap-2 rounded-lg border border-dashed text-xs text-muted-foreground">
          <ImageOff className="size-4" aria-hidden="true" />
          {error}
        </div>
      ) : !imageUrl ? (
        // 报告 A4/O8：截图加载态改用骨架屏，占位高度与图片容器一致，不会跳动
        <Skeleton className="h-24 w-full rounded-lg" />
      ) : (
        <>
          <button
            type="button"
            className="group relative block w-full overflow-hidden rounded-lg border bg-black text-left"
            onClick={() => setExpanded(true)}
            aria-label="查看操作截图大图"
          >
            <img
              src={imageUrl}
              alt={`${interactionEventLabel(event.event)}操作截图`}
              className="max-h-52 w-full object-contain transition group-hover:opacity-80"
            />
            <span className="absolute right-2 bottom-2 flex items-center gap-1 rounded-md bg-black/70 px-2 py-1 text-xs text-white">
              <ZoomIn className="size-3.5" aria-hidden="true" />
              查看大图
            </span>
          </button>
          <Dialog open={expanded} onOpenChange={setExpanded}>
            <DialogContent className="sm:max-w-6xl">
              <DialogHeader>
                <DialogTitle>{interactionEventLabel(event.event)}</DialogTitle>
                <DialogDescription>
                  第 {event.attempt_number || 1} 次执行 ·{" "}
                  {formatDateTime(event.created_at)}
                </DialogDescription>
              </DialogHeader>
              <div className="overflow-hidden rounded-lg border bg-black">
                <img
                  src={imageUrl}
                  alt={`${interactionEventLabel(event.event)}操作截图大图`}
                  className="max-h-[72vh] w-full object-contain"
                />
              </div>
            </DialogContent>
          </Dialog>
        </>
      )}
    </div>
  )
}

function interactionApiBase() {
  return new URL(OpenAPI.BASE || window.location.origin, window.location.origin)
    .toString()
    .replace(/\/$/, "")
}
