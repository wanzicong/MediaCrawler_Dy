import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ArrowLeft,
  Download,
  ExternalLink,
  FileVideo,
  Film,
  LoaderCircle,
  PlaySquare,
  RefreshCw,
} from "lucide-react"
import { useState } from "react"

import {
  type DouyinMediaAssetPublic,
  DouyinService,
  type DouyinWorkPublic,
} from "@/client"
import { CopyableId } from "@/components/Common/CopyableId"
import { EmptyState } from "@/components/Common/EmptyState"
import { PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { TimeAgo } from "@/components/Common/TimeAgo"
import { SourceBadge } from "@/components/Douyin/SourceSelect"
import { SubtitlePanel } from "@/components/Douyin/SubtitlePanel"
import { TaskStatusBadge } from "@/components/Douyin/TaskStatusBadge"
import { TrackBadge } from "@/components/Douyin/TrackSelect"
import { downloadMedia } from "@/components/Douyin/UnifiedWorksPanel"
import {
  subtitleTrackSource,
  useVideoPreviewSource,
} from "@/components/Douyin/useVideoPreviewSource"
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
import { formatDateTime } from "@/lib/time"
import { cn } from "@/lib/utils"
import { getDouyinVideoUrl } from "@/utils"

export const Route = createFileRoute("/_layout/douyin-library_/video/$awemeId")(
  {
    component: VideoDetailPage,
    head: () => ({ meta: [{ title: "视频详情 - 灵感采集台" }] }),
  },
)

/**
 * 视频详情页。
 *
 * 以作品（aweme_id）为主键：同一作品可能被多个任务采到，这里把各任务下的
 * 资产、字幕与采集时间全部列出来，播放优先用「已下载」的那份，
 * 否则回退到采集地址在线播放。入口在视频资源库列表与任务详情的作品列表。
 */
function VideoDetailPage() {
  const { awemeId } = Route.useParams()
  const [titleExpanded, setTitleExpanded] = useState(false)
  // 作品号是唯一的，直接用搜索定位再取精确匹配。
  // 注意两个默认值都会漏数据：作品库默认只返回「已下载」且按作品去重，
  // 这里要的是「各任务下的副本」，所以显式放开下载状态并切到任务粒度。
  const worksQuery = useQuery({
    queryKey: ["douyin-video-detail", awemeId],
    queryFn: () =>
      DouyinService.listLibraryWorks({
        search: awemeId,
        downloadStatus: "all",
        groupBy: "task",
        limit: 100,
      }),
  })
  // 任务信息（赛道 / 状态 / 采集时间）来自任务列表，作品行里只有媒体与字幕
  const tasksQuery = useQuery({
    queryKey: ["douyin-video-detail-tasks"],
    queryFn: () => DouyinService.listTasks({ limit: 100 }),
    staleTime: 30_000,
  })
  const taskMap = new Map(
    (tasksQuery.data?.data ?? []).map((task) => [task.id, task]),
  )

  const copies = (worksQuery.data?.data ?? []).filter(
    (row) => row.aweme.aweme_id === awemeId,
  )
  // 播放优先选已下载的副本，其次任一副本（后者会走采集地址在线播放）
  const primary =
    copies.find((row) => row.media?.download_available) ?? copies[0]

  if (worksQuery.isError) {
    return (
      <QueryErrorState
        title="视频详情读取失败"
        description="暂时无法获取这个作品的详情，请检查服务连接后重试。"
        onRetry={() => void worksQuery.refetch()}
        retrying={worksQuery.isFetching}
      />
    )
  }

  if (worksQuery.isLoading) {
    return (
      <div className="page-stack">
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-72 w-full rounded-xl" />
      </div>
    )
  }

  if (!primary) {
    return (
      <EmptyState
        icon={Film}
        title="没有找到这个作品"
        description="它可能已被清理，或者作品号不正确。返回视频资源库换个条件再找找。"
        action={
          <Button size="sm" asChild>
            <Link to="/douyin-library">返回视频资源库</Link>
          </Button>
        }
      />
    )
  }

  const aweme = primary.aweme
  const subtitle = primary.media?.subtitle
  const title = aweme.title || aweme.aweme_id
  // 采集来的标题常常是整段带话题的文案，默认收两行，需要时再展开
  const collapsibleTitle = title.length > 60

  return (
    <div className="page-stack">
      <PageHero
        eyebrow="视频详情"
        icon={FileVideo}
        title={title}
        titleClassName={cn(
          "break-words text-lg sm:text-xl",
          collapsibleTitle && !titleExpanded && "line-clamp-2",
        )}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {/* 详情页不轮询：下载 / 转写进行中时手动刷新一次即可 */}
            <Button
              size="sm"
              variant="outline"
              disabled={worksQuery.isFetching}
              onClick={() => {
                void worksQuery.refetch()
                void tasksQuery.refetch()
              }}
            >
              <RefreshCw
                className={worksQuery.isFetching ? "animate-spin" : ""}
              />
              刷新
            </Button>
            <Button size="sm" variant="outline" asChild>
              <a
                href={aweme.aweme_url || getDouyinVideoUrl(aweme.aweme_id)}
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink />
                在抖音中打开
              </a>
            </Button>
            <Button size="sm" variant="outline" asChild>
              <Link
                to="/douyin-library/feed"
                search={{ start: `video-${aweme.aweme_id}` }}
              >
                <PlaySquare />
                沉浸播放
              </Link>
            </Button>
            {primary.media?.download_available && (
              <DownloadAssetButton asset={primary.media} />
            )}
          </div>
        }
      >
        <div className="space-y-2">
          {collapsibleTitle && (
            <button
              type="button"
              className="block w-fit text-xs font-medium text-primary hover:underline"
              aria-expanded={titleExpanded}
              onClick={() => setTitleExpanded((expanded) => !expanded)}
            >
              {titleExpanded ? "收起标题" : "展开全部标题"}
            </button>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="ghost" size="sm" className="-ml-3" asChild>
              <Link to="/douyin-library">
                <ArrowLeft />
                返回视频资源库
              </Link>
            </Button>
            <span className="rounded-full border bg-card/70 px-3 py-1 text-xs font-medium">
              {aweme.nickname || "匿名创作者"}
            </span>
            <span className="rounded-full border bg-card/70 px-3 py-1 text-xs font-medium">
              发布{" "}
              {formatDateTime(
                aweme.create_time ? aweme.create_time * 1_000 : null,
                { fallback: "未知" },
              )}
            </span>
            <SourceBadge
              sourceType={aweme.source_type}
              sourceName={aweme.source_name}
              sourceLabel={aweme.source_label}
            />
            <span className="flex items-center gap-1 rounded-full border bg-card/70 px-3 py-1 text-xs font-medium">
              作品 <CopyableId value={aweme.aweme_id} label="作品号" />
            </span>
            {(primary.tags?.length ?? 0) > 0 &&
              (primary.tags ?? []).map((tag) => (
                <Badge key={tag.id} variant="outline">
                  #{tag.name}
                </Badge>
              ))}
          </div>
        </div>
      </PageHero>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <VideoPlayer copy={primary} />
        <div className="space-y-3">
          <Card className="py-0">
            <CardHeader className="p-4 pb-2">
              <CardTitle className="text-sm">互动数据</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-3 p-4 pt-2 text-xs">
              <Metric label="点赞" value={aweme.liked_count} />
              <Metric label="评论" value={aweme.comment_count} />
              <Metric label="收藏" value={aweme.collected_count} />
              <Metric label="分享" value={aweme.share_count} />
              <Metric
                label="已存评论"
                value={primary.persisted_comment_count}
              />
            </CardContent>
          </Card>
          <Card className="py-0">
            <CardHeader className="p-4 pb-2">
              <CardTitle className="text-sm">处理状态</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5 p-4 pt-2 text-xs">
              <StatusRow
                label="视频"
                value={mediaStatusText(primary.media)}
                detail={mediaDetailText(primary.media)}
              />
              <StatusRow
                label="字幕"
                value={
                  subtitle ? subtitleStatusText(subtitle.status) : "未生成字幕"
                }
                detail={
                  subtitle
                    ? `${subtitle.language || "auto"} · ${
                        subtitle.segments?.length ?? 0
                      } 段 · ${Math.round(subtitle.duration_seconds)}s`
                    : undefined
                }
              />
              <StatusRow
                label="采集任务"
                value={`共 ${copies.length} 个任务`}
              />
            </CardContent>
          </Card>
        </div>
      </div>

      <Card className="py-0">
        <CardHeader className="p-4 pb-2">
          <CardTitle className="text-sm">字幕内容</CardTitle>
        </CardHeader>
        <CardContent className="p-4 pt-2">
          {primary.media ? (
            <SubtitlePanel asset={primary.media} />
          ) : (
            <p className="text-xs text-muted-foreground">
              这个作品还没有媒体资产，先下载或执行字幕处理后再回来查看。
            </p>
          )}
        </CardContent>
      </Card>

      <Card className="overflow-hidden py-0">
        <CardHeader className="p-4 pb-2">
          <CardTitle className="text-sm">
            采集来源（{copies.length} 个任务）
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>任务</TableHead>
                  <TableHead>所属赛道</TableHead>
                  <TableHead>任务状态</TableHead>
                  <TableHead>视频 / 存储</TableHead>
                  <TableHead>字幕</TableHead>
                  <TableHead>采集时间</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {copies.map((row) => {
                  const task = taskMap.get(row.aweme.task_id)
                  return (
                    <TableRow key={row.media?.id ?? row.aweme.task_id}>
                      <TableCell>
                        <Link
                          to="/douyin/$taskId"
                          params={{ taskId: row.aweme.task_id }}
                          className="font-mono text-xs text-primary hover:underline"
                          aria-label={`进入任务 ${row.aweme.task_id}`}
                        >
                          {row.aweme.task_id.slice(0, 8)}
                        </Link>
                      </TableCell>
                      <TableCell>
                        {task?.track_id ? (
                          <TrackBadge
                            trackId={task.track_id}
                            trackName={task.track_name}
                            isDefault={task.track_is_default}
                            className="max-w-40"
                          />
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            —
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        {task ? (
                          <TaskStatusBadge status={task.status} />
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            —
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-xs">
                        {mediaStatusText(row.media)}
                        {/* 失败原因经常很长，这里截断展示，完整内容靠 title 悬停可读 */}
                        <span
                          className="ml-1 text-muted-foreground"
                          title={row.media?.error ?? undefined}
                        >
                          {mediaDetailText(row.media)}
                        </span>
                      </TableCell>
                      <TableCell className="text-xs">
                        {row.media?.subtitle
                          ? subtitleStatusText(row.media.subtitle.status)
                          : "无字幕"}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {task ? <TimeAgo value={task.created_at} /> : "—"}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function VideoPlayer({ copy }: { copy: DouyinWorkPublic }) {
  const source = useVideoPreviewSource({
    taskId: copy.aweme.task_id,
    asset: copy.media,
    aweme: copy.aweme,
  })
  // 播放器自身的报错（采集地址过期、存储文件损坏）与初始化错误合并展示。
  // 报错跟着流地址存：地址一变旧报错自动失效，不必再用 effect 重置状态。
  const [playerError, setPlayerError] = useState<{
    url: string | null
    message: string
  } | null>(null)
  const displayError =
    (playerError?.url === source.url ? playerError.message : null) ??
    source.error

  return (
    <Card className="overflow-hidden py-0">
      <CardContent className="p-0">
        <div className="relative flex aspect-video items-center justify-center overflow-hidden bg-black">
          {source.url && (
            <video
              key={source.url}
              className="h-full w-full"
              src={source.url}
              controls
              autoPlay
              playsInline
              preload="metadata"
              onError={() =>
                setPlayerError({
                  url: source.url,
                  message:
                    source.mode === "file"
                      ? "视频无法播放，请检查文件格式或存储服务"
                      : "采集地址已失效或源站拒绝访问，请在该任务重新采集后再播放",
                })
              }
            >
              <track
                kind="captions"
                src={subtitleTrackSource(copy.media)}
                srcLang={copy.media?.subtitle?.language || "zh"}
                label="任务字幕"
                default
              />
              当前浏览器不支持视频播放。
            </video>
          )}
          {/* 三种状态都覆盖在播放器之上（绝对定位），避免与 <video> 抢同一行布局 */}
          {source.loading && (
            <div className="absolute inset-0 flex items-center justify-center gap-2 text-sm text-white/70">
              <LoaderCircle className="animate-spin" />
              正在准备视频流…
            </div>
          )}
          {!source.loading && displayError && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/80">
              <p className="max-w-md px-6 text-center text-sm text-red-300">
                {displayError}
              </p>
            </div>
          )}
          {!source.loading && !displayError && source.unavailable && (
            <div className="absolute inset-0 flex items-center justify-center px-8 text-center text-white">
              <div className="flex max-w-lg flex-col items-center gap-2">
                <p className="text-base font-medium">暂无可播放的视频</p>
                <p className="text-sm leading-6 text-white/65">
                  该作品既没有下载好的文件，也没有保存的采集地址。先去对应任务下载后再回来。
                </p>
              </div>
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t px-4 py-2 text-xs text-muted-foreground">
          <span>
            {source.mode === "file"
              ? "播放已下载的文件（按需读取片段）"
              : "播放采集地址（服务端代理转发）"}
          </span>
          <span>
            来源任务{" "}
            <Link
              to="/douyin/$taskId"
              params={{ taskId: copy.aweme.task_id }}
              className="font-mono text-primary hover:underline"
            >
              {copy.aweme.task_id.slice(0, 8)}
            </Link>
          </span>
        </div>
      </CardContent>
    </Card>
  )
}

function DownloadAssetButton({ asset }: { asset: DouyinMediaAssetPublic }) {
  const { showErrorToast } = useCustomToast()
  return (
    <Button
      size="sm"
      variant="outline"
      onClick={() => downloadMedia(asset.task_id, asset, showErrorToast)}
    >
      <Download />
      下载
    </Button>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg bg-muted/45 px-2.5 py-2">
      <p className="text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-sm font-semibold tabular-nums">{value}</p>
    </div>
  )
}

function StatusRow({
  label,
  value,
  detail,
}: {
  label: string
  value: string
  detail?: string
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">
        <span className="font-medium">{value}</span>
        {detail && (
          <span className="mt-0.5 block text-[10px] text-muted-foreground">
            {detail}
          </span>
        )}
      </span>
    </div>
  )
}

function mediaStatusText(asset?: DouyinMediaAssetPublic | null): string {
  if (!asset) return "未下载"
  if (asset.download_available) {
    return asset.storage_backend === "minio" ? "云端已存" : "本地已存"
  }
  if (asset.status === "temporary") return "仅字幕（未保留视频）"
  if (asset.status === "failed") return "下载失败"
  if (asset.status === "queued") return "排队中"
  if (asset.status === "downloading") return "下载中"
  return "未下载"
}

function mediaDetailText(asset?: DouyinMediaAssetPublic | null): string {
  if (!asset) return ""
  if (asset.download_available) return formatFileSize(asset.file_size)
  return asset.error ? asset.error.slice(0, 40) : ""
}

function subtitleStatusText(status: string): string {
  const labels: Record<string, string> = {
    pending: "排队中",
    running: "处理中",
    completed: "已完成",
    failed: "失败",
  }
  return labels[status] ?? status
}

function formatFileSize(value: number) {
  if (!value) return "0 B"
  const units = ["B", "KB", "MB", "GB"]
  let size = value
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size.toFixed(1)} ${units[unit]}`
}
