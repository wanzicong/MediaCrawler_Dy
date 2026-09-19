import { Infinity as InfinityIcon, Layers } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { readEnumStorage, writeStorage } from "@/lib/storage"

/**
 * 列表加载方式：滚动加载（默认）或分页。
 *
 * 背景：作品列表原先只有「翻页」一种形态，翻到第 5 页还要点回溯；
 * 现在默认改成滚到底自动续拉，同时保留分页给需要「跳到第 N 页 / 每页条数」的场景。
 * 与视图模式一样按列表分别持久化，刷新后保持用户的选择。
 */
export type ListLoadMode = "scroll" | "paged"

export const LIST_LOAD_MODES = ["scroll", "paged"] as const

export function usePersistentLoadMode(storageKey: string) {
  const [mode, setMode] = useState<ListLoadMode>(() =>
    readEnumStorage<ListLoadMode>(storageKey, LIST_LOAD_MODES, "scroll"),
  )
  const changeMode = (next: ListLoadMode) => {
    setMode(next)
    writeStorage(storageKey, next)
  }
  return [mode, changeMode] as const
}

export function LoadModeToggle({
  value,
  onChange,
  label = "切换列表加载方式",
  className,
}: {
  value: ListLoadMode
  onChange: (mode: ListLoadMode) => void
  label?: string
  className?: string
}) {
  return (
    <fieldset
      className={`m-0 flex shrink-0 items-center rounded-lg border bg-background p-0.5 ${className ?? ""}`}
    >
      <legend className="sr-only">{label}</legend>
      <Button
        type="button"
        size="sm"
        variant={value === "scroll" ? "secondary" : "ghost"}
        className="h-8 gap-1.5 px-2.5 text-xs"
        aria-pressed={value === "scroll"}
        onClick={() => onChange("scroll")}
      >
        <InfinityIcon className="size-4" /> 滚动加载
      </Button>
      <Button
        type="button"
        size="sm"
        variant={value === "paged" ? "secondary" : "ghost"}
        className="h-8 gap-1.5 px-2.5 text-xs"
        aria-pressed={value === "paged"}
        onClick={() => onChange("paged")}
      >
        <Layers className="size-4" /> 分页
      </Button>
    </fieldset>
  )
}
