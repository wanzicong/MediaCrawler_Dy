import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  Captions,
  ChevronDown,
  Download,
  ExternalLink,
  FileDown,
  Languages,
  LayoutGrid,
  List,
  ListFilter,
  LoaderCircle,
  MessageCircle,
  PlaySquare,
  RefreshCw,
  RotateCcw,
  Search,
  Table2,
} from "lucide-react"
import { useMemo, useState } from "react"

import {
  type CrawlTaskPublic,
  type DouyinAwemePublic,
  type DouyinMediaAssetPublic,
  DouyinService,
  type DouyinTagRefPublic,
  DouyinTagsService,
  type DouyinWorkPublic,
  OpenAPI,
} from "@/client"
import { AwemeActions } from "@/components/Douyin/AwemeActions"
import { BatchCommentDialog } from "@/components/Douyin/BatchCommentDialog"
import { InteractionComposerDialog } from "@/components/Douyin/InteractionComposerDialog"
import { MediaMigrationDialog } from "@/components/Douyin/MediaMigrationDialog"
import { ProcessMediaDialog } from "@/components/Douyin/ProcessMediaDialog"
import { SourceBadge } from "@/components/Douyin/SourceSelect"
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
import {
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu"
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
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
type WorkView = "table" | "rows" | "cards"

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
  const [view, setView] = useState<WorkView>("table")
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
  const recrawlComments = useMutation({
    mutationFn: async (awemeIds: string[]) => {
      let created = 0
      for (const awemeId of awemeIds) {
        await DouyinService.recrawlAwemeComments({
          taskId,
          awemeId,
          requestBody: {
            fetch_sub_comments: Boolean(task.request.fetch_sub_comments),
            max_comments_per_aweme: Number(
              task.request.max_comments_per_aweme ?? 10,
            ),
            request_delay_level:
              task.request.request_delay_level === "ultra_steady"
                ? "ultra_steady"
                : "steady",
            account_id: task.account_id ?? undefined,
          },
        })
        created += 1
      }
      return created
    },
    onSuccess: async (created) => {
      showSuccessToast(`已为 ${created} 个视频创建评论补采任务`)
      setSelected([])
      await queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] })
    },
    onError: handleError.bind(showErrorToast),
  })
  const rows = worksQuery.data?.data ?? []
  const pageIds = rows.map((row) => row.aweme.aweme_id)
  const allPageSelected =
    pageIds.length > 0 && pageIds.every((id) => selected.includes(id))
  const selectedWorks = rows.filter((row) =>
    selected.includes(row.aweme.aweme_id),
  )
  const somePageSelected = selectedWorks.length > 0 && !allPageSelected
  const togglePageSelection = (checked: boolean) => {
    setSelected((current) =>
      checked
        ? Array.from(new Set([...current, ...pageIds]))
        : current.filter((id) => !pageIds.includes(id)),
    )
  }
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
            {rows.some(
              (row) =>
                row.media?.download_available ||
                Boolean(row.aweme.video_download_url),
            ) && (
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
                条，临时字幕 {summary.temporary} 条，下载失败{" "}
                {summary.download_failed} 条
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
              label="下载完成 / 仅字幕"
              value={`${summary.downloaded} / ${summary.temporary}`}
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
              label="本地 / 云端"
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
                setSelected([])
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
              setSelected([])
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
              setSelected([])
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
              setSelected([])
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
              setSelected([])
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
          <div className="mr-1 flex items-center gap-2">
            <Checkbox
              id={`select-task-page-${taskId}`}
              aria-label="选择本页作品"
              checked={
                allPageSelected
                  ? true
                  : somePageSelected
                    ? "indeterminate"
                    : false
              }
              disabled={!rows.length}
              onCheckedChange={(checked) =>
                togglePageSelection(checked === true)
              }
            />
            <label
              htmlFor={`select-task-page-${taskId}`}
              className="cursor-pointer whitespace-nowrap text-sm text-muted-foreground"
            >
              {selectedWorks.length
                ? `已选 ${selectedWorks.length}`
                : "全选本页"}
            </label>
          </div>
          <BatchCommentDialog
            selectedWorks={selectedWorks}
            onCreated={() => setSelected([])}
          >
            <Button size="sm" disabled={!selectedWorks.length}>
              <MessageCircle />
              批量发送评论
            </Button>
          </BatchCommentDialog>
          <Button
            size="sm"
            variant="outline"
            onClick={() => exportSelection("comments")}
            disabled={!selected.length}
          >
            <FileDown />
            导出评论 TXT
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              if (
                selected.length <= 20 ||
                window.confirm(
                  `将为 ${selected.length} 个视频分别创建评论补采任务，确认继续？`,
                )
              )
                recrawlComments.mutate(selected)
            }}
            disabled={!selected.length || recrawlComments.isPending}
          >
            <MessageCircle />
            {recrawlComments.isPending ? "正在创建…" : "批量补采评论"}
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

        <Tabs
          value={view}
          onValueChange={(value) => setView(value as WorkView)}
          className="gap-4"
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted-foreground">
              当前结果 {worksQuery.data?.count ?? 0} 条
            </p>
            <TabsList
              aria-label="选择作品展示方式"
              className="h-10 w-full p-1 sm:w-auto"
            >
              <TabsTrigger value="table" className="px-3 sm:px-4">
                <Table2 aria-hidden="true" />
                表格
              </TabsTrigger>
              <TabsTrigger value="rows" className="px-3 sm:px-4">
                <List aria-hidden="true" />
                横条
              </TabsTrigger>
              <TabsTrigger value="cards" className="px-3 sm:px-4">
                <LayoutGrid aria-hidden="true" />
                卡片
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="table" className="mt-0">
            <div className="overflow-x-auto rounded-xl border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10">
                      <Checkbox
                        aria-label="选择本页作品"
                        checked={
                          allPageSelected
                            ? true
                            : somePageSelected
                              ? "indeterminate"
                              : false
                        }
                        onCheckedChange={(checked) =>
                          togglePageSelection(checked === true)
                        }
                      />
                    </TableHead>
                    <TableHead>作品</TableHead>
                    <TableHead className="hidden lg:table-cell">
                      发布时间
                    </TableHead>
                    <TableHead className="hidden xl:table-cell">
                      互动数据
                    </TableHead>
                    <TableHead>已保存评论</TableHead>
                    <TableHead>视频 / 存储</TableHead>
                    <TableHead>字幕</TableHead>
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
                                    : current.filter(
                                        (id) => id !== aweme.aweme_id,
                                      ),
                                )
                              }
                            />
                          </TableCell>
                          <TableCell className="min-w-80 max-w-lg">
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
                                <SourceBadge
                                  sourceType={aweme.source_type}
                                  sourceLabel={aweme.source_label}
                                  className="mt-2"
                                />
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
                                <WorkQuickActions
                                  taskId={taskId}
                                  aweme={aweme}
                                  asset={asset}
                                  active={active}
                                  onDownload={(media) =>
                                    downloadMedia(taskId, media, showErrorToast)
                                  }
                                  onRetry={(assetId) => retry.mutate([assetId])}
                                  onRetranslate={(assetId) =>
                                    retranslate.mutate(assetId)
                                  }
                                />
                              </div>
                            </div>
                          </TableCell>
                          <TableCell className="hidden min-w-36 whitespace-nowrap lg:table-cell">
                            <p>{formatUnix(aweme.create_time)}</p>
                            <p className="mt-1 text-xs text-muted-foreground">
                              抓取 {formatDate(aweme.fetched_at)}
                            </p>
                          </TableCell>
                          <TableCell className="hidden min-w-40 text-sm xl:table-cell">
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
                                    ? "云端"
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
                        </TableRow>
                      )
                    })
                  ) : (
                    <TableRow>
                      <TableCell
                        colSpan={7}
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
          </TabsContent>

          <TabsContent value="rows" className="mt-0">
            <ul aria-label="作品横条列表" className="space-y-3">
              {rows.length ? (
                rows.map((row) => (
                  <WorkRowItem
                    key={row.aweme.id}
                    taskId={taskId}
                    row={row}
                    active={active}
                    checked={selected.includes(row.aweme.aweme_id)}
                    onCheckedChange={(checked) =>
                      setSelected((current) =>
                        checked
                          ? Array.from(
                              new Set([...current, row.aweme.aweme_id]),
                            )
                          : current.filter((id) => id !== row.aweme.aweme_id),
                      )
                    }
                    onDownload={(asset) =>
                      downloadMedia(taskId, asset, showErrorToast)
                    }
                    onRetry={(assetId) => retry.mutate([assetId])}
                    onRetranslate={(assetId) => retranslate.mutate(assetId)}
                  />
                ))
              ) : (
                <EmptyWorksState loading={worksQuery.isLoading} />
              )}
            </ul>
          </TabsContent>

          <TabsContent value="cards" className="mt-0">
            <ul
              aria-label="作品卡片列表"
              className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"
            >
              {rows.length ? (
                rows.map((row) => (
                  <WorkCardItem
                    key={row.aweme.id}
                    taskId={taskId}
                    row={row}
                    active={active}
                    checked={selected.includes(row.aweme.aweme_id)}
                    onCheckedChange={(checked) =>
                      setSelected((current) =>
                        checked
                          ? Array.from(
                              new Set([...current, row.aweme.aweme_id]),
                            )
                          : current.filter((id) => id !== row.aweme.aweme_id),
                      )
                    }
                    onDownload={(asset) =>
                      downloadMedia(taskId, asset, showErrorToast)
                    }
                    onRetry={(assetId) => retry.mutate([assetId])}
                    onRetranslate={(assetId) => retranslate.mutate(assetId)}
                  />
                ))
              ) : (
                <EmptyWorksState loading={worksQuery.isLoading} />
              )}
            </ul>
          </TabsContent>
        </Tabs>
        <Pager
          page={page}
          count={worksQuery.data?.count ?? 0}
          onChange={(nextPage) => {
            setPage(nextPage)
            setSelected([])
          }}
        />
      </CardContent>
    </Card>
  )
}

