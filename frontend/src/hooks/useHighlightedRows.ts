import { useEffect, useRef, useState } from "react"

/**
 * 行级数据变化高亮（报告 A6）。
 *
 * 背景：列表靠轮询刷新，但刷新是「无声」的 —— 任务从 queued 变成 running、
 * 下载状态从 downloading 变成 downloaded，用户完全看不出来，只能自己一行行比对。
 *
 * 用法：
 * ```ts
 * const highlighted = useHighlightedRows(
 *   rows,
 *   (row) => row.id,
 *   (row) => `${row.status}:${row.updated_at}`,   // 参与比对的「版本指纹」
 * )
 * // 行上：className={cn(highlighted.has(row.id) && "animate-row-highlight")}
 * ```
 *
 * 行为要点：
 * - **首次加载不闪**：只在「已经渲染过一版数据」之后发生的变更才算变化，
 *   否则打开页面的瞬间整屏都会闪一下。
 * - 高亮在 durationMs 后自动消失，不需要调用方清理。
 * - 指纹不变的行不闪（比如只是列表顺序变了）。
 */
export function useHighlightedRows<T>(
  items: T[],
  getId: (item: T) => string,
  getVersion: (item: T) => string | number,
  durationMs = 2_500,
): Set<string> {
  const previous = useRef<Map<string, string | number> | null>(null)
  const [highlighted, setHighlighted] = useState<Set<string>>(new Set())
  const timerRef = useRef<number | null>(null)

  // 用 ref 保存最新的取值函数，避免因调用方每次 render 新建箭头函数而反复触发 effect
  const getIdRef = useRef(getId)
  const getVersionRef = useRef(getVersion)
  getIdRef.current = getId
  getVersionRef.current = getVersion

  useEffect(() => {
    const next = new Map<string, string | number>()
    for (const item of items) {
      next.set(getIdRef.current(item), getVersionRef.current(item))
    }

    const before = previous.current
    previous.current = next

    // 首次拿到数据（或从空变为非空）不视为「变化」
    if (before === null || before.size === 0) return

    const changed = new Set<string>()
    for (const [id, version] of next) {
      const oldVersion = before.get(id)
      if (oldVersion !== undefined && oldVersion !== version) {
        changed.add(id)
      }
    }

    if (changed.size === 0) return

    setHighlighted(changed)
    if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    timerRef.current = window.setTimeout(() => {
      setHighlighted(new Set())
      timerRef.current = null
    }, durationMs)

    return () => {
      // 组件卸载时清掉定时器；下一次 effect 会重新计时
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
  }, [items, durationMs])

  return highlighted
}
