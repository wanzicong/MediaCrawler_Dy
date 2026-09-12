import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getExpandedRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  type RowData,
  type SortingState,
  useReactTable,
  type VisibilityState,
} from "@tanstack/react-table"
import { ChevronRight, Download } from "lucide-react"
import { Fragment, type ReactNode, useState } from "react"

import { ColumnVisibilityMenu } from "@/components/Common/ColumnVisibilityMenu"
import { EmptyState } from "@/components/Common/EmptyState"
import { Pager, type PagerProps } from "@/components/Common/Pager"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import {
  RowContextMenu,
  type RowMenuItem,
} from "@/components/Common/RowContextMenu"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useRowKeyboardNav } from "@/hooks/useRowKeyboardNav"
import { type CsvColumn, downloadCsv } from "@/lib/csv"
import { cn } from "@/lib/utils"

/**
 * 通用数据表格。
 *
 * 改造前它只有 `columns` + `data` 两个 prop，且：
 *   - 无 loading / error 接口（靠外部 Suspense，非 Suspense 场景必然空表闪烁）
 *   - 只有客户端分页，TanStack Table 的 sorting / rowSelection / columnVisibility / 服务端分页能力全部未启用
 *   - 空态与分页条文案硬编码英文，与中文界面混排
 *   - 列写死，列多的表窄屏只能靠横向滚动
 * 结果是 20 个业务列表里只有 2 个（admin / items）用它，其余全部手写 <Table>。
 *
 * 现在补齐这些能力，且**向后兼容**：不传任何新 prop 时，行为与改造前一致
 * （仅多了中文文案、overflow-x-auto 与表头列设置入口）。
 */

declare module "@tanstack/react-table" {
  // 类型参数必须与 TanStack 原声明完全一致（含 extends RowData 约束），
  // 否则 TS 会报 2428「All declarations of 'ColumnMeta' must have identical type parameters」。
  interface ColumnMeta<TData extends RowData, TValue> {
    /** 列可见性菜单里显示的名称 */
    title?: string
    /** 该列固定在右侧（横向滚动时不消失），通常用于操作列 */
    sticky?: boolean
    /**
     * 列级逃生口：需要把行数据 / 单元格值之外的上下文传给单元格渲染时的备用位。
     * （同时让 TData / TValue 真正参与类型，避免被 lint 判为未使用而重命名。）
     */
    cellContext?: { row: TData; value: TValue }
  }
}

export interface DataTableError {
  title: string
  description: string
  onRetry?: () => void
  retrying?: boolean
}

export interface ServerPagination extends Omit<PagerProps, "total"> {
  total: number
}

export interface RowSelectionConfig<TData> {
  /** 统一用 Set：改造前多处用 Array + includes，是 O(n) 查找。 */
  selected: Set<string>
  getRowId: (row: TData) => string
  onToggle: (id: string) => void
  /** 传入后表头出现「本页全选」复选框，参数为当前页所有行 id。 */
  onToggleAll?: (ids: string[]) => void
  /** 行复选框的无障碍标签，默认「选择此行」 */
  rowLabel?: (row: TData) => string
}

