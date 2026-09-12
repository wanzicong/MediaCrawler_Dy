import type { Column } from "@tanstack/react-table"
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/**
 * 可点击排序的表头（报告 O20）。
 *
 * 背景：报告指出「无排序的列表（任务/互动/账号/日志）补服务端排序，表头可点击 + 排序指示器」。
 *
 * ⚠️ **重要前提**：服务端排序必须有后端支持。经核查，下列接口**没有排序参数**，
 * 因此它们无法在纯前端范围内补排序（需要后端加 sortBy/sortOrder）：
 *   - DouyinListRequestLogsData（只有 limit/skip）
 *   - UsersReadUsersData / ItemsReadItemsData（只有 limit/skip）
 * 有排序参数、且已具备排序入口的：douyin-tags（4 种）、douyin-creators、douyin-library。
 *
 * 提供两个变体：
 * - `SortableHeader`：给 TanStack `DataTable` 用，接 column 对象。
 * - `SortableHeaderButton`：给**手写 <Table>** 用，不依赖 TanStack，接当前排序状态与切换回调。
 */

/** 给 TanStack DataTable 用。列定义里写：header: ({ column }) => <SortableHeader column={column} label="创建时间" /> */
export function SortableHeader<TData, TValue>({
  column,
  label,
  align = "left",
  className,
}: {
  column: Column<TData, TValue>
  label: string
  align?: "left" | "right"
  className?: string
}) {
  if (!column.getCanSort()) {
    return <span className={className}>{label}</span>
  }

  const sorted = column.getIsSorted()

  return (
    <SortableHeaderButton
      label={label}
      align={align}
      className={className}
      active={Boolean(sorted)}
      direction={sorted === "desc" ? "desc" : "asc"}
      onToggle={() => column.toggleSorting(sorted === "asc")}
    />
  )
}

/**
 * 给手写 <Table> 用。
 *
 * 用法：
 * ```tsx
 * // 页面里把服务端排序值（如 "aweme_count:desc"）拆成字段与方向
 * <SortableHeaderButton
 *   label="作品数"
 *   align="right"
 *   active={sortBy === "aweme_count"}
 *   direction={sortOrder}
 *   onToggle={() => toggleSort("aweme_count")}
 * />
 * ```
 * `onToggle` 由页面实现：同字段则翻转方向，不同字段则切到该字段的默认方向（通常是 desc）。
 */
export function SortableHeaderButton({
  label,
  active,
  direction,
  onToggle,
  align = "left",
  className,
  title,
}: {
  label: string
  /** 当前是否按本列排序 */
  active: boolean
  /** 本列当前方向；active 为 false 时忽略 */
  direction: "asc" | "desc"
  onToggle: () => void
  align?: "left" | "right"
  className?: string
  /** 悬停提示，用于说明该列排的是什么 */
  title?: string
}) {
  const SortIcon = active
    ? direction === "asc"
      ? ArrowUp
      : ArrowDown
    : ChevronsUpDown

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      title={title}
      className={cn(
        "-ml-2 h-8 gap-1 px-2 font-medium",
        align === "right" && "ml-auto -mr-2",
        className,
      )}
      aria-label={`按${label}排序${
        active ? (direction === "asc" ? "（当前升序）" : "（当前降序）") : ""
      }`}
      aria-sort={
        active ? (direction === "asc" ? "ascending" : "descending") : "none"
      }
      onClick={onToggle}
    >
      {label}
      <SortIcon
        className={cn("size-3.5", active ? "opacity-100" : "opacity-40")}
      />
    </Button>
  )
}