type WorkItemProps = {
  taskId: string
  row: DouyinWorkPublic
  active: boolean
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  onDownload: (asset: DouyinMediaAssetPublic) => void
  onRetry: (assetId: string) => void
  onRetranslate: (assetId: string) => void
}

function WorkRowItem({
  taskId,
  row,
  active,
  checked,
  onCheckedChange,
  onDownload,
  onRetry,
  onRetranslate,
}: WorkItemProps) {
  const { aweme, media: asset } = row
  const title = aweme.title || aweme.aweme_id

  return (
    <li className="grid gap-5 rounded-2xl border bg-card p-4 shadow-xs transition-colors hover:border-primary/30 lg:grid-cols-[minmax(0,1.35fr)_minmax(26rem,1fr)]">
      <div className="flex min-w-0 gap-3">
        <Checkbox
          checked={checked}
          aria-label={`选择作品：${title}`}
          onCheckedChange={(value) => onCheckedChange(value === true)}
        />
        <WorkCover aweme={aweme} className="h-28 w-20" />
        <div className="min-w-0 flex-1">
          <h3 className="line-clamp-2 font-semibold leading-6">{title}</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {aweme.nickname || "匿名作者"}
          </p>
          <SourceBadge
            sourceType={aweme.source_type}
            sourceLabel={aweme.source_label}
            className="mt-2"
          />
          <p className="mt-1 font-mono text-[11px] text-muted-foreground">
            {aweme.aweme_id}
          </p>
          <WorkTags tags={row.tags} />
          <WorkQuickActions
            taskId={taskId}
            aweme={aweme}
            asset={asset}
            active={active}
            onDownload={onDownload}
            onRetry={onRetry}
            onRetranslate={onRetranslate}
          />
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl bg-muted/25 p-3 text-sm">
          <p className="font-medium">互动与评论</p>
          <div className="mt-2 grid grid-cols-4 gap-2 text-xs text-muted-foreground">
            <span>赞 {compact(aweme.liked_count)}</span>
            <span>评 {compact(aweme.comment_count)}</span>
            <span>藏 {compact(aweme.collected_count)}</span>
            <span>转 {compact(aweme.share_count)}</span>
          </div>
          <div className="mt-3 flex items-center justify-between gap-3">
            <span className="text-xs text-muted-foreground">
              发布 {formatUnix(aweme.create_time)}
            </span>
            <CommentsDialog
              taskId={taskId}
              aweme={aweme}
              count={row.persisted_comment_count}
              active={active}
            />
          </div>
        </div>
        <WorkPipelineStatus asset={asset} />
      </div>
    </li>
  )
}

