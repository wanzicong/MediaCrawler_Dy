import { formatDateTime, formatRelativeTime } from "@/lib/time"
import { cn } from "@/lib/utils"

/**
 * 相对时间（报告 A16）。
 *
 * 背景：列表里的时间列全是绝对时间「2026/09/12 18:40」，一列扫下来
 * 很难一眼判断「这条是刚刚的还是昨天的」。这里显示相对时间，
 * 悬停（`title`）给出精确到分钟的绝对时间，两者都不丢。
 *
 * 用法：
 * ```tsx
 * <TimeAgo value={item.created_at} />
 * <TimeAgo value={item.last_seen_at} neverText="从未" />
 * ```
 */
export function TimeAgo({
  value,
  /** 空值文案，`null` 表示时间字段用「从未」语义 */
  neverText,
  className,
}: {
  value: string | number | Date | null | undefined
  neverText?: string
  className?: string
}) {
  const fallback = neverText ?? "—"
  const absolute = formatDateTime(value, { fallback })
  const relative = formatRelativeTime(value, fallback)

  return (
    <span className={cn("whitespace-nowrap", className)} title={absolute}>
      {relative}
    </span>
  )
}
