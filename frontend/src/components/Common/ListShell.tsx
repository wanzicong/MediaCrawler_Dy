import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import { BulkActionBar } from "@/components/Common/BulkActionBar"
import type {
  DataTableError,
  ServerPagination,
} from "@/components/Common/DataTable"
import { EmptyState } from "@/components/Common/EmptyState"
import { type FilterChip, FilterChips } from "@/components/Common/FilterChips"
import { FilterPresetBar } from "@/components/Common/FilterPresetBar"
import { Pager, type PagerProps } from "@/components/Common/Pager"
import { PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { RefreshIndicator } from "@/components/Common/RefreshIndicator"
import {
  type ListViewMode,
  ViewModeToggle,
} from "@/components/Common/ViewModeToggle"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

/**
 * 列表页统一外壳。
 *
 * 把「页头 + 筛选栏 + 筛选 chips + 筛选预设 + 视图切换 + 刷新指示 + 三态分发 +
 * 分页 + 批量操作栏」收在一处，业务列表只传配置。
 *
 * 改造前的状态：20 个列表里 16 个手写 <Table>，三态实现各不相同
 * （有的把空态和加载态合并、有的完全没有错误态，接口失败被静默显示成「暂无数据」），
 * 筛选状态只能从各个 Select 的当前值去猜，也没有批量操作栏。
 *
 * 最小用法：
 * ```tsx
 * <ListShell
 *   title="标签管理"
 *   loading={query.isPending}
 *   error={query.isError ? { title: "加载失败", description: "请稍后重试", onRetry: refetch, retrying: query.isFetching } : null}
 *   empty={rows.length === 0}
 *   onRefresh={refetch}
 *   refreshing={query.isFetching}
 *   updatedAt={query.dataUpdatedAt}
 *   pager={{ page, pageSize, total: query.data?.count ?? 0, onPageChange: setPage, showJumper: true }}
 * >
 *   <Table>…</Table>
 * </ListShell>
 * ```
 */
export interface ListShellProps {
  title: string
  description?: string
  eyebrow?: string
  icon?: LucideIcon

  /** 页头右侧操作区（「新建」等主按钮） */
  actions?: ReactNode
  /** 筛选栏内容，渲染在页头下方 */
  filters?: ReactNode
  /** 已应用筛选的 chip 可视化（A2）；falsy 项会被自动过滤 */
  chips?: FilterChip[]
  /** chips 旁的「清除全部」回调 */
  onClearFilters?: () => void
  /** 筛选预设条（A10）配置 */
  presets?: {
    storageKey: string
    currentFilters: Record<string, unknown>
    onApply: (filters: Record<string, unknown>) => void
  }
  /** 传了就渲染视图切换按钮组 */
  viewMode?: { value: ListViewMode; onChange: (mode: ListViewMode) => void }

  loading: boolean
  /** 骨架行数，默认 5 */
  loadingRows?: number
  error: DataTableError | null
  empty: boolean
  emptyText?: string
  emptyState?: ReactNode

  onRefresh?: () => void
  refreshing?: boolean
  /** 上次成功获取数据的时间戳（query 的 dataUpdatedAt），用于「X 秒前更新」 */
  updatedAt?: number
  /** 自动刷新开关（A14） */
  autoRefresh?: boolean
  onAutoRefreshChange?: (value: boolean) => void

  /** 批量操作栏（A3）：count>0 时从底部浮现 */
  bulkActions?: { count: number; onClear: () => void; actions: ReactNode }

  /** 有值则渲染分页条 */
  pager?: ServerPagination

  /** 不给 Card 外壳（子元素自带头部/卡片时用） */
  bare?: boolean
  children: ReactNode
  className?: string
}

export function ListShell({
  title,
  description,
  eyebrow,
  icon,
  actions,
  filters,
  chips,
  onClearFilters,
  presets,
  viewMode,
  loading,
  loadingRows = 5,
  error,
  empty,
  emptyText = "暂无数据",
  emptyState,
  onRefresh,
  refreshing = false,
  updatedAt,
  autoRefresh,
  onAutoRefreshChange,
  bulkActions,
  pager,
  bare = false,
  children,
  className,
}: ListShellProps) {
  const body = (() => {
    if (error) {
      return (
        <QueryErrorState
          title={error.title}
          description={error.description}
          onRetry={error.onRetry ?? (() => {})}
          retrying={error.retrying}
        />
      )
    }

    if (loading) {
      return (
        <div className="flex flex-col gap-2">
          {Array.from({ length: loadingRows }, (_, index) => (
            <Skeleton key={`list-skeleton-${index}`} className="h-11 w-full" />
          ))}
        </div>
      )
    }

    if (empty) {
      return emptyState ?? <EmptyState title={emptyText} />
    }

    return children
  })()

  const hasFilterBlock = Boolean(
    filters ||
      chips?.some((chip) => typeof chip === "object" && chip !== null) ||
      presets,
  )

  return (
    <div className={cn("page-stack", className)}>
      <PageHero
        eyebrow={eyebrow}
        icon={icon}
        title={title}
        description={description}
        actions={
          <>
            {actions}
            {viewMode && (
              <ViewModeToggle
                value={viewMode.value}
                onChange={viewMode.onChange}
              />
            )}
            {onRefresh && (
              <RefreshIndicator
                updatedAt={updatedAt}
                refreshing={refreshing}
                onRefresh={onRefresh}
                autoRefresh={autoRefresh}
                onAutoRefreshChange={onAutoRefreshChange}
              />
            )}
          </>
        }
      />

      {hasFilterBlock && (
        <Card>
          <CardContent className="flex flex-col gap-3 pt-6">
            {filters}
            {presets && (
              <FilterPresetBar
                storageKey={presets.storageKey}
                currentFilters={presets.currentFilters}
                onApply={presets.onApply}
              />
            )}
            {chips && <FilterChips chips={chips} onClearAll={onClearFilters} />}
          </CardContent>
        </Card>
      )}

      {bare ? (
        <div className="flex flex-col gap-4">{body}</div>
      ) : (
        <Card>
          <CardContent className="flex flex-col gap-4 pt-6">{body}</CardContent>
        </Card>
      )}

      {pager && !error && !loading && <Pager {...pager} />}

      {bulkActions && (
        <BulkActionBar
          count={bulkActions.count}
          onClear={bulkActions.onClear}
          actions={bulkActions.actions}
        />
      )}
    </div>
  )
}

export type { DataTableError, ServerPagination, PagerProps }
