import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

/**
 * 空状态。
 *
 * 背景：改造前空态几乎全是「暂无数据」四个字，不告诉用户下一步该做什么。
 * 这里要求「标题 + 说明 + 主行动按钮」三件套，让空态成为引导入口而不是死胡同。
 *
 * 用法：
 * ```tsx
 * <EmptyState
 *   icon={Tags}
 *   title="还没有标签"
 *   description="从已有作品里抽取标签，用于后续筛选与归类。"
 *   action={<Button onClick={sync}>同步历史标签</Button>}
 * />
 * ```
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
  compact = false,
}: {
  icon?: LucideIcon
  title: string
  description?: string
  action?: ReactNode
  className?: string
  /** 用于嵌在表格单元格里的紧凑形态 */
  compact?: boolean
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 text-center",
        compact ? "px-4 py-8" : "rounded-2xl border border-dashed px-5 py-14",
        className,
      )}
    >
      {Icon && (
        <span className="flex size-11 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
          <Icon className="size-5" />
        </span>
      )}
      <div className="max-w-md">
        <p className="font-medium text-foreground">{title}</p>
        {description && (
          <p className="mt-1 text-sm leading-6 text-pretty text-muted-foreground">
            {description}
          </p>
        )}
      </div>
      {action && <div className="mt-1">{action}</div>}
    </div>
  )
}
