import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  Outlet,
  useRouterState,
} from "@tanstack/react-router"
import {
  Captions,
  Database,
  Download,
  ExternalLink,
  Film,
  FolderSearch2,
  HardDrive,
  Languages,
  ListFilter,
  PlaySquare,
  RefreshCw,
  RotateCcw,
  Search,
  UploadCloud,
  UserRound,
} from "lucide-react"
import { useMemo, useState } from "react"

import {
  type CrawlTaskPublic,
  type DouyinMediaAssetPublic,
  DouyinService,
  DouyinTagsService,
  type DouyinWorkPublic,
} from "@/client"
import { MetricCard, PageHero } from "@/components/Common/PageShell"
import { AwemeActions } from "@/components/Douyin/AwemeActions"
import { downloadMedia } from "@/components/Douyin/UnifiedWorksPanel"
import { VideoPreviewDialog } from "@/components/Douyin/VideoPreviewDialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import { getDouyinVideoUrl, handleError } from "@/utils"

const pageSize = 24
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

const sortValues = new Set<SortValue>([
  "downloaded_at:desc",
  "published_at:desc",
  "published_at:asc",
  "liked_count:desc",
  "comment_count:desc",
  "collected_count:desc",
  "persisted_comment_count:desc",
  "file_size:desc",
])

export type LibraryFeedSearch = {
  start?: string
  q: string | undefined
  task: string | undefined
  creator: string | undefined
  tag: string | undefined
  storage: "all" | "local" | "minio" | undefined
  subtitle: "all" | "pending" | "running" | "completed" | "failed" | undefined
  sort: SortValue | undefined
}

export const Route = createFileRoute("/_layout/douyin-library")({
  validateSearch: (search: Record<string, unknown>) => ({
    q: typeof search.q === "string" ? search.q : undefined,
    task: typeof search.task === "string" ? search.task : undefined,
    creator: typeof search.creator === "string" ? search.creator : undefined,
    tag: typeof search.tag === "string" ? search.tag : undefined,
    storage: ["all", "local", "minio"].includes(String(search.storage))
      ? (search.storage as LibraryFeedSearch["storage"])
      : undefined,
    subtitle: ["all", "pending", "running", "completed", "failed"].includes(
      String(search.subtitle),
    )
      ? (search.subtitle as LibraryFeedSearch["subtitle"])
      : undefined,
    sort:
      typeof search.sort === "string" &&
      sortValues.has(search.sort as SortValue)
        ? (search.sort as SortValue)
        : undefined,
  }),
  component: DouyinVideoLibrary,
  head: () => ({ meta: [{ title: "视频资源库 - 灵感采集台" }] }),
})

