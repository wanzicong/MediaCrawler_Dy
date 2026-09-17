import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ArrowLeft,
  ArrowRight,
  ChevronDown,
  ClipboardList,
  KeyRound,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  SearchX,
  Target,
  Trash2,
  UsersRound,
} from "lucide-react"
import { type FormEvent, useEffect, useMemo, useRef, useState } from "react"

import {
  ApiError,
  type CrawlTaskPublic,
  type DouyinCreatorPublic,
  type DouyinCreatorStatus,
  DouyinCreatorsService,
  type DouyinKeywordPublic,
  type DouyinKeywordStatus,
  DouyinKeywordsService,
  DouyinService,
  type DouyinTrackDetailPublic,
  DouyinTracksService,
} from "@/client"
import { confirmDialog } from "@/components/Common/confirm-dialog"
import { EmptyState } from "@/components/Common/EmptyState"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { TableColumnMenu } from "@/components/Common/TableColumnMenu"
import { creatorNameLabel } from "@/components/Douyin/presentation"
import {
  TaskGroupToggle,
  usePersistentGroupMode,
} from "@/components/Douyin/TaskGrouping"
import { TaskIdentity } from "@/components/Douyin/TaskIdentity"
import {
  activeTaskStatuses,
  TaskStatusBadge,
} from "@/components/Douyin/TaskStatusBadge"
import { DOUYIN_TASK_PARAMETER_DEFAULTS } from "@/components/Douyin/taskParameters"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
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
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import { useHighlightedRows } from "@/hooks/useHighlightedRows"
import { type TableColumnDef, useTableColumns } from "@/hooks/useTableColumns"
import { formatDateTime } from "@/lib/time"
import { cn } from "@/lib/utils"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/douyin-tracks_/$trackId")({
  component: DouyinTrackDetailPage,
  head: () => ({ meta: [{ title: "赛道详情 - 灵感采集台" }] }),
})

const keywordStatusLabels: Record<DouyinKeywordStatus, string> = {
  unprocessed: "未爬取",
  active: "进行中",
  crawled: "已爬取",
  failed: "需重试",
}

const creatorStatusLabels: Record<DouyinCreatorStatus, string> = {
  unprocessed: "未爬取",
  active: "进行中",
  crawled: "已爬取",
  failed: "需重试",
}

// 报告 A1：列可见性 —— 赛道关键词表的列清单。
// 必须是模块级稳定常量，放在组件里每次新建会让勾选状态被重置。
const KEYWORD_COLUMNS = [
  // 选择列自带表头复选框，藏掉就没法批量操作，永不可隐藏
  { key: "select", title: "选择", alwaysVisible: true },
  { key: "keyword", title: "关键词" },
  { key: "status", title: "状态" },
  { key: "counts", title: "任务 / 作品" },
  // 操作列一律常显，隐藏后用户无法编辑/移除
  { key: "actions", title: "操作", alwaysVisible: true },
] as const satisfies readonly TableColumnDef[]

function parseLibraryLines(value: string): string[] {
  const seen = new Set<string>()
  return value
    .split(/\r?\n/)
    .map((item) => item.trim().replace(/\s+/g, " "))
    .filter((item) => {
      const normalized = item.toLocaleLowerCase("zh-CN")
      if (!item || seen.has(normalized)) return false
      seen.add(normalized)
      return true
    })
    .slice(0, 100)
}

