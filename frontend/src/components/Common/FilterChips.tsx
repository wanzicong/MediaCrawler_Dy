import { X } from "lucide-react"

import { cn } from "@/lib/utils"

/**
 * 已应用筛选条件的 chip 可视化（报告 A2）。
 *
 * 背景：改造前多维筛选页（资源库/评论/关键词/互动/日志）的筛选状态只体现在
 * 各个 Select 的当前值里，用户扫一眼不知道「现在到底筛了什么」，也没有一键清除。
 *
 * 用法：
 * ```tsx
 * <FilterChips
 *   chips={[
 *     trackId !== "all" && { key: "track", label: "赛道", value: trackName, onRemove: () => setTrackId("all") },
 *     search && { key: "q", label: "搜索", value: search, onRemove: () => setSearch("") },
 *   ]}
 *   onClearAll={resetAll}
 * />
 * ```
 * chips 里允许出现 false / undefined / null，会被自动过滤，方便写条件表达式。
 */

export type FilterChipValue = {
  key: string
  /** 维度名，如「赛道」「状态」 */
  label: string
  /** 当前值（已本地化的展示文本） */
  value: string
  onRemove: () => void
}

/**
 * chips 数组的元素类型。
 *
 * 故意放得很宽：业务侧惯用写法是 `someFilter && { ... }`，而 `someFilter` 可能是
 * 字符串（空时产出 ""）或 boolean 变量（产出 boolean），这些都不该报类型错。
 * 真正决定是否渲染的是**结构**（是不是带 key/label/value 的对象），不是真假值。
 */
export type FilterChip = FilterChipValue | boolean | null | undefined | 0 | ""

export function FilterChips({
  chips,
  onClearAll,
  className,
}: {
  chips: FilterChip[]
  /** 传了就显示「清除全部」 */
  onClearAll?: () => void
  className?: string
}) {
  // 按结构过滤，而不是按真假值：`true` / 非空字符串也会被正确地当成「无条件项」丢掉
  const active = chips.filter(
    (chip): chip is FilterChipValue =>
      typeof chip === "object" && chip !== null,
  )
  if (active.length === 0) return null

  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
      <span className="text-xs text-muted-foreground">已筛选</span>
      {active.map((chip) => (
        <button
          key={chip.key}
          type="button"
          onClick={chip.onRemove}
          aria-label={`移除筛选：${chip.label} ${chip.value}`}
          className="group inline-flex max-w-[16rem] items-center gap-1 rounded-full border bg-muted/60 px-2.5 py-1 text-xs transition-colors hover:bg-muted"
        >
          <span className="shrink-0 text-muted-foreground">{chip.label}</span>
          <span className="truncate font-medium">{chip.value}</span>
          <X className="size-3 shrink-0 opacity-50 transition-opacity group-hover:opacity-100" />
        </button>
      ))}
      {onClearAll && active.length > 1 && (
        <button
          type="button"
          onClick={onClearAll}
          className="rounded-full px-2 py-1 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          清除全部
        </button>
      )}
    </div>
  )
}