function DouyinVideoLibrary() {
  const routeSearch = Route.useSearch()
  const feedRouteActive = useRouterState({
    select: (state) => state.location.pathname.endsWith("/feed"),
  })
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [page, setPage] = useState(0)
  const [search, setSearch] = useState(routeSearch.q ?? "")
  const [taskId, setTaskId] = useState(routeSearch.task ?? "all")
  const [creatorHash, setCreatorHash] = useState(routeSearch.creator ?? "all")
  const [tagId, setTagId] = useState(routeSearch.tag ?? "all")
  const [storageBackend, setStorageBackend] = useState<
    "all" | "local" | "minio"
  >(routeSearch.storage ?? "all")
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

  const tasksQuery = useQuery({
    queryKey: ["douyin-library-tasks"],
    queryFn: () => DouyinService.listTasks({ limit: 100 }),
    staleTime: 30_000,
  })
  const creatorsQuery = useQuery({
    queryKey: ["douyin-library-creators", taskId],
    queryFn: () =>
      DouyinService.listLibraryCreators({
        taskId: taskId === "all" ? undefined : taskId,
      }),
    staleTime: 30_000,
  })
  const tagsQuery = useQuery({
    queryKey: ["douyin-library-tags", taskId],
    queryFn: () =>
      DouyinTagsService.listTags({
        taskId: taskId === "all" ? undefined : taskId,
        sortBy: "aweme_count",
        sortOrder: "desc",
        limit: 500,
      }),
    staleTime: 30_000,
  })
  const worksQuery = useQuery({
    queryKey: [
      "douyin-library-works",
      page,
      search,
      taskId,
      creatorHash,
      tagId,
      storageBackend,
      subtitleStatus,
      sort,
    ],
    queryFn: () =>
      DouyinService.listLibraryWorks({
        search: search.trim() || undefined,
        taskId: taskId === "all" ? undefined : taskId,
        creatorHash: creatorHash === "all" ? undefined : creatorHash,
        tagId: tagId === "all" ? undefined : tagId,
        downloadStatus: "downloaded",
        storageBackend,
        subtitleStatus,
        sortBy,
        sortOrder,
        skip: page * pageSize,
        limit: pageSize,
      }),
    placeholderData: (previous) => previous,
    refetchInterval: 5_000,
  })
  const taskMap = useMemo(
    () => new Map((tasksQuery.data?.data ?? []).map((task) => [task.id, task])),
    [tasksQuery.data?.data],
  )
  const rows = worksQuery.data?.data ?? []
  const pageLocal = rows.filter(
    (row) => row.media?.storage_backend === "local",
  ).length
  const pageMinio = rows.filter(
    (row) => row.media?.storage_backend === "minio",
  ).length

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
  const migrationFilters = {
    search: search.trim() || undefined,
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
          ? `已将 ${result.queued} 个本地视频加入 MinIO 迁移队列`
          : result.message,
      )
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const feedSearch: LibraryFeedSearch = {
    q: search.trim() || undefined,
    task: taskId === "all" ? undefined : taskId,
    creator: creatorHash === "all" ? undefined : creatorHash,
    tag: tagId === "all" ? undefined : tagId,
    storage: storageBackend,
    subtitle: subtitleStatus,
    sort,
  }

  if (feedRouteActive) return <Outlet />

  const resetPage = () => setPage(0)
  return (
    <div className="page-stack">
      <PageHero
        eyebrow="内容资产中心"
        icon={FolderSearch2}
        title="视频资源库"
        description="跨任务管理所有已下载作品。按关键词、任务、创作者、存储位置和字幕状态筛选，直接播放、查看评论或继续处理。"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button asChild disabled={!rows.length}>
              <Link to="/douyin-library/feed" search={feedSearch}>
                <PlaySquare />
                沉浸播放
              </Link>
            </Button>
            <Button
              variant="secondary"
              disabled={
                migrateLibrary.isPending ||
                storageBackend === "minio" ||
                !(worksQuery.data?.count ?? 0)
              }
              onClick={() => {
                if (
                  window.confirm(
                    "确认把当前筛选条件下的所有本地视频上传到 MinIO？只有完整上传并校验成功后才会删除本地文件。",
                  )
                ) {
                  migrateLibrary.mutate()
                }
              }}
            >
              <UploadCloud />
              {migrateLibrary.isPending ? "正在加入队列…" : "本地视频转 MinIO"}
            </Button>
            <Button
              variant="outline"
              onClick={() => invalidate()}
              disabled={worksQuery.isFetching}
            >
              <RefreshCw
                className={worksQuery.isFetching ? "animate-spin" : ""}
              />
              刷新资源
            </Button>
          </div>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard
            icon={Film}
            label="匹配视频"
            value={worksQuery.data?.count ?? 0}
            tone="violet"
            compact
          />
          <MetricCard
            icon={UserRound}
            label="可选创作者"
            value={creatorsQuery.data?.count ?? 0}
            tone="blue"
            compact
          />
          <MetricCard
            icon={HardDrive}
            label="本页本地存储"
            value={pageLocal}
            tone="mint"
            compact
          />
          <MetricCard
            icon={Database}
            label="本页 MinIO"
            value={pageMinio}
            tone="coral"
            compact
          />
        </div>
      </PageHero>

      <Card>
        <CardContent className="space-y-4 p-4 md:p-6">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-7">
            <div className="relative md:col-span-2 xl:col-span-2">
              <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value)
                  resetPage()
                }}
                placeholder="搜索标题、描述、创作者或作品号"
                className="pl-9"
              />
            </div>
            <Select
              value={taskId}
              onValueChange={(value) => {
                setTaskId(value)
                setCreatorHash("all")
                setTagId("all")
                resetPage()
              }}
            >
              <SelectTrigger>
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
              <SelectTrigger>
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
              <SelectTrigger>
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
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部存储</SelectItem>
                <SelectItem value="local">本地服务器</SelectItem>
                <SelectItem value="minio">MinIO</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={subtitleStatus}
              onValueChange={(value) => {
                setSubtitleStatus(value as typeof subtitleStatus)
                resetPage()
              }}
            >
              <SelectTrigger>
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
          <div className="flex flex-col gap-3 border-t pt-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted-foreground">
              只展示已下载资源；点击卡片操作可直接播放、下载、查看或重爬评论。
            </p>
            <Select
              value={sort}
              onValueChange={(value) => {
                setSort(value as SortValue)
                resetPage()
              }}
            >
              <SelectTrigger className="w-full sm:w-52">
                <ListFilter />
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
        </CardContent>
      </Card>

      {rows.length ? (
        <div className="grid gap-5 md:grid-cols-2 2xl:grid-cols-3">
          {rows.map((row) => (
            <VideoCard
              key={row.aweme.id}
              row={row}
              task={taskMap.get(row.aweme.task_id)}
              retry={(asset) =>
                retry.mutate({ taskId: row.aweme.task_id, assetId: asset.id })
              }
              retranslate={(asset) =>
                retranslate.mutate({
                  taskId: row.aweme.task_id,
                  assetId: asset.id,
                })
              }
              onDownload={(asset) =>
                downloadMedia(row.aweme.task_id, asset, showErrorToast)
              }
              feedSearch={feedSearch}
            />
          ))}
        </div>
      ) : (
        <div className="rounded-3xl border border-dashed py-24 text-center text-muted-foreground">
          <Film className="mx-auto mb-4 size-10 opacity-40" />
          {worksQuery.isLoading
            ? "正在加载视频资源…"
            : "没有符合当前条件的已下载视频"}
        </div>
      )}

      <Pager
        page={page}
        count={worksQuery.data?.count ?? 0}
        onChange={setPage}
      />
    </div>
  )
}

