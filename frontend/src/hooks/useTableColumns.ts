import { useCallback, useMemo, useState } from "react"

import { readJsonStorage, writeJsonStorage } from "@/lib/storage"

/**
 * 手写 <Table> 的列可见性（报告 A1）。
 *
 * 背景：DataTable 上的列可见性只覆盖 admin / items 两个页面，
 * 其余列表全是手写 `<Table>`（任务 7 列、作品 7 列、评论 6 列、日志 7 列…），
 * 用户没法把不关心的列收起来，窄屏只能横向拖。
 *
 * 存储策略：**存「被隐藏的列」而不是「可见的列」**。
 * 这样以后给表格加新列时，新列默认是可见的，不会因为旧的偏好记录而被意外藏起来。
 *
 * 用法：
 * ```tsx
 * const TASK_COLUMNS = [
 *   { key: "id", title: "任务 ID" },
 *   { key: "status", title: "状态" },
 *   { key: "track", title: "赛道" },
 *   { key: "actions", title: "操作", alwaysVisible: true },  // 操作列不允许隐藏
 * ] as const satisfies readonly TableColumnDef[]
 *
 * const { isVisible, visibleCount, menuProps } = useTableColumns({
 *   storageKey: "douyin-tasks-columns",
 *   columns: TASK_COLUMNS,
 * })
 *
 * // 表头与单元格都要包一层；空态的 colSpan 用 visibleCount
 * {isVisible("status") && <TableHead>状态</TableHead>}
 * ...
 * <TableColumnMenu {...menuProps} />
 * ```
 *
 * ⚠️ 必须同步改的地方：
 * 1. 表头与**每一行**的单元格都要各自包一层 isVisible 判断，漏一处就会列错位。
 * 2. 空态 / 加载态行的 `colSpan` 必须从写死的数字改成 `visibleCount`。
 * 3. 视图切换时（table / rows / cards）只有 table 视图需要这个。
 */

export type TableColumnDef = {
  /** 稳定的列标识，进本地存储，不要随便改 */
  key: string
  /** 列设置菜单里显示的名字 */
  title: string
  /** 该列永远可见（如操作列），不出现在菜单里 */
  alwaysVisible?: boolean
  /** 默认是否隐藏（首次使用时生效） */
  defaultHidden?: boolean
}

export type TableColumnMenuProps = {
  columns: readonly TableColumnDef[]
  hidden: Set<string>
  visibleCount: number
  toggle: (key: string) => void
  showAll: () => void
}

export function useTableColumns({
  storageKey,
  columns,
}: {
  storageKey: string
  columns: readonly TableColumnDef[]
}): {
  isVisible: (key: string) => boolean
  visibleCount: number
  hidden: Set<string>
  toggle: (key: string) => void
  showAll: () => void
  menuProps: TableColumnMenuProps
} {
  const toggleableKeys = useMemo(
    () => columns.filter((column) => !column.alwaysVisible).map((c) => c.key),
    [columns],
  )
  const defaultHidden = useMemo(
    () => columns.filter((column) => column.defaultHidden).map((c) => c.key),
    [columns],
  )

  const [hidden, setHidden] = useState<Set<string>>(() => {
    const saved = readJsonStorage<string[]>(
      storageKey,
      defaultHidden,
      (value) => Array.isArray(value),
    )
    // 只保留仍然存在的列（列被删掉后，旧偏好里的 key 要清理掉）
    return new Set(saved.filter((key) => toggleableKeys.includes(key)))
  })

  const toggle = useCallback(
    (key: string) => {
      if (!toggleableKeys.includes(key)) return
      setHidden((current) => {
        const next = new Set(current)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        writeJsonStorage(storageKey, [...next])
        return next
      })
    },
    [storageKey, toggleableKeys],
  )

  const showAll = useCallback(() => {
    setHidden(new Set())
    writeJsonStorage(storageKey, [])
  }, [storageKey])

  const isVisible = useCallback((key: string) => !hidden.has(key), [hidden])

  const visibleCount = columns.filter(
    (column) => !hidden.has(column.key),
  ).length

  return {
    isVisible,
    visibleCount,
    hidden,
    toggle,
    showAll,
    menuProps: {
      columns,
      hidden,
      visibleCount,
      toggle,
      showAll,
    },
  }
}
