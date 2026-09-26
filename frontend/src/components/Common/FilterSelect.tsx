import type { LucideIcon } from "lucide-react"
import { Search } from "lucide-react"
import { type ReactNode, useMemo, useState } from "react"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from "@/components/ui/select"
import { cn } from "@/lib/utils"

export type FilterSelectOption = {
  value: string
  label: string
  /** 选项行内的图标（例如来源类型） */
  icon?: ReactNode
}

/** 超过这个数量就启用下拉内搜索（否则一次性渲染几千个选项会卡住主线程） */
const SEARCH_THRESHOLD = 12
/** 单次最多渲染的选项数：剩下的靠搜索缩小范围 */
const MAX_VISIBLE_OPTIONS = 60

/**
 * 高效的筛选下拉。
 *
 * 背景：Radix 的 `SelectContent` 只在展开时挂载，但**父组件每次渲染都会先创建
 * 全部选项元素**（JSX children 是急切求值的）。资源库/评论/互动这些页面把
 * 2000+ 个来源、500 个标签、100 个任务分别塞进下拉里，于是每渲染一次就要创建
 * 约 3000 个 SelectItem（含图标与徽标），点击导航时主线程被卡住数秒。
 *
 * 这里做三件事：
 * 1. **展开才创建选项**：未展开时只渲染触发按钮；触发的文案由本组件自己按
 *    `options` 查表渲染，因此不依赖 Radix 的选项注册，收起状态显示依旧准确。
 * 2. **大目录启用下拉内搜索**：选项数超过阈值时给出搜索框，只渲染命中的前
 *    60 项，并提示还有多少项被折叠。
 * 3. 触发按钮与选项外观沿用 ui/select 的样式，行为与原来的 Radix 下拉一致。
 */
export function FilterSelect({
  value,
  onValueChange,
  options,
  ariaLabel,
  placeholder = "全部",
  className,
  disabled,
  leadingIcon: LeadingIcon,
  searchPlaceholder = "输入关键字筛选",
  emptyText = "没有匹配的选项",
  maxVisible = MAX_VISIBLE_OPTIONS,
  searchThreshold = SEARCH_THRESHOLD,
}: {
  value: string
  onValueChange: (value: string) => void
  options: readonly FilterSelectOption[]
  ariaLabel: string
  placeholder?: string
  className?: string
  disabled?: boolean
  /** 触发按钮左侧的固定图标 */
  leadingIcon?: LucideIcon
  searchPlaceholder?: string
  /** 搜索无命中时的提示文案 */
  emptyText?: string
  maxVisible?: number
  /** 超过多少个选项就启用下拉内搜索 */
  searchThreshold?: number
}) {
  const [open, setOpen] = useState(false)
  const [term, setTerm] = useState("")

  const searchable = options.length > searchThreshold
  const selected = useMemo(
    () => options.find((option) => option.value === value),
    [options, value],
  )
  const matched = useMemo(() => {
    const keyword = term.trim().toLowerCase()
    if (!searchable || !keyword) return options
    return options.filter((option) =>
      option.label.toLowerCase().includes(keyword),
    )
  }, [options, searchable, term])
  const visible = matched.slice(0, maxVisible)
  const hiddenCount = matched.length - visible.length

  return (
    <Select
      value={value}
      onValueChange={onValueChange}
      disabled={disabled}
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) setTerm("")
      }}
    >
      <SelectTrigger className={className} aria-label={ariaLabel}>
        {LeadingIcon && <LeadingIcon aria-hidden="true" />}
        {selected ? (
          <span data-slot="select-value" className="truncate">
            {selected.label}
          </span>
        ) : (
          <span
            data-slot="select-value"
            data-placeholder=""
            className="truncate text-muted-foreground"
          >
            {placeholder}
          </span>
        )}
      </SelectTrigger>
      <SelectContent
        className={cn(
          "max-h-80",
          // 带搜索框时让视口按内容撑开，否则固定高度会把搜索框挤成一条
          searchable && "[&_[data-radix-select-viewport]]:h-auto",
        )}
      >
        {open && (
          <>
            {searchable && (
              <div className="sticky top-0 z-10 -m-1 mb-1 bg-popover p-1">
                <div className="relative">
                  <Search
                    aria-hidden="true"
                    className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground"
                  />
                  <Input
                    value={term}
                    aria-label={`${ariaLabel}：搜索选项`}
                    placeholder={searchPlaceholder}
                    className="h-8 pl-7 text-xs"
                    onChange={(event) => setTerm(event.target.value)}
                    // Radix 会接管下拉内的按键做首字母跳转，这里放行给搜索框
                    onKeyDown={(event) => event.stopPropagation()}
                  />
                </div>
              </div>
            )}
            {visible.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.icon}
                {option.label}
              </SelectItem>
            ))}
            {hiddenCount > 0 && (
              <p className="px-2 py-1.5 text-xs text-muted-foreground">
                还有 {hiddenCount} 项，继续输入可缩小范围
              </p>
            )}
            {searchable && matched.length === 0 && (
              <p className="px-2 py-1.5 text-xs text-muted-foreground">
                {emptyText}
              </p>
            )}
          </>
        )}
      </SelectContent>
    </Select>
  )
}
