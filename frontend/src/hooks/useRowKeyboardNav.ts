import { useCallback, useEffect, useState } from "react"

/**
 * 列表键盘导航（报告 A13）。
 *
 * 背景：全站列表只能用鼠标操作 —— 想快速扫一批任务再逐条打开，得反复移动鼠标。
 * 这里补上 ↑↓ 移动、Enter 打开、Space 勾选、Esc 取消这套通用交互。
 *
 * 用法：
 * ```ts
 * const nav = useRowKeyboardNav({
 *   rowIds: rows.map((r) => r.id),
 *   onActivate: (id) => openDetail(id),
 *   onToggleSelect: (id) => toggle(id),
 * })
 *
 * <div {...nav.containerProps}>
 *   {rows.map((row, index) => (
 *     <TableRow
 *       data-active={nav.activeId === row.id}
 *       className="data-[active=true]:bg-muted/60"
 *     >…</TableRow>
 *   ))}
 * </div>
 * ```
 *
 * 注意：
 * - 只在容器/后代获得焦点时响应，避免和全局快捷键打架。
 * - 输入框、文本域、可编辑元素内的按键一律不拦截（否则没法在筛选框里打字）。
 * - 用了 roving 思路但**不改 DOM 焦点**，只标 `data-active`，
 *   这样不会跟表格里已有的按钮、复选框抢焦点。
 */
export function useRowKeyboardNav({
  rowIds,
  onActivate,
  onToggleSelect,
  onEscape,
  enabled = true,
}: {
  rowIds: string[]
  onActivate?: (id: string, index: number) => void
  onToggleSelect?: (id: string, index: number) => void
  onEscape?: () => void
  enabled?: boolean
}) {
  const [activeIndex, setActiveIndex] = useState(-1)

  // 行数变少时把游标收回有效范围，否则会指向不存在的行
  useEffect(() => {
    setActiveIndex((current) => {
      if (current < 0) return current
      if (current >= rowIds.length) return rowIds.length - 1
      return current
    })
  }, [rowIds.length])

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (!enabled) return

      // 正在输入时不拦截
      const target = event.target as HTMLElement | null
      const tag = target?.tagName
      if (
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        tag === "SELECT" ||
        target?.isContentEditable
      ) {
        return
      }

      const move = (delta: number) => {
        event.preventDefault()
        setActiveIndex((current) => {
          const next = current + delta
          if (next < 0) return rowIds.length > 0 ? 0 : -1
          if (next >= rowIds.length) return rowIds.length - 1
          return next
        })
      }

      switch (event.key) {
        case "ArrowDown":
          move(1)
          break
        case "ArrowUp":
          move(-1)
          break
        case "Home":
          if (rowIds.length > 0) {
            event.preventDefault()
            setActiveIndex(0)
          }
          break
        case "End":
          if (rowIds.length > 0) {
            event.preventDefault()
            setActiveIndex(rowIds.length - 1)
          }
          break
        case "Enter": {
          const id = rowIds[activeIndex]
          if (id !== undefined && onActivate) {
            event.preventDefault()
            onActivate(id, activeIndex)
          }
          break
        }
        case " ": {
          const id = rowIds[activeIndex]
          if (id !== undefined && onToggleSelect) {
            event.preventDefault()
            onToggleSelect(id, activeIndex)
          }
          break
        }
        case "Escape":
          if (onEscape) {
            event.preventDefault()
            onEscape()
          }
          setActiveIndex(-1)
          break
        default:
          break
      }
    },
    [activeIndex, enabled, onActivate, onEscape, onToggleSelect, rowIds],
  )

  return {
    activeIndex,
    activeId: rowIds[activeIndex] ?? null,
    setActiveIndex,
    containerProps: {
      onKeyDown: handleKeyDown,
      tabIndex: 0,
      role: "grid" as const,
      "aria-label": "列表，可用上下方向键移动、回车打开、空格勾选",
    },
  }
}
