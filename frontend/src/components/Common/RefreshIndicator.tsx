import { RefreshCw } from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/**
 * 刷新指示器（报告 A14）。
 *
 * 背景：改造前列表页要么只有一个光秃秃的「刷新」按钮，要么什么都没 ——
 * 用户不知道数据是几秒前的、现在是不是在自动刷新、要不要手动点一下。
 * 这里把三件事讲清楚：上次更新时间、自动刷新开关、手动刷新。
 *
 * 「X 秒前」靠本地 tick 驱动，不依赖 query 的 dataUpdatedAt 变化。
 */
export function RefreshIndicator({
  updatedAt,
  refreshing,
  onRefresh,
  autoRefresh,
  onAutoRefreshChange,
  className,
}: {
  /** 上次成功获取数据的时间戳（TanStack Query 的 `dataUpdatedAt`） */
  updatedAt?: number
  refreshing: boolean
  onRefresh: () => void
  /** 传了就显示自动刷新开关 */
  autoRefresh?: boolean
  onAutoRefreshChange?: (value: boolean) => void
  className?: string
}) {
  const [, forceTick] = useState(0)

  // 每 10 秒重算一次相对时间；没有 updatedAt 时不跑定时器
  useEffect(() => {
    if (!updatedAt) return
    const timer = window.setInterval(() => forceTick((n) => n + 1), 10_000)
    return () => window.clearInterval(timer)
  }, [updatedAt])

  const relativeText = (() => {
    if (!updatedAt) return null
    const seconds = Math.max(0, Math.floor((Date.now() - updatedAt) / 1000))
    if (seconds < 5) return "刚刚更新"
    if (seconds < 60) return `${seconds} 秒前更新`
    const minutes = Math.floor(seconds / 60)
    if (minutes < 60) return `${minutes} 分钟前更新`
    return `${Math.floor(minutes / 60)} 小时前更新`
  })()

  return (
    <div className={cn("flex items-center gap-2", className)}>
      {relativeText && (
        <span className="hidden text-xs text-muted-foreground sm:inline">
          {refreshing ? "正在刷新…" : relativeText}
        </span>
      )}

      {onAutoRefreshChange && (
        <Button
          type="button"
          variant={autoRefresh ? "secondary" : "ghost"}
          size="sm"
          className="h-8 gap-1.5 text-xs"
          aria-pressed={autoRefresh}
          onClick={() => onAutoRefreshChange(!autoRefresh)}
        >
          <span
            className={cn(
              "size-1.5 rounded-full",
              autoRefresh
                ? "status-pulse bg-emerald-500"
                : "bg-muted-foreground/40",
            )}
          />
          自动刷新
        </Button>
      )}

      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-8 gap-1.5"
        aria-label="刷新列表"
        disabled={refreshing}
        onClick={onRefresh}
      >
        <RefreshCw className={cn("size-4", refreshing && "animate-spin")} />
        <span className="hidden sm:inline">刷新</span>
      </Button>
    </div>
  )
}
