import { Layers, Rows3 } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { readEnumStorage, writeStorage } from "@/lib/storage"

/**
 * 「聚合 / 逐条」这套展示口径，任务列表与赛道详情共用。
 *
 * 聚合口径：同一批目标内容（关键词 / 作品 / 达人）的多次运行合并成一行，
 * 行内给出运行次数与数据合计；需要看每次运行时再展开。
 */

export type TaskGroupMode = "task" | "group"

export const TASK_GROUP_MODES = ["task", "group"] as const

export function usePersistentGroupMode(storageKey: string) {
  const [mode, setMode] = useState<TaskGroupMode>(() =>
    readEnumStorage<TaskGroupMode>(storageKey, TASK_GROUP_MODES, "group"),
  )
  const changeMode = (next: TaskGroupMode) => {
    setMode(next)
    writeStorage(storageKey, next)
  }
  return [mode, changeMode] as const
}

/** 逐条 / 聚合 切换（与 ViewModeToggle 同款外观） */
export function TaskGroupToggle({
  value,
  onChange,
  label = "切换任务列表聚合方式",
}: {
  value: TaskGroupMode
  onChange: (mode: TaskGroupMode) => void
  label?: string
}) {
  return (
    <fieldset className="m-0 flex shrink-0 items-center rounded-lg border bg-background p-0.5">
      <legend className="sr-only">{label}</legend>
      <Button
        type="button"
        size="sm"
        variant={value === "group" ? "secondary" : "ghost"}
        className="h-8 gap-1.5 px-2.5 text-xs"
        aria-pressed={value === "group"}
        onClick={() => onChange("group")}
      >
        <Layers className="size-4" /> 聚合
      </Button>
      <Button
        type="button"
        size="sm"
        variant={value === "task" ? "secondary" : "ghost"}
        className="h-8 gap-1.5 px-2.5 text-xs"
        aria-pressed={value === "task"}
        onClick={() => onChange("task")}
      >
        <Rows3 className="size-4" /> 逐条
      </Button>
    </fieldset>
  )
}
