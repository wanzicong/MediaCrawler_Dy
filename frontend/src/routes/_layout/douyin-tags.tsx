import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Download, Film, RefreshCw, Search, Tags } from "lucide-react"
import { useDeferredValue, useEffect, useMemo, useState } from "react"

import { DouyinTagsService } from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import { FilterChips } from "@/components/Common/FilterChips"
import { FilterPresetBar } from "@/components/Common/FilterPresetBar"
import { Pager } from "@/components/Common/Pager"
import { PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { RefreshIndicator } from "@/components/Common/RefreshIndicator"
import { SortableHeaderButton } from "@/components/Common/SortableHeader"
import { TableColumnMenu } from "@/components/Common/TableColumnMenu"
import { TimeAgo } from "@/components/Common/TimeAgo"
import {
  allTracksValue,
  TrackSelect,
  useTrackCatalog,
} from "@/components/Douyin/TrackSelect"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
import { useRowKeyboardNav } from "@/hooks/useRowKeyboardNav"
import { type TableColumnDef, useTableColumns } from "@/hooks/useTableColumns"
import { downloadCsv } from "@/lib/csv"
import {
  compactSearch,
  readEnumParam,
  readStringParam,
} from "@/lib/search-params"
import { formatDateTime } from "@/lib/time"
import { handleError } from "@/utils"

// 报告 O4：筛选上 URL —— 排序值白名单，既拦住手改 URL 传进来的脏值，也作为 sort 的类型来源
const SORT_VALUES = [
  "aweme_count:desc",
  "task_count:desc",
  "last_seen_at:desc",
  "name:asc",
] as const
type TagSort = (typeof SORT_VALUES)[number]

/** 报告 O20：可排序的字段（与表头一一对应） */
type TagSortField = "aweme_count" | "task_count" | "last_seen_at" | "name"

/** 首次点某列时用的方向：名称按升序更自然，数值/时间按降序（大的/新的在前）更有意义 */
const DEFAULT_ORDER_BY_FIELD: Record<TagSortField, "asc" | "desc"> = {
  aweme_count: "desc",
  task_count: "desc",
  last_seen_at: "desc",
  name: "asc",
}

// 报告 O4：本路由的查询参数类型。字段刻意全部写成可选属性（`q?:` 而不是 `q: T | undefined`）：
// TS 里 `x: T | undefined` 的键仍是必填的，会让所有指向本路由的 <Link> / navigate 被要求带 search。
// page 保持 string（URL 参数本来就是字符串，进 state 时由 parseSearchPage 解析为数字页码）。
type TagSearch = {
  track?: string
  q?: string
  sort?: TagSort
  page?: string
}

export const Route = createFileRoute("/_layout/douyin-tags")({
  // 报告 O4：筛选上 URL —— 刷新 / 分享链接 / 深链都能还原赛道、搜索词、排序与页码
  validateSearch: (search: Record<string, unknown>): TagSearch => ({
    track: readStringParam(search, "track"),
    q: readStringParam(search, "q"),
    sort: readEnumParam(search, "sort", SORT_VALUES),
    page: readStringParam(search, "page"),
  }),
  component: DouyinTagManagement,
})

const pageSize = 50

// 报告 A1：列可见性 —— 标签表的列清单。
// 必须是模块级稳定常量：放组件内每次渲染都会新建，hooks 里的 columns 依赖会失效、偏好被重置。
const TAG_COLUMNS = [
  { key: "name", title: "标签" },
  { key: "awemeCount", title: "视频" },
  { key: "taskCount", title: "任务" },
  { key: "lastSeen", title: "最近发现" },
  // 操作列藏掉用户就没法跳到视频列表了，永远可见
  { key: "actions", title: "操作", alwaysVisible: true },
] as const satisfies readonly TableColumnDef[]

// 报告 O4：URL 里的 page 是字符串，非法值（手改 URL）一律回落到第 1 页（0 基）
function parseSearchPage(value: string | undefined): number {
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : 0
}

// 默认排序；与默认值相同就不算「已应用筛选」，chips 里不展示
const defaultSort: TagSort = "aweme_count:desc"

// 排序值的中文名映射（报告 A2：chips 里展示用）
const sortLabels: Record<string, string> = {
  "aweme_count:desc": "关联视频最多",
  "task_count:desc": "关联任务最多",
  "last_seen_at:desc": "最近发现",
  "name:asc": "标签名称",
}

function DouyinTagManagement() {
  const queryClient = useQueryClient()
  // 报告 O4：筛选上 URL —— 改用本路由的 navigate（search 有类型），初值一律从 URL 还原
  const navigate = Route.useNavigate()
  // 报告 O4：URL 查询参数；search 这个名字已被搜索词占用，所以这里叫 urlSearch
  const urlSearch = Route.useSearch()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  // 报告 A1：列可见性 —— 表头 / 单元格 / 空态 colSpan 都要跟着这个走
  const { isVisible, visibleCount, menuProps } = useTableColumns({
    storageKey: "douyin-tags-columns",
    columns: TAG_COLUMNS,
  })
  const [page, setPage] = useState(() => parseSearchPage(urlSearch.page))
  const [trackId, setTrackId] = useState(urlSearch.track ?? allTracksValue)
  const [search, setSearch] = useState(urlSearch.q ?? "")
  // 用 deferred value 做输入防抖：输入框即时回显，查询与查询键跟随延迟值，避免每次按键都打接口
  const deferredSearch = useDeferredValue(search)
  const [sort, setSort] = useState<TagSort>(urlSearch.sort ?? defaultSort)
  const [sortBy, sortOrder] = sort.split(":") as [TagSortField, "asc" | "desc"]

  // 报告 O20：表头可点击排序。点同一列翻转方向，点另一列切到该列的默认方向。
  // 排序改变结果顺序但不改变结果集，所以只重置页码，不计入筛选条件。
  const toggleSort = (field: TagSortField) => {
    setSort((current) => {
      const [currentField, currentOrder] = current.split(":") as [
        TagSortField,
        "asc" | "desc",
      ]
      const nextOrder =
        currentField === field
          ? currentOrder === "desc"
            ? "asc"
            : "desc"
          : DEFAULT_ORDER_BY_FIELD[field]
      return `${field}:${nextOrder}` as TagSort
    })
    setPage(0)
  }
  // 报告 O4：筛选上 URL —— 赛道 / 搜索词 / 排序 / 页码任一变化都写回查询参数，
  // 与默认值相同的键交给 compactSearch 丢掉，未筛选时地址栏就是干净的 /douyin-tags。
  // 这里用 replace: true 是有意的取舍：不加的话每改一次筛选就多一条浏览器历史，
  // 用户得按十次「后退」才能离开本页；加 replace 后刷新 / 分享 / 深链 / 收藏都生效，
  // 但「后退」回到的是上一个页面，而不是上一条筛选。
  // 依赖只放筛选 state 与 navigate（不放 urlSearch 对象），避免回写触发自身再次执行。
  useEffect(() => {
    void navigate({
      to: "/douyin-tags",
      replace: true,
      search: compactSearch(
        {
          track: trackId === allTracksValue ? undefined : trackId,
          q: search.trim() || undefined,
          sort,
          page: page > 0 ? String(page) : undefined,
        },
        { sort: defaultSort, page: "0" },
      ),
    })
  }, [trackId, search, sort, page, navigate])
  const tagsQuery = useQuery({
    queryKey: ["douyin-tags", trackId, page, deferredSearch, sort],
    queryFn: () =>
      DouyinTagsService.listTags({
        trackId: trackId === allTracksValue ? undefined : trackId,
        search: deferredSearch.trim() || undefined,
        sortBy,
        sortOrder,
        skip: page * pageSize,
        limit: pageSize,
      }),
    placeholderData: (previous) => previous,
  })
  // 赛道名仅用于 chips 展示（复用 TrackSelect 的赛道目录查询，命中同一 queryKey 缓存）
  const { data: trackCatalog } = useTrackCatalog()
  const trackName =
    trackCatalog?.data?.find((track) => track.id === trackId)?.name ?? trackId
  const sync = useMutation({
    mutationFn: () => DouyinTagsService.syncTags(),
    onSuccess: async (result) => {
      showSuccessToast(
        `已扫描 ${result.aweme_count} 个作品，新增 ${result.created_count} 个标签、${result.binding_count} 条关联`,
      )
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["douyin-tags"] }),
        queryClient.invalidateQueries({ queryKey: ["douyin-library-tags"] }),
        queryClient.invalidateQueries({ queryKey: ["douyin-works-tags"] }),
        queryClient.invalidateQueries({ queryKey: ["douyin-library-works"] }),
      ])
    },
    onError: handleError.bind(showErrorToast),
  })
  const rows = tagsQuery.data?.data ?? []
  // 本页合计原本每次渲染做两次 reduce，数据不变时无需重算，收进 memo 一次遍历算完
  const { pageAwemeCount, pageTaskCount } = useMemo(
    () =>
      rows.reduce(
        (acc, item) => ({
          pageAwemeCount: acc.pageAwemeCount + item.aweme_count,
          pageTaskCount: acc.pageTaskCount + item.task_count,
        }),
        { pageAwemeCount: 0, pageTaskCount: 0 },
      ),
    [rows],
  )
  // 「查看视频」按钮与键盘回车共用同一份库页跳转参数，避免两处写法漂移
  const librarySearchFor = (tagId: string) => ({
    track: trackId === allTracksValue ? undefined : trackId,
    source: undefined,
    q: undefined,
    task: undefined,
    creator: undefined,
    tag: tagId,
    storage: undefined,
    subtitle: undefined,
    sort: undefined,
  })
  // 清空全部筛选：chips 的「清除全部」与空态里的「清除筛选条件」共用同一份逻辑
  const resetFilters = () => {
    setTrackId(allTracksValue)
    setSearch("")
    setSort(defaultSort)
    setPage(0)
  }
  // 报告 A4：空态要分流 —— 有筛选条件造成的空，引导「清除筛选」；真的没数据，才引导「同步历史标签」。
  // 排序不改变结果集，只影响顺序，所以不计入筛选条件。
  const hasFilter = trackId !== allTracksValue || Boolean(search.trim())
  // 报告 A13：表视图键盘导航（↑↓ 移动、回车打开该标签的视频列表）
  const nav = useRowKeyboardNav({
    rowIds: rows.map((row) => row.id),
    onActivate: (id) => {
      void navigate({ to: "/douyin-library", search: librarySearchFor(id) })
    },
  })
  return (
    <div className="page-stack">
      <PageHero
        compact
        title="标签管理"
        actions={
          <>
            {/* 报告 A14：刷新指示器（上次更新时间 + 手动刷新），替换页面原有的裸刷新按钮 */}
            <RefreshIndicator
              updatedAt={tagsQuery.dataUpdatedAt}
              refreshing={tagsQuery.isFetching}
              onRefresh={() => void tagsQuery.refetch()}
            />
            {/* 报告 A12：导出当前页标签（全量导出需后端流式接口，本次不做） */}
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                downloadCsv(`标签列表-第${page + 1}页`, rows, [
                  { header: "标签名", value: (row) => row.name },
                  { header: "关联视频数", value: (row) => row.aweme_count },
                  { header: "关联任务数", value: (row) => row.task_count },
                  {
                    header: "最近采集时间",
                    value: (row) =>
                      formatDateTime(row.last_seen_at, { fallback: "从未" }),
                  },
                ])
              }
              disabled={!rows.length}
              aria-label="导出当前页标签为 CSV"
            >
              <Download />
              导出
            </Button>
            <Button
              size="sm"
              onClick={() => sync.mutate()}
              disabled={sync.isPending}
            >
              <RefreshCw className={sync.isPending ? "animate-spin" : ""} />
              同步历史标签
            </Button>
          </>
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="whitespace-nowrap text-xs text-muted-foreground">
            标签{" "}
            <strong className="text-foreground">
              {tagsQuery.data?.count ?? 0}
            </strong>{" "}
            · 本页视频{" "}
            <strong className="text-foreground">{pageAwemeCount}</strong> ·
            本页任务{" "}
            <strong className="text-foreground">{pageTaskCount}</strong>
          </span>
          <div className="relative min-w-64 flex-[2]">
            {/* 装饰图标：输入框本身已有 aria-label，图标对读屏隐藏避免重复播报 */}
            <Search
              aria-hidden="true"
              className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value)
                setPage(0)
              }}
              placeholder="搜索标签"
              aria-label="搜索标签"
              className="h-9 pl-9"
            />
          </div>
          <TrackSelect
            value={trackId}
            onValueChange={(value) => {
              setTrackId(value)
              setPage(0)
            }}
            includeAll
            allowDisabled
            autoSelectDefault={false}
            className="h-9 min-w-44 flex-1"
            ariaLabel="按赛道筛选标签"
          />
          {/* 报告 A1：列显示/隐藏入口，放在筛选栏右端 */}
          <TableColumnMenu {...menuProps} className="h-9" />
          {/* 报告 O20：排序入口已改为表头点击（见下方 TableHead），
              此处的下拉与之功能重复，故移除；已应用的排序仍会显示在下方 chips 里。 */}
        </div>
        {/* 报告 A2：筛选 chips，把已应用的赛道 / 搜索 / 排序可视化并可单独移除 */}
        <FilterChips
          className="mt-2"
          chips={[
            trackId !== allTracksValue && {
              key: "track",
              label: "赛道",
              value: trackName,
              onRemove: () => {
                setTrackId(allTracksValue)
                setPage(0)
              },
            },
            search.trim()
              ? {
                  key: "q",
                  label: "搜索",
                  value: search,
                  onRemove: () => {
                    setSearch("")
                    setPage(0)
                  },
                }
              : false,
            sort !== defaultSort && {
              key: "sort",
              label: "排序",
              value: sortLabels[sort] ?? sort,
              onRemove: () => {
                setSort(defaultSort)
                setPage(0)
              },
            },
          ]}
          onClearAll={resetFilters}
        />
        {/* 报告 A10：筛选预设（localStorage 持久化，一键套用赛道 / 搜索 / 排序） */}
        <FilterPresetBar
          className="mt-2"
          storageKey="douyin-tags-filter-presets"
          currentFilters={{ trackId, search, sort }}
          onApply={(filters) => {
            setTrackId(filters.trackId)
            setSearch(filters.search)
            setSort(filters.sort)
            setPage(0)
          }}
        />
      </PageHero>

      <Card>
        <CardContent className="space-y-3 p-3">
          {tagsQuery.isError ? (
            // 接口失败时原实现只落到「暂无标签」空态，会误导用户以为真的没数据，这里显式给出错误态与重试
            <QueryErrorState
              title="标签列表加载失败"
              description="无法获取标签数据，请检查网络或后端服务后重试。"
              onRetry={() => tagsQuery.refetch()}
              retrying={tagsQuery.isFetching}
            />
          ) : (
            // 窄屏下 5 列表格会被 overflow-hidden 直接截断，改为横向滚动
            <div
              className="overflow-x-auto rounded-xl border"
              {...nav.containerProps}
            >
              <Table>
                <TableHeader>
                  <TableRow>
                    {/* 报告 O20：表头可点击排序 + 排序指示器（后端支持这 4 个排序字段） */}
                    {/* 报告 A1：整个 SortableHeaderButton 一起包，不能只包外层的 TableHead */}
                    {isVisible("name") && (
                      <TableHead>
                        <SortableHeaderButton
                          label="标签"
                          active={sortBy === "name"}
                          direction={sortOrder}
                          onToggle={() => toggleSort("name")}
                          title="按标签名称排序"
                        />
                      </TableHead>
                    )}
                    {isVisible("awemeCount") && (
                      <TableHead>
                        <SortableHeaderButton
                          label="视频"
                          active={sortBy === "aweme_count"}
                          direction={sortOrder}
                          onToggle={() => toggleSort("aweme_count")}
                          title="按关联视频数排序"
                        />
                      </TableHead>
                    )}
                    {isVisible("taskCount") && (
                      <TableHead>
                        <SortableHeaderButton
                          label="任务"
                          active={sortBy === "task_count"}
                          direction={sortOrder}
                          onToggle={() => toggleSort("task_count")}
                          title="按关联任务数排序"
                        />
                      </TableHead>
                    )}
                    {isVisible("lastSeen") && (
                      <TableHead>
                        <SortableHeaderButton
                          label="最近发现"
                          active={sortBy === "last_seen_at"}
                          direction={sortOrder}
                          onToggle={() => toggleSort("last_seen_at")}
                          title="按最近发现时间排序"
                        />
                      </TableHead>
                    )}
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.length ? (
                    rows.map((item) => (
                      <TableRow
                        key={item.id}
                        data-active={nav.activeId === item.id}
                        className="data-[active=true]:bg-muted/60"
                      >
                        {isVisible("name") && (
                          <TableCell className="font-medium">
                            #{item.name}
                          </TableCell>
                        )}
                        {isVisible("awemeCount") && (
                          <TableCell>{item.aweme_count}</TableCell>
                        )}
                        {isVisible("taskCount") && (
                          <TableCell>{item.task_count}</TableCell>
                        )}
                        {isVisible("lastSeen") && (
                          <TableCell>
                            {/* 报告 A16：时点列改相对时间，悬停看绝对时间 */}
                            <TimeAgo
                              value={item.last_seen_at}
                              neverText="从未"
                            />
                          </TableCell>
                        )}
                        <TableCell className="text-right">
                          <Button size="sm" variant="outline" asChild>
                            <Link
                              to="/douyin-library"
                              search={librarySearchFor(item.id)}
                            >
                              <Film />
                              查看视频
                            </Link>
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))
                  ) : tagsQuery.isLoading ? (
                    // 报告 O8：首次加载（还没有任何缓存数据）用骨架屏占位，
                    // 保留表格的列结构，数据到达时不会整体跳动。
                    Array.from({ length: 6 }, (_, index) => (
                      <TableRow key={`tags-skeleton-${index}`}>
                        {isVisible("name") && (
                          <TableCell>
                            <Skeleton className="h-4 w-32" />
                          </TableCell>
                        )}
                        {isVisible("awemeCount") && (
                          <TableCell>
                            <Skeleton className="h-4 w-10" />
                          </TableCell>
                        )}
                        {isVisible("taskCount") && (
                          <TableCell>
                            <Skeleton className="h-4 w-10" />
                          </TableCell>
                        )}
                        {isVisible("lastSeen") && (
                          <TableCell>
                            <Skeleton className="h-4 w-20" />
                          </TableCell>
                        )}
                        <TableCell className="text-right">
                          <Skeleton className="ml-auto h-8 w-24 rounded-md" />
                        </TableCell>
                      </TableRow>
                    ))
                  ) : hasFilter ? (
                    // 报告 A4：空是筛选造成的，行动按钮指向「清除筛选」而不是引导同步
                    <TableRow>
                      {/* 报告 A1：colSpan 跟随可见列数，否则隐藏列后空态只占一半宽度 */}
                      <TableCell colSpan={visibleCount} className="p-0">
                        <EmptyState
                          compact
                          icon={Tags}
                          title="没有符合当前条件的标签"
                          description="可以换个搜索词，或切回「全部赛道」后再试。"
                          action={
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={resetFilters}
                            >
                              清除筛选条件
                            </Button>
                          }
                        />
                      </TableCell>
                    </TableRow>
                  ) : (
                    // 报告 A4：真的一个标签都没有时，把下一步动作（同步历史标签）直接给出来
                    <TableRow>
                      {/* 报告 A1：colSpan 跟随可见列数，否则隐藏列后空态只占一半宽度 */}
                      <TableCell colSpan={visibleCount} className="p-0">
                        <EmptyState
                          compact
                          icon={Tags}
                          title="还没有标签"
                          description="标签从已采集作品中自动抽取，并建立与作品的关联。"
                          action={
                            <Button
                              size="sm"
                              onClick={() => sync.mutate()}
                              disabled={sync.isPending}
                            >
                              <RefreshCw
                                className={sync.isPending ? "animate-spin" : ""}
                              />
                              同步历史标签
                            </Button>
                          }
                        />
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
                {/* 报告 A11：表尾合计（复用本页已有的合计值，仅本页有数据时展示） */}
                {rows.length > 0 && (
                  <TableFooter>
                    <TableRow>
                      {/* 报告 A1：合计行也要跟着列可见性，否则整行错位 */}
                      {isVisible("name") && <TableCell>本页合计</TableCell>}
                      {isVisible("awemeCount") && (
                        <TableCell>{pageAwemeCount}</TableCell>
                      )}
                      {isVisible("taskCount") && (
                        <TableCell>{pageTaskCount}</TableCell>
                      )}
                      {isVisible("lastSeen") && <TableCell />}
                      <TableCell />
                    </TableRow>
                  </TableFooter>
                )}
              </Table>
            </div>
          )}
          <Pager
            page={page}
            pageSize={pageSize}
            total={tagsQuery.data?.count ?? 0}
            onPageChange={setPage}
            showJumper
            totalLabel={(total) => `共 ${total} 个标签`}
          />
        </CardContent>
      </Card>
    </div>
  )
}
