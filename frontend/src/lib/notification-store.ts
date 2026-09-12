import { useSyncExternalStore } from "react"

import { readJsonStorage, writeJsonStorage } from "@/lib/storage"

/**
 * 前端通知中心的数据层。
 *
 * 背景：改造前操作结果只靠 toast 传达，而 toast 稍纵即逝 —— 错过就查不到发生过什么。
 * 这里留存最近 50 条，并持久化到 localStorage，刷新后仍在。
 *
 * 刻意做成**模块级 store 而非 React Context**：投递方是 main.tsx 里的
 * QueryCache / MutationCache 全局错误处理，那里拿不到组件树里的 context。
 * 订阅侧用 useSyncExternalStore 接入 React。
 */

export type NotificationKind = "error" | "success" | "info"

export type AppNotification = {
  id: string
  kind: NotificationKind
  title: string
  description?: string
  createdAt: number
  read: boolean
}

const STORAGE_KEY = "app-notifications"
const MAX_ITEMS = 50
/** 相同内容的重复投递合并窗口，避免接口重试时刷屏 */
const DEDUPE_WINDOW_MS = 5_000

let notifications: AppNotification[] = readJsonStorage<AppNotification[]>(
  STORAGE_KEY,
  [],
  (value): value is AppNotification[] => Array.isArray(value),
)

const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) listener()
}

function persist() {
  writeJsonStorage(STORAGE_KEY, notifications)
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** useSyncExternalStore 要求引用稳定：只有真正变更时才换新数组 */
function getSnapshot(): AppNotification[] {
  return notifications
}

let idCounter = 0

export function pushNotification(
  input: Omit<AppNotification, "id" | "createdAt" | "read">,
): void {
  const now = Date.now()

  const isDuplicate = notifications.some(
    (item) =>
      item.title === input.title &&
      item.description === input.description &&
      now - item.createdAt < DEDUPE_WINDOW_MS,
  )
  if (isDuplicate) return

  idCounter += 1
  const next: AppNotification = {
    ...input,
    id: `${now}-${idCounter}`,
    createdAt: now,
    read: false,
  }

  notifications = [next, ...notifications].slice(0, MAX_ITEMS)
  persist()
  emit()
}

export function markAllRead(): void {
  if (notifications.every((item) => item.read)) return
  notifications = notifications.map((item) => ({ ...item, read: true }))
  persist()
  emit()
}

export function markRead(id: string): void {
  let changed = false
  notifications = notifications.map((item) => {
    if (item.id !== id || item.read) return item
    changed = true
    return { ...item, read: true }
  })
  if (!changed) return
  persist()
  emit()
}

export function clearNotifications(): void {
  if (notifications.length === 0) return
  notifications = []
  persist()
  emit()
}

export function useNotifications(): AppNotification[] {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
}

export function useUnreadNotificationCount(): number {
  const items = useNotifications()
  return items.reduce((count, item) => (item.read ? count : count + 1), 0)
}
