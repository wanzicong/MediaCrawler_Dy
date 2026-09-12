import { Bookmark, Plus, Trash2 } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { type FilterPreset, useFilterPresets } from "@/hooks/useFilterPresets"
import { cn } from "@/lib/utils"

/**
 * 筛选预设条（报告 A10 / CF4）。
 *
 * 背景：改造前 12 个带筛选的列表全部不持久化，用户每次进来都要重设一遍
 * 「只看失败的」「只看今天的」这类高频组合。
 *
 * 用法（自包含，只需要三个东西）：
 * ```tsx
 * <FilterPresetBar
 *   storageKey="douyin-tasks-filter-presets"
 *   currentFilters={{ status: statusFilter, trackId, sourceValue }}
 *   onApply={(f) => { setStatusFilter(f.status); setTrackId(f.trackId); ... }}
 * />
 * ```
 */
export function FilterPresetBar<T extends Record<string, unknown>>({
  storageKey,
  currentFilters,
  onApply,
  label = "筛选预设",
  className,
}: {
  storageKey: string
  /** 当前筛选状态；点「存为预设」时会被原样保存 */
  currentFilters: T
  onApply: (filters: T) => void
  label?: string
  className?: string
}) {
  const { presets, savePreset, removePreset } = useFilterPresets<T>(storageKey)
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")

  const handleSave = () => {
    const trimmed = name.trim()
    if (!trimmed) return
    savePreset(trimmed, currentFilters)
    setName("")
    setOpen(false)
  }

  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
      <span className="flex items-center gap-1 text-xs text-muted-foreground">
        <Bookmark className="size-3" />
        {label}
      </span>

      {presets.length === 0 && (
        <span className="text-xs text-muted-foreground/70">
          暂无，可把当前筛选存下来复用
        </span>
      )}

      {presets.map((preset: FilterPreset<T>) => (
        <span
          key={preset.id}
          className="group inline-flex items-center overflow-hidden rounded-full border bg-muted/40"
        >
          <button
            type="button"
            className="px-2.5 py-1 text-xs font-medium transition-colors hover:bg-muted"
            onClick={() => onApply(preset.filters)}
          >
            {preset.name}
          </button>
          <button
            type="button"
            aria-label={`删除预设 ${preset.name}`}
            className="px-1.5 py-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
            onClick={() => removePreset(preset.id)}
          >
            <Trash2 className="size-3" />
          </button>
        </span>
      ))}

      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-7 gap-1 px-2 text-xs text-muted-foreground"
        onClick={() => setOpen(true)}
      >
        <Plus className="size-3" />
        存为预设
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>保存筛选预设</DialogTitle>
            <DialogDescription>
              当前筛选条件会被保存到本地，下次一键套用。
            </DialogDescription>
          </DialogHeader>
          <Input
            autoFocus
            value={name}
            aria-label="预设名称"
            placeholder="例如：仅失败、仅今日"
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault()
                handleSave()
              }
            }}
          />
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
            >
              取消
            </Button>
            <Button type="button" disabled={!name.trim()} onClick={handleSave}>
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
