import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Download, Languages, RefreshCw, RotateCcw } from "lucide-react"

import {
  type CrawlTaskPublic,
  type DouyinMediaAssetPublic,
  DouyinService,
  OpenAPI,
} from "@/client"
import { MediaMigrationDialog } from "@/components/Douyin/MediaMigrationDialog"
import { ProcessMediaDialog } from "@/components/Douyin/ProcessMediaDialog"
import { VideoPreviewDialog } from "@/components/Douyin/VideoPreviewDialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

export function MediaPipelinePanel({
  task,
  active,
}: {
  task: CrawlTaskPublic
  active: boolean
}) {
  const taskId = task.id
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const mediaQuery = useQuery({
    queryKey: ["douyin-media", taskId],
    queryFn: () => DouyinService.listMedia({ taskId, limit: 100 }),
    refetchInterval: (query) => {
      const processing = query.state.data?.data.some(
        (asset) =>
          asset.status === "queued" ||
          asset.status === "downloading" ||
          asset.subtitle?.status === "pending" ||
          asset.subtitle?.status === "running" ||
          [
            "queued",
            "uploading",
            "verifying",
            "switching",
            "cleanup_pending",
          ].includes(asset.migration_status),
      )
      return active || processing ? 2_000 : false
    },
  })
  const summaryQuery = useQuery({
    queryKey: ["douyin-media-summary", taskId],
    queryFn: () => DouyinService.getMediaSummary({ taskId }),
    refetchInterval: active ? 2_000 : 5_000,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["douyin-media", taskId] }),
      queryClient.invalidateQueries({
        queryKey: ["douyin-media-summary", taskId],
      }),
    ])
  }
  const retryMutation = useMutation({
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
      showSuccessToast("失败任务已重新排队")
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const retranslateMutation = useMutation({
    mutationFn: (assetId: string) =>
      DouyinService.retranslateMedia({ taskId, assetId }),
    onSuccess: async () => {
      showSuccessToast("字幕已重新提交")
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const assets = mediaQuery.data?.data ?? []
  const failedAssets = assets
    .filter(
      (asset) =>
        asset.status === "failed" || asset.subtitle?.status === "failed",
    )
    .map((asset) => asset.id)
  const summary = summaryQuery.data

  return (
    <Card>
      <CardHeader className="gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <CardTitle>视频下载与字幕</CardTitle>
          <CardDescription className="mt-1">
            视频按任务保存到本地服务器或 MinIO，字幕正文和进度持久化到
            PostgreSQL。
          </CardDescription>
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
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              mediaQuery.refetch()
              summaryQuery.refetch()
            }}
            disabled={mediaQuery.isFetching}
          >
            <RefreshCw
              className={mediaQuery.isFetching ? "animate-spin" : ""}
            />
            刷新
          </Button>
          {failedAssets.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => retryMutation.mutate(failedAssets)}
              disabled={retryMutation.isPending}
            >
              <RotateCcw />
              重试失败项
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {summary && (
          <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-6">
            <SummaryItem label="媒体总数" value={summary.total} />
            <SummaryItem
              label="下载完成 / 失败"
              value={`${summary.downloaded} / ${summary.download_failed}`}
            />
            <SummaryItem
              label="字幕完成 / 失败"
              value={`${summary.subtitle_completed} / ${summary.subtitle_failed}`}
            />
            <SummaryItem
              label="处理中"
              value={
                summary.queued +
                summary.downloading +
                summary.subtitle_pending +
                summary.subtitle_running
              }
            />
            <SummaryItem
              label="本地 / MinIO"
              value={`${summary.local_downloaded} / ${summary.minio_downloaded}`}
            />
            <SummaryItem
              label="迁移中 / 失败"
              value={`${summary.migration_queued + summary.migration_running + summary.migration_cleanup_pending} / ${summary.migration_failed}`}
            />
          </div>
        )}

        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>作品 ID</TableHead>
                <TableHead>存储</TableHead>
                <TableHead>下载进度</TableHead>
                <TableHead>存储迁移</TableHead>
                <TableHead>字幕进度</TableHead>
                <TableHead>字幕内容</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {assets.length ? (
                assets.map((asset) => (
                  <MediaRow
                    key={asset.id}
                    asset={asset}
                    taskId={taskId}
                    retrying={retryMutation.isPending}
                    retranslating={retranslateMutation.isPending}
                    onRetry={() => retryMutation.mutate([asset.id])}
                    onRetranslate={() => retranslateMutation.mutate(asset.id)}
                    onError={showErrorToast}
                  />
                ))
              ) : (
                <TableRow>
                  <TableCell
                    colSpan={7}
                    className="h-28 text-center text-muted-foreground"
                  >
                    {mediaQuery.isLoading
                      ? "加载媒体任务…"
                      : "当前任务未启用视频处理，或尚未抓到可下载作品。"}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

function MediaRow({
  asset,
  taskId,
  retrying,
  retranslating,
  onRetry,
  onRetranslate,
  onError,
}: {
  asset: DouyinMediaAssetPublic
  taskId: string
  retrying: boolean
  retranslating: boolean
  onRetry: () => void
  onRetranslate: () => void
  onError: (message: string) => void
}) {
  const failed =
    asset.status === "failed" || asset.subtitle?.status === "failed"

  return (
    <TableRow>
      <TableCell className="font-mono text-xs">{asset.aweme_id}</TableCell>
      <TableCell>
        <Badge variant="secondary">
          {asset.storage_backend === "minio" ? "MinIO" : "本地"}
        </Badge>
      </TableCell>
      <TableCell className="min-w-44">
        <PipelineStatus
          status={asset.status}
          progress={asset.progress}
          error={asset.error}
        />
      </TableCell>
      <TableCell className="min-w-48">
        <MigrationStatusView asset={asset} />
      </TableCell>
      <TableCell className="min-w-44">
        {asset.subtitle ? (
          <PipelineStatus
            status={asset.subtitle.status}
            progress={asset.subtitle.progress}
            error={asset.subtitle.error}
          />
        ) : (
          <span className="text-xs text-muted-foreground">未启用</span>
        )}
      </TableCell>
      <TableCell className="max-w-md">
        {asset.subtitle?.full_text ? (
          <details>
            <summary className="cursor-pointer line-clamp-2 text-sm">
              {asset.subtitle.full_text}
            </summary>
            <p className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap rounded bg-muted/50 p-3 text-sm">
              {asset.subtitle.full_text}
            </p>
          </details>
        ) : (
          <span className="text-xs text-muted-foreground">-</span>
        )}
      </TableCell>
      <TableCell>
        <div className="flex justify-end gap-1">
          {asset.download_available && (
            <VideoPreviewDialog taskId={taskId} asset={asset} />
          )}
          {((asset.storage_backend === "local" &&
            asset.migration_status === "failed") ||
            asset.migration_status === "cleanup_pending") && (
            <MediaMigrationDialog
              taskId={taskId}
              eligibleCount={1}
              assetIds={[asset.id]}
              compact
            />
          )}
          {asset.download_available && (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="下载视频"
              onClick={() => downloadMedia(taskId, asset, onError)}
            >
              <Download />
            </Button>
          )}
          {failed && (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="重试媒体任务"
              onClick={onRetry}
              disabled={retrying}
            >
              <RotateCcw />
            </Button>
          )}
          {asset.download_available && (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="重新翻译字幕"
              onClick={onRetranslate}
              disabled={retranslating}
            >
              <Languages />
            </Button>
          )}
        </div>
      </TableCell>
    </TableRow>
  )
}

function MigrationStatusView({ asset }: { asset: DouyinMediaAssetPublic }) {
  const labels: Record<string, string> = {
    idle: asset.storage_backend === "minio" ? "无需迁移" : "未迁移",
    queued: "等待上传",
    uploading: "上传中",
    verifying: "完整性校验中",
    switching: "切换存储中",
    cleanup_pending: "MinIO 已生效，等待清理本地文件",
    completed: "迁移完成",
    failed: "迁移失败",
  }
  const active = [
    "queued",
    "uploading",
    "verifying",
    "switching",
    "cleanup_pending",
  ].includes(asset.migration_status)
  return (
    <div className="space-y-1.5">
      <Badge
        variant={
          asset.migration_status === "failed" ? "destructive" : "outline"
        }
      >
        {labels[asset.migration_status] ?? asset.migration_status}
      </Badge>
      {(active || asset.migration_status === "failed") && (
        <>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className={
                asset.migration_status === "failed"
                  ? "h-full bg-destructive"
                  : "h-full bg-primary"
              }
              style={{
                width: `${Math.max(0, Math.min(asset.migration_progress, 100))}%`,
              }}
            />
          </div>
          {asset.migration_error && (
            <p className="line-clamp-2 text-xs text-destructive">
              {asset.migration_error}
            </p>
          )}
        </>
      )}
    </div>
  )
}

function PipelineStatus({
  status,
  progress,
  error,
}: {
  status: string
  progress: number
  error: string | null
}) {
  const labels: Record<string, string> = {
    queued: "等待中",
    downloading: "下载中",
    downloaded: "已下载",
    pending: "等待字幕",
    running: "字幕处理中",
    completed: "字幕完成",
    failed: "失败",
  }
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <Badge variant={status === "failed" ? "destructive" : "outline"}>
          {labels[status] ?? status}
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
      {error && (
        <p className="line-clamp-2 text-xs text-destructive">{error}</p>
      )}
    </div>
  )
}

function SummaryItem({
  label,
  value,
}: {
  label: string
  value: number | string
}) {
  return (
    <div className="rounded-lg bg-muted/50 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold">{value}</p>
    </div>
  )
}

async function downloadMedia(
  taskId: string,
  asset: DouyinMediaAssetPublic,
  onError: (message: string) => void,
) {
  try {
    const token = localStorage.getItem("access_token")
    const response = await fetch(
      `${OpenAPI.BASE}/api/v1/douyin/tasks/${taskId}/media/${asset.id}/file`,
      { headers: token ? { Authorization: `Bearer ${token}` } : undefined },
    )
    if (!response.ok) throw new Error(`视频下载失败 (${response.status})`)
    const objectUrl = URL.createObjectURL(await response.blob())
    const anchor = document.createElement("a")
    anchor.href = objectUrl
    anchor.download = `douyin-${asset.aweme_id}.mp4`
    anchor.click()
    URL.revokeObjectURL(objectUrl)
  } catch (reason) {
    onError(reason instanceof Error ? reason.message : "视频下载失败")
  }
}
