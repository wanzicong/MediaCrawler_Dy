import { X } from "lucide-react"
import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/**
 * 批量操作工具栏（报告 A3）。
 *
 * 背景：改造前选中若干行后，可执行的操作散落在页面顶部/底部的各个按钮里，
 * 用户勾选完还得回去找按钮；选中数量也不总是显眼。
 * 这里统一为「选中后从底部浮现」的操作栏，操作集中、随时可清空。
 *
 * 用法：
 * ```tsx
 * <BulkActionBar
 *   count={selected.size}
 *   onClear={() => setSelected(new Set())}
 *   actions={
 *     <>
 *       <Button size="sm" onClick={bulkDelete}>批量删除</Button>
 *       <Button size="sm" variant="outline" onClick={export}>导出</Button>
 *     </>
 *   }
 * />
 * ```
 * count 为 0 时不渲染。
 */
export function BulkActionBar({
  count,
  onClear,
  actions,
  label,
  className,
}: {
  count: number
  onClear: () => void
  actions: ReactNode
  /** 计数文案定制，默认「已选 N 项」 */
  label?: string
  className?: string
}) {
  if (count <= 0) return null

  return (
    <div
      role="toolbar"
      aria-label="批量操作"
      className={cn(
        "fixed inset-x-0 bottom-4 z-50 mx-auto flex w-fit max-w-[calc(100vw-2rem)] flex-wrap items-center gap-2 rounded-2xl border bg-background/95 px-3 py-2 shadow-lg backdrop-blur supports-[backdrop-filter]:bg-background/80",
        className,
      )}
    >
      <span className="pl-1 text-sm font-medium">
        {label ?? `已选 ${count} 项`}
      </span>
      <span className="h-5 w-px bg-border" />
      <div className="flex flex-wrap items-center gap-2">{actions}</div>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="ml-1 gap-1 text-muted-foreground"
        onClick={onClear}
      >
        <X className="size-3.5" />
        清空
      </Button>
    </div>
  )
}
