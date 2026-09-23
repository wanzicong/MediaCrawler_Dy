import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Heart, Star, UserRoundPlus } from "lucide-react"
import { useDeferredValue, useState } from "react"

import {
  type DouyinAccountAwemePublic,
  DouyinAccountsService,
  type DouyinFollowingPublic,
  DouyinService,
} from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import {
  LoadModeToggle,
  usePersistentLoadMode,
} from "@/components/Common/LoadModeToggle"
import { Pager } from "@/components/Common/Pager"
import { PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { RefreshIndicator } from "@/components/Common/RefreshIndicator"
import { ScrollLoader } from "@/components/Common/ScrollLoader"
import { CreateTaskDialog } from "@/components/Douyin/CreateTaskDialog"
import { CreatorAvatar } from "@/components/Douyin/CreatorAvatar"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useListFeed } from "@/hooks/useListFeed"
import { formatDateTime } from "@/lib/time"

export const Route = createFileRoute("/_layout/douyin-mine")({
  component: MyAssetsPage,
  head: () => ({ meta: [{ title: "我的 - 灵感采集台" }] }),
})

type Tab = "following" | "liked" | "collected"
const pageSize = 40

function MyAssetsPage() {
  const accountsQuery = useQuery({
    queryKey: ["douyin-accounts", "mine"],
    queryFn: () => DouyinAccountsService.listAccounts({ limit: 100 }),
  })
  const accounts = accountsQuery.data?.data ?? []
  const [accountId, setAccountId] = useState("")
  const activeId = accountId || accounts[0]?.id || ""
  const active = accounts.find((item) => item.id === activeId)

  const [tab, setTab] = useState<Tab>("following")
  const [search, setSearch] = useState("")
  const deferredSearch = useDeferredValue(search)
  const [sort, setSort] = useState("fetched_at:desc")
  const [page, setPage] = useState(0)
  const [loadMode, changeLoadMode] = usePersistentLoadMode(
    "douyin-mine-load-mode",
  )

  const summaryQuery = useQuery({
    queryKey: ["douyin-mine-summary", activeId],
    queryFn: () => DouyinService.getMineSummary({ accountId: activeId }),
    enabled: Boolean(activeId),
  })
  const [sortBy, sortOrder] = sort.split(":") as [string, "asc" | "desc"]

  const followingFeed = useListFeed({
    queryKey: ["douyin-mine-followings", activeId, deferredSearch, sort],
    pageSize,
    mode: loadMode,
    page,
    fetchPage: async (skip, limit) => {
      const result = await DouyinService.getMineFollowings({
        accountId: activeId,
        search: deferredSearch.trim() || undefined,
        sortBy: sortBy as "fetched_at",
        sortOrder,
        skip,
        limit,
      })
      return result
    },
    getKey: (item) => item.id,
  })
  const awemeFeed = useListFeed({
    queryKey: ["douyin-mine-awemes", activeId, tab, deferredSearch, sort],
    pageSize,
    mode: loadMode,
    page,
    fetchPage: async (skip, limit) => {
      const result = await DouyinService.getMineAwemes({
        accountId: activeId,
        kind: tab === "collected" ? "collected" : "liked",
        search: deferredSearch.trim() || undefined,
        sortBy: sortBy as "fetched_at",
        sortOrder,
        skip,
        limit,
      })
      return result
    },
    getKey: (item) => item.id,
  })
  const feed = tab === "following" ? followingFeed : awemeFeed

  return (
    <div className="page-stack">
      <PageHero
        eyebrow="账号资产"
        icon={Star}
        title="我的"
        description="按账号查看并采集「我关注的博主」「我点赞的作品」「我收藏的作品」；数据按账号独立保存，与内容库互不影响。"
      >
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={activeId}
            onValueChange={(value) => {
              setAccountId(value)
              setPage(0)
            }}
          >
            <SelectTrigger className="h-9 min-w-40" aria-label="选择账号">
              <SelectValue
                placeholder={
                  accountsQuery.isLoading ? "正在加载账号…" : "选择账号"
                }
              />
            </SelectTrigger>
            <SelectContent>
              {accounts.map((item) => (
                <SelectItem key={item.id} value={item.id}>
                  账号 · {item.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {activeId && (
            <>
              <CreateTaskDialog
                initialTrackId=""
                initialCrawlType="following"
                initialAccountId={activeId}
                triggerLabel="采集关注"
                triggerVariant="outline"
              />
              <CreateTaskDialog
                initialTrackId=""
                initialCrawlType="liked"
                initialAccountId={activeId}
                triggerLabel="采集点赞"
                triggerVariant="outline"
              />
              <CreateTaskDialog
                initialTrackId=""
                initialCrawlType="collected"
                initialAccountId={activeId}
                triggerLabel="采集收藏"
                triggerVariant="outline"
              />
            </>
          )}
          <RefreshIndicator
            updatedAt={feed.dataUpdatedAt}
            refreshing={feed.isFetching}
            onRefresh={() => void feed.refetch()}
          />
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          关注{" "}
          <strong className="text-foreground">
            {summaryQuery.data?.following_count ?? "—"}
          </strong>
          {" · "}点赞{" "}
          <strong className="text-foreground">
            {summaryQuery.data?.liked_count ?? "—"}
          </strong>
          {" · "}收藏{" "}
          <strong className="text-foreground">
            {summaryQuery.data?.collected_count ?? "—"}
          </strong>
          {active?.name ? `（${active.name}）` : ""}
          {" · "}最近采集{" "}
          {summaryQuery.data?.following_fetched_at
            ? formatDateTime(summaryQuery.data.following_fetched_at, {
                fallback: "—",
              })
            : "—"}
        </p>
      </PageHero>

      <Card>
        <CardContent className="space-y-3 pt-6">
          <div className="flex flex-wrap items-center gap-2">
            <Tabs
              value={tab}
              onValueChange={(value) => {
                setTab(value as Tab)
                setPage(0)
              }}
            >
              <TabsList>
                <TabsTrigger value="following">我的关注</TabsTrigger>
                <TabsTrigger value="liked">我的点赞</TabsTrigger>
                <TabsTrigger value="collected">我的收藏</TabsTrigger>
              </TabsList>
            </Tabs>
            <Input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value)
                setPage(0)
              }}
              placeholder="搜索昵称 / 作品"
              className="h-9 max-w-56"
            />
            <Select value={sort} onValueChange={setSort}>
              <SelectTrigger className="h-9 w-40" aria-label="排序方式">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="fetched_at:desc">最近采集</SelectItem>
                {tab === "following" ? (
                  <SelectItem value="follower_count:desc">粉丝最多</SelectItem>
                ) : (
                  <SelectItem value="liked_count:desc">点赞最多</SelectItem>
                )}
              </SelectContent>
            </Select>
            <LoadModeToggle value={loadMode} onChange={changeLoadMode} />
          </div>

          {feed.isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : feed.isError ? (
            <QueryErrorState
              title="读取失败"
              description="请稍后重试，或先为这个账号采集一次。"
              onRetry={() => void feed.refetch()}
            />
          ) : feed.rows.length === 0 ? (
            <EmptyState
              icon={
                tab === "following"
                  ? UserRoundPlus
                  : tab === "liked"
                    ? Heart
                    : Star
              }
              title={deferredSearch ? "没有匹配的记录" : "还没有采集数据"}
              description={
                deferredSearch
                  ? "换个关键词试试。"
                  : "点右上角对应按钮创建采集任务，完成后数据会出现在这里。"
              }
            />
          ) : (
            <div className="overflow-x-auto rounded-xl border">
              <Table className="min-w-[760px]">
                <TableHeader>
                  <TableRow>
                    <TableHead>
                      {tab === "following" ? "博主" : "作品"}
                    </TableHead>
                    <TableHead>
                      {tab === "following" ? "粉丝/作品" : "作者"}
                    </TableHead>
                    <TableHead>
                      {tab === "following" ? "关系" : "互动"}
                    </TableHead>
                    <TableHead>采集时间</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {feed.rows.map((rawRow) => {
                    // 两个 Tab 的行结构不同：这里按当前 Tab 取各自字段
                    const row = rawRow as DouyinFollowingPublic &
                      DouyinAccountAwemePublic
                    return (
                    <TableRow key={row.id}>
                      <TableCell className="max-w-96">
                        {tab === "following" ? (
                          <span className="flex items-center gap-2">
                            <CreatorAvatar
                              name={row.nickname || "博主"}
                              seed={row.uid_hash}
                              src={row.avatar_url || undefined}
                              className="size-8"
                            />
                            <span className="truncate text-xs font-medium">
                              {row.nickname || "未命名博主"}
                            </span>
                          </span>
                        ) : (
                          <span className="line-clamp-2 block text-xs">
                            {row.title || row.aweme_id}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {tab === "following"
                          ? `${row.follower_count} / ${row.aweme_count}`
                          : row.nickname || "—"}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {tab === "following" ? (
                          row.is_mutual ? (
                            <Badge variant="secondary">互关</Badge>
                          ) : (
                            "已关注"
                          )
                        ) : (
                          `赞 ${row.liked_count} · 评 ${row.comment_count} · 藏 ${row.collected_count}`
                        )}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatDateTime(row.fetched_at, { fallback: "—" })}
                      </TableCell>
                      <TableCell className="text-right">
                        {tab === "following" ? (
                          row.in_creator_list ? (
                            <Badge variant="secondary">已在名单</Badge>
                          ) : (
                            <span className="text-xs text-muted-foreground">
                              未入名单
                            </span>
                          )
                        ) : (
                          <a
                            className="text-xs text-primary hover:underline"
                            href={
                              row.aweme_url ||
                              `https://www.douyin.com/video/${row.aweme_id}`
                            }
                            target="_blank"
                            rel="noreferrer"
                          >
                            在抖音中打开
                          </a>
                        )}
                      </TableCell>
                    </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          )}

          {loadMode === "scroll" && feed.rows.length > 0 && (
            <ScrollLoader
              loadedCount={feed.rows.length}
              total={feed.total}
              hasMore={feed.hasMore}
              isFetching={feed.isFetchingMore}
              onLoadMore={feed.loadMore}
            />
          )}
          {loadMode === "paged" && (
            <Pager
              page={page}
              pageSize={pageSize}
              total={feed.total}
              totalLabel={(total) => `共 ${total} 条`}
              onPageChange={setPage}
              showJumper
            />
          )}
        </CardContent>
      </Card>
    </div>
  )
}
