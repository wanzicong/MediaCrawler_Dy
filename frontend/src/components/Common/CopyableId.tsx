import { Check, Copy } from "lucide-react"

import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import { cn } from "@/lib/utils"

/**
 * 可点击复制的 ID。
 *
 * 背景：任务 ID / 作品 ID / 评论 ID 都是 UUID，表格里全量显示会挤爆列宽，
 * 截断后又没法取到完整值。这里做「截断显示 + 悬停看全文 + 点击复制」。
 */
export function CopyableId({
  value,
  label = "ID",
  head = 8,
  tail = 4,
  className,
}: {
  value: string
  /** 无障碍标签与提示文案里的名称，如「任务 ID」 */
  label?: string
  /** 保留的头部字符数 */
  head?: number
  /** 保留的尾部字符数 */
  tail?: number
  className?: string
}) {
  const [copiedText, copy] = useCopyToClipboard()
  const copied = copiedText === value

  const isShort = value.length <= head + tail + 1
  const display = isShort
    ? value
    : `${value.slice(0, head)}…${value.slice(-tail)}`

  return (
    <button
      type="button"
      title={value}
      aria-label={`复制${label}：${value}`}
      onClick={() => void copy(value)}
      className={cn(
        "group inline-flex max-w-full items-center gap-1 rounded px-1 py-0.5 font-mono text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        className,
      )}
    >
      <span className="truncate">{display}</span>
      {copied ? (
        <Check className="size-3 shrink-0 text-emerald-500" />
      ) : (
        <Copy className="size-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-60" />
      )}
    </button>
  )
}
