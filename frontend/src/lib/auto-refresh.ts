import { useSyncExternalStore } from "react"

import { readJsonStorage, writeJsonStorage } from "@/lib/storage"

/**
 * 全局「页面自动刷新」偏好。
 *
 * 背景：此前刷新节奏是写死在代码里的（各处 activeInterval 大多是 10 秒，
 * 且只在还有进行中任务时轮询）。用户既无法整体关掉自动刷新，也不能调快/调慢，
 * 长任务跑起来时只能被动接受这个节奏。
 *
 * 这里把开关与间隔收敛成一份全局偏好：所有轮询（useSmartPolling 与少量手写
 * refetchInterval）都从这里取频率；关掉后一律停轮询，只保留手动刷新。
 *
 * 与 notification-store 一样刻意用模块级 store + useSyncExternalStore：
 * 订阅方分散在各个页面与弹窗里，用 Context 需要把 Provider 串到 QueryClient
 * 之外的每一层，反而更重。
 */

export type AutoRefreshSettings = {
  /** 是否允许页面自动刷新（关闭后只有手动刷新） */
  enabled: boolean
  /** 自动刷新间隔（毫秒） */
  intervalMs: number
}

export const AUTO_REFRESH_STORAGE_KEY = "auto-refresh-settings"

/** 可选间隔：5 / 10 / 30 / 60 秒 */
export const AUTO_REFRESH_INTERVALS = [5_000, 10_000, 30_000, 60_000] as const

const MIN_INTERVAL_MS = 3_000
const MAX_INTERVAL_MS = 600_000

export const DEFAULT_AUTO_REFRESH_SETTINGS: AutoRefreshSettings = {
  enabled: true,
  intervalMs: 10_000,
}

function isAutoRefreshSettings(value: unknown): value is AutoRefreshSettings {
  if (typeof value !== "object" || value === null) return false
  const candidate = value as Partial<AutoRefreshSettings>
  return (
    typeof candidate.enabled === "boolean" &&
    typeof candidate.intervalMs === "number" &&
    Number.isFinite(candidate.intervalMs) &&
    candidate.intervalMs >= MIN_INTERVAL_MS &&
    candidate.intervalMs <= MAX_INTERVAL_MS
  )
}

function clampInterval(intervalMs: number): number {
  if (!Number.isFinite(intervalMs))
    return DEFAULT_AUTO_REFRESH_SETTINGS.intervalMs
  return Math.min(
    MAX_INTERVAL_MS,
    Math.max(MIN_INTERVAL_MS, Math.round(intervalMs)),
  )
}

let settings: AutoRefreshSettings = readJsonStorage(
  AUTO_REFRESH_STORAGE_KEY,
  DEFAULT_AUTO_REFRESH_SETTINGS,
  isAutoRefreshSettings,
)

const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** useSyncExternalStore 要求引用稳定：只有真正变更时才换新对象 */
function getSnapshot(): AutoRefreshSettings {
  return settings
}

/** 多标签页同步：另一个标签改了偏好，这个标签的轮询节奏也跟着变 */
if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key !== AUTO_REFRESH_STORAGE_KEY) return
    settings = readJsonStorage(
      AUTO_REFRESH_STORAGE_KEY,
      DEFAULT_AUTO_REFRESH_SETTINGS,
      isAutoRefreshSettings,
    )
    emit()
  })
}

/** 更新偏好（可只改一部分），并同步到 localStorage 与所有订阅方。 */
export function setAutoRefreshSettings(
  patch: Partial<AutoRefreshSettings>,
): AutoRefreshSettings {
  const next: AutoRefreshSettings = {
    enabled: patch.enabled ?? settings.enabled,
    intervalMs:
      patch.intervalMs === undefined
        ? settings.intervalMs
        : clampInterval(patch.intervalMs),
  }
  if (
    next.enabled === settings.enabled &&
    next.intervalMs === settings.intervalMs
  ) {
    return settings
  }
  settings = next
  writeJsonStorage(AUTO_REFRESH_STORAGE_KEY, next)
  emit()
  return next
}

/** 读取当前偏好（组件内使用；变更会触发重渲染）。 */
export function useAutoRefreshSettings(): AutoRefreshSettings {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
}

/**
 * 轮询用的间隔：关闭自动刷新时返回 false，调用方直接把它当 refetchInterval 用。
 */
export function useAutoRefreshInterval(): number | false {
  const { enabled, intervalMs } = useAutoRefreshSettings()
  return enabled ? intervalMs : false
}

/** 把毫秒间隔显示成「10 秒」。 */
export function formatAutoRefreshInterval(intervalMs: number): string {
  const seconds = intervalMs / 1_000
  return Number.isInteger(seconds)
    ? `${seconds} 秒`
    : `${seconds.toFixed(1)} 秒`
}
