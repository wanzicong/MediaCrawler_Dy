import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  Captions,
  Download,
  ExternalLink,
  FileDown,
  Languages,
  ListFilter,
  LoaderCircle,
  MessageCircle,
  PlaySquare,
  RefreshCw,
  RotateCcw,
  Search,
} from "lucide-react"
import { useMemo, useState } from "react"

import {
  type CrawlTaskPublic,
  type DouyinAwemePublic,
  type DouyinMediaAssetPublic,
  DouyinService,
  DouyinTagsService,
  OpenAPI,
} from "@/client"
import { AwemeActions } from "@/components/Douyin/AwemeActions"
import { InteractionComposerDialog } from "@/components/Douyin/InteractionComposerDialog"
import { MediaMigrationDialog } from "@/components/Douyin/MediaMigrationDialog"
import { ProcessMediaDialog } from "@/components/Douyin/ProcessMediaDialog"
import { VideoPreviewDialog } from "@/components/Douyin/VideoPreviewDialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
import { getDouyinVideoUrl, handleError } from "@/utils"

const pageSize = 20
type SortValue =
  | "published_at:desc"
  | "published_at:asc"
  | "liked_count:desc"
  | "comment_count:desc"
  | "collected_count:desc"
  | "persisted_comment_count:desc"

export function UnifiedWorksPanel({
  task,
  active,
}: {
  task: CrawlTaskPublic
  active: boolean
}) {
  const taskId = task.id
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [page, setPage] = useState(0)
  const [search, setSearch] = useState("")
  const [sort, setSort] = useState<SortValue>("published_at:desc")
  const [downloadStatus, setDownloadStatus] = useState("all")
  const [subtitleStatus, setSubtitleStatus] = useState("all")
  const [tagId, setTagId] = useState("all")
  const [selected, setSelected] = useState<string[]>([])
  const [subtitleFormat, setSubtitleFormat] = useState<"srt" | "vtt" | "txt">(
    "srt",
  )
  const [sortBy, sortOrder] = sort.split(":") as [
    (
      | "published_at"
      | "liked_count"
      | "comment_count"
      | "collected_count"
      | "persisted_comment_count"
    ),
    "asc" | "desc",
  ]
  const worksQuery = useQuery({
    queryKey: [
      "douyin-works",
      taskId,
      page,
      search,
      sort,
      downloadStatus,
      subtitleStatus,
      tagId,
    ],
    queryFn: () =>
      DouyinService.listWorks({
        taskId,
        search: search.trim() || undefined,
        downloadStatus: downloadStatus === "all" ? undefined : downloadStatus,
        subtitleStatus: subtitleStatus === "all" ? undefined : subtitleStatus,
        tagId: tagId === "all" ? undefined : tagId,
        sortBy,
        sortOrder,
        skip: page * pageSize,
        limit: pageSize,
      }),
    placeholderData: (previous) => previous,
    refetchInterval: active ? 2_000 : 5_000,
  })
  const tagsQuery = useQuery({
    queryKey: ["douyin-works-tags", taskId],
    queryFn: () =>
      DouyinTagsService.listTags({
        taskId,
        sortBy: "aweme_count",
        sortOrder: "desc",
        limit: 500,
      }),
    staleTime: 30_000,
  })
  const summaryQuery = useQuery({
    queryKey: ["douyin-media-summary", taskId],
    queryFn: () => DouyinService.getMediaSummary({ taskId }),
    refetchInterval: active ? 2_000 : 5_000,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["douyin-works", taskId] }),
      queryClient.invalidateQueries({ queryKey: ["douyin-media", taskId] }),
      queryClient.invalidateQueries({
        queryKey: ["douyin-media-summary", taskId],
      }),
    ])
  }
  const retry = useMutation({
    mutationFn: (assetIds: string[]) =>
      DouyinService.retryMedia({
        taskId,
        requestBody: {
          asset_ids: assetIds,
          retry_downloads: true,
          retry_subtitles: true,
        },
      }),
    onSuccess: async () => {
      showSuccessToast("失败项已重新排队")
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const retranslate = useMutation({
    mutationFn: (assetId: string) =>
      DouyinService.retranslateMedia({ taskId, assetId }),
    onSuccess: async () => {
      showSuccessToast("字幕已重新提交到远程服务")
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const rows = worksQuery.data?.data ?? []
  const pageIds = rows.map((row) => row.aweme.aweme_id)
  const allPageSelected =
    pageIds.length > 0 && pageIds.every((id) => selected.includes(id))
  const selectedAssets = rows
    .filter((row) => selected.includes(row.aweme.aweme_id) && row.media)
    .map((row) => row.media as DouyinMediaAssetPublic)
  const failedAssets = useMemo(
    () =>
      rows
        .map((row) => row.media)
        .filter((asset): asset is DouyinMediaAssetPublic =>
          Boolean(
            asset &&
              (asset.status === "failed" ||
                asset.subtitle?.status === "failed"),
          ),
        )
        .map((asset) => asset.id),
    [rows],
  )
  const summary = summaryQuery.data
  const lastMediaActivity = rows.reduce<string | null>((latest, row) => {
    const updatedAt = row.media?.updated_at
    if (!updatedAt) return latest
    return !latest || new Date(updatedAt) > new Date(latest)
      ? updatedAt
      : latest
  }, null)

  const exportSelection = async (kind: "comments" | "subtitles") => {
    if (!selected.length) {
      showErrorToast("请先选择至少一个作品")
      return
    }
    try {
      await downloadExport(
        taskId,
        kind,
        kind === "comments"
          ? { aweme_ids: selected }
          : { aweme_ids: selected, format: subtitleFormat },
      )
      showSuccessToast(kind === "comments" ? "评论 TXT 已导出" : "字幕已导出")
    } catch (reason) {
      showErrorToast(reason instanceof Error ? reason.message : "导出失败")
    }
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader className="border-b bg-muted/20">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <p className="text-sm font-medium text-primary">统一内容工作区</p>
            <CardTitle className="mt-1">作品、下载与字幕</CardTitle>
            <p className="mt-2 text-sm text-muted-foreground">
              一条作品记录同时展示发布时间、互动、已保存评论、视频存储和字幕状态。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {(summary?.local_downloaded ?? 0) > 0 && (
              <MediaMigrationDialog
                taskId={taskId}
                eligibleCount={summary?.local_downloaded ?? 0}
              />
            )}
            {!active &&
              task.checkpoint_phase !== "crawl" &&
              task.aweme_count > 0 && <ProcessMediaDialog task={task} />}
            {rows.some((row) => row.media?.download_available) && (
              <Button variant="outline" asChild>
                <Link
                  to="/douyin/$taskId/feed"
                  params={{ taskId }}
                  search={{ start: undefined }}
                >
                  <PlaySquare />
                  沉浸播放
                </Link>
              </Button>
            )}
            <Button
              variant="outline"
              onClick={() => invalidate()}
              disabled={worksQuery.isFetching}
            >
              <RefreshCw
                className={worksQuery.isFetching ? "animate-spin" : ""}
              />
              刷新
            </Button>
          </div>
        </div>
        {summary && task.status === "processing_media" && (
          <output className="mt-4 flex items-start gap-3 rounded-xl border border-cyan-500/30 bg-cyan-500/5 p-4">
            <LoaderCircle className="mt-0.5 size-5 shrink-0 animate-spin text-cyan-600" />
            <div className="space-y-1">
              <p className="text-sm font-medium">
                {task.resume_count > 0
                  ? `第 ${task.resume_count} 次恢复正在处理媒体`
                  : "正在处理视频与字幕"}
              </p>
              <p className="text-xs leading-5 text-muted-foreground">
                下载中 {summary.downloading} 条，排队 {summary.queued}{" "}
                条，下载失败 {summary.download_failed} 条
                {lastMediaActivity
                  ? `；最近进度更新：${formatDate(lastMediaActivity)}`
                  : ""}
                。页面每 2 秒自动刷新，无需重复提交。
              </p>
            </div>
          </output>
        )}
        {summary && (
          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
            <Summary label="作品" value={task.aweme_count} />
            <Summary
              label="视频完成"
              value={`${summary.downloaded} / ${summary.total}`}
            />
            <Summary
              label="下载中 / 排队"
              value={`${summary.downloading} / ${summary.queued}`}
            />
            <Summary label="视频失败" value={summary.download_failed} />
            <Summary
              label="字幕完成 / 失败"
              value={`${summary.subtitle_completed} / ${summary.subtitle_failed}`}
            />
            <Summary
              label="本地 / MinIO"
              value={`${summary.local_downloaded} / ${summary.minio_downloaded}`}
            />
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-4 p-4 md:p-6">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
          <div className="relative min-w-64 flex-1">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value)
                setPage(0)
              }}
              placeholder="搜索标题、作者或作品号"
              className="pl-9"
            />
          </div>
          <Select
            value={sort}
            onValueChange={(value) => {
              setSort(value as SortValue)
              setPage(0)
            }}
          >
            <SelectTrigger className="w-full xl:w-48">
              <ListFilter />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="published_at:desc">最新发布</SelectItem>
              <SelectItem value="published_at:asc">最早发布</SelectItem>
              <SelectItem value="liked_count:desc">点赞最多</SelectItem>
              <SelectItem value="comment_count:desc">评论最多</SelectItem>
              <SelectItem value="collected_count:desc">收藏最多</SelectItem>
              <SelectItem value="persisted_comment_count:desc">
                已保存评论最多
              </SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={downloadStatus}
            onValueChange={(value) => {
              setDownloadStatus(value)
              setPage(0)
            }}
          >
            <SelectTrigger className="w-full xl:w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部视频状态</SelectItem>
              <SelectItem value="downloaded">视频已完成</SelectItem>
              <SelectItem value="downloading">视频下载中</SelectItem>
              <SelectItem value="failed">视频失败</SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={subtitleStatus}
            onValueChange={(value) => {
              setSubtitleStatus(value)
              setPage(0)
            }}
          >
            <SelectTrigger className="w-full xl:w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部字幕状态</SelectItem>
              <SelectItem value="completed">字幕已完成</SelectItem>
              <SelectItem value="running">字幕处理中</SelectItem>
              <SelectItem value="failed">字幕失败</SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={tagId}
            onValueChange={(value) => {
              setTagId(value)
              setPage(0)
            }}
          >
            <SelectTrigger className="w-full xl:w-44">
              <SelectValue placeholder="全部标签" />
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
        </div>

        <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-muted/20 p-3">
          <span className="mr-1 text-sm text-muted-foreground">
            已选 {selected.length} 项
          </span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => exportSelection("comments")}
            disabled={!selected.length}
          >
            <FileDown />
            导出评论 TXT
          </Button>
          <Select
            value={subtitleFormat}
            onValueChange={(value) =>
              setSubtitleFormat(value as "srt" | "vtt" | "txt")
            }
          >
            <SelectTrigger className="h-8 w-24">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="srt">SRT</SelectItem>
              <SelectItem value="vtt">VTT</SelectItem>
              <SelectItem value="txt">TXT</SelectItem>
            </SelectContent>
          </Select>
          <Button
            size="sm"
            variant="outline"
            onClick={() => exportSelection("subtitles")}
            disabled={!selected.length}
          >
            <Captions />
            导出字幕
          </Button>
          {failedAssets.length > 0 && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => retry.mutate(failedAssets)}
              disabled={retry.isPending}
            >
              <RotateCcw />
              重试本页失败项
            </Button>
          )}
          {selectedAssets.some(
            (asset) =>
              asset.storage_backend === "local" && asset.download_available,
          ) && (
            <MediaMigrationDialog
              taskId={taskId}
              eligibleCount={selectedAssets.length}
              assetIds={selectedAssets.map((asset) => asset.id)}
              compact
            />
          )}
        </div>

        <div className="overflow-x-auto rounded-xl border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <Checkbox
                    checked={allPageSelected}
                    onCheckedChange={(checked) =>
                      setSelected((current) =>
                        checked
                          ? Array.from(new Set([...current, ...pageIds]))
                          : current.filter((id) => !pageIds.includes(id)),
                      )
                    }
                  />
                </TableHead>
                <TableHead>作品</TableHead>
                <TableHead>发布时间</TableHead>
                <TableHead>互动数据</TableHead>
                <TableHead>已保存评论</TableHead>
                <TableHead>视频 / 存储</TableHead>
                <TableHead>字幕</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length ? (
                rows.map((row) => {
                  const aweme = row.aweme
                  const asset = row.media
                  return (
                    <TableRow key={aweme.id} className="align-top">
                      <TableCell>
                        <Checkbox
                          checked={selected.includes(aweme.aweme_id)}
                          onCheckedChange={(checked) =>
                            setSelected((current) =>
                              checked
                                ? [...current, aweme.aweme_id]
                                : current.filter((id) => id !== aweme.aweme_id),
                            )
                          }
                        />
                      </TableCell>
                      <TableCell className="min-w-72 max-w-md">
                        <div className="flex gap-3">
                          {aweme.cover_url ? (
                            <img
                              src={aweme.cover_url}
                              alt=""
                              loading="lazy"
                              className="h-20 w-14 shrink-0 rounded-lg object-cover"
                            />
                          ) : (
                            <div className="h-20 w-14 shrink-0 rounded-lg bg-muted" />
                          )}
                          <div className="min-w-0">
                            <p className="line-clamp-2 font-medium">
                              {aweme.title || aweme.aweme_id}
                            </p>
                            <p className="mt-1 text-sm text-muted-foreground">
                              {aweme.nickname || "匿名作者"}
                            </p>
                            <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                              {aweme.aweme_id}
                            </p>
                            {(row.tags?.length ?? 0) > 0 && (
                              <div className="mt-2 flex flex-wrap gap-1">
                                {(row.tags ?? []).slice(0, 4).map((tag) => (
                                  <Badge key={tag.id} variant="outline">
                                    #{tag.name}
                                  </Badge>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="min-w-36 whitespace-nowrap">
                        <p>{formatUnix(aweme.create_time)}</p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          抓取 {formatDate(aweme.fetched_at)}
                        </p>
                      </TableCell>
                      <TableCell className="min-w-40 text-sm">
                        <div className="grid grid-cols-2 gap-x-3 gap-y-1">
                          <span>赞 {compact(aweme.liked_count)}</span>
                          <span>评 {compact(aweme.comment_count)}</span>
                          <span>藏 {compact(aweme.collected_count)}</span>
                          <span>转 {compact(aweme.share_count)}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <CommentsDialog
                          taskId={taskId}
                          aweme={aweme}
                          count={row.persisted_comment_count}
                          active={active}
                        />
                      </TableCell>
                      <TableCell className="min-w-48">
                        {asset ? (
                          <PipelineView
                            label={
                              asset.storage_backend === "minio"
                                ? "MinIO"
                                : "本地"
                            }
                            status={asset.status}
                            progress={asset.progress}
                            error={asset.error}
                            detail={`已尝试 ${asset.attempt_count} 次 · 更新于 ${formatDate(asset.updated_at)}`}
                          />
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            未创建下载任务
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="min-w-48">
                        {asset?.subtitle ? (
                          <PipelineView
                            label={asset.subtitle.language || "远程字幕"}
                            status={asset.subtitle.status}
                            progress={asset.subtitle.progress}
                            error={asset.subtitle.error}
                          />
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            未生成字幕
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex min-w-max justify-end gap-1">
                          <AwemeActions
                            taskId={taskId}
                            aweme={aweme}
                            active={active}
                          />
                          {asset?.download_available && (
                            <VideoPreviewDialog taskId={taskId} asset={asset} />
                          )}
                          {asset?.download_available && (
                            <Button size="icon-sm" variant="ghost" asChild>
                              <Link
                                to="/douyin/$taskId/feed"
                                params={{ taskId }}
                                search={{ start: `video-${aweme.aweme_id}` }}
                                aria-label="从此视频开始沉浸播放"
                              >
                                <PlaySquare />
                              </Link>
                            </Button>
                          )}
                          {asset?.download_available && (
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              aria-label="下载视频"
                              onClick={() =>
                                downloadMedia(taskId, asset, showErrorToast)
                              }
                            >
                              <Download />
                            </Button>
                          )}
                          {asset &&
                            (asset.status === "failed" ||
                              asset.subtitle?.status === "failed") && (
                              <Button
                                size="icon-sm"
                                variant="ghost"
                                aria-label="重试"
                                onClick={() => retry.mutate([asset.id])}
                              >
                                <RotateCcw />
                              </Button>
                            )}
                          {asset?.download_available && (
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              aria-label="重新翻译"
                              onClick={() => retranslate.mutate(asset.id)}
                            >
                              <Languages />
                            </Button>
                          )}
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
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })
              ) : (
                <TableRow>
                  <TableCell
                    colSpan={8}
                    className="h-36 text-center text-muted-foreground"
                  >
                    {worksQuery.isLoading
                      ? "加载作品…"
                      : "没有符合筛选条件的作品"}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
        <Pager
          page={page}
          count={worksQuery.data?.count ?? 0}
          onChange={setPage}
        />
      </CardContent>
    </Card>
  )
}

function CommentsDialog({
  taskId,
  aweme,
  count,
  active,
}: {
  taskId: string
  aweme: DouyinAwemePublic
  count: number
  active: boolean
}) {
  const [open, setOpen] = useState(false)
  const [commentPage, setCommentPage] = useState(0)
  const [sort, setSort] = useState<"published_at" | "like_count">(
    "published_at",
  )
  const query = useQuery({
    queryKey: ["douyin-comments", taskId, aweme.aweme_id, sort, commentPage],
    queryFn: () =>
      DouyinService.listComments({
        taskId,
        awemeId: aweme.aweme_id,
        sortBy: sort,
        sortOrder: "desc",
        skip: commentPage * 100,
        limit: 100,
      }),
    enabled: open,
    refetchInterval: open && active ? 3_000 : false,
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <MessageCircle />
          {count} 条
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-hidden sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{aweme.title || aweme.aweme_id}</DialogTitle>
          <DialogDescription>已保存评论及评论发布时间</DialogDescription>
        </DialogHeader>
        <div className="flex justify-end">
          <Select
            value={sort}
            onValueChange={(value) => {
              setSort(value as "published_at" | "like_count")
              setCommentPage(0)
            }}
          >
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="published_at">按时间</SelectItem>
              <SelectItem value="like_count">按点赞</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="max-h-[60vh] space-y-3 overflow-y-auto pr-2">
          {query.data?.data.length ? (
            query.data.data.map((comment) => (
              <div
                key={comment.id}
                className="rounded-xl border bg-muted/20 p-4"
              >
                <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
                  <span>{comment.nickname || "匿名"}</span>
                  <div className="flex items-center gap-2">
                    <span>
                      {formatUnix(comment.create_time)} · 赞{" "}
                      {comment.like_count}
                    </span>
                    <InteractionComposerDialog
                      taskId={taskId}
                      aweme={aweme}
                      interactionType="comment_reply"
                      targetComment={comment}
                      compact
                    />
                  </div>
                </div>
                <p className="mt-2 whitespace-pre-wrap text-sm leading-6">
                  {comment.content || "-"}
                </p>
              </div>
            ))
          ) : (
            <p className="py-12 text-center text-sm text-muted-foreground">
              {query.isLoading ? "加载评论…" : "暂无已保存评论"}
            </p>
          )}
        </div>
        {(query.data?.count ?? 0) > 100 && (
          <div className="flex items-center justify-end gap-2 border-t pt-3">
            <span className="mr-auto text-xs text-muted-foreground">
              第 {commentPage + 1} 页 · 共 {query.data?.count ?? 0} 条
            </span>
            <Button
              size="sm"
              variant="outline"
              disabled={commentPage === 0}
              onClick={() => setCommentPage((value) => value - 1)}
            >
              上一页
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={(commentPage + 1) * 100 >= (query.data?.count ?? 0)}
              onClick={() => setCommentPage((value) => value + 1)}
            >
              下一页
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function PipelineView({
  label,
  status,
  progress,
  error,
  detail,
}: {
  label: string
  status: string
  progress: number
  error: string | null
  detail?: string
}) {
  const labels: Record<string, string> = {
    queued: "等待",
    downloading: "下载中",
    downloaded: "已完成",
    pending: "等待",
    running: "处理中",
    completed: "已完成",
    failed: "失败",
  }
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <Badge variant={status === "failed" ? "destructive" : "outline"}>
          {label} · {labels[status] ?? status}
        </Badge>
        <span className="text-xs text-muted-foreground">{progress}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className={
            status === "failed" ? "h-full bg-destructive" : "h-full bg-primary"
          }
          style={{ width: `${Math.max(0, Math.min(progress, 100))}%` }}
        />
      </div>
      {detail && <p className="text-xs text-muted-foreground">{detail}</p>}
      {error && (
        <p className="line-clamp-2 text-xs text-destructive">{error}</p>
      )}
    </div>
  )
}

function Summary({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-xl border bg-card p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
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
  if (count <= pageSize) return null
  return (
    <div className="flex items-center justify-end gap-3">
      <span className="text-sm text-muted-foreground">
        第 {page + 1}/{pages} 页 · 共 {count} 项
      </span>
      <Button
        size="sm"
        variant="outline"
        disabled={page === 0}
        onClick={() => onChange(page - 1)}
      >
        上一页
      </Button>
      <Button
        size="sm"
        variant="outline"
        disabled={page + 1 >= pages}
        onClick={() => onChange(page + 1)}
      >
        下一页
      </Button>
    </div>
  )
}

export async function downloadExport(
  taskId: string,
  kind: "comments" | "subtitles",
  body: object,
) {
  const token = localStorage.getItem("access_token")
  const response = await fetch(
    `${browserApiBase()}/api/v1/douyin/tasks/${taskId}/exports/${kind}`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    },
  )
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string
    } | null
    throw new Error(payload?.detail || `导出失败 (${response.status})`)
  }
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement("a")
  anchor.href = url
  const disposition = response.headers.get("Content-Disposition") || ""
  const match =
    disposition.match(/filename\*=UTF-8''([^;]+)/i) ||
    disposition.match(/filename="?([^";]+)"?/i)
  anchor.download = match ? decodeURIComponent(match[1]) : `douyin-${kind}`
  anchor.click()
  URL.revokeObjectURL(url)
}

export async function downloadMedia(
  taskId: string,
  asset: DouyinMediaAssetPublic,
  onError: (message: string) => void,
) {
  try {
    const token = localStorage.getItem("access_token")
    const response = await fetch(
      `${browserApiBase()}/api/v1/douyin/tasks/${taskId}/media/${asset.id}/file`,
      { headers: token ? { Authorization: `Bearer ${token}` } : undefined },
    )
    if (!response.ok) throw new Error(`视频下载失败 (${response.status})`)
    const url = URL.createObjectURL(await response.blob())
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = `douyin-${asset.aweme_id}.mp4`
    anchor.click()
    URL.revokeObjectURL(url)
  } catch (reason) {
    onError(reason instanceof Error ? reason.message : "视频下载失败")
  }
}

function browserApiBase() {
  if (import.meta.env.DEV) return window.location.origin
  return new URL(OpenAPI.BASE || window.location.origin, window.location.origin)
    .toString()
    .replace(/\/$/, "")
}
function formatDate(value: string | null) {
  return value
    ? new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "short",
        timeStyle: "short",
      }).format(new Date(value))
    : "-"
}
function formatUnix(value: number | null) {
  return value ? formatDate(new Date(value * 1_000).toISOString()) : "未知"
}
function compact(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value)
}
