import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  FolderPlus,
  Heart,
  ListPlus,
  RefreshCw,
  Star,
  Trash2,
  UserRoundPlus,
} from "lucide-react"
import { useDeferredValue, useMemo, useState } from "react"

import {
  type ApiError,
  type DouyinAccountAwemePublic,
  DouyinAccountsService,
  type DouyinCreatorPublic,
  DouyinCreatorsService,
  DouyinService,
} from "@/client"
import { BulkActionBar } from "@/components/Common/BulkActionBar"
import { confirmDialog } from "@/components/Common/confirm-dialog"
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
import {
  usePersistentViewMode,
  ViewModeToggle,
} from "@/components/Common/ViewModeToggle"
import { AssignCategoryDialog } from "@/components/Douyin/AssignCategoryDialog"
import { CreateTaskDialog } from "@/components/Douyin/CreateTaskDialog"
import { CreatorAvatar } from "@/components/Douyin/CreatorAvatar"
import {
  CreatorCard,
  creatorCardGridClass,
} from "@/components/Douyin/CreatorCard"
import { TrackSelect } from "@/components/Douyin/TrackSelect"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
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
import useCustomToast from "@/hooks/useCustomToast"
import { useListFeed } from "@/hooks/useListFeed"
import { formatDateTime } from "@/lib/time"
import { cn } from "@/lib/utils"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/douyin-mine")({
  component: MyAssetsPage,
  head: () => ({ meta: [{ title: "我的 - 灵感采集台" }] }),
})

