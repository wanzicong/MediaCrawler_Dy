import { LayoutGrid, List, Table2 } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"

export type ListViewMode = "table" | "rows" | "cards"

export function usePersistentViewMode(storageKey: string) {
  const [viewMode, setViewMode] = useState<ListViewMode>(() => {
    const saved = localStorage.getItem(storageKey)
    return saved === "rows" || saved === "cards" ? saved : "table"
  })

  const changeViewMode = (mode: ListViewMode) => {
    setViewMode(mode)
    localStorage.setItem(storageKey, mode)
  }

  return [viewMode, changeViewMode] as const
}

export function ViewModeToggle({
  value,
  onChange,
  label = "切换列表展示方式",
  className,
}: {
  value: ListViewMode
  onChange: (mode: ListViewMode) => void
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
        variant={value === "table" ? "secondary" : "ghost"}
        className="h-8 gap-1.5 px-2.5 text-xs"
        aria-pressed={value === "table"}
        onClick={() => onChange("table")}
      >
        <Table2 className="size-4" /> 表格
      </Button>
      <Button
        type="button"
        size="sm"
        variant={value === "rows" ? "secondary" : "ghost"}
        className="h-8 gap-1.5 px-2.5 text-xs"
        aria-pressed={value === "rows"}
        onClick={() => onChange("rows")}
      >
        <List className="size-4" /> 横条
      </Button>
      <Button
        type="button"
        size="sm"
        variant={value === "cards" ? "secondary" : "ghost"}
        className="h-8 gap-1.5 px-2.5 text-xs"
        aria-pressed={value === "cards"}
        onClick={() => onChange("cards")}
      >
        <LayoutGrid className="size-4" /> 卡片
      </Button>
    </fieldset>
  )
}