export interface DataTableProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[]
  data: TData[]

  /** 显示骨架行，替代空表闪烁 */
  loading?: boolean
  /** 骨架行数，默认 5 */
  loadingRows?: number
  /** 请求失败态；给了就渲染错误提示 + 重试，而不是伪装成「无数据」 */
  error?: DataTableError | null
  /** 空态文案，默认「暂无数据」 */
  emptyText?: string
  /** 更丰富的空态（带图标与行动按钮），优先级高于 emptyText */
  emptyState?: ReactNode

  /** 服务端分页：传了就不再走客户端分页，data 视为当前页数据 */
  serverPagination?: ServerPagination
  /** 行选择 */
  rowSelection?: RowSelectionConfig<TData>
  /** 包一层横向滚动容器，默认 true */
  scrollX?: boolean
  /** 表格最小宽度（列多时避免挤压），如 "min-w-[900px]" */
  minWidthClass?: string

  /** 受控排序状态；配合 onSortingChange 用于**服务端排序** */
  sorting?: SortingState
  onSortingChange?: (sorting: SortingState) => void
  /** 关闭客户端排序（不传 onSortingChange 时默认开启，表头可点即排） */
  disableClientSorting?: boolean
  /** 受控列可见性 */
  columnVisibility?: VisibilityState
  onColumnVisibilityChange?: (visibility: VisibilityState) => void
  /** 是否显示「列」设置入口，默认 true */
  showColumnMenu?: boolean
  /** 表格上方工具条右侧的额外内容 */
  toolbar?: ReactNode

  /** 【A6】轮询后数据发生变化的行 id，这些行会闪一下（配合 index.css 的 .row-highlight） */
  highlightedIds?: Set<string>
  /** 【A5】行展开区域；给了就可展开，返回 null 表示该行不可展开 */
  renderExpanded?: (row: TData) => ReactNode
  /** 【A7】行右键菜单项；给了就启用右键 */
  contextMenu?: (row: TData) => RowMenuItem[]
  /** 【A11】表尾（合计行等） */
  footer?: ReactNode
  /** 【A13】启用键盘导航（↑↓ 移动 / Enter 激活 / Space 勾选） */
  keyboardNav?: {
    onActivate?: (row: TData) => void
    /** 勾选行为复用 rowSelection.onToggle；这里只需声明是否启用 */
    enabled?: boolean
  }
  /** 【A12】导出当前页 / 已选中为 CSV */
  exportConfig?: {
    /** 不带扩展名的文件名 */
    filename: string
    columns: CsvColumn<TData>[]
  }

  className?: string
}