function WorkCardItem({
  taskId,
  row,
  active,
  checked,
  onCheckedChange,
  onDownload,
  onRetry,
  onRetranslate,
}: WorkItemProps) {
  const { aweme, media: asset } = row
  const title = aweme.title || aweme.aweme_id

  return (
    <li className="flex min-w-0 flex-col overflow-hidden rounded-xl border bg-card shadow-xs transition hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md">
      <div className="relative aspect-video overflow-hidden bg-muted">
        {aweme.cover_url ? (
          <img
            src={aweme.cover_url}
            alt=""
            loading="lazy"
            className="size-full object-cover"
          />
        ) : (
          <div className="size-full bg-muted" />
        )}
        <div className="absolute left-2 top-2 rounded-lg bg-background/90 p-1.5 shadow-sm backdrop-blur">
          <Checkbox
            checked={checked}
            aria-label={`选择作品：${title}`}
            onCheckedChange={(value) => onCheckedChange(value === true)}
          />
        </div>
        <div className="absolute bottom-2 right-2 rounded-full bg-background/90 px-2 py-0.5 text-[11px] font-medium shadow-sm backdrop-blur">
          {formatUnix(aweme.create_time)}
        </div>
      </div>

      <div className="flex flex-1 flex-col p-3">
        <h3 className="line-clamp-2 min-h-10 text-sm font-semibold leading-5">
          {title}
        </h3>
        <p className="mt-0.5 truncate text-xs text-muted-foreground">
          {aweme.nickname || "匿名作者"}
        </p>
        <SourceBadge
          sourceType={aweme.source_type}
          sourceLabel={aweme.source_label}
          className="mt-2"
        />
        <WorkTags tags={row.tags} />
        <div className="mt-3 grid grid-cols-4 gap-1 rounded-lg bg-muted/25 p-2 text-center text-[11px]">
          <span>赞 {compact(aweme.liked_count)}</span>
          <span>评 {compact(aweme.comment_count)}</span>
          <span>藏 {compact(aweme.collected_count)}</span>
          <span>转 {compact(aweme.share_count)}</span>
        </div>
        <details className="group mt-2">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-md border-t pt-2 text-[11px] font-medium text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none [&::-webkit-details-marker]:hidden">
            <span>视频与字幕状态</span>
            <ChevronDown className="size-3.5 transition group-open:rotate-180" />
          </summary>
          <div className="pt-2">
            <WorkPipelineStatus asset={asset} />
          </div>
        </details>
        <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t pt-3">
          <CommentsDialog
            taskId={taskId}
            aweme={aweme}
            count={row.persisted_comment_count}
            active={active}
          />
          <WorkQuickActions
            taskId={taskId}
            aweme={aweme}
            asset={asset}
            active={active}
            onDownload={onDownload}
            onRetry={onRetry}
            onRetranslate={onRetranslate}
          />
        </div>
      </div>
    </li>
  )
}

