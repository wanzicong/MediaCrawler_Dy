import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ArrowLeft,
  ExternalLink,
  Heart,
  MessageCircle,
  RefreshCw,
  Star,
  Users,
} from "lucide-react"
import { useState } from "react"

import {
  ApiError,
  type DouyinCreatorPublic,
  DouyinCreatorsService,
  DouyinService,
  type DouyinWorkPublic,
} from "@/client"
import { CopyableId } from "@/components/Common/CopyableId"
import { EmptyState } from "@/components/Common/EmptyState"
import { PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { ScrollLoader } from "@/components/Common/ScrollLoader"
import { TimeAgo } from "@/components/Common/TimeAgo"
import {
  usePersistentViewMode,
  ViewModeToggle,
} from "@/components/Common/ViewModeToggle"
import { CreatorAvatar } from "@/components/Douyin/CreatorAvatar"
import { SourceBadge } from "@/components/Douyin/SourceSelect"
import { TaskStatusBadge } from "@/components/Douyin/TaskStatusBadge"
import { TrackBadge } from "@/components/Douyin/TrackSelect"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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
import { useListFeed } from "@/hooks/useListFeed"
import { formatDateTime } from "@/lib/time"
import { handleError } from "@/utils"

const worksPageSize = 24

export const Route = createFileRoute("/_layout/douyin-creators_/$creatorId")({
  component: CreatorDetailPage,
  head: () => ({ meta: [{ title: "达人详情 - 灵感采集台" }] }),
})

/**
 * 达人详情页。
 *
 * 左侧是主页基础信息（头像、抖音号、粉丝/获赞/主页作品数、签名、IP 属地，
 * 由「刷新达人信息」同步回填），右侧是统计与关联任务；下方是该达人在我们这里
 * 已采集的作品列表（按作品库接口过滤 creator_hash，滚动加载）。
 */
function CreatorDetailPage() {
  const { creatorId } = Route.useParams()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [syncing, setSyncing] = useState(false)
  // 主页基础信息的三视图（卡片 / 横条 / 表格），偏好持久化，与列表页一致
  const [viewMode, changeViewMode] = usePersistentViewMode(
    "douyin-creator-detail-view",
  )

  const creatorsQuery = useQuery({
    queryKey: ["douyin-creator", creatorId],
    // 之前这里拉「列表前 500 条」再按 id 找，达人超过 500 位后
    // 后面的达人一进详情页就是「没有找到这位达人」。改为单条查询接口。
    queryFn: async () => {
      try {
        return await DouyinCreatorsService.getCreator({ creatorId })
      } catch (error) {
        // 404 表示达人确实不存在（已删除 / 链接过期）：返回 null 走「没有找到」空态，
        // 其余错误照常抛出，由下面的「读取失败」重试态处理。
        if (error instanceof ApiError && error.status === 404) return null
        throw error
      }
    },
  })
  const creator = creatorsQuery.data ?? null

  const tasksQuery = useQuery({
    queryKey: ["douyin-creator-tasks", creatorId],
    queryFn: () => DouyinCreatorsService.listCreatorTasks({ creatorId }),
    enabled: Boolean(creator),
  })

  const worksFeed = useListFeed<DouyinWorkPublic>({
    queryKey: ["douyin-creator-works", creator?.creator_hash ?? ""],
    pageSize: worksPageSize,
    mode: "scroll",
    page: 0,
    fetchPage: (skip, limit) =>
      DouyinService.listLibraryWorks({
        creatorHash: creator?.creator_hash,
        downloadStatus: "all",
        limit,
        skip,
      }),
    getKey: (row) => row.aweme.aweme_id,
  })

  const refreshProfile = useMutation({
    mutationFn: async () => {
      setSyncing(true)
      return DouyinCreatorsService.syncCreatorProfiles({
        requestBody: {
          creator_ids: [creatorId],
          limit: 1,
          only_missing: false,
        },
      })
    },
    onSuccess: async (result) => {
      setSyncing(false)
      if (result.synced_count === 0) {
        showErrorToast(
          result.data[0]?.profile_error || "主页信息同步失败，请稍后重试",
        )
      } else {
        showSuccessToast("已更新该达人的主页信息")
      }
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["douyin-creator", creatorId],
        }),
        queryClient.invalidateQueries({ queryKey: ["douyin-creators"] }),
      ])
    },
    onError: (error: ApiError) => {
      setSyncing(false)
      handleError.call(showErrorToast, error)
    },
  })

  if (creatorsQuery.isError) {
    return (
      <QueryErrorState
        title="达人详情读取失败"
        description="请检查服务连接后重试。"
        onRetry={() => void creatorsQuery.refetch()}
        retrying={creatorsQuery.isFetching}
      />
    )
  }
  if (creatorsQuery.isLoading) {
    return (
      <div className="page-stack">
        <Skeleton className="h-28 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    )
  }
  if (!creator) {
    return (
      <EmptyState
        icon={Users}
        title="没有找到这位达人"
        description="它可能已被删除。返回达人列表看看其它达人。"
        action={
          <Button size="sm" asChild>
            <Link to="/douyin-creators">返回达人列表</Link>
          </Button>
        }
      />
    )
  }

  const tasks = tasksQuery.data ?? []

  return (
    <div className="page-stack">
      <PageHero
        eyebrow="达人详情"
        icon={Users}
        title={creator.nickname || "未命名达人"}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={syncing || refreshProfile.isPending}
              onClick={() => refreshProfile.mutate()}
            >
              <RefreshCw className={syncing ? "animate-spin" : ""} />
              {syncing ? "同步中…" : "刷新主页信息"}
            </Button>
            <Button size="sm" variant="outline" asChild>
              <a
                href={`https://www.douyin.com/user/${creator.sec_uid}`}
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink />
                在抖音中打开
              </a>
            </Button>
            <Button size="sm" variant="outline" asChild>
              <Link
                to="/douyin-library"
                search={{ creator: creator.creator_hash }}
              >
                在作品库中筛选
              </Link>
            </Button>
          </div>
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" size="sm" className="-ml-3" asChild>
            <Link to="/douyin-creators">
              <ArrowLeft />
              返回达人列表
            </Link>
          </Button>
          <TrackBadge
            trackId={creator.track_id}
            trackName={creator.track_name}
            isDefault={creator.track_is_default}
          />
          <Badge variant={creator.enabled ? "secondary" : "outline"}>
            {creator.enabled ? "已启用" : "已停用"}
          </Badge>
          {creator.unique_id && (
            <span className="rounded-full border bg-card/70 px-3 py-1 text-xs">
              抖音号 {creator.unique_id}
            </span>
          )}
          {creator.ip_location && (
            <span className="rounded-full border bg-card/70 px-3 py-1 text-xs">
              {creator.ip_location}
            </span>
          )}
          <span className="flex items-center gap-1 rounded-full border bg-card/70 px-3 py-1 text-xs">
            达人 ID <CopyableId value={creator.id} label="达人 ID" />
          </span>
        </div>
      </PageHero>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Card className="py-0">
          <CardHeader className="flex flex-row items-center justify-between gap-3 p-4 pb-2">
            <CardTitle className="text-sm">主页基础信息</CardTitle>
            {/* 三种展示形式与列表页一致：表格（默认）/ 横条 / 卡片，偏好本地持久化 */}
            <ViewModeToggle
              value={viewMode}
              onChange={changeViewMode}
              label="切换达人信息展示方式"
            />
          </CardHeader>
          <CardContent className="p-4 pt-2">
            {viewMode === "table" ? (
              <CreatorProfileTable creator={creator} />
            ) : viewMode === "rows" ? (
              <CreatorProfileRows creator={creator} />
            ) : (
              <CreatorProfileCards creator={creator} />
            )}
          </CardContent>
        </Card>

        <Card className="py-0">
          <CardHeader className="p-4 pb-2">
            <CardTitle className="text-sm">采集情况</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5 p-4 pt-2 text-xs">
            <StatusRow label="关联任务" value={`${creator.task_count} 个`} />
            <StatusRow
              label="进行中"
              value={`${creator.active_task_count} 个`}
            />
            <StatusRow
              label="最近采集"
              value={formatDateTime(creator.last_crawled_at, {
                fallback: "从未",
              })}
            />
            <StatusRow
              label="最近更新"
              value={formatDateTime(creator.updated_at, { fallback: "—" })}
            />
            <StatusRow
              label="加入时间"
              value={formatDateTime(creator.created_at, { fallback: "—" })}
            />
          </CardContent>
        </Card>
      </div>

      <Card className="py-0">
        <CardHeader className="p-4 pb-2">
          <CardTitle className="text-sm">关联任务（{tasks.length}）</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {tasks.length === 0 ? (
            <p className="p-4 pt-0 text-xs text-muted-foreground">
              这位达人还没有关联的采集任务。
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>任务</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>作品</TableHead>
                    <TableHead>评论</TableHead>
                    <TableHead>创建时间</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tasks.map((task) => (
                    <TableRow key={task.id}>
                      <TableCell>
                        <Link
                          to="/douyin/$taskId"
                          params={{ taskId: task.id }}
                          className="line-clamp-2 max-w-md text-xs text-primary hover:underline"
                          title={task.display_title ?? task.id}
                        >
                          {task.display_title || task.id.slice(0, 8)}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <TaskStatusBadge status={task.status} />
                      </TableCell>
                      <TableCell className="text-xs">
                        {task.aweme_count}
                      </TableCell>
                      <TableCell className="text-xs">
                        {task.comment_count}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        <TimeAgo value={task.created_at} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="py-0">
        <CardHeader className="p-4 pb-2">
          <CardTitle className="text-sm">
            已采集作品（{worksFeed.total}）
          </CardTitle>
        </CardHeader>
        <CardContent className="p-4 pt-2">
          {worksFeed.isError ? (
            <QueryErrorState
              title="作品读取失败"
              description="请检查服务连接后重试。"
              onRetry={() => void worksFeed.refetch()}
              retrying={worksFeed.isFetching}
            />
          ) : worksFeed.isLoading ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 6 }, (_, index) => (
                <Skeleton
                  key={`creator-work-${index}`}
                  className="h-24 rounded-xl"
                />
              ))}
            </div>
          ) : worksFeed.rows.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              这位达人还没有采集到作品。
            </p>
          ) : (
            <>
              <div className="grid max-h-[32rem] gap-2 overflow-y-auto pr-1 sm:grid-cols-2 xl:grid-cols-3">
                {worksFeed.rows.map((row) => (
                  <CreatorWorkRow key={row.aweme.aweme_id} row={row} />
                ))}
              </div>
              <ScrollLoader
                loadedCount={worksFeed.rows.length}
                total={worksFeed.total}
                hasMore={worksFeed.hasMore}
                isFetching={worksFeed.isFetchingMore}
                onLoadMore={worksFeed.loadMore}
              />
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function CreatorWorkRow({ row }: { row: DouyinWorkPublic }) {
  const aweme = row.aweme
  return (
    <Link
      to="/douyin-library/video/$awemeId"
      params={{ awemeId: aweme.aweme_id }}
      className="flex gap-2 rounded-xl border p-2 transition hover:border-primary/35"
    >
      <div className="aspect-video w-20 shrink-0 overflow-hidden rounded bg-muted">
        {aweme.cover_url ? (
          <img
            src={aweme.cover_url}
            alt=""
            className="h-full w-full object-cover"
            loading="lazy"
          />
        ) : null}
      </div>
      <div className="min-w-0 flex-1">
        <p className="line-clamp-2 text-xs font-medium leading-4.5">
          {aweme.title || aweme.aweme_id}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <Heart className="size-3" />
            {aweme.liked_count}
          </span>
          <span className="inline-flex items-center gap-1">
            <MessageCircle className="size-3" />
            {aweme.comment_count}
          </span>
          <span className="inline-flex items-center gap-1">
            <Star className="size-3" />
            {aweme.collected_count}
          </span>
          <span>{row.persisted_comment_count} 条已存评论</span>
        </div>
        <div className="mt-1 flex items-center gap-1">
          <SourceBadge
            sourceType={aweme.source_type}
            sourceLabel={aweme.source_label}
            className="text-[10px]"
          />
        </div>
      </div>
    </Link>
  )
}

/**
 * 主页基础信息的字段清单：三种展示形式共用同一份数据，避免三种视图口径漂移。
 *
 * 参数：
 *     creator: 达人公开模型。
 * 返回：
 *     按展示顺序排列的「字段名 / 展示值」列表。
 */
function creatorProfileFields(creator: DouyinCreatorPublic) {
  return [
    { label: "抖音昵称", value: creator.nickname || "未命名达人" },
    { label: "抖音号", value: creator.unique_id || "—" },
    { label: "粉丝", value: creator.follower_count.toLocaleString("zh-CN") },
    {
      label: "获赞",
      value: creator.total_favorited.toLocaleString("zh-CN"),
    },
    {
      label: "主页作品",
      value: creator.aweme_total_count.toLocaleString("zh-CN"),
    },
    {
      label: "已采集作品",
      value: creator.aweme_count.toLocaleString("zh-CN"),
    },
    { label: "IP 属地", value: creator.ip_location || "—" },
    { label: "个性签名", value: creator.signature || "—" },
    {
      label: "主页同步",
      value: creator.profile_synced_at
        ? formatDateTime(creator.profile_synced_at, { fallback: "—" })
        : creator.profile_error
          ? `同步失败：${creator.profile_error}`
          : "未同步",
    },
    { label: "备注", value: creator.notes || "—" },
  ]
}

/** 卡片视图（默认）：头像 + 签名 + 指标块，适合快速扫一眼。 */
function CreatorProfileCards({ creator }: { creator: DouyinCreatorPublic }) {
  return (
    <div className="space-y-3">
      <div className="flex items-start gap-3">
        <CreatorAvatar
          name={creator.nickname}
          seed={creator.creator_hash}
          src={creator.avatar_url || undefined}
          className="size-16"
          initialClassName="text-xl"
        />
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-base font-semibold">
            {creator.nickname || "未命名达人"}
          </p>
          {creator.signature && (
            <p className="whitespace-pre-wrap break-words text-xs leading-5 text-muted-foreground">
              {creator.signature}
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            {creator.profile_synced_at ? (
              <>
                主页信息更新于 <TimeAgo value={creator.profile_synced_at} />
              </>
            ) : creator.profile_error ? (
              <span className="text-destructive">
                同步失败：{creator.profile_error}
              </span>
            ) : (
              "主页信息未同步，点右上角「刷新主页信息」补全"
            )}
          </p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Metric label="粉丝" value={creator.follower_count} />
        <Metric label="获赞" value={creator.total_favorited} />
        <Metric label="主页作品" value={creator.aweme_total_count} />
        <Metric label="已采集作品" value={creator.aweme_count} />
      </div>
      {creator.notes && (
        <p className="rounded-lg bg-muted/45 px-3 py-2 text-xs text-muted-foreground">
          备注：{creator.notes}
        </p>
      )}
    </div>
  )
}

/** 横条视图：一行一条「字段 / 值」，信息密度介于卡片与表格之间。 */
function CreatorProfileRows({ creator }: { creator: DouyinCreatorPublic }) {
  return (
    <div className="flex flex-col gap-1.5">
      {creatorProfileFields(creator).map((field) => (
        <div
          key={field.label}
          className="flex items-start justify-between gap-3 rounded-lg bg-muted/35 px-2.5 py-1.5 text-xs"
        >
          <span className="shrink-0 text-muted-foreground">{field.label}</span>
          <span className="min-w-0 break-words text-right font-medium">
            {field.value}
          </span>
        </div>
      ))}
    </div>
  )
}

/** 表格视图：字段名与值两列，适合逐项核对与复制。 */
function CreatorProfileTable({ creator }: { creator: DouyinCreatorPublic }) {
  return (
    <div className="overflow-x-auto rounded-xl border">
      <Table className="min-w-[420px]">
        <TableHeader>
          <TableRow>
            <TableHead className="w-32">字段</TableHead>
            <TableHead>值</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {creatorProfileFields(creator).map((field) => (
            <TableRow key={field.label}>
              <TableCell className="text-xs text-muted-foreground">
                {field.label}
              </TableCell>
              <TableCell className="break-words text-xs">
                {field.value}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg bg-muted/45 px-2.5 py-2">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-sm font-semibold tabular-nums">{value}</p>
    </div>
  )
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  )
}