function DouyinTrackDetailPage() {
  const { trackId } = Route.useParams()
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [search, setSearch] = useState("")
  const [keywordFilter, setKeywordFilter] = useState<"all" | "without_tasks">(
    "all",
  )
  const [selectedKeywordIds, setSelectedKeywordIds] = useState<Set<string>>(
    new Set(),
  )
  const [searchCreators, setSearchCreators] = useState("")
  const [addOpen, setAddOpen] = useState(false)
  const [addCreatorsOpen, setAddCreatorsOpen] = useState(false)
  const [editingKeyword, setEditingKeyword] =
    useState<DouyinKeywordPublic | null>(null)
  const [removingKeyword, setRemovingKeyword] =
    useState<DouyinKeywordPublic | null>(null)
  const [editingCreator, setEditingCreator] =
    useState<DouyinCreatorPublic | null>(null)
  const [removingCreator, setRemovingCreator] =
    useState<DouyinCreatorPublic | null>(null)
  const [resetOpen, setResetOpen] = useState(false)

  const trackQuery = useQuery({
    queryKey: ["douyin-track", trackId],
    queryFn: () => DouyinTracksService.getTrack({ trackId }),
    retry: false,
    // 只有赛道仍有进行中任务时才轮询；空闲即停止，避免本页多路轮询长期空转
    refetchInterval: (query) =>
      (query.state.data?.active_task_count ?? 0) > 0 ? 10_000 : false,
  })
  // 已知问题：关键词/达人接口都是无分页全量返回，数据量大时首屏会明显变慢，
  // 后续应改为服务端分页（本次改造不动接口参数）。
  const keywordsQuery = useQuery({
    queryKey: ["douyin-track-keywords", trackId],
    queryFn: () => DouyinTracksService.listTrackKeywords({ trackId }),
    retry: false,
    // 关键词状态里只有 active 表示「进行中」，其余都是终态
    refetchInterval: (query) =>
      query.state.data?.data.some((item) => item.status === "active")
        ? 10_000
        : false,
  })
  const creatorsQuery = useQuery({
    queryKey: ["douyin-track-creators", trackId],
    queryFn: () => DouyinTracksService.listTrackCreators({ trackId }),
    retry: false,
    // 同上：达人全部进入终态后不再轮询
    refetchInterval: (query) =>
      query.state.data?.data.some((item) => item.status === "active")
        ? 10_000
        : false,
  })
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["douyin-track", trackId] }),
      queryClient.invalidateQueries({
        queryKey: ["douyin-track-keywords", trackId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["douyin-track-creators", trackId],
      }),
      queryClient.invalidateQueries({ queryKey: ["douyin-tracks"] }),
      queryClient.invalidateQueries({ queryKey: ["douyin-keywords"] }),
      queryClient.invalidateQueries({ queryKey: ["douyin-creators"] }),
    ])
  }
  const unlink = useMutation({
    mutationFn: (keywordId: string) =>
      DouyinTracksService.removeTrackKeyword({ trackId, keywordId }),
    onSuccess: async () => {
      setRemovingKeyword(null)
      showSuccessToast("关键词已移回默认赛道，历史任务与内容数据已保留")
      await refresh()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const deleteKeywords = useMutation({
    mutationFn: (keywordIds: string[]) =>
      DouyinKeywordsService.bulkDeleteKeywords({
        requestBody: { ids: keywordIds },
      }),
    onSuccess: async (result) => {
      setSelectedKeywordIds(new Set())
      showSuccessToast(result.message)
      await refresh()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const removeCreator = useMutation({
    mutationFn: (creatorId: string) =>
      DouyinTracksService.removeTrackCreator({ trackId, creatorId }),
    onSuccess: async () => {
      setRemovingCreator(null)
      showSuccessToast("达人已移回默认赛道，历史任务与内容数据已保留")
      await refresh()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const resetTrack = useMutation({
    mutationFn: () => DouyinTracksService.resetTrack({ trackId }),
    onSuccess: async (result) => {
      setResetOpen(false)
      setSelectedKeywordIds(new Set())
      showSuccessToast(result.message)
      await refresh()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })

  const keywords = keywordsQuery.data?.data ?? []
  const creators = creatorsQuery.data?.data ?? []
  // 关键词/达人的筛选是纯客户端全量遍历，包 useMemo 避免轮询 tick、勾选等
  // 与筛选条件无关的重渲染都重新扫一遍整个列表。
  const term = search.trim().toLocaleLowerCase("zh-CN")
  const filteredKeywords = useMemo(
    () =>
      keywordFilter === "without_tasks"
        ? keywords.filter((item) => item.task_count === 0)
        : keywords,
    [keywords, keywordFilter],
  )
  const visibleKeywords = useMemo(
    () =>
      term
        ? filteredKeywords.filter(
            (item) =>
              item.keyword.toLocaleLowerCase("zh-CN").includes(term) ||
              item.notes.toLocaleLowerCase("zh-CN").includes(term),
          )
        : filteredKeywords,
    [filteredKeywords, term],
  )
  const visibleKeywordIds = visibleKeywords.map((item) => item.id)
  const creatorTerm = searchCreators.trim().toLocaleLowerCase("zh-CN")
  const visibleCreators = useMemo(
    () =>
      creatorTerm
        ? creators.filter(
            (item) =>
              item.nickname.toLocaleLowerCase("zh-CN").includes(creatorTerm) ||
              item.sec_uid.toLocaleLowerCase("zh-CN").includes(creatorTerm) ||
              item.notes.toLocaleLowerCase("zh-CN").includes(creatorTerm),
          )
        : creators,
    [creators, creatorTerm],
  )
  // 报告 A6：轮询刷新后采集状态发生变化的关键词/达人行会短暂高亮，指纹取 status
  const highlightedKeywordIds = useHighlightedRows(
    keywords,
    (item) => item.id,
    (item) => item.status,
  )
  const highlightedCreatorIds = useHighlightedRows(
    creators,
    (item) => item.id,
    (item) => item.status,
  )
  // 报告 A1：列可见性 —— 赛道关键词表（达人表不接入）
  const {
    isVisible: isKeywordColumnVisible,
    visibleCount: keywordVisibleCount,
    menuProps: keywordColumnMenuProps,
  } = useTableColumns({
    storageKey: "douyin-track-keywords-columns",
    columns: KEYWORD_COLUMNS,
  })
  // 报告 A4/O8：空态要区分「筛选后为空」与「确实没有数据」
  // 前者给「清除筛选」，后者给创建入口，避免空态变成死胡同
  const keywordsEmptyByFilter =
    Boolean(term) || keywordFilter === "without_tasks"
  const creatorsEmptyByFilter = Boolean(creatorTerm)

  if (trackQuery.isLoading) {
    // 报告 A4/O8：加载态改用骨架屏并保留页面结构，数据到达时不会整页跳动
    return (
      <div className="space-y-3">
        <Card className="gap-0 overflow-hidden py-0">
          <CardContent className="space-y-3 p-3">
            <Skeleton className="h-7 w-56" />
            <Skeleton className="h-4 w-full max-w-xl" />
            <div className="flex flex-wrap gap-2">
              <Skeleton className="h-8 w-28" />
              <Skeleton className="h-8 w-32" />
            </div>
          </CardContent>
        </Card>
        <Skeleton className="h-9 w-80 rounded-xl" />
        <Card>
          <CardContent className="space-y-2 p-4">
            {Array.from({ length: 6 }, (_, index) => (
              <Skeleton
                key={`track-detail-skeleton-${index}`}
                className="h-12 w-full rounded-xl"
              />
            ))}
          </CardContent>
        </Card>
      </div>
    )
  }
  if (!trackQuery.data || trackQuery.isError) {
    const unavailable =
      trackQuery.error instanceof ApiError &&
      [403, 404].includes(trackQuery.error.status)
    return (
      <div className="space-y-3">
        <QueryErrorState
          title={
            unavailable ? "赛道不存在或当前账号无权访问" : "赛道详情读取失败"
          }
          description={
            unavailable
              ? "该赛道可能已被删除，或当前账号没有访问权限；可返回赛道列表选择其他赛道。"
              : "暂时无法获取赛道详情，请检查服务连接后重试。"
          }
          onRetry={() => void trackQuery.refetch()}
          retrying={trackQuery.isFetching}
        />
        <div className="text-center">
          {/* 赛道列表的 search 三个字段都是可选的，显式补齐以匹配路由声明 */}
          <Button variant="outline" asChild>
            <Link
              to="/douyin-tracks"
              search={{
                run: undefined,
                search: undefined,
                viewMode: undefined,
              }}
            >
              返回赛道列表
            </Link>
          </Button>
        </div>
      </div>
    )
  }

  const track = trackQuery.data
  const allVisibleKeywordsSelected =
    visibleKeywordIds.length > 0 &&
    visibleKeywordIds.every((id) => selectedKeywordIds.has(id))
  const someVisibleKeywordsSelected = visibleKeywordIds.some((id) =>
    selectedKeywordIds.has(id),
  )
  return (
    <div className="space-y-3">
      <Card className="gap-0 overflow-hidden py-0">
        <CardContent className="p-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              {/* 同上：赛道列表的 search 字段全为可选，显式补齐并清空 run */}
              <Button variant="ghost" size="sm" className="-ml-2 h-7" asChild>
                <Link
                  to="/douyin-tracks"
                  search={{
                    run: undefined,
                    search: undefined,
                    viewMode: undefined,
                  }}
                >
                  <ArrowLeft /> 返回赛道列表
                </Link>
              </Button>
              <div className="mt-1 flex items-center gap-2">
                <span className="flex size-8 items-center justify-center rounded-lg bg-violet-500/12 text-violet-700 dark:text-violet-300">
                  <Target aria-hidden="true" className="size-4" />
                </span>
                <h1 className="truncate text-xl font-semibold">{track.name}</h1>
                <Badge variant={track.enabled ? "default" : "secondary"}>
                  配置：{track.enabled ? "启用" : "停用"}
                </Badge>
                {track.is_default && <Badge variant="outline">默认赛道</Badge>}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
                <span className="font-medium">最近一次采集</span>
                {track.last_task_status ? (
                  <TaskStatusBadge status={track.last_task_status} />
                ) : (
                  <Badge variant="outline">尚未运行</Badge>
                )}
                {track.last_run_at && (
                  <span>{formatDateTime(track.last_run_at)}</span>
                )}
                {track.last_task_id && (
                  <Link
                    to="/douyin/$taskId"
                    params={{ taskId: track.last_task_id }}
                    className="font-medium text-primary hover:underline"
                  >
                    查看任务
                  </Link>
                )}
                <InlineData
                  label="关键词"
                  value={`${track.enabled_keyword_count}/${track.keyword_count}`}
                />
                <InlineData
                  label="任务"
                  value={track.task_count}
                  detail={`${track.active_task_count} 运行中`}
                />
                <InlineData label="作品" value={track.aweme_count} />
                <InlineData label="评论" value={track.comment_count} />
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => setResetOpen(true)}
              >
                <RefreshCw /> 重置赛道
              </Button>
              {/* 带 run 跳到赛道列表，直接打开该赛道的运营工作区 */}
              <Button size="sm" asChild>
                <Link
                  to="/douyin-tracks"
                  search={{
                    run: track.id,
                    search: undefined,
                    viewMode: undefined,
                  }}
                >
                  启动赛道采集
                </Link>
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="keywords" className="space-y-3">
        <TabsList>
          <TabsTrigger value="keywords">
            关键词（{track.keyword_count}）
          </TabsTrigger>
          <TabsTrigger value="creators">达人（{creators.length}）</TabsTrigger>
          <TabsTrigger value="tasks">任务（{track.task_count}）</TabsTrigger>
          <TabsTrigger value="settings">赛道设置</TabsTrigger>
        </TabsList>
        <TabsContent value="keywords">
          <Card>
            <CardHeader className="space-y-0 p-4 pb-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <CardTitle className="text-base">赛道关键词</CardTitle>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    每个关键词唯一归属一个赛道；移动后，后续任务与筛选会使用新归属。
                  </p>
                </div>
                <Button
                  size="sm"
                  disabled={keywordsQuery.isError}
                  onClick={() => setAddOpen(true)}
                >
                  <Plus /> 添加或移动关键词
                </Button>
              </div>
            </CardHeader>
            <CardContent className="p-4 pt-2">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <div className="relative min-w-56 flex-1 sm:max-w-sm">
                  <Search
                    aria-hidden="true"
                    className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                  />
                  <Input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="筛选当前赛道关键词"
                    aria-label="筛选当前赛道关键词"
                    className="h-8 pl-9"
                  />
                </div>
                <div className="flex rounded-md border bg-muted/30 p-0.5">
                  <Button
                    type="button"
                    size="sm"
                    variant={keywordFilter === "all" ? "secondary" : "ghost"}
                    className="h-7 px-2.5"
                    onClick={() => setKeywordFilter("all")}
                  >
                    全部 {keywords.length}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant={
                      keywordFilter === "without_tasks" ? "secondary" : "ghost"
                    }
                    className="h-7 px-2.5"
                    onClick={() => setKeywordFilter("without_tasks")}
                  >
                    未创建任务{" "}
                    {keywords.filter((item) => item.task_count === 0).length}
                  </Button>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  className="h-8"
                  disabled={
                    !selectedKeywordIds.size || deleteKeywords.isPending
                  }
                  onClick={async () => {
                    const selectedRows = keywords.filter((item) =>
                      selectedKeywordIds.has(item.id),
                    )
                    const taskCount = selectedRows.reduce(
                      (total, item) => total + item.task_count,
                      0,
                    )
                    // 报告 O15：改用统一确认框
                    const confirmed = await confirmDialog({
                      title: `确定永久删除选中的 ${selectedRows.length} 个关键词吗？`,
                      description: `将同时删除其独占的 ${taskCount} 个任务及对应作品、评论和互动记录；此操作不可撤销。`,
                      confirmText: "删除",
                      variant: "destructive",
                    })
                    if (!confirmed) return
                    deleteKeywords.mutate([...selectedKeywordIds])
                  }}
                >
                  <Trash2 />
                  删除选中
                  {selectedKeywordIds.size
                    ? `（${selectedKeywordIds.size}）`
                    : ""}
                </Button>
                {/* 报告 A1：列可见性入口 */}
                <TableColumnMenu {...keywordColumnMenuProps} />
              </div>
              {keywordsQuery.isError ? (
                <QueryErrorState
                  title="赛道关键词读取失败"
                  description="暂时无法获取当前赛道的关键词，请检查服务连接后重试。"
                  onRetry={() => void keywordsQuery.refetch()}
                  retrying={keywordsQuery.isFetching}
                  className="py-8"
                />
              ) : (
                <div className="max-h-[560px] overflow-auto rounded-lg border">
                  <Table>
                    <TableHeader className="sticky top-0 z-10 bg-background">
                      <TableRow>
                        {/* 报告 A1：列可见性 */}
                        {isKeywordColumnVisible("select") && (
                          <TableHead className="h-9 w-10">
                            <Checkbox
                              aria-label="选择当前筛选结果中的全部关键词"
                              checked={
                                allVisibleKeywordsSelected
                                  ? true
                                  : someVisibleKeywordsSelected
                                    ? "indeterminate"
                                    : false
                              }
                              onCheckedChange={(checked) => {
                                setSelectedKeywordIds((current) => {
                                  const next = new Set(current)
                                  for (const id of visibleKeywordIds) {
                                    if (checked) next.add(id)
                                    else next.delete(id)
                                  }
                                  return next
                                })
                              }}
                            />
                          </TableHead>
                        )}
                        {isKeywordColumnVisible("keyword") && (
                          <TableHead className="h-9">关键词</TableHead>
                        )}
                        {isKeywordColumnVisible("status") && (
                          <TableHead className="h-9">状态</TableHead>
                        )}
                        {isKeywordColumnVisible("counts") && (
                          <TableHead className="h-9">任务 / 作品</TableHead>
                        )}
                        {isKeywordColumnVisible("actions") && (
                          <TableHead className="h-9 text-right">操作</TableHead>
                        )}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {/* 报告 A4/O8：加载态保留表头与列结构，先铺骨架行再落数据 */}
                      {keywordsQuery.isLoading &&
                        Array.from({ length: 6 }, (_, rowIndex) => (
                          <TableRow
                            key={`keyword-skeleton-${rowIndex}`}
                            className="hover:bg-transparent"
                          >
                            {/* 报告 A1：列可见性 */}
                            {isKeywordColumnVisible("select") && (
                              <TableCell className="w-10 py-2">
                                <Skeleton className="size-4" />
                              </TableCell>
                            )}
                            {isKeywordColumnVisible("keyword") && (
                              <TableCell className="py-2">
                                <Skeleton className="h-4 w-40" />
                              </TableCell>
                            )}
                            {isKeywordColumnVisible("status") && (
                              <TableCell className="py-2">
                                <Skeleton className="h-5 w-16 rounded-full" />
                              </TableCell>
                            )}
                            {isKeywordColumnVisible("counts") && (
                              <TableCell className="py-2">
                                <Skeleton className="h-4 w-12" />
                              </TableCell>
                            )}
                            {isKeywordColumnVisible("actions") && (
                              <TableCell className="py-2">
                                <Skeleton className="ml-auto h-7 w-28" />
                              </TableCell>
                            )}
                          </TableRow>
                        ))}
                      {visibleKeywords.map((keyword) => (
                        <TableRow
                          key={keyword.id}
                          className={
                            highlightedKeywordIds.has(keyword.id)
                              ? "row-highlight"
                              : undefined
                          }
                        >
                          {/* 报告 A1：列可见性 */}
                          {isKeywordColumnVisible("select") && (
                            <TableCell className="w-10 py-2">
                              <Checkbox
                                aria-label={`选择关键词 ${keyword.keyword}`}
                                checked={selectedKeywordIds.has(keyword.id)}
                                onCheckedChange={(checked) => {
                                  setSelectedKeywordIds((current) => {
                                    const next = new Set(current)
                                    if (checked) next.add(keyword.id)
                                    else next.delete(keyword.id)
                                    return next
                                  })
                                }}
                              />
                            </TableCell>
                          )}
                          {isKeywordColumnVisible("keyword") && (
                            <TableCell className="max-w-60 py-2">
                              <p className="truncate font-medium">
                                {keyword.keyword}
                              </p>
                              {keyword.notes && (
                                <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
                                  {keyword.notes.startsWith("赛道：")
                                    ? `历史备注（不代表当前归属）：${keyword.notes}`
                                    : `备注：${keyword.notes}`}
                                </p>
                              )}
                            </TableCell>
                          )}
                          {isKeywordColumnVisible("status") && (
                            <TableCell className="py-2">
                              <Badge
                                variant={
                                  keyword.enabled ? "outline" : "secondary"
                                }
                                className="whitespace-nowrap"
                              >
                                {keyword.enabled
                                  ? keywordStatusLabels[keyword.status]
                                  : "已停用"}
                              </Badge>
                            </TableCell>
                          )}
                          {isKeywordColumnVisible("counts") && (
                            <TableCell className="whitespace-nowrap py-2 text-xs text-muted-foreground">
                              {keyword.task_count} / {keyword.aweme_count}
                            </TableCell>
                          )}
                          {isKeywordColumnVisible("actions") && (
                            <TableCell className="py-2">
                              <div className="flex justify-end gap-1">
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 px-2"
                                  aria-label={`编辑关键词 ${keyword.keyword}`}
                                  onClick={() => setEditingKeyword(keyword)}
                                >
                                  <Pencil /> 编辑
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 px-2 text-destructive"
                                  aria-label={`移除关键词 ${keyword.keyword}`}
                                  disabled={track.is_default}
                                  title={
                                    track.is_default
                                      ? "默认赛道的关键词不能移除，请将它移动到其他赛道"
                                      : "移回默认赛道"
                                  }
                                  onClick={() => setRemovingKeyword(keyword)}
                                >
                                  <Trash2 />
                                  {track.is_default ? "默认归属" : "移回默认"}
                                </Button>
                              </div>
                            </TableCell>
                          )}
                        </TableRow>
                      ))}
                      {!keywordsQuery.isLoading && !visibleKeywords.length && (
                        <TableRow className="hover:bg-transparent">
                          {/* 报告 A1：列可见性 —— 空态列数跟随可见列 */}
                          <TableCell
                            colSpan={keywordVisibleCount}
                            className="p-0"
                          >
                            {keywordsEmptyByFilter ? (
                              <EmptyState
                                compact
                                icon={SearchX}
                                title="没有匹配的赛道关键词"
                                description="当前搜索或筛选条件下没有关键词，清除后可以查看该赛道的全部关键词。"
                                action={
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() => {
                                      setSearch("")
                                      setKeywordFilter("all")
                                    }}
                                  >
                                    清除筛选
                                  </Button>
                                }
                              />
                            ) : (
                              <EmptyState
                                compact
                                icon={KeyRound}
                                title="当前赛道还没有关键词"
                                description="关键词是赛道采集的入口，添加后即可在本赛道下发起任务并把内容归档过来。"
                                action={
                                  <Button
                                    size="sm"
                                    onClick={() => setAddOpen(true)}
                                  >
                                    <Plus /> 添加第一个关键词
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
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="creators">
          <Card>
            <CardHeader className="space-y-0 p-4 pb-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <CardTitle className="text-base">赛道达人</CardTitle>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    每位达人唯一归属一个赛道；移动后，后续任务与筛选会使用新归属。
                  </p>
                </div>
                <Button
                  size="sm"
                  disabled={creatorsQuery.isError}
                  onClick={() => setAddCreatorsOpen(true)}
                >
                  <Plus /> 添加或移动达人
                </Button>
              </div>
            </CardHeader>
            <CardContent className="p-4 pt-2">
              <div className="relative mb-2 max-w-sm">
                <Search
                  aria-hidden="true"
                  className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                />
                <Input
                  value={searchCreators}
                  onChange={(event) => setSearchCreators(event.target.value)}
                  placeholder="筛选当前赛道达人"
                  aria-label="筛选当前赛道达人"
                  className="h-8 pl-9"
                />
              </div>
              {creatorsQuery.isError ? (
                <QueryErrorState
                  title="赛道达人读取失败"
                  description="暂时无法获取当前赛道的达人，请检查服务连接后重试。"
                  onRetry={() => void creatorsQuery.refetch()}
                  retrying={creatorsQuery.isFetching}
                  className="py-8"
                />
              ) : (
                <div className="max-h-[560px] overflow-auto rounded-lg border">
                  <Table>
                    <TableHeader className="sticky top-0 z-10 bg-background">
                      <TableRow>
                        <TableHead className="h-9">达人</TableHead>
                        <TableHead className="h-9">状态</TableHead>
                        <TableHead className="h-9">任务 / 作品</TableHead>
                        <TableHead className="h-9 text-right">操作</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {/* 报告 A4/O8：加载态保留表头与列结构，先铺骨架行再落数据 */}
                      {creatorsQuery.isLoading &&
                        Array.from({ length: 5 }, (_, rowIndex) => (
                          <TableRow
                            key={`creator-skeleton-${rowIndex}`}
                            className="hover:bg-transparent"
                          >
                            <TableCell className="py-2">
                              <Skeleton className="h-4 w-40" />
                            </TableCell>
                            <TableCell className="py-2">
                              <Skeleton className="h-5 w-16 rounded-full" />
                            </TableCell>
                            <TableCell className="py-2">
                              <Skeleton className="h-4 w-12" />
                            </TableCell>
                            <TableCell className="py-2">
                              <Skeleton className="ml-auto h-7 w-28" />
                            </TableCell>
                          </TableRow>
                        ))}
                      {visibleCreators.map((creator) => (
                        <TableRow
                          key={creator.id}
                          className={
                            highlightedCreatorIds.has(creator.id)
                              ? "row-highlight"
                              : undefined
                          }
                        >
                          <TableCell className="max-w-72 py-2">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <p className="truncate font-medium">
                                {creatorNameLabel(creator)}
                              </p>
                              {creator.is_placeholder && (
                                <Badge
                                  variant="outline"
                                  className="border-amber-400/60 bg-amber-50 text-amber-700"
                                >
                                  待补全
                                </Badge>
                              )}
                            </div>
                            {creator.is_placeholder && (
                              <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
                                脱敏身份 · 补全主页链接后可创建任务
                              </p>
                            )}
                            {creator.notes && (
                              <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
                                {creator.notes}
                              </p>
                            )}
                          </TableCell>
                          <TableCell className="py-2">
                            <Badge
                              variant={
                                creator.enabled ? "outline" : "secondary"
                              }
                              className="whitespace-nowrap"
                            >
                              {creator.enabled
                                ? creatorStatusLabels[creator.status]
                                : "已停用"}
                            </Badge>
                          </TableCell>
                          <TableCell className="whitespace-nowrap py-2 text-xs text-muted-foreground">
                            {creator.task_count} / {creator.aweme_count}
                          </TableCell>
                          <TableCell className="py-2">
                            <div className="flex justify-end gap-1">
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 px-2"
                                aria-label={`编辑达人 ${creatorNameLabel(creator)}`}
                                onClick={() => setEditingCreator(creator)}
                              >
                                <Pencil /> 编辑
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 px-2 text-destructive"
                                aria-label={`移除达人 ${creatorNameLabel(creator)}`}
                                disabled={track.is_default}
                                title={
                                  track.is_default
                                    ? "默认赛道的达人不能移除，请将它移动到其他赛道"
                                    : "移回默认赛道"
                                }
                                onClick={() => setRemovingCreator(creator)}
                              >
                                <Trash2 />
                                {track.is_default ? "默认归属" : "移回默认"}
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                      {!creatorsQuery.isLoading && !visibleCreators.length && (
                        <TableRow className="hover:bg-transparent">
                          <TableCell colSpan={4} className="p-0">
                            {creatorsEmptyByFilter ? (
                              <EmptyState
                                compact
                                icon={SearchX}
                                title="没有匹配的赛道达人"
                                description="当前搜索条件下没有达人，清除后可以查看该赛道的全部达人。"
                                action={
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() => setSearchCreators("")}
                                  >
                                    清除筛选
                                  </Button>
                                }
                              />
                            ) : (
                              <EmptyState
                                compact
                                icon={UsersRound}
                                title="当前赛道还没有达人"
                                description="添加达人后可以按主页抓取其作品，内容同样会归档到本赛道。"
                                action={
                                  <Button
                                    size="sm"
                                    onClick={() => setAddCreatorsOpen(true)}
                                  >
                                    <Plus /> 添加第一个达人
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
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="tasks">
          <TrackTasksPanel trackId={trackId} keywords={keywords} />
        </TabsContent>
        <TabsContent
          value="settings"
          forceMount
          className="data-[state=inactive]:hidden"
        >
          <div className="max-w-3xl">
            <TrackEditor key={track.id} track={track} onSaved={refresh} />
          </div>
        </TabsContent>
      </Tabs>

      <Dialog open={resetOpen} onOpenChange={setResetOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>重置赛道“{track.name}”？</DialogTitle>
            <DialogDescription>
              系统会先停止正在运行的任务，再永久删除本赛道的全部关键词、达人、任务、视频、评论、互动和请求日志。赛道名称及配置会保留，此操作无法撤销。
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-sm">
            将清理 {track.keyword_count} 个关键词、{creators.length} 个达人、
            {track.task_count} 个任务、{track.aweme_count} 个作品和
            {track.comment_count} 条评论。
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={resetTrack.isPending}
              onClick={() => setResetOpen(false)}
            >
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={resetTrack.isPending}
              onClick={() => resetTrack.mutate()}
            >
              {resetTrack.isPending ? "正在停止并清理…" : "确认重置"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AddTrackKeywordsDialog
        trackId={trackId}
        trackName={track.name}
        linkedKeywords={keywords}
        open={addOpen}
        onOpenChange={setAddOpen}
        onAdded={refresh}
      />
      {editingKeyword && (
        <EditKeywordDialog
          item={editingKeyword}
          open
          onOpenChange={(open) => !open && setEditingKeyword(null)}
          onSaved={async () => {
            setEditingKeyword(null)
            await refresh()
          }}
        />
      )}
      <Dialog
        open={Boolean(removingKeyword)}
        onOpenChange={(open) => !open && setRemovingKeyword(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              从当前赛道移除“{removingKeyword?.keyword}”？
            </DialogTitle>
            <DialogDescription>
              关键词会迁移到默认赛道；历史任务、作品和评论不会被删除。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemovingKeyword(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={!removingKeyword || unlink.isPending}
              onClick={() =>
                removingKeyword && unlink.mutate(removingKeyword.id)
              }
            >
              {unlink.isPending ? "正在移除…" : "确认移除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AddTrackCreatorsDialog
        trackId={trackId}
        trackName={track.name}
        linkedCreators={creators}
        open={addCreatorsOpen}
        onOpenChange={setAddCreatorsOpen}
        onAdded={refresh}
      />
      {editingCreator && (
        <EditCreatorDialog
          item={editingCreator}
          open
          onOpenChange={(open) => !open && setEditingCreator(null)}
          onSaved={async () => {
            setEditingCreator(null)
            await refresh()
          }}
        />
      )}
      <Dialog
        open={Boolean(removingCreator)}
        onOpenChange={(open) => !open && setRemovingCreator(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              从当前赛道移除“
              {removingCreator ? creatorNameLabel(removingCreator) : "该达人"}
              ”？
            </DialogTitle>
            <DialogDescription>
              达人会迁移到默认赛道；历史任务、作品和评论不会被删除。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemovingCreator(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={!removingCreator || removeCreator.isPending}
              onClick={() =>
                removingCreator && removeCreator.mutate(removingCreator.id)
              }
            >
              {removeCreator.isPending ? "正在移除…" : "确认移除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

const crawlTypeLabels: Record<CrawlTaskPublic["crawl_type"], string> = {
  search: "关键词搜索",
  detail: "指定作品",
  creator: "创作者作品",
  creator_from_aweme: "视频作者作品",
  liked: "账号点赞",
  collected: "账号收藏",
}

const taskFilterTabs = [
  { key: "all", label: "全部" },
  { key: "active", label: "进行中" },
  { key: "attention", label: "需处理" },
  { key: "succeeded", label: "已完成" },
] as const
type TaskFilterKey = (typeof taskFilterTabs)[number]["key"]
const attentionStatuses = ["failed", "interrupted", "waiting_login"]

function taskKeywordNames(
  task: CrawlTaskPublic,
  keywordNameById: Map<string, string>,
) {
  const request = task.request as Record<string, unknown>
  const ids = Array.isArray(request.keyword_ids)
    ? request.keyword_ids.filter(
        (value): value is string => typeof value === "string",
      )
    : []
  if (ids.length) {
    const names = ids
      .map((id) => keywordNameById.get(id))
      .filter((value): value is string => Boolean(value))
    if (names.length) return [...new Set(names)]
  }
  const words = Array.isArray(request.keywords)
    ? request.keywords.filter(
        (value): value is string => typeof value === "string",
      )
    : []
  return [...new Set(words)]
}

function TrackTasksPanel({
  trackId,
  keywords,
}: {
  trackId: string
  keywords: DouyinKeywordPublic[]
}) {
  const [statusFilter, setStatusFilter] = useState<TaskFilterKey>("all")
  const [search, setSearch] = useState("")
  // 与任务列表同一套口径：默认聚合（一组一行），可切回逐条
  const [groupMode, changeGroupMode] = usePersistentGroupMode(
    "douyin-track-tasks-group-mode",
  )
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null)
  const tasksQuery = useQuery({
    queryKey: ["douyin-track-tasks", trackId],
    queryFn: () => DouyinService.listTasks({ trackId, skip: 0, limit: 100 }),
    retry: false,
    // 原来固定 3 秒拉一次，任务全部结束后仍在空转；改为仅当列表里还有进行中任务时轮询
    refetchInterval: (query) =>
      query.state.data?.data.some((task) =>
        activeTaskStatuses.includes(task.status),
      )
        ? 3_000
        : false,
  })
  const tasks = tasksQuery.data?.data ?? []
  const keywordNameById = new Map(
    keywords.map((item) => [item.id, item.keyword]),
  )
  const term = search.trim().toLocaleLowerCase("zh-CN")
  const filtered = tasks.filter((task) => {
    const matchesStatus =
      statusFilter === "all" ||
      (statusFilter === "active" && activeTaskStatuses.includes(task.status)) ||
      (statusFilter === "attention" &&
        attentionStatuses.includes(task.status)) ||
      (statusFilter === "succeeded" && task.status === "succeeded")
    if (!matchesStatus) return false
    if (!term) return true
    return [
      task.display_title ?? "",
      crawlTypeLabels[task.crawl_type],
      ...(task.creator_names ?? []),
      ...taskKeywordNames(task, keywordNameById),
    ].some((value) => value.toLocaleLowerCase("zh-CN").includes(term))
  })
  const groupMap = new Map<string, CrawlTaskPublic[]>()
  filtered.forEach((task) => {
    const names = taskKeywordNames(task, keywordNameById)
    const isCreatorTask = ["creator", "creator_from_aweme"].includes(
      task.crawl_type,
    )
    const creatorNames = task.creator_names?.length ? task.creator_names : []
    const buckets = creatorNames.length
      ? creatorNames
      : names.length
        ? names
        : [isCreatorTask ? "达人爬取" : "未指定关键词"]
    buckets.forEach((name) => {
      const list = groupMap.get(name) ?? []
      list.push(task)
      groupMap.set(name, list)
    })
  })
  const groups = [...groupMap.entries()]
    .map(([name, groupTasks]) => ({
      name,
      tasks: groupTasks.sort((a, b) =>
        b.created_at.localeCompare(a.created_at),
      ),
      latest: Math.max(
        ...groupTasks.map((task) => new Date(task.created_at).getTime()),
      ),
    }))
    .sort((a, b) => b.latest - a.latest)

  return (
    <Card>
      <CardHeader className="space-y-0 p-4 pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="text-base">赛道任务</CardTitle>
            <p className="mt-0.5 text-xs text-muted-foreground">
              按关键词 /
              达人分组展示；命中多个关键词或达人的任务会同时出现在对应分组。
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <TaskGroupToggle
              value={groupMode}
              onChange={changeGroupMode}
              label="切换赛道任务的聚合方式"
            />
            <Button
              size="sm"
              variant="outline"
              disabled={tasksQuery.isFetching}
              onClick={() => void tasksQuery.refetch()}
            >
              <RefreshCw
                className={tasksQuery.isFetching ? "animate-spin" : ""}
              />
              刷新
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 p-4 pt-2">
        <div className="flex flex-wrap items-center gap-2">
          <fieldset className="m-0 flex items-center rounded-lg border p-0.5">
            <legend className="sr-only">按状态筛选任务</legend>
            {taskFilterTabs.map((tab) => (
              <Button
                key={tab.key}
                size="sm"
                variant={statusFilter === tab.key ? "secondary" : "ghost"}
                className="h-8 px-3 text-xs"
                aria-pressed={statusFilter === tab.key}
                onClick={() => setStatusFilter(tab.key)}
              >
                {tab.label}
              </Button>
            ))}
          </fieldset>
          <div className="relative min-w-52 flex-1">
            <Search
              aria-hidden="true"
              className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索任务标题、类型或关键词"
              aria-label="搜索赛道任务"
              className="h-9 pl-9"
            />
          </div>
        </div>

        {tasksQuery.isError ? (
          <QueryErrorState
            title="赛道任务读取失败"
            description="暂时无法获取当前赛道的任务，请检查服务连接后重试。"
            onRetry={() => void tasksQuery.refetch()}
            retrying={tasksQuery.isFetching}
            className="py-8"
          />
        ) : tasksQuery.isLoading ? (
          // 报告 A4/O8：分组列表加载态改用骨架屏，避免「正在加载…」四个字后整块跳动
          <div className="space-y-2">
            {Array.from({ length: 4 }, (_, index) => (
              <Skeleton
                key={`track-task-skeleton-${index}`}
                className="h-16 w-full rounded-xl"
              />
            ))}
          </div>
        ) : groups.length === 0 ? (
          <EmptyState
            icon={tasks.length ? SearchX : ClipboardList}
            title={
              tasks.length ? "没有匹配当前筛选条件的任务" : "当前赛道还没有任务"
            }
            description={
              tasks.length
                ? "可放宽状态或关键词筛选条件后再查看。"
                : "启动赛道采集后，任务会按关键词 / 达人分组出现在这里。"
            }
            action={
              tasks.length ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setSearch("")
                    setStatusFilter("all")
                  }}
                >
                  重置筛选条件
                </Button>
              ) : (
                <Button size="sm" asChild>
                  {/* 与顶部「启动赛道采集」一致：带 run 跳到赛道列表打开运营工作区 */}
                  <Link
                    to="/douyin-tracks"
                    search={{
                      run: trackId,
                      search: undefined,
                      viewMode: undefined,
                    }}
                  >
                    启动赛道采集
                  </Link>
                </Button>
              )
            }
          />
        ) : (
          groups.map((group) => {
            const active = group.tasks.filter((task) =>
              activeTaskStatuses.includes(task.status),
            ).length
            const attention = group.tasks.filter((task) =>
              attentionStatuses.includes(task.status),
            ).length
            const done = group.tasks.filter(
              (task) => task.status === "succeeded",
            ).length
            const summary = [
              active ? `${active} 进行中` : "",
              attention ? `${attention} 需处理` : "",
              done ? `${done} 已完成` : "",
            ]
              .filter(Boolean)
              .join(" · ")
            return (
              <div key={group.name} className="rounded-xl border">
                <div className="flex flex-wrap items-center gap-2 border-b bg-muted/30 px-3 py-2">
                  <Badge variant="secondary">{group.name}</Badge>
                  <span className="text-xs text-muted-foreground">
                    {group.tasks.length} 个任务
                  </span>
                  <span className="flex-1" />
                  {summary && (
                    <span className="text-[10px] text-muted-foreground">
                      {summary}
                    </span>
                  )}
                </div>
                <div className="divide-y">
                  {groupMode === "group"
                    ? // 聚合：一组一行，给出运行次数与数据合计，展开才看每次运行
                      (() => {
                        const latest = group.tasks[0]
                        const awemeTotal = group.tasks.reduce(
                          (sum, task) => sum + task.aweme_count,
                          0,
                        )
                        const commentTotal = group.tasks.reduce(
                          (sum, task) => sum + task.comment_count,
                          0,
                        )
                        const expanded = expandedGroup === group.name
                        return (
                          <>
                            <div className="flex flex-wrap items-center gap-3 px-3 py-2.5">
                              <TaskStatusBadge status={latest.status} />
                              {/* 与任务列表同款：点目标内容前的箭头展开/收起运行记录 */}
                              <button
                                type="button"
                                className="flex min-w-0 flex-1 items-start gap-2 text-left"
                                aria-expanded={expanded}
                                aria-label={
                                  expanded
                                    ? `收起「${group.name}」的运行记录`
                                    : `展开「${group.name}」的运行记录`
                                }
                                onClick={() =>
                                  setExpandedGroup(expanded ? null : group.name)
                                }
                              >
                                <ChevronDown
                                  aria-hidden="true"
                                  className={cn(
                                    "mt-0.5 size-3.5 shrink-0 text-muted-foreground transition",
                                    expanded && "rotate-180",
                                  )}
                                />
                                <span className="min-w-0">
                                  <TaskIdentity
                                    task={latest}
                                    className="text-sm"
                                  />
                                  {group.tasks.length > 1 && (
                                    <span className="mt-0.5 block text-[10px] text-muted-foreground">
                                      共 {group.tasks.length} 次运行 · 最近一次{" "}
                                      {formatDateTime(latest.created_at)}
                                    </span>
                                  )}
                                </span>
                              </button>
                              <span className="whitespace-nowrap text-xs text-muted-foreground">
                                作品 {awemeTotal} · 评论 {commentTotal}
                              </span>
                              <span className="whitespace-nowrap text-xs text-muted-foreground">
                                {formatDateTime(latest.created_at)}
                              </span>
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 px-2"
                                asChild
                              >
                                <Link
                                  to="/douyin/$taskId"
                                  params={{ taskId: latest.id }}
                                >
                                  最近一次
                                  <ArrowRight />
                                </Link>
                              </Button>
                            </div>
                            {expanded &&
                              group.tasks.map((task) => (
                                <div
                                  key={task.id}
                                  className="flex flex-wrap items-center gap-3 bg-muted/20 px-3 py-2"
                                >
                                  <TaskStatusBadge status={task.status} />
                                  <div className="min-w-0 flex-1">
                                    <TaskIdentity
                                      task={task}
                                      className="text-xs"
                                    />
                                  </div>
                                  <span className="whitespace-nowrap text-xs text-muted-foreground">
                                    作品 {task.aweme_count} · 评论{" "}
                                    {task.comment_count}
                                  </span>
                                  <span className="whitespace-nowrap text-xs text-muted-foreground">
                                    {formatDateTime(task.created_at)}
                                  </span>
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    className="h-7 px-2"
                                    asChild
                                  >
                                    <Link
                                      to="/douyin/$taskId"
                                      params={{ taskId: task.id }}
                                    >
                                      查看
                                      <ArrowRight />
                                    </Link>
                                  </Button>
                                </div>
                              ))}
                          </>
                        )
                      })()
                    : group.tasks.map((task) => (
                        <div
                          key={task.id}
                          className="flex flex-wrap items-center gap-3 px-3 py-2.5"
                        >
                          <TaskStatusBadge status={task.status} />
                          <div className="min-w-0 flex-1">
                            <TaskIdentity task={task} className="text-sm" />
                            {task.error && (
                              <p className="mt-0.5 truncate text-[10px] text-destructive">
                                {task.error}
                              </p>
                            )}
                          </div>
                          <span className="whitespace-nowrap text-xs text-muted-foreground">
                            作品 {task.aweme_count} · 评论 {task.comment_count}
                          </span>
                          <span className="whitespace-nowrap text-xs text-muted-foreground">
                            {formatDateTime(task.created_at)}
                          </span>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2"
                            asChild
                          >
                            <Link
                              to="/douyin/$taskId"
                              params={{ taskId: task.id }}
                            >
                              查看
                              <ArrowRight />
                            </Link>
                          </Button>
                        </div>
                      ))}
                </div>
              </div>
            )
          })
        )}
      </CardContent>
    </Card>
  )
}

function TrackEditor({
  track,
  onSaved,
}: {
  track: DouyinTrackDetailPublic
  onSaved: () => Promise<unknown>
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [name, setName] = useState(track.name)
  const [description, setDescription] = useState(track.description)
  const [prompt, setPrompt] = useState(track.prompt)
  const [replyTemplatesText, setReplyTemplatesText] = useState(
    track.reply_templates.join("\n"),
  )
  const [keywordCategoriesText, setKeywordCategoriesText] = useState(
    track.keyword_categories.join("\n"),
  )
  const [enabled, setEnabled] = useState(track.enabled)
  const [taskDefaults, setTaskDefaults] = useState(track.default_task_config)
  const previousTrack = useRef(track)
  useEffect(() => {
    const previous = previousTrack.current
    const hasDraft =
      name !== previous.name ||
      description !== previous.description ||
      prompt !== previous.prompt ||
      replyTemplatesText !== previous.reply_templates.join("\n") ||
      keywordCategoriesText !== previous.keyword_categories.join("\n") ||
      enabled !== previous.enabled ||
      JSON.stringify(taskDefaults) !==
        JSON.stringify(previous.default_task_config)
    if (!hasDraft) {
      setName(track.name)
      setDescription(track.description)
      setPrompt(track.prompt)
      setReplyTemplatesText(track.reply_templates.join("\n"))
      setKeywordCategoriesText(track.keyword_categories.join("\n"))
      setEnabled(track.enabled)
      setTaskDefaults(track.default_task_config)
    }
    previousTrack.current = track
  }, [
    description,
    enabled,
    keywordCategoriesText,
    name,
    prompt,
    replyTemplatesText,
    taskDefaults,
    track,
  ])
  const mutation = useMutation({
    mutationFn: () =>
      DouyinTracksService.editTrack({
        trackId: track.id,
        requestBody: {
          name,
          description,
          prompt,
          reply_templates: parseLibraryLines(replyTemplatesText),
          keyword_categories: parseLibraryLines(keywordCategoriesText),
          enabled,
          default_task_config: { ...taskDefaults, mode: "separate" },
        },
      }),
    onSuccess: async (updated) => {
      setName(updated.name)
      setDescription(updated.description)
      setPrompt(updated.prompt)
      setReplyTemplatesText(updated.reply_templates.join("\n"))
      setKeywordCategoriesText(updated.keyword_categories.join("\n"))
      setEnabled(updated.enabled)
      setTaskDefaults(updated.default_task_config)
      showSuccessToast("赛道信息与提示词已保存")
      await onSaved()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const dirty =
    name !== track.name ||
    description !== track.description ||
    prompt !== track.prompt ||
    replyTemplatesText !== track.reply_templates.join("\n") ||
    keywordCategoriesText !== track.keyword_categories.join("\n") ||
    enabled !== track.enabled ||
    JSON.stringify(taskDefaults) !== JSON.stringify(track.default_task_config)

  return (
    <Card>
      <CardHeader className="p-4 pb-2">
        <CardTitle className="text-base">赛道信息与提示词</CardTitle>
        <p className="text-xs text-muted-foreground">
          提示词作为赛道运营策略沉淀，暂不直接改变爬取参数。
        </p>
      </CardHeader>
      <CardContent className="space-y-3 p-4 pt-2">
        <div className="space-y-1">
          <Label htmlFor="detail-track-name" className="text-xs">
            赛道名称
          </Label>
          <Input
            id="detail-track-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="h-8"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="detail-track-description" className="text-xs">
            定位与目标人群
          </Label>
          <Textarea
            id="detail-track-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            rows={3}
            className="resize-y"
          />
        </div>
        <details className="rounded-lg border bg-muted/20">
          <summary className="cursor-pointer px-3 py-2.5 text-sm font-medium">
            评论话术与关键词分类
          </summary>
          <div className="grid gap-3 border-t p-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="detail-reply-templates" className="text-xs">
                评论/回复话术（每行一条）
              </Label>
              <Textarea
                id="detail-reply-templates"
                value={replyTemplatesText}
                onChange={(event) => setReplyTemplatesText(event.target.value)}
                rows={6}
                placeholder={"欢迎交流具体需求\n可以私信我了解详情"}
              />
              <p className="text-xs text-muted-foreground">
                手动创建的视频评论和回复也会自动沉淀到这里，最多保留 100 条。
              </p>
            </div>
            <div className="space-y-1">
              <Label htmlFor="detail-keyword-categories" className="text-xs">
                关键词分类（每行一个）
              </Label>
              <Textarea
                id="detail-keyword-categories"
                value={keywordCategoriesText}
                onChange={(event) =>
                  setKeywordCategoriesText(event.target.value)
                }
                rows={6}
                placeholder={"品类词\n场景词\n意向词"}
              />
              <p className="text-xs text-muted-foreground">
                关键词只能选择当前赛道已定义的分类，移动赛道时会重新校验。
              </p>
            </div>
          </div>
        </details>
        <div className="space-y-1">
          <div className="flex items-center justify-between gap-2">
            <Label htmlFor="detail-track-prompt" className="text-xs">
              赛道提示词
            </Label>
            <span className="text-[10px] text-muted-foreground">
              {prompt.length}/10000
            </span>
          </div>
          <Textarea
            id="detail-track-prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={9}
            maxLength={10000}
            placeholder="例如：分析该赛道评论中的用户需求、购买阻力、常见异议与可转化信号。"
            className="resize-y"
          />
        </div>
        <div className="flex items-center gap-2 text-sm">
          <Checkbox
            id="detail-track-enabled"
            checked={enabled}
            disabled={track.is_default}
            onCheckedChange={(checked) => setEnabled(checked === true)}
          />
          <Label htmlFor="detail-track-enabled">启用该赛道</Label>
        </div>
        {track.is_default && (
          <p className="text-xs text-muted-foreground">
            默认赛道用于承接未指定归属的数据，因此必须保持启用。
          </p>
        )}
        <details className="rounded-lg border bg-muted/20" open>
          <summary className="cursor-pointer px-3 py-2.5 text-sm font-medium">
            默认爬取配置
          </summary>
          <div className="grid gap-3 border-t p-3 sm:grid-cols-2">
            <div>
              <Label className="text-xs">任务组织方式</Label>
              <div className="mt-1 rounded-md border bg-muted/20 px-3 py-2">
                <p className="text-sm font-medium">每个关键词独立任务</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  固定一词一任务，不再合并多个关键词。
                </p>
              </div>
            </div>
            <div>
              <Label htmlFor="default-max-awemes" className="text-xs">
                单任务作品上限
              </Label>
              <Input
                id="default-max-awemes"
                type="number"
                min={1}
                max={1000}
                className="mt-1 h-9"
                value={
                  taskDefaults.max_awemes ??
                  DOUYIN_TASK_PARAMETER_DEFAULTS.maxAwemes
                }
                onChange={(event) =>
                  setTaskDefaults({
                    ...taskDefaults,
                    max_awemes: Number(event.target.value),
                  })
                }
              />
            </div>
            <div>
              <Label htmlFor="default-max-comments" className="text-xs">
                单作品评论上限
              </Label>
              <Input
                id="default-max-comments"
                type="number"
                min={1}
                max={1000}
                className="mt-1 h-9"
                value={taskDefaults.max_comments_per_aweme ?? 10}
                onChange={(event) =>
                  setTaskDefaults({
                    ...taskDefaults,
                    max_comments_per_aweme: Number(event.target.value),
                  })
                }
              />
            </div>
            <div>
              <Label htmlFor="default-start-page" className="text-xs">
                起始页码
              </Label>
              <Input
                id="default-start-page"
                type="number"
                min={1}
                className="mt-1 h-9"
                value={taskDefaults.start_page ?? 1}
                onChange={(event) =>
                  setTaskDefaults({
                    ...taskDefaults,
                    start_page: Number(event.target.value),
                  })
                }
              />
            </div>
            <div>
              <Label htmlFor="default-concurrency" className="text-xs">
                抓取并发
              </Label>
              <Input
                id="default-concurrency"
                type="number"
                min={1}
                max={5}
                className="mt-1 h-9"
                value={taskDefaults.concurrency ?? 1}
                onChange={(event) =>
                  setTaskDefaults({
                    ...taskDefaults,
                    concurrency: Number(event.target.value),
                  })
                }
              />
            </div>
            <div>
              <Label htmlFor="default-delay" className="text-xs">
                请求风控档位
              </Label>
              <select
                id="default-delay"
                className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={taskDefaults.request_delay_level ?? "steady"}
                onChange={(event) =>
                  setTaskDefaults({
                    ...taskDefaults,
                    request_delay_level: event.target.value as
                      | "fast"
                      | "steady"
                      | "ultra_steady",
                  })
                }
              >
                <option value="fast">快 · 1–2 秒</option>
                <option value="steady">稳 · 3–6 秒</option>
                <option value="ultra_steady">极稳 · 6–12 秒</option>
              </select>
            </div>
            <div>
              <Label htmlFor="default-request-interval" className="text-xs">
                最小请求间隔（秒）
              </Label>
              <Input
                id="default-request-interval"
                type="number"
                min={0.2}
                max={60}
                step={0.1}
                className="mt-1 h-9"
                value={taskDefaults.request_interval_seconds ?? 1}
                onChange={(event) =>
                  setTaskDefaults({
                    ...taskDefaults,
                    request_interval_seconds: Number(event.target.value),
                  })
                }
              />
            </div>
            <div>
              <Label htmlFor="default-publish-time" className="text-xs">
                发布时间
              </Label>
              <select
                id="default-publish-time"
                className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={taskDefaults.publish_time ?? 0}
                onChange={(event) =>
                  setTaskDefaults({
                    ...taskDefaults,
                    publish_time: Number(event.target.value),
                  })
                }
              >
                <option value={0}>不限</option>
                <option value={1}>一天内</option>
                <option value={7}>一周内</option>
                <option value={180}>半年内</option>
              </select>
            </div>
            <div>
              <Label htmlFor="default-browser-mode" className="text-xs">
                临时登录浏览器
              </Label>
              <select
                id="default-browser-mode"
                className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={taskDefaults.browser_mode ?? "default"}
                onChange={(event) =>
                  setTaskDefaults({
                    ...taskDefaults,
                    browser_mode:
                      event.target.value === "default"
                        ? null
                        : (event.target.value as "local" | "remote"),
                  })
                }
              >
                <option value="default">跟随服务配置</option>
                <option value="local">本机浏览器</option>
                <option value="remote">云端托管浏览器</option>
              </select>
            </div>
            <div className="flex items-center gap-2 text-sm">
              <Checkbox
                id="default-fetch-comments"
                checked={taskDefaults.fetch_comments ?? true}
                onCheckedChange={(checked) =>
                  setTaskDefaults({
                    ...taskDefaults,
                    fetch_comments: checked === true,
                    fetch_sub_comments:
                      checked === true
                        ? taskDefaults.fetch_sub_comments
                        : false,
                  })
                }
              />
              <Label htmlFor="default-fetch-comments">默认采集评论</Label>
            </div>
            <div className="flex items-center gap-2 text-sm">
              <Checkbox
                id="default-fetch-sub-comments"
                checked={
                  (taskDefaults.fetch_comments ?? true) &&
                  (taskDefaults.fetch_sub_comments ?? false)
                }
                disabled={!(taskDefaults.fetch_comments ?? true)}
                onCheckedChange={(checked) =>
                  setTaskDefaults({
                    ...taskDefaults,
                    fetch_sub_comments: checked === true,
                  })
                }
              />
              <Label htmlFor="default-fetch-sub-comments">
                默认采集二级评论
              </Label>
            </div>
            <div className="rounded-lg border border-blue-200/70 bg-blue-50/60 p-3 text-xs leading-5 text-blue-950 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-100 sm:col-span-2">
              采集任务不会自动下载。这里保存的是独立“下载与字幕”任务的默认参数，创建媒体任务时仍可修改。
            </div>
            <div className="flex items-center gap-2 text-sm">
              <Checkbox
                id="default-translate-subtitles"
                checked={taskDefaults.translate_subtitles ?? false}
                onCheckedChange={(checked) =>
                  setTaskDefaults({
                    ...taskDefaults,
                    translate_subtitles: checked === true,
                    download_media: true,
                    media_processing_mode: "batch",
                  })
                }
              />
              <Label htmlFor="default-translate-subtitles">
                媒体任务默认生成字幕
              </Label>
            </div>
            <div>
              <Label htmlFor="default-media-storage" className="text-xs">
                视频存储
              </Label>
              <select
                id="default-media-storage"
                className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={taskDefaults.media_storage ?? "default"}
                onChange={(event) =>
                  setTaskDefaults({
                    ...taskDefaults,
                    media_storage:
                      event.target.value === "default"
                        ? null
                        : (event.target.value as "local" | "minio"),
                  })
                }
              >
                <option value="default">跟随服务配置</option>
                <option value="local">本地服务器</option>
                <option value="minio">云端存储</option>
              </select>
            </div>
            {taskDefaults.translate_subtitles && (
              <div>
                <Label
                  htmlFor="default-transcription-language"
                  className="text-xs"
                >
                  视频语言
                </Label>
                <Input
                  id="default-transcription-language"
                  className="mt-1 h-9"
                  value={taskDefaults.transcription_language ?? "auto"}
                  placeholder="auto、zh、en"
                  onChange={(event) =>
                    setTaskDefaults({
                      ...taskDefaults,
                      transcription_language: event.target.value,
                    })
                  }
                />
              </div>
            )}
          </div>
          <p className="border-t px-3 py-2 text-xs text-muted-foreground">
            采集参数在启动赛道任务时带入；媒体参数在创建“下载与字幕”任务时带入，两类配置互不串联执行。
          </p>
        </details>
        <div className="flex justify-end gap-2 border-t pt-3">
          <Button
            size="sm"
            variant="outline"
            disabled={!prompt || mutation.isPending}
            onClick={() => setPrompt("")}
          >
            清空提示词
          </Button>
          <Button
            size="sm"
            disabled={!dirty || !name.trim() || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "保存中…" : "保存修改"}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function AddTrackKeywordsDialog({
  trackId,
  trackName,
  linkedKeywords,
  open,
  onOpenChange,
  onAdded,
}: {
  trackId: string
  trackName: string
  linkedKeywords: DouyinKeywordPublic[]
  open: boolean
  onOpenChange: (open: boolean) => void
  onAdded: () => Promise<unknown>
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [newValues, setNewValues] = useState("")
  const [search, setSearch] = useState("")
  const [selected, setSelected] = useState<Map<string, string>>(new Map())
  const candidatesQuery = useQuery({
    queryKey: ["douyin-track-keyword-candidates", search],
    queryFn: () =>
      DouyinKeywordsService.listKeywords({
        search: search.trim() || undefined,
        enabled: true,
        sortBy: "task_count",
        sortOrder: "desc",
        limit: 100,
      }),
    enabled: open,
    placeholderData: (previous) => previous,
  })
  const linkedIds = new Set(linkedKeywords.map((item) => item.id))
  const candidates = (candidatesQuery.data?.data ?? []).filter(
    (item) => !linkedIds.has(item.id),
  )
  const mutation = useMutation({
    mutationFn: (keywords: string[]) =>
      DouyinTracksService.appendTrackKeywords({
        trackId,
        requestBody: { keywords },
      }),
    onSuccess: async () => {
      setNewValues("")
      setSearch("")
      setSelected(new Map())
      onOpenChange(false)
      showSuccessToast("关键词已归入当前赛道")
      await onAdded()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const submitNew = () => {
    const values = parseKeywords(newValues)
    if (!values.length) return showErrorToast("请填写至少一个关键词")
    mutation.mutate(values)
  }
  const submitExisting = async () => {
    const values = [...selected.values()]
    if (!values.length) return showErrorToast("请至少选择一个关键词")
    // 报告 O15：改用统一确认框
    const confirmed = await confirmDialog({
      title: `确认将已选的 ${values.length} 个关键词移动到“${trackName}”？`,
      description: "后续任务和内容筛选会使用新的赛道归属。",
      confirmText: "移动",
    })
    if (!confirmed) return
    mutation.mutate(values)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>添加或移动赛道关键词</DialogTitle>
          <DialogDescription>
            新关键词会直接归入当前赛道；已有关键词会从原赛道迁移过来。
          </DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="new">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="new">新建关键词</TabsTrigger>
            <TabsTrigger value="existing">移动已有关键词</TabsTrigger>
          </TabsList>
          <TabsContent value="existing" className="space-y-3 pt-2">
            <div className="relative">
              <Search
                aria-hidden="true"
                className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索现有关键词"
                aria-label="搜索可关联的现有关键词"
                className="pl-9"
              />
            </div>
            <div className="max-h-72 overflow-y-auto rounded-lg border p-1">
              {candidates.map((item) => (
                <div
                  key={item.id}
                  className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm hover:bg-muted/60"
                >
                  <Checkbox
                    id={`candidate-keyword-${item.id}`}
                    checked={selected.has(item.id)}
                    onCheckedChange={(checked) =>
                      setSelected((current) => {
                        const next = new Map(current)
                        if (checked === true) next.set(item.id, item.keyword)
                        else next.delete(item.id)
                        return next
                      })
                    }
                    aria-label={`选择关键词 ${item.keyword}`}
                  />
                  <Label
                    htmlFor={`candidate-keyword-${item.id}`}
                    className="min-w-0 flex-1 cursor-pointer truncate font-medium"
                  >
                    {item.keyword}
                  </Label>
                  <span className="text-xs text-muted-foreground">
                    {item.track_name}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {item.task_count} 任务 · {item.aweme_count} 作品
                  </span>
                </div>
              ))}
              {!candidates.length &&
                (candidatesQuery.isLoading ? (
                  <div className="space-y-1">
                    {Array.from({ length: 4 }, (_, index) => (
                      <Skeleton
                        key={`candidate-keyword-skeleton-${index}`}
                        className="h-9 w-full"
                      />
                    ))}
                  </div>
                ) : (
                  <EmptyState
                    compact
                    icon={KeyRound}
                    title="没有可移动的关键词"
                    description="关键词库里没有其他可分派的关键词，可切换到「新建关键词」标签直接创建并归入当前赛道。"
                  />
                ))}
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                已选择 {selected.size} 个
              </span>
              <Button
                size="sm"
                disabled={!selected.size || mutation.isPending}
                onClick={submitExisting}
              >
                移动已选关键词
              </Button>
            </div>
          </TabsContent>
          <TabsContent value="new" className="space-y-3 pt-2">
            <div className="space-y-1">
              <Label htmlFor="new-track-keywords">新关键词</Label>
              <Textarea
                id="new-track-keywords"
                rows={8}
                value={newValues}
                onChange={(event) => setNewValues(event.target.value)}
                placeholder={
                  "一行一个，或使用逗号分隔\n例如：同城探店\n本地生活"
                }
              />
            </div>
            <div className="flex justify-end">
              <Button
                size="sm"
                disabled={
                  !parseKeywords(newValues).length || mutation.isPending
                }
                onClick={submitNew}
              >
                创建到当前赛道
              </Button>
            </div>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}

function EditKeywordDialog({
  item,
  open,
  onOpenChange,
  onSaved,
}: {
  item: DouyinKeywordPublic
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => Promise<unknown>
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [keyword, setKeyword] = useState(item.keyword)
  const [notes, setNotes] = useState(item.notes)
  const [enabled, setEnabled] = useState(item.enabled)
  const mutation = useMutation({
    mutationFn: () =>
      DouyinKeywordsService.editKeyword({
        keywordId: item.id,
        requestBody: {
          keyword: item.task_count ? undefined : keyword,
          notes,
          enabled,
        },
      }),
    onSuccess: async () => {
      showSuccessToast("关键词信息已更新")
      await onSaved()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    mutation.mutate()
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form className="space-y-4" onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>编辑关键词</DialogTitle>
            <DialogDescription>
              修改备注和启停状态不会改变该关键词的赛道归属。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1">
            <Label htmlFor="edit-track-keyword">关键词</Label>
            <Input
              id="edit-track-keyword"
              value={keyword}
              disabled={item.task_count > 0}
              onChange={(event) => setKeyword(event.target.value)}
            />
            {item.task_count > 0 && (
              <p className="text-xs text-muted-foreground">
                已关联历史任务，词面不可直接修改；可新建正确词并移除当前关联。
              </p>
            )}
          </div>
          <div className="space-y-1">
            <Label htmlFor="edit-track-keyword-notes">备注</Label>
            <Textarea
              id="edit-track-keyword-notes"
              rows={4}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Checkbox
              id="edit-global-keyword-enabled"
              checked={enabled}
              onCheckedChange={(checked) => setEnabled(checked === true)}
            />
            <Label htmlFor="edit-global-keyword-enabled">启用该关键词</Label>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              取消
            </Button>
            <Button
              type="submit"
              disabled={!keyword.trim() || mutation.isPending}
            >
              {mutation.isPending ? "保存中…" : "保存修改"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function InlineData({
  label,
  value,
  detail,
}: {
  label: string
  value: string | number
  detail?: string
}) {
  return (
    <span className="whitespace-nowrap">
      {label} <strong className="font-semibold text-foreground">{value}</strong>
      {detail && <span className="ml-1">({detail})</span>}
    </span>
  )
}

function parseKeywords(value: string) {
  return [
    ...new Set(
      value
        .split(/[\n,，;；]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ]
}

function parseCreatorTargets(value: string) {
  return [
    ...new Set(
      value
        .split(/[\n,，;；]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ]
}

function AddTrackCreatorsDialog({
  trackId,
  trackName,
  linkedCreators,
  open,
  onOpenChange,
  onAdded,
}: {
  trackId: string
  trackName: string
  linkedCreators: DouyinCreatorPublic[]
  open: boolean
  onOpenChange: (open: boolean) => void
  onAdded: () => Promise<unknown>
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [newValues, setNewValues] = useState("")
  const [search, setSearch] = useState("")
  const [selected, setSelected] = useState<Map<string, string>>(new Map())
  const candidatesQuery = useQuery({
    queryKey: ["douyin-track-creator-candidates", search],
    queryFn: () =>
      DouyinCreatorsService.listCreators({
        search: search.trim() || undefined,
        enabled: true,
        sortBy: "task_count",
        sortOrder: "desc",
        limit: 100,
      }),
    enabled: open,
    placeholderData: (previous) => previous,
  })
  const linkedIds = new Set(linkedCreators.map((item) => item.id))
  const candidates = (candidatesQuery.data?.data ?? []).filter(
    (item) => !linkedIds.has(item.id),
  )
  const mutation = useMutation({
    mutationFn: (creators: string[]) =>
      DouyinTracksService.appendTrackCreators({
        trackId,
        requestBody: { creators },
      }),
    onSuccess: async () => {
      setNewValues("")
      setSearch("")
      setSelected(new Map())
      onOpenChange(false)
      showSuccessToast("达人已归入当前赛道")
      await onAdded()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const submitNew = () => {
    const values = parseCreatorTargets(newValues)
    if (!values.length) return showErrorToast("请填写至少一个达人")
    mutation.mutate(values)
  }
  const submitExisting = async () => {
    const values = [...selected.values()]
    if (!values.length) return showErrorToast("请至少选择一个达人")
    // 报告 O15：改用统一确认框
    const confirmed = await confirmDialog({
      title: `确认将已选的 ${values.length} 位达人移动到“${trackName}”？`,
      description: "后续任务和内容筛选会使用新的赛道归属。",
      confirmText: "移动",
    })
    if (!confirmed) return
    mutation.mutate(values)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>添加或移动赛道达人</DialogTitle>
          <DialogDescription>
            新达人会直接归入当前赛道；已有达人会从原赛道迁移过来。支持粘贴主页链接或平台达人标识。
          </DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="new">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="new">新建达人</TabsTrigger>
            <TabsTrigger value="existing">移动已有达人</TabsTrigger>
          </TabsList>
          <TabsContent value="existing" className="space-y-3 pt-2">
            <div className="relative">
              <Search
                aria-hidden="true"
                className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索已有达人"
                aria-label="搜索可关联的已有达人"
                className="pl-9"
              />
            </div>
            <div className="max-h-72 overflow-y-auto rounded-lg border p-1">
              {candidates.map((item) => (
                <div
                  key={item.id}
                  className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm hover:bg-muted/60"
                >
                  <Checkbox
                    id={`candidate-creator-${item.id}`}
                    checked={selected.has(item.id)}
                    onCheckedChange={(checked) =>
                      setSelected((current) => {
                        const next = new Map(current)
                        if (checked === true) next.set(item.id, item.sec_uid)
                        else next.delete(item.id)
                        return next
                      })
                    }
                    aria-label={`选择达人 ${creatorNameLabel(item)}`}
                  />
                  <Label
                    htmlFor={`candidate-creator-${item.id}`}
                    className="min-w-0 flex-1 cursor-pointer truncate font-medium"
                  >
                    {creatorNameLabel(item)}
                  </Label>
                  <span className="text-xs text-muted-foreground">
                    {item.track_name}
                  </span>
                  <span className="whitespace-nowrap text-xs text-muted-foreground">
                    {item.task_count} 任务 · {item.aweme_count} 作品
                  </span>
                </div>
              ))}
              {!candidates.length &&
                (candidatesQuery.isLoading ? (
                  <div className="space-y-1">
                    {Array.from({ length: 4 }, (_, index) => (
                      <Skeleton
                        key={`candidate-creator-skeleton-${index}`}
                        className="h-9 w-full"
                      />
                    ))}
                  </div>
                ) : (
                  <EmptyState
                    compact
                    icon={UsersRound}
                    title="没有可移动的达人"
                    description="达人库里没有其他可分派的达人，可切换到「新建达人」标签直接创建并归入当前赛道。"
                  />
                ))}
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                已选择 {selected.size} 位
              </span>
              <Button
                size="sm"
                disabled={!selected.size || mutation.isPending}
                onClick={submitExisting}
              >
                移动已选达人
              </Button>
            </div>
          </TabsContent>
          <TabsContent value="new" className="space-y-3 pt-2">
            <div className="space-y-1">
              <Label htmlFor="new-track-creators">新达人</Label>
              <Textarea
                id="new-track-creators"
                rows={8}
                value={newValues}
                onChange={(event) => setNewValues(event.target.value)}
                placeholder={
                  "一行一个，或使用逗号分隔，粘贴主页链接或平台达人标识\n例如：https://www.douyin.com/user/MS4wLjABAAAA…"
                }
              />
            </div>
            <div className="flex justify-end">
              <Button
                size="sm"
                disabled={
                  !parseCreatorTargets(newValues).length || mutation.isPending
                }
                onClick={submitNew}
              >
                创建到当前赛道
              </Button>
            </div>
          </TabsContent>
        </Tabs>
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
  onSaved: () => Promise<unknown>
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [nickname, setNickname] = useState(item.nickname)
  const [notes, setNotes] = useState(item.notes)
  const [enabled, setEnabled] = useState(item.enabled)
  const mutation = useMutation({
    mutationFn: () =>
      DouyinCreatorsService.editCreator({
        creatorId: item.id,
        requestBody: { nickname, notes, enabled },
      }),
    onSuccess: async () => {
      showSuccessToast("达人信息已更新")
      await onSaved()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    mutation.mutate()
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form className="space-y-4" onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>编辑达人</DialogTitle>
            <DialogDescription>
              修改昵称、备注和启停状态不会改变该达人的赛道归属。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1">
            <Label htmlFor="edit-track-creator-nickname">昵称</Label>
            <Input
              id="edit-track-creator-nickname"
              value={nickname}
              onChange={(event) => setNickname(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="edit-track-creator-notes">备注</Label>
            <Textarea
              id="edit-track-creator-notes"
              rows={4}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Checkbox
              id="edit-track-creator-enabled"
              checked={enabled}
              onCheckedChange={(checked) => setEnabled(checked === true)}
            />
            <Label htmlFor="edit-track-creator-enabled">启用该达人</Label>
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
              {mutation.isPending ? "保存中…" : "保存修改"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
