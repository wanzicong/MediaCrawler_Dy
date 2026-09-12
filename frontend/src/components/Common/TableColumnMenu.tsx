import { Columns3, RotateCcw } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import type { TableColumnMenuProps } from "@/hooks/useTableColumns"
import { cn } from "@/lib/utils"

/**
 * 列显示/隐藏菜单（报告 A1），给**手写 <Table>** 用。
 *
 * 配合 @/hooks/useTableColumns 使用，直接把它返回的 menuProps 展开进来：
 * ```tsx
 * const { isVisible, visibleCount, menuProps } = useTableColumns({ storageKey, columns })
 * ...
 * <TableColumnMenu {...menuProps} />
 * ```
 *
 * 注意：菜单项用 DropdownMenuCheckboxItem 直接作为 Content 的子元素，
 * 不要用 div 包一层 —— 那会破坏 Radix 的方向键导航（报告 H16 同类问题）。
 */
export function TableColumnMenu({
  columns,
  hidden,
  toggle,
  showAll,
  className,
  label = "列",
}: TableColumnMenuProps & { className?: string; label?: string }) {
  // 永远可见的列（如操作列）不进菜单，它们不是可选项
  const toggleable = columns.filter((column) => !column.alwaysVisible)
  if (toggleable.length <= 1) return null

  const hiddenCount = toggleable.filter((column) =>
    hidden.has(column.key),
  ).length

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className={cn("h-8 gap-1.5", className)}
          aria-label={
            hiddenCount > 0
              ? `设置显示的列，当前隐藏了 ${hiddenCount} 列`
              : "设置显示的列"
          }
        >
          <Columns3 className="size-4" />
          <span className="hidden sm:inline">{label}</span>
          {hiddenCount > 0 && (
            <span className="text-xs text-muted-foreground">
              （隐藏 {hiddenCount}）
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuLabel>显示的列</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {toggleable.map((column) => (
          <DropdownMenuCheckboxItem
            key={column.key}
            checked={!hidden.has(column.key)}
            onCheckedChange={() => toggle(column.key)}
            // 勾选后不关闭菜单，方便连续调整多列
            onSelect={(event) => event.preventDefault()}
          >
            {column.title}
          </DropdownMenuCheckboxItem>
        ))}
        {hiddenCount > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="justify-center gap-1.5 text-sm"
              onSelect={() => showAll()}
            >
              <RotateCcw className="size-3.5" />
              恢复全部列
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
