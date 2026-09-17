import { Play } from "lucide-react"
import type { ReactNode } from "react"

import type { DouyinAwemePublic, DouyinMediaAssetPublic } from "@/client"
import { VideoPreviewDialog } from "@/components/Douyin/VideoPreviewDialog"
import { cn } from "@/lib/utils"

/**
 * 封面即播放入口：作品已下载或保存了采集地址时，点击封面直接打开视频预览弹窗。
 *
 * 没有可播放来源的作品保持静态封面（不渲染按钮），避免出现「点了没反应」的假入口；
 * 悬停时才浮出播放角标，不干扰封面原本的信息密度。
 */
export function CoverPlayTrigger({
  taskId,
  aweme,
  asset,
  imageClassName,
  fallback,
  playIconClassName = "size-4",
  buttonClassName = "h-full w-full",
  onPlay,
}: {
  taskId: string
  aweme: DouyinAwemePublic
  asset?: DouyinMediaAssetPublic | null
  /** 封面 <img> 的类名，由调用方决定尺寸与圆角 */
  imageClassName: string
  /** 作品没有封面图时的占位内容 */
  fallback: ReactNode
  playIconClassName?: string
  /**
   * 触发器按钮的尺寸类名：默认铺满已限定尺寸的封面容器。
   * 放在 flex 行内、尺寸由封面自身决定时要传 `shrink-0`，
   * 否则 `w-full` 会撑开整行、把相邻的文字列挤成 0 宽。
   */
  buttonClassName?: string
  /**
   * 由调用方接管播放（列表行把封面与操作列按钮合并到同一个预览弹窗）。
   * 不传时本组件自己持有一个预览弹窗。
   */
  onPlay?: () => void
}) {
  const canPreview = Boolean(
    asset?.download_available || aweme.video_download_url,
  )
  const cover = aweme.cover_url ? (
    <img
      src={aweme.cover_url}
      alt=""
      loading="lazy"
      className={imageClassName}
    />
  ) : (
    fallback
  )
  if (!canPreview) return cover
  const button = (
    <button
      type="button"
      aria-label={`播放视频 ${aweme.title || aweme.aweme_id}`}
      title="点击播放"
      className={cn(
        "group/cover relative block cursor-pointer",
        buttonClassName,
      )}
      onClick={onPlay}
    >
      {cover}
      <span className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/25 opacity-0 transition group-hover/cover:opacity-100">
        <span className="flex size-9 items-center justify-center rounded-full bg-black/60 text-white shadow-lg">
          <Play aria-hidden="true" className={playIconClassName} />
        </span>
      </span>
    </button>
  )
  if (onPlay) return button
  return (
    <VideoPreviewDialog
      taskId={taskId}
      asset={asset}
      aweme={aweme}
      trigger={button}
    />
  )
}