type Tab = "following" | "liked" | "collected"
const pageSize = 40
/** 批量加入达人名单：每批条数与批间隔（后端单批上限 200，这里取更保守的值限流） */
const promoteBatchSize = 50
const promoteBatchIntervalMs = 800

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
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  // 批量加入达人名单的弹窗、目标赛道与进度（进度只在批量运行时显示）
  const [promoteOpen, setPromoteOpen] = useState(false)
  const [promoteTrackId, setPromoteTrackId] = useState("")
  const [promoteProgress, setPromoteProgress] = useState<{
    added: number
    remaining: number
  } | null>(null)
  const [loadMode, changeLoadMode] = usePersistentLoadMode(
    "douyin-mine-load-mode",
  )
  // 关注列表与达人列表共用同一套展示形态（表格 / 横条 / 卡片）
  const [followingView, setFollowingView] = usePersistentViewMode(
    "douyin-mine-following-view",
  )
  // 已进达人名单的关注可像达人列表一样多选后批量操作
  const [selectedCreators, setSelectedCreators] = useState<Set<string>>(
    new Set(),
  )
  const [assignCategoryOpen, setAssignCategoryOpen] = useState(false)

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
  /** 关注列表的写入（加入名单 / 清洗 / 启停 / 移出名单）后同步刷新两个列表 */
  const refreshAfterPromote = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["douyin-mine-followings"] }),
      queryClient.invalidateQueries({ queryKey: ["douyin-creators"] }),
    ])
  }
  /**
   * 批量加入达人名单：按批调用后端并留出批间隔。
   *
   * 服务端限流保证单次请求最多处理 promoteBatchSize 位，前端在这里串行续批，
   * 每批之间等待 promoteBatchIntervalMs，避免一次点下去向上千条关注同时写入。
   */
  const promoteFollowings = useMutation({
    mutationFn: async () => {
      let added = 0
      let remaining = 0
      setPromoteProgress({ added, remaining })
      // 硬上限兜底：后端异常返回「还有剩余但没有进展」时也不会无限循环
      for (let round = 0; round < 200; round += 1) {
        const result = await DouyinService.promoteMineFollowings({
          requestBody: {
            account_id: activeId,
            track_id: promoteTrackId || undefined,
            search: deferredSearch.trim() || undefined,
            limit: promoteBatchSize,
          },
        })
        added += result.added_count
        remaining = result.remaining_count
        setPromoteProgress({ added, remaining })
        if (
          remaining === 0 ||
          result.added_count + result.existing_count === 0
        ) {
          break
        }
        await new Promise((resolve) =>
          setTimeout(resolve, promoteBatchIntervalMs),
        )
      }
      return { added, remaining }
    },
    onSuccess: async ({ added, remaining }) => {
      showSuccessToast(
        remaining
          ? `已加入 ${added} 位达人，仍有 ${remaining} 位未加入（可再次点击继续）`
          : `已加入 ${added} 位达人到达人名单`,
      )
      setPromoteProgress(null)
      setPromoteOpen(false)
      await refreshAfterPromote()
    },
    onError: (error) => {
      setPromoteProgress(null)
      handleError.call(showErrorToast, error as ApiError)
    },
  })
  /** 行内加入名单：只处理这一位（同样走服务端的单批接口） */
  const promoteOneFollowing = useMutation({
    mutationFn: (followingId: string) =>
      DouyinService.promoteMineFollowings({
        requestBody: {
          account_id: activeId,
          track_id: promoteTrackId || undefined,
          following_ids: [followingId],
          limit: 1,
        },
      }),
    onSuccess: async (result) => {
      showSuccessToast(
        result.added_count ? "已加入达人名单" : "该博主已在达人名单中",
      )
      await refreshAfterPromote()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })

  /** 关注列表里已进名单的博主就是达人：启停 / 删除 / 批量操作直接复用达人侧接口 */
  const toggleCreator = useMutation({
    mutationFn: (item: DouyinCreatorPublic) =>
      DouyinCreatorsService.editCreator({
        creatorId: item.id,
        requestBody: { enabled: !item.enabled },
      }),
    onSuccess: refreshAfterPromote,
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const removeCreator = useMutation({
    mutationFn: (id: string) =>
      DouyinCreatorsService.deleteCreator({ creatorId: id }),
    onSuccess: async () => {
      showSuccessToast("已从达人名单移除，历史任务和作品未受影响")
      await refreshAfterPromote()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const bulkRemoveCreators = useMutation({
    mutationFn: (ids: string[]) =>
      DouyinCreatorsService.bulkDeleteCreators({ requestBody: { ids } }),
    onSuccess: async () => {
      showSuccessToast(`已从达人名单移除 ${selectedCreators.size} 位`)
      setSelectedCreators(new Set())
      await refreshAfterPromote()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  // 「刷新主页信息」：按批清洗（未进名单的先加入名单），进度沿用达人列表的口径
  const [profileSyncProgress, setProfileSyncProgress] = useState<{
    synced: number
    failed: number
    remaining: number
  } | null>(null)
  const syncFollowingProfiles = useMutation({
    mutationFn: async () => {
      let synced = 0
      let failed = 0
      let remaining = 0
      setProfileSyncProgress({ synced, failed, remaining })
      // 硬上限兜底：后端异常时不会无限循环
      for (let round = 0; round < 60; round += 1) {
        const result = await DouyinService.syncMineFollowingsProfiles({
          requestBody: {
            account_id: activeId,
            track_id: promoteTrackId || undefined,
            limit: promoteBatchSize,
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
        await new Promise((resolve) =>
          setTimeout(resolve, promoteBatchIntervalMs),
        )
      }
      return { synced, failed }
    },
    onSuccess: async ({ synced, failed }) => {
      showSuccessToast(
        failed
          ? `已清洗 ${synced} 位博主的主页信息，${failed} 位失败（可稍后重试）`
          : `已清洗 ${synced} 位博主的主页信息`,
      )
      setProfileSyncProgress(null)
      await refreshAfterPromote()
    },
    onError: (error) => {
      setProfileSyncProgress(null)
      handleError.call(showErrorToast, error as ApiError)
    },
  })
  /** 行内清洗：只处理这一位（会先加入达人名单再拉主页信息） */
  const syncOneFollowing = useMutation({
    mutationFn: (followingId: string) =>
      DouyinService.syncMineFollowingsProfiles({
        requestBody: {
          account_id: activeId,
          track_id: promoteTrackId || undefined,
          following_ids: [followingId],
          limit: 1,
        },
      }),
    onSuccess: async (result) => {
      const row = result.data[0]
      showSuccessToast(
        result.synced_count
          ? `已清洗「${row?.creator?.nickname ?? "该博主"}」的主页信息`
          : "主页信息清洗失败，请稍后重试",
      )
      await refreshAfterPromote()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const followingRows = followingFeed.rows
  // 批量任务对话框需要稳定的达人数组，否则每次渲染都会重置弹窗状态
  const selectedCreatorRows = useMemo(
    () =>
      followingRows
        .map((row) => row.creator)
        .filter((item): item is DouyinCreatorPublic =>
          item ? selectedCreators.has(item.id) : false,
        ),
    [followingRows, selectedCreators],
  )
  // 与达人列表一致的三种展示形态
  const followingListClass =
    followingView === "cards"
      ? creatorCardGridClass
      : followingView === "rows"
        ? "space-y-2"
        : "overflow-hidden rounded-xl border"

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
              setSelectedCreators(new Set())
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
                setSelectedCreators(new Set())
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
              placeholder={
                tab === "following"
                  ? "搜索昵称、抖音号或备注"
                  : "搜索昵称 / 作品"
              }
              aria-label={
                tab === "following"
                  ? "搜索关注博主的昵称、抖音号或备注"
                  : "搜索昵称或作品"
              }
              className="h-9 max-w-56"
            />
            <Select value={sort} onValueChange={setSort}>
              <SelectTrigger className="h-9 w-40" aria-label="排序方式">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="fetched_at:desc">最近采集</SelectItem>
                {tab === "following" ? (
                  <>
                    <SelectItem value="profile_synced_at:desc">
                      最近更新信息
                    </SelectItem>
                    <SelectItem value="follower_count:desc">
                      粉丝最多
                    </SelectItem>
                    <SelectItem value="aweme_total_count:desc">
                      主页作品最多
                    </SelectItem>
                    <SelectItem value="nickname:asc">昵称 A-Z</SelectItem>
                  </>
                ) : (
                  <SelectItem value="liked_count:desc">点赞最多</SelectItem>
                )}
              </SelectContent>
            </Select>
            {tab === "following" && activeId && (
              <Button
                size="sm"
                variant="outline"
                className="h-9 gap-1.5"
                onClick={() => setPromoteOpen(true)}
                title="把「我的关注」里未进入达人名单的博主批量加入达人名单"
              >
                <ListPlus className="size-4" />
                加入达人名单
              </Button>
            )}
            {tab === "following" && activeId && (
              <Button
                size="sm"
                variant="outline"
                className="h-9 gap-1.5"
                disabled={
                  syncFollowingProfiles.isPending ||
                  Boolean(profileSyncProgress)
                }
                onClick={() => syncFollowingProfiles.mutate()}
                title="从抖音主页清洗真实昵称、抖音号、粉丝数、IP 属地等信息；未进达人名单的博主会先加入名单（默认赛道）"
              >
                <RefreshCw
                  className={
                    syncFollowingProfiles.isPending
                      ? "size-4 animate-spin"
                      : "size-4"
                  }
                />
                {profileSyncProgress
                  ? `清洗中 ${profileSyncProgress.synced}${
                      profileSyncProgress.remaining
                        ? ` / 剩 ${profileSyncProgress.remaining}`
                        : ""
                    }`
                  : "刷新主页信息"}
              </Button>
            )}
            {tab === "following" && (
              <ViewModeToggle
                value={followingView}
                onChange={setFollowingView}
              />
            )}
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
          ) : tab === "following" ? (
            // 关注列表与达人列表共用同一张卡片：展示、按钮、交互完全一致；
            // 还没进名单的博主只能拿到平台脱敏昵称，先提供「清洗主页信息」入口
            <div className={followingListClass}>
              {followingRows.map((row) => {
                const creator = row.creator ?? null
                if (creator) {
                  return (
                    <CreatorCard
                      key={row.id}
                      creator={creator}
                      viewMode={followingView}
                      highlighted={false}
                      selected={selectedCreators.has(creator.id)}
                      onToggleSelect={(checked) =>
                        setSelectedCreators((current) => {
                          const next = new Set(current)
                          if (checked) next.add(creator.id)
                          else next.delete(creator.id)
                          return next
                        })
                      }
                      onToggle={toggleCreator.mutate}
                      onRemove={removeCreator.mutate}
                      onSaved={refreshAfterPromote}
                      extra={
                        <p className="mt-1 text-[10px] text-muted-foreground">
                          关注时间{" "}
                          {formatDateTime(row.fetched_at, { fallback: "—" })}
                          {" · "}
                          {row.is_mutual ? "互关" : "已关注"}
                          {row.nickname ? ` · 平台昵称 ${row.nickname}` : ""}
                        </p>
                      }
                    />
                  )
                }
                return (
                  <Card
                    key={row.id}
                    className={cn(
                      followingView === "table"
                        ? "rounded-none border-0 border-b shadow-none last:border-b-0"
                        : "transition hover:shadow-md",
                    )}
                  >
                    <CardContent
                      className={
                        followingView === "cards"
                          ? "p-4"
                          : "flex flex-wrap items-center gap-3 p-3"
                      }
                    >
                      <CreatorAvatar
                        name={row.nickname || "博主"}
                        seed={row.uid_hash}
                        src={row.avatar_url || undefined}
                        className="size-12"
                        initialClassName="text-base"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="truncate font-medium">
                            {row.nickname || "未命名博主"}
                          </p>
                          <Badge
                            variant="outline"
                            className="border-amber-400/60 bg-amber-50 text-amber-700"
                          >
                            未清洗
                          </Badge>
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">
                          平台只返回脱敏昵称 · 粉丝 {row.follower_count} · 作品{" "}
                          {row.aweme_count} ·{" "}
                          {row.is_mutual ? "互关" : "已关注"} · 关注时间{" "}
                          {formatDateTime(row.fetched_at, { fallback: "—" })}
                        </p>
                      </div>
                      <div
                        className={`flex flex-wrap justify-end gap-1 ${
                          followingView === "cards" ? "mt-3" : "ml-auto"
                        }`}
                      >
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={syncOneFollowing.isPending}
                          onClick={() => syncOneFollowing.mutate(row.id)}
                          title="拉取主页真实昵称、抖音号、粉丝数等信息（会先加入达人名单）"
                        >
                          <RefreshCw /> 清洗主页信息
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 px-2 text-xs"
                          disabled={promoteOneFollowing.isPending}
                          onClick={() => promoteOneFollowing.mutate(row.id)}
                          title="加入达人名单（未在弹窗选择赛道时使用默认赛道）"
                        >
                          <ListPlus className="size-3.5" />
                          加入名单
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          ) : (
            <div className="overflow-x-auto rounded-xl border">
              <Table className="min-w-[760px]">
                <TableHeader>
                  <TableRow>
                    <TableHead>作品</TableHead>
                    <TableHead>作者</TableHead>
                    <TableHead>互动</TableHead>
                    <TableHead>采集时间</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {feed.rows.map((rawRow) => {
                    const row = rawRow as DouyinAccountAwemePublic
                    return (
                      <TableRow key={row.id}>
                        <TableCell className="max-w-96">
                          <span className="line-clamp-2 block text-xs">
                            {row.title || row.aweme_id}
                          </span>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {row.nickname || "—"}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {`赞 ${row.liked_count} · 评 ${row.comment_count} · 藏 ${row.collected_count}`}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {formatDateTime(row.fetched_at, { fallback: "—" })}
                        </TableCell>
                        <TableCell className="text-right">
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

      {/* 批量加入达人名单：按批 + 批间隔调用后端，运行中不允许关闭弹窗 */}
      <Dialog
        open={promoteOpen}
        onOpenChange={(open) => {
          if (!promoteFollowings.isPending) setPromoteOpen(open)
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>批量加入达人名单</DialogTitle>
            <DialogDescription>
              把该账号「我的关注」里还没进入达人名单的博主加入达人名单；已在名单中的会自动跳过，不会重复创建。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-2">
              <Label>目标赛道</Label>
              <TrackSelect
                value={promoteTrackId}
                onValueChange={setPromoteTrackId}
                enabled={promoteOpen}
              />
            </div>
            <ul className="list-disc space-y-1 pl-5 text-xs leading-5 text-muted-foreground">
              <li>
                每批最多 {promoteBatchSize} 位，批与批之间间隔约{" "}
                {promoteBatchIntervalMs / 1000} 秒（服务端单次上限 200 位）。
              </li>
              <li>
                {deferredSearch.trim()
                  ? `只处理当前搜索「${deferredSearch.trim()}」命中的关注。`
                  : "未设置搜索词时按粉丝数从多到少依次加入。"}
              </li>
              <li>
                加入后可以直接点上方「刷新主页信息」清洗真实昵称、抖音号等资料，
                也可以到达人列表用「未拉取详情」筛选后批量创建「达人详情」任务。
              </li>
            </ul>
            {promoteProgress && (
              <output className="block text-xs text-muted-foreground">
                已加入 {promoteProgress.added} 位
                {promoteProgress.remaining
                  ? ` · 剩余 ${promoteProgress.remaining} 位`
                  : " · 已完成"}
              </output>
            )}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={promoteFollowings.isPending}
              onClick={() => setPromoteOpen(false)}
            >
              取消
            </Button>
            <Button
              type="button"
              variant="brand"
              disabled={!promoteTrackId || promoteFollowings.isPending}
              onClick={() => promoteFollowings.mutate()}
            >
              {promoteFollowings.isPending ? "加入中…" : "开始加入"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 已进达人名单的关注就是达人：批量操作与达人列表保持一致 */}
      {tab === "following" && selectedCreators.size > 0 && (
        <BulkActionBar
          count={selectedCreators.size}
          label={`已选 ${selectedCreators.size} 位达人`}
          onClear={() => setSelectedCreators(new Set())}
          actions={
            <>
              <CreateTaskDialog
                initialTrackId=""
                initialCrawlType="creator"
                initialCreators={selectedCreatorRows}
                triggerLabel="批量创建任务"
                triggerVariant="secondary"
              />
              <Button
                size="sm"
                variant="destructive"
                disabled={bulkRemoveCreators.isPending}
                onClick={async () => {
                  const ok = await confirmDialog({
                    title: `把选中的 ${selectedCreators.size} 位移出达人名单？`,
                    description: "只是移出名单，历史任务和作品不会被删除。",
                    confirmText: "移出名单",
                    variant: "destructive",
                  })
                  if (!ok) return
                  bulkRemoveCreators.mutate([...selectedCreators])
                }}
              >
                <Trash2 />
                移出名单
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
      )}
      <AssignCategoryDialog
        open={assignCategoryOpen}
        onOpenChange={setAssignCategoryOpen}
        creatorIds={[...selectedCreators]}
        onDone={showSuccessToast}
        onError={showErrorToast}
      />
    </div>
  )
}
