import { useVirtualizer, type VirtualItem } from "@tanstack/react-virtual"
import type { RefObject } from "react"

/**
 * 长列表虚拟滚动（报告 O19）。
 *
 * 背景：全站列表都没有虚拟滚动，DOM 里一次性铺满全部行。
 * 目前 pageSize 多为 50/100 还撑得住，但有几处是**单页无上限**的：
 * 达人列表（一次 200 位，且是卡片网格）、互动详情的事件列表、监控的执行步骤。
 *
 * ⚠️ 关于返回值：@tanstack/react-virtual 的 `useVirtualizer` 返回的是**方法**
 * （`getVirtualItems()` / `getTotalSize()`），不是属性。这里把它们解包成
 * 普通的 `virtualItems` / `totalSize` 字段，调用方写起来更直观，也不容易记错。
 *
 * 用法（表格）——用上下两条占位行撑出滚动高度，中间只渲染可视区：
 * ```tsx
 * const scrollRef = useRef<HTMLDivElement>(null)
 * const { virtualItems, totalSize } = useVirtualRows({
 *   count: rows.length,
 *   scrollRef,
 *   estimateSize: 56,
 *   enabled: rows.length > VIRTUALIZE_THRESHOLD,
 * })
 * const paddingTop = virtualItems.length ? virtualItems[0].start : 0
 * const paddingBottom = virtualItems.length
 *   ? totalSize - virtualItems[virtualItems.length - 1].end
 *   : 0
 *
 * <div ref={scrollRef} className="max-h-[70vh] overflow-auto">
 *   <TableBody>
 *     <tr style={{ height: paddingTop }} />
 *     {virtualItems.map((item) => renderRow(rows[item.index], item.index))}
 *     <tr style={{ height: paddingBottom }} />
 *   </TableBody>
 * </div>
 * ```
 *
 * 卡片 / 网格用法（用 transform 定位）：
 * ```tsx
 * <div ref={scrollRef} className="max-h-[70vh] overflow-auto">
 *   <div style={{ height: totalSize, position: "relative" }}>
 *     {virtualItems.map((item) => (
 *       <div
 *         key={rows[item.index].id}
 *         ref={measureElement}
 *         data-index={item.index}
 *         style={{
 *           position: "absolute",
 *           top: 0,
 *           left: 0,
 *           width: "100%",
 *           transform: `translateY(${item.start}px)`,
 *         }}
 *       >
 *         {renderCard(rows[item.index])}
 *       </div>
 *     ))}
 *   </div>
 * </div>
 * ```
 *
 * 注意：
 * - 只在 `enabled` 为 true（通常 = 数量超过阈值）时才启用；短列表必须走原路径，零行为变化。
 * - `estimateSize` 给一个接近真实行高的值，否则滚动条会跳；卡片高度不固定时用
 *   `data-index` + `ref={measureElement}` 让库动态测量。
 * - 行的 key 必须用数据 id（不要用 index），否则滚动时 React 会复用错行。
 */
export function useVirtualRows({
  count,
  scrollRef,
  estimateSize = 56,
  overscan = 10,
  enabled = true,
}: {
  count: number
  /** 滚动容器（表格场景就是包住 <Table> 的那个 overflow 容器） */
  scrollRef: RefObject<HTMLElement | null>
  /** 估算行高，尽量接近真实值 */
  estimateSize?: number
  /** 可视区外上下各多渲染几项，减少滚动白屏 */
  overscan?: number
  enabled?: boolean
}): {
  virtualItems: VirtualItem[]
  totalSize: number
  measureElement: (node: Element | null) => void
} {
  const virtualizer = useVirtualizer({
    count,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => estimateSize,
    overscan,
    enabled,
  })

  return {
    virtualItems: virtualizer.getVirtualItems(),
    totalSize: virtualizer.getTotalSize(),
    measureElement: virtualizer.measureElement,
  }
}

/** 数量超过这个阈值才值得开虚拟滚动 */
export const VIRTUALIZE_THRESHOLD = 80
