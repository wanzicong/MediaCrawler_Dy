import type { LucideIcon } from "lucide-react"
import { Fragment, type ReactNode } from "react"

import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu"

/**
 * 行右键菜单（报告 A7）。
 *
 * 背景：资源库/评论/互动/作品面板的操作列挤了 5–6 个按钮，窄屏靠横向滚动才够用。
 * 右键菜单把低频操作（复制 ID、打开抖音页、重试、删除）挪出去，操作列只留 1–2 个高频项。
 * 同时它天然解决了「操作列冻结」之后仍然很宽的问题。
 *
 * 用法（直接包住 `<TableRow>`，Radix 的 asChild 会把触发挂到这一行上）：
 * ```tsx
 * <RowContextMenu
 *   label={item.title}
 *   items={[
 *     { label: "复制作品 ID", icon: Copy, onSelect: () => copy(item.aweme_id) },
 *     { label: "打开抖音页", icon: ExternalLink, onSelect: () => window.open(url, "_blank", "noopener,noreferrer") },
 *     { separatorBefore: true, label: "重试", icon: RotateCcw, onSelect: retry },
 *     { separatorBefore: true, label: "删除", icon: Trash2, destructive: true, onSelect: remove },
 *   ]}
 * >
 *   <TableRow>…</TableRow>
 * </RowContextMenu>
 * ```
 */
export type RowMenuItem = {
  label: string
  onSelect: () => void
  icon?: LucideIcon
  /** 标红，用于删除等不可逆操作 */
  destructive?: boolean
  disabled?: boolean
  /** 在这一项之前插入分隔线，用于把操作分组 */
  separatorBefore?: boolean
}

export function RowContextMenu({
  items,
  children,
  label,
}: {
  items: RowMenuItem[]
  /** 必须是一个能接受 ref 的元素，通常是 <TableRow> 或 <div> */
  children: ReactNode
  /** 菜单顶部的说明文字（一般放行标题 / ID） */
  label?: string
}) {
  const visible = items.filter(Boolean)
  if (visible.length === 0) return <>{children}</>

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent className="w-48">
        {label && (
          <>
            <ContextMenuLabel className="truncate">{label}</ContextMenuLabel>
            <ContextMenuSeparator />
          </>
        )}
        {visible.map((item, index) => (
          // 用 Fragment 而不是 div 包一层：Radix 菜单要求 MenuItem / Separator
          // 是 Content 的直接子元素，套一层容器会破坏方向键导航（报告 H16 同类问题）。
          <Fragment key={`${item.label}-${index}`}>
            {item.separatorBefore && index > 0 && <ContextMenuSeparator />}
            <ContextMenuItem
              disabled={item.disabled}
              variant={item.destructive ? "destructive" : "default"}
              onSelect={() => item.onSelect()}
            >
              {item.icon && <item.icon />}
              {item.label}
            </ContextMenuItem>
          </Fragment>
        ))}
      </ContextMenuContent>
    </ContextMenu>
  )
}