export function DataTable<TData, TValue>({
  columns,
  data,
  loading = false,
  loadingRows = 5,
  error = null,
  emptyText = "暂无数据",
  emptyState,
  serverPagination,
  rowSelection,
  scrollX = true,
  minWidthClass,
  sorting,
  onSortingChange,
  disableClientSorting = false,
  columnVisibility,
  onColumnVisibilityChange,
  showColumnMenu = true,
  toolbar,
  highlightedIds,
  renderExpanded,
  contextMenu,
  footer,
  keyboardNav,
  exportConfig,
  className,
}: DataTableProps<TData, TValue>) {
  const isServerPaginated = Boolean(serverPagination)
  const isServerSorted = Boolean(onSortingChange)
  const [internalSorting, setInternalSorting] = useState<SortingState>([])
  const [internalVisibility, setInternalVisibility] = useState<VisibilityState>(
    {},
  )

  const expandColumn: ColumnDef<TData, unknown> | null = renderExpanded
    ? {
        id: "__expand__",
        header: () => <span className="sr-only">展开</span>,
        cell: ({ row }) =>
          row.getCanExpand() ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label={row.getIsExpanded() ? "收起详情" : "展开详情"}
              aria-expanded={row.getIsExpanded()}
              onClick={() => row.toggleExpanded()}
            >
              <ChevronRight
                className={cn(
                  "size-4 transition-transform",
                  row.getIsExpanded() && "rotate-90",
                )}
              />
            </Button>
          ) : null,
        meta: { sticky: true },
      }
    : null

  const selectionColumn: ColumnDef<TData, unknown> | null = rowSelection
    ? {
        id: "__select__",
        header: () =>
          rowSelection.onToggleAll ? (
            <Checkbox
              aria-label="全选本页"
              checked={
                data.length > 0 &&
                data.every((row) =>
                  rowSelection.selected.has(rowSelection.getRowId(row)),
                )
              }
              onCheckedChange={() =>
                rowSelection.onToggleAll?.(
                  data.map((row) => rowSelection.getRowId(row)),
                )
              }
            />
          ) : null,
        cell: ({ row }) => {
          const id = rowSelection.getRowId(row.original)
          return (
            <Checkbox
              aria-label={rowSelection.rowLabel?.(row.original) ?? "选择此行"}
              checked={rowSelection.selected.has(id)}
              onCheckedChange={() => rowSelection.onToggle(id)}
            />
          )
        },
        meta: { sticky: true },
      }
    : null

  const prefixColumns = [selectionColumn, expandColumn].filter(
    Boolean,
  ) as ColumnDef<TData, TValue>[]

  const table = useReactTable({
    data,
    columns: (prefixColumns.length > 0
      ? [...prefixColumns, ...columns]
      : columns) as ColumnDef<TData, TValue>[],
    state: {
      sorting: sorting ?? internalSorting,
      columnVisibility: columnVisibility ?? internalVisibility,
    },
    onSortingChange: (updater) => {
      const next =
        typeof updater === "function"
          ? updater(sorting ?? internalSorting)
          : updater
      if (onSortingChange) onSortingChange(next)
      else setInternalSorting(next)
    },
    onColumnVisibilityChange: (updater) => {
      const next =
        typeof updater === "function"
          ? updater(columnVisibility ?? internalVisibility)
          : updater
      if (onColumnVisibilityChange) onColumnVisibilityChange(next)
      else setInternalVisibility(next)
    },
    // 服务端排序时不启用客户端排序模型，否则会在当前页内二次排序
    manualSorting: isServerSorted,
    getCoreRowModel: getCoreRowModel(),
    ...(renderExpanded
      ? {
          getRowCanExpand: () => true,
          getExpandedRowModel: getExpandedRowModel(),
        }
      : {}),
    ...(isServerSorted || disableClientSorting || isServerPaginated
      ? {}
      : { getSortedRowModel: getSortedRowModel() }),
    // 服务端分页时数据已是单页，不能再叠加客户端分页
    ...(isServerPaginated
      ? {}
      : { getPaginationRowModel: getPaginationRowModel() }),
  })

  const leafColumns = table.getVisibleLeafColumns()
  const columnCount = leafColumns.length

  const displayRows = table.getRowModel().rows
  const rowIdOf = (row: (typeof displayRows)[number]) =>
    rowSelection ? rowSelection.getRowId(row.original) : row.id

  // 【A13】键盘导航。hook 不能条件调用，所以始终调用、用 enabled 控制是否响应。
  const keyboardState = useRowKeyboardNav({
    rowIds: displayRows.map(rowIdOf),
    enabled: Boolean(keyboardNav),
    onActivate: (id) => {
      const row = displayRows.find((candidate) => rowIdOf(candidate) === id)
      if (row) keyboardNav?.onActivate?.(row.original)
    },
    onToggleSelect: rowSelection
      ? (id) => {
          rowSelection.onToggle(id)
        }
      : undefined,
  })

  const body = (() => {
    if (error) {
      return (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={columnCount} className="p-0">
            <QueryErrorState
              title={error.title}
              description={error.description}
              onRetry={error.onRetry ?? (() => {})}
              retrying={error.retrying}
            />
          </TableCell>
        </TableRow>
      )
    }

    if (loading) {
      // 骨架屏是固定占位，索引即稳定 key
      return Array.from({ length: loadingRows }, (_, rowIndex) => (
        <TableRow key={`skeleton-${rowIndex}`} className="hover:bg-transparent">
          {Array.from({ length: columnCount }, (_, cellIndex) => (
            <TableCell key={`skeleton-cell-${cellIndex}`}>
              <Skeleton className="h-4 w-full" />
            </TableCell>
          ))}
        </TableRow>
      ))
    }

    const rows = table.getRowModel().rows
    if (rows.length === 0) {
      return (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={columnCount} className="p-0">
            {emptyState ?? <EmptyState compact title={emptyText} />}
          </TableCell>
        </TableRow>
      )
    }

    return rows.map((row) => {
      const rowId = rowSelection ? rowSelection.getRowId(row.original) : row.id
      // A6：数据变化的行闪一下
      const isHighlighted = highlightedIds?.has(rowId) ?? false
      const isActive = keyboardState?.activeId === rowId

      const rowElement = (
        <TableRow
          key={row.id}
          data-active={isActive}
          className={cn(
            isHighlighted && "row-highlight",
            isActive && "bg-muted/60",
          )}
        >
          {row.getVisibleCells().map((cell) => {
            const sticky = cell.column.columnDef.meta?.sticky
            return (
              <TableCell
                key={cell.id}
                className={cn(
                  sticky &&
                    "sticky right-0 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80",
                )}
              >
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </TableCell>
            )
          })}
        </TableRow>
      )

      const withContextMenu =
        contextMenu && contextMenu(row.original).length > 0 ? (
          <RowContextMenu items={contextMenu(row.original)}>
            {rowElement}
          </RowContextMenu>
        ) : (
          rowElement
        )

      // 展开行需要与数据行成对出现，所以用 Fragment 包一层
      return (
        <Fragment key={row.id}>
          {withContextMenu}
          {renderExpanded && row.getIsExpanded() && (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={columnCount} className="bg-muted/30 p-4">
                {renderExpanded(row.original)}
              </TableCell>
            </TableRow>
          )}
        </Fragment>
      )
    })
  })()

  const pagination = serverPagination ? (
    <Pager {...serverPagination} />
  ) : table.getPageCount() > 1 ? (
    <Pager
      page={table.getState().pagination.pageIndex}
      pageSize={table.getState().pagination.pageSize}
      total={data.length}
      onPageChange={(page) => table.setPageIndex(page)}
      pageSizeOptions={[5, 10, 25, 50]}
      onPageSizeChange={(size) => table.setPageSize(size)}
      alwaysShow={false}
      className="border-t bg-muted/20 p-4"
    />
  ) : null

  // 【A12】导出范围：有选中就导出选中，否则导出当前页。
  // 「导出全部」涉及全量数据，必须走后端流式接口，不在这里做。
  const exportRows = (() => {
    if (!exportConfig) return []
    if (rowSelection && rowSelection.selected.size > 0) {
      return data.filter((row) =>
        rowSelection.selected.has(rowSelection.getRowId(row)),
      )
    }
    return displayRows.map((row) => row.original)
  })()
  const exportingSelected = Boolean(
    rowSelection && rowSelection.selected.size > 0,
  )

  const hasToolbar = showColumnMenu || toolbar || exportConfig

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      {hasToolbar && (
        <div className="flex items-center justify-end gap-2">
          {toolbar}
          {exportConfig && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-8 gap-1.5"
              disabled={exportRows.length === 0}
              aria-label={
                exportingSelected
                  ? `导出选中的 ${exportRows.length} 条为 CSV`
                  : `导出本页 ${exportRows.length} 条为 CSV`
              }
              onClick={() =>
                downloadCsv(
                  exportConfig.filename,
                  exportRows,
                  exportConfig.columns,
                )
              }
            >
              <Download className="size-4" />
              <span className="hidden sm:inline">
                {exportingSelected
                  ? `导出选中 ${exportRows.length} 条`
                  : "导出本页"}
              </span>
            </Button>
          )}
          {showColumnMenu && <ColumnVisibilityMenu table={table} />}
        </div>
      )}

      <div
        {...(keyboardNav ? keyboardState.containerProps : {})}
        className={cn(scrollX && "overflow-x-auto rounded-xl border")}
      >
        <Table className={minWidthClass}>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id} className="hover:bg-transparent">
                {headerGroup.headers.map((header) => {
                  const sticky = header.column.columnDef.meta?.sticky
                  return (
                    <TableHead
                      key={header.id}
                      className={cn(
                        sticky &&
                          "sticky right-0 z-10 bg-background backdrop-blur supports-[backdrop-filter]:bg-background/95",
                      )}
                    >
                      {header.isPlaceholder
                        ? null
                        : flexRender(
                            header.column.columnDef.header,
                            header.getContext(),
                          )}
                    </TableHead>
                  )
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>{body}</TableBody>
          {/* 【A11】合计行 / 列聚合 */}
          {footer && !loading && !error && (
            <TableFooter>
              <TableRow className="hover:bg-transparent">{footer}</TableRow>
            </TableFooter>
          )}
        </Table>
      </div>
      {pagination}
    </div>
  )
}
