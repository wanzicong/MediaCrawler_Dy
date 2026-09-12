import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { cn } from "@/lib/utils"

/**
 * 共享分页器。
 *
 * 背景：改造前全站有 5 份各自实现的 Pager
 * （douyin-keywords / TaskResults / UnifiedWorksPanel / douyin-library / douyin-comments），
 * 全部只有「上一页 / 下一页」，没有页码跳转、没有每页条数切换、没有首末页。
 * 新代码一律用这个，不要再本地实现。
 */

export interface PagerProps {
  /** 0-indexed，与 TanStack Table 的 pageIndex 一致。 */
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  pageSizeOptions?: number[]
  onPageSizeChange?: (size: number) => void
  /** 显示页码跳转输入框 */
  showJumper?: boolean
  /** 只有一页时也渲染分页条（默认 true，保证「共 N 条」始终可见） */
  alwaysShow?: boolean
  /** 「共 N 条」的文案定制，默认「共 N 条」 */
  totalLabel?: (total: number) => string
  className?: string
}

const DEFAULT_PAGE_SIZE_OPTIONS = [20, 50, 100]

export function Pager({
  page,
  pageSize,
  total,
  onPageChange,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
  onPageSizeChange,
  showJumper = false,
  alwaysShow = true,
  totalLabel,
  className,
}: PagerProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const [jumpValue, setJumpValue] = useState(String(page + 1))

  // 外部翻页（或数据变化导致页码回退）时同步输入框
  useEffect(() => {
    setJumpValue(String(page + 1))
  }, [page])

  if (!alwaysShow && pageCount <= 1) return null

  const isFirst = page <= 0
  const isLast = page + 1 >= pageCount

  const goTo = (next: number) => {
    const clamped = Math.min(Math.max(next, 0), pageCount - 1)
    if (clamped !== page) onPageChange(clamped)
  }

  const commitJump = () => {
    const parsed = Number(jumpValue)
    if (!Number.isFinite(parsed)) {
      setJumpValue(String(page + 1))
      return
    }
    goTo(Math.trunc(parsed) - 1)
  }

  return (
    <div
      className={cn(
        "flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="text-sm text-muted-foreground">
          {totalLabel ? totalLabel(total) : `共 ${total} 条`}
        </span>

        {onPageSizeChange && (
          <div className="flex items-center gap-x-2">
            <span className="text-sm text-muted-foreground">每页</span>
            <Select
              value={`${pageSize}`}
              onValueChange={(value) => onPageSizeChange(Number(value))}
            >
              <SelectTrigger className="h-8 w-[76px]" aria-label="每页显示条数">
                <SelectValue placeholder={pageSize} />
              </SelectTrigger>
              <SelectContent side="top">
                {pageSizeOptions.map((size) => (
                  <SelectItem key={size} value={`${size}`}>
                    {size}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>

      <div className="flex items-center gap-x-4">
        {showJumper && pageCount > 1 && (
          <div className="flex items-center gap-x-1.5 text-sm text-muted-foreground">
            <span>第</span>
            <Input
              className="h-8 w-14 text-center"
              inputMode="numeric"
              value={jumpValue}
              aria-label="跳到指定页码"
              onChange={(event) => setJumpValue(event.target.value)}
              onBlur={commitJump}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault()
                  commitJump()
                }
              }}
            />
            <span>/ {pageCount} 页</span>
          </div>
        )}

        {!showJumper && (
          <span className="text-sm text-muted-foreground">
            第 {page + 1} / {pageCount} 页
          </span>
        )}

        <div className="flex items-center gap-x-1">
          <Button
            variant="outline"
            size="sm"
            className="h-8 w-8 p-0"
            disabled={isFirst}
            onClick={() => goTo(0)}
          >
            <span className="sr-only">第一页</span>
            <ChevronsLeft className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-8 w-8 p-0"
            disabled={isFirst}
            onClick={() => goTo(page - 1)}
          >
            <span className="sr-only">上一页</span>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-8 w-8 p-0"
            disabled={isLast}
            onClick={() => goTo(page + 1)}
          >
            <span className="sr-only">下一页</span>
            <ChevronRight className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-8 w-8 p-0"
            disabled={isLast}
            onClick={() => goTo(pageCount - 1)}
          >
            <span className="sr-only">最后一页</span>
            <ChevronsRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  )
}