function WorkCover({
  aweme,
  className,
}: {
  aweme: DouyinAwemePublic
  className: string
}) {
  return aweme.cover_url ? (
    <img
      src={aweme.cover_url}
      alt=""
      loading="lazy"
      className={`${className} shrink-0 rounded-xl object-cover`}
    />
  ) : (
    <div className={`${className} shrink-0 rounded-xl bg-muted`} />
  )
}

function WorkTags({ tags }: { tags?: DouyinTagRefPublic[] }) {
  if (!tags?.length) return null
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {tags.slice(0, 4).map((tag) => (
        <Badge key={tag.id} variant="outline">
          #{tag.name}
        </Badge>
      ))}
    </div>
  )
}

function WorkQuickActions({
  taskId,
  aweme,
  asset,
  active,
  onDownload,
  onRetry,
  onRetranslate,
}: {
  taskId: string
  aweme: DouyinAwemePublic
  asset: DouyinMediaAssetPublic | null
  active: boolean
  onDownload: (asset: DouyinMediaAssetPublic) => void
  onRetry: (assetId: string) => void
  onRetranslate: (assetId: string) => void
}) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1">
      {(asset?.download_available || aweme.video_download_url) && (
        <VideoPreviewDialog
          taskId={taskId}
          asset={asset}
          aweme={aweme}
          sourceUrl={aweme.video_download_url}
        />
      )}
      <AwemeActions taskId={taskId} aweme={aweme} active={active}>
        {(asset?.download_available || aweme.video_download_url) && (
          <DropdownMenuItem asChild>
            <Link
              to="/douyin/$taskId/feed"
              params={{ taskId }}
              search={{ start: `video-${aweme.aweme_id}` }}
            >
              <PlaySquare />
              沉浸播放
            </Link>
          </DropdownMenuItem>
        )}
        {asset?.download_available && (
          <DropdownMenuItem onSelect={() => onDownload(asset)}>
            <Download />
            下载视频
          </DropdownMenuItem>
        )}
        {asset &&
          (asset.status === "failed" ||
            asset.subtitle?.status === "failed") && (
            <DropdownMenuItem onSelect={() => onRetry(asset.id)}>
              <RotateCcw />
              重试失败处理
            </DropdownMenuItem>
          )}
        {asset?.download_available && (
          <DropdownMenuItem onSelect={() => onRetranslate(asset.id)}>
            <Languages />
            重新翻译
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <a
            href={getDouyinVideoUrl(aweme.aweme_id)}
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLink />
            在抖音中打开视频
          </a>
        </DropdownMenuItem>
      </AwemeActions>
    </div>
  )
}

function WorkPipelineStatus({
  asset,
}: {
  asset: DouyinMediaAssetPublic | null
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div>
        {asset ? (
          <PipelineView
            label={asset.storage_backend === "minio" ? "云端" : "本地"}
            status={asset.status}
            progress={asset.progress}
            error={asset.error}
            detail={`已尝试 ${asset.attempt_count} 次 · 更新于 ${formatDate(asset.updated_at)}`}
          />
        ) : (
          <span className="text-xs text-muted-foreground">未创建下载任务</span>
        )}
      </div>
      <div>
        {asset?.subtitle ? (
          <PipelineView
            label={asset.subtitle.language || "远程字幕"}
            status={asset.subtitle.status}
            progress={asset.subtitle.progress}
            error={asset.subtitle.error}
          />
        ) : (
          <span className="text-xs text-muted-foreground">未生成字幕</span>
        )}
      </div>
    </div>
  )
}

function EmptyWorksState({ loading }: { loading: boolean }) {
  return (
    <div className="col-span-full rounded-xl border border-dashed py-16 text-center text-sm text-muted-foreground">
      {loading ? "加载作品…" : "没有符合筛选条件的作品"}
    </div>
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