function VideoCard({
  row,
  task,
  retry,
  retranslate,
  onDownload,
  feedSearch,
}: {
  row: DouyinWorkPublic
  task?: CrawlTaskPublic
  retry: (asset: DouyinMediaAssetPublic) => void
  retranslate: (asset: DouyinMediaAssetPublic) => void
  onDownload: (asset: DouyinMediaAssetPublic) => void
  feedSearch: LibraryFeedSearch
}) {
  const aweme = row.aweme
  const asset = row.media
  const active = task ? activeStatuses.has(task.status) : false
  return (
    <Card className="group overflow-hidden transition hover:-translate-y-0.5 hover:shadow-lg">
      <div className="relative aspect-video overflow-hidden bg-muted">
        {aweme.cover_url ? (
          <img
            src={aweme.cover_url}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover transition duration-500 group-hover:scale-[1.03]"
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <Film className="size-12 opacity-25" />
          </div>
        )}
        <div className="absolute inset-x-0 bottom-0 flex items-end justify-between bg-gradient-to-t from-black/75 to-transparent p-3 pt-10 text-white">
          <span className="text-xs">发布 {formatUnix(aweme.create_time)}</span>
          <Badge className="border-white/20 bg-black/35 text-white hover:bg-black/35">
            {asset?.storage_backend === "minio" ? "MinIO" : "本地"}
          </Badge>
        </div>
      </div>
      <CardContent className="space-y-4 p-5">
        <div>
          <h2 className="line-clamp-2 min-h-12 font-semibold leading-6">
            {aweme.title || aweme.aweme_id}
          </h2>
          <div className="mt-2 flex items-center justify-between gap-3 text-xs text-muted-foreground">
            <span className="truncate">{aweme.nickname || "匿名创作者"}</span>
            <span className="font-mono">{aweme.aweme_id}</span>
          </div>
          {(row.tags?.length ?? 0) > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {(row.tags ?? []).slice(0, 5).map((tag) => (
                <Badge key={tag.id} variant="outline">
                  #{tag.name}
                </Badge>
              ))}
            </div>
          )}
        </div>
        <div className="grid grid-cols-4 rounded-xl bg-muted/40 p-3 text-center text-xs">
          <Stat label="点赞" value={compact(aweme.liked_count)} />
          <Stat label="评论" value={compact(aweme.comment_count)} />
          <Stat label="收藏" value={compact(aweme.collected_count)} />
          <Stat label="已存" value={compact(row.persisted_comment_count)} />
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Badge variant="outline">{task ? taskLabel(task) : "历史任务"}</Badge>
          {asset?.subtitle?.status === "completed" && (
            <Badge variant="secondary">
              <Captions /> 字幕完成
            </Badge>
          )}
          <span className="ml-auto">
            {formatFileSize(asset?.file_size ?? 0)}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-1 border-t pt-4">
          {asset?.download_available && (
            <VideoPreviewDialog taskId={aweme.task_id} asset={asset} />
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
          {asset?.download_available && (
            <Button
              size="icon-sm"
              variant="ghost"
              aria-label="重新翻译"
              onClick={() => retranslate(asset)}
            >
              <Languages />
            </Button>
          )}
          {asset &&
            (asset.status === "failed" ||
              asset.subtitle?.status === "failed") && (
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label="重试资源"
                onClick={() => retry(asset)}
              >
                <RotateCcw />
              </Button>
            )}
          <div className="ml-auto flex items-center gap-1">
            <AwemeActions
              taskId={aweme.task_id}
              aweme={aweme}
              active={active}
            />
            <Button size="icon-sm" variant="ghost" asChild>
              <a
                href={getDouyinVideoUrl(aweme.aweme_id)}
                target="_blank"
                rel="noreferrer"
                aria-label="在抖音中打开视频"
              >
                <ExternalLink />
              </a>
            </Button>
            <Button size="icon-sm" variant="ghost" asChild>
              <Link
                to="/douyin/$taskId"
                params={{ taskId: aweme.task_id }}
                aria-label="进入任务"
              >
                <ExternalLink />
              </Link>
            </Button>
            {asset?.download_available && (
              <Button size="icon-sm" variant="ghost" asChild>
                <Link
                  to="/douyin-library/feed"
                  search={{
                    ...feedSearch,
                    start: `video-${aweme.aweme_id}`,
                  }}
                  aria-label="沉浸播放"
                >
                  <PlaySquare />
                </Link>
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="font-semibold">{value}</p>
      <p className="mt-1 text-muted-foreground">{label}</p>
    </div>
  )
}

function Pager({
  page,
  count,
  onChange,
}: {
  page: number
  count: number
  onChange: (page: number) => void
}) {
  const pages = Math.max(1, Math.ceil(count / pageSize))
  if (pages <= 1) return null
  return (
    <div className="flex items-center justify-center gap-3 py-2">
      <Button
        variant="outline"
        disabled={page === 0}
        onClick={() => onChange(page - 1)}
      >
        上一页
      </Button>
      <span className="text-sm text-muted-foreground">
        第 {page + 1} / {pages} 页 · 共 {count} 条
      </span>
      <Button
        variant="outline"
        disabled={page + 1 >= pages}
        onClick={() => onChange(page + 1)}
      >
        下一页
      </Button>
    </div>
  )
}

function taskLabel(task: CrawlTaskPublic) {
  const request = task.request as { keywords?: string[]; video_ids?: string[] }
  const target = request.keywords?.[0] || request.video_ids?.[0]
  return target
    ? `${task.crawl_type} · ${target}`
    : `${task.crawl_type} · ${task.id.slice(0, 8)}`
}

function formatUnix(value: number | null) {
  if (!value) return "未知"
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium" }).format(
    new Date(value * 1_000),
  )
}

function compact(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value)
}

function formatFileSize(value: number) {
  if (!value) return "未知大小"
  const units = ["B", "KB", "MB", "GB"]
  const index = Math.min(
    Math.floor(Math.log(value) / Math.log(1024)),
    units.length - 1,
  )
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`
}
