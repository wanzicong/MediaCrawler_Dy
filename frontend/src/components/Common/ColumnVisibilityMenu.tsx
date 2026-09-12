import type { Table } from "@tanstack/react-table"
import { Columns3 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

/**
 * 列可见性菜单（报告 A1 的实用子集：显示/隐藏列）。
 *
 * 背景：改造前所有表格的列都是写死的，窄屏只能靠横向滚动，列多的表
 * （资源库/评论/日志）在笔记本上必须来回拖。这里至少让用户能关掉不关心的列。
 *
 * 用法：由 DataTable 内部渲染，业务侧只需给列定义加上 `meta.title` 作为菜单里的名称。
 * ```ts
 * { accessorKey: "aweme_id", header: ..., meta: { title: "作品 ID" } }
 * ```
 */
export function ColumnVisibilityMenu<TData>({
  table,
  className,
}: {
  table: Table<TData>
  className?: string
}) {
  // id 以 __ 开头的内部列（如选择列）不暴露给用户
  const columns = table
    .getAllColumns()
    .filter((column) => column.getCanHide() && !column.id.startsWith("__"))

  if (columns.length === 0) return null

  const hiddenCount = columns.filter((column) => !column.getIsVisible()).length

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className={className ?? "h-8 gap-1.5"}
          aria-label="设置显示的列"
        >
          <Columns3 className="size-4" />
          <span className="hidden sm:inline">列</span>
          {hiddenCount > 0 && (
            <span className="text-xs text-muted-foreground">
              （隐藏 {hiddenCount}）
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
        <DropdownMenuLabel>显示列</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {columns.map((column) => {
          const title =
            (column.columnDef.meta as { title?: string } | undefined)?.title ??
            column.id
          return (
            <DropdownMenuCheckboxItem
              key={column.id}
              checked={column.getIsVisible()}
              onCheckedChange={(value) =>
                column.toggleVisibility(Boolean(value))
              }
              onSelect={(event) => event.preventDefault()}
            >
              {title}
            </DropdownMenuCheckboxItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
