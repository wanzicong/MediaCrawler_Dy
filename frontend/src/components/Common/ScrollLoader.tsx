import { LoaderCircle } from "lucide-react"
import { useEffect, useRef } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/**
 * 滚动加载的触底哨兵。
 *
 * 进入视口（提前 480px）就自动续拉下一页；同时保留一个「加载更多」按钮，
 * 兜住 IntersectionObserver 不可用、列表太短撑不出滚动条等场景。
 * 语义与无障碍：状态文案用 aria-live 播报，键盘用户可以直接按按钮。
 */
export function ScrollLoader({
  loadedCount,
  total,
  hasMore,
  isFetching,
  onLoadMore,
  className,
}: {
  loadedCount: number
  total: number
  hasMore: boolean
  isFetching: boolean
  onLoadMore: () => void
  className?: string
}) {
  const sentinelRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const node = sentinelRef.current
    if (!node || !hasMore || isFetching) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) onLoadMore()
      },
      { rootMargin: "480px 0px" },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [hasMore, isFetching, onLoadMore])

  return (
    <div
      ref={sentinelRef}
      data-testid="scroll-loader"
      className={cn(
        "flex flex-col items-center gap-2 py-4 text-xs text-muted-foreground",
        className,
      )}
      aria-live="polite"
    >
      {hasMore ? (
        isFetching ? (
          <span className="flex items-center gap-1.5">
            <LoaderCircle className="size-3.5 animate-spin" />
            正在加载更多… 已加载 {loadedCount} / {total}
          </span>
        ) : (
          <>
            <span>
              已加载 {loadedCount} / {total}
            </span>
            {/* 加载中不渲染按钮：禁用态按钮带 pointer-events-none，
                点击会落到父节点上，自动续拉与手动点击混在一起时也不好点 */}
            <Button size="sm" variant="outline" onClick={onLoadMore}>
              加载更多
            </Button>
          </>
        )
      ) : (
        <span>已加载全部 {total} 条</span>
      )}
    </div>
  )
}
