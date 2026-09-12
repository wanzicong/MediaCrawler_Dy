import { useCallback, useState } from "react"

import { readJsonStorage, writeJsonStorage } from "@/lib/storage"

/**
 * 筛选预设：把常用筛选组合存下来，一键套用。
 *
 * 背景：改造前 12 个带筛选的列表全部不持久化，用户每次进来都要重设一遍
 * （「只看失败的」「只看今天的」这类高频组合尤其烦）。
 *
 * 用法：
 * ```ts
 * const { presets, savePreset, removePreset } = useFilterPresets<MyFilters>("douyin-tasks-filters")
 * // 套用：onClick={() => setFilters(preset.filters)}
 * // 保存：savePreset("仅失败", { status: "failed", trackId: "all" })
 * ```
 */

export type FilterPreset<T> = {
  id: string
  name: string
  filters: T
  createdAt: number
}

const MAX_PRESETS = 12

export function useFilterPresets<T extends Record<string, unknown>>(
  storageKey: string,
) {
  const [presets, setPresets] = useState<FilterPreset<T>[]>(() =>
    readJsonStorage<FilterPreset<T>[]>(
      storageKey,
      [],
      (value): value is FilterPreset<T>[] =>
        Array.isArray(value) &&
        value.every(
          (item) =>
            typeof item === "object" &&
            item !== null &&
            typeof (item as FilterPreset<T>).name === "string",
        ),
    ),
  )

  const commit = useCallback(
    (next: FilterPreset<T>[]) => {
      setPresets(next)
      writeJsonStorage(storageKey, next)
    },
    [storageKey],
  )

  /** 同名预设覆盖，避免存出一堆同名项。 */
  const savePreset = useCallback(
    (name: string, filters: T) => {
      setPresets((current) => {
        const trimmed = name.trim()
        if (!trimmed) return current

        const existing = current.find((item) => item.name === trimmed)
        const next = existing
          ? current.map((item) =>
              item.name === trimmed ? { ...item, filters } : item,
            )
          : [
              {
                id: `preset-${current.length}-${trimmed}`,
                name: trimmed,
                filters,
                createdAt: Date.now(),
              },
              ...current,
            ].slice(0, MAX_PRESETS)

        writeJsonStorage(storageKey, next)
        return next
      })
    },
    [storageKey],
  )

  const removePreset = useCallback(
    (id: string) => {
      setPresets((current) => {
        const next = current.filter((item) => item.id !== id)
        writeJsonStorage(storageKey, next)
        return next
      })
    },
    [storageKey],
  )

  return { presets, savePreset, removePreset, clearPresets: () => commit([]) }
}
