import { useSyncExternalStore } from "react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { cn } from "@/lib/utils"

/**
 * 承诺式确认对话框（报告 O15）。
 *
 * 背景：改造前全站有 20 处用 `window.confirm(...)` 做危险操作二次确认
 * （批量删除、删除账号、迁移、重试…）。原生弹窗的问题：
 *   - 无法定制（不能标红、不能给详情、不能加「此操作不可撤销」提示）
 *   - 不参与页面的键盘导航与焦点管理
 *   - 无法在 Playwright 里稳定断言（浏览器原生对话框要走 dialog 事件）
 *
 * 用法（和 window.confirm 一样直观，但异步）：
 * ```ts
 * const ok = await confirmDialog({
 *   title: "删除选中的 12 个任务？",
 *   description: "删除后不可恢复，已采集的数据也会一并移除。",
 *   confirmText: "删除",
 *   variant: "destructive",
 * })
 * if (!ok) return
 * ```
 *
 * 需要在应用根部挂一次 `<ConfirmDialogHost />`（已挂在 _layout.tsx）。
 * 与 notification-store 同理，用模块级 store 而非 Context —— 调用点在事件处理函数里，
 * 拿不到组件树的 context，且这样每处替换只需改一行。
 */

export type ConfirmOptions = {
  title: string
  description?: string
  confirmText?: string
  cancelText?: string
  /** destructive 会把确认按钮标红，用于删除等不可逆操作 */
  variant?: "default" | "destructive"
}

type ConfirmState = ConfirmOptions & {
  id: number
  resolve: (value: boolean) => void
}

let current: ConfirmState | null = null
const listeners = new Set<() => void>()
let idCounter = 0

function emit() {
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function getSnapshot(): ConfirmState | null {
  return current
}

/** 弹出一个确认框，返回用户是否点了确认。 */
export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  // 前一个还没关就被再次调用时，先把前一个当作取消，避免状态错乱
  current?.resolve(false)

  return new Promise<boolean>((resolve) => {
    idCounter += 1
    current = { ...options, id: idCounter, resolve }
    emit()
  })
}

function settle(value: boolean) {
  const state = current
  current = null
  emit()
  state?.resolve(value)
}

export function ConfirmDialogHost() {
  const state = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
  const open = state !== null

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) settle(false)
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{state?.title}</AlertDialogTitle>
          {state?.description && (
            <AlertDialogDescription>{state.description}</AlertDialogDescription>
          )}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => settle(false)}>
            {state?.cancelText ?? "取消"}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={() => settle(true)}
            className={cn(
              state?.variant === "destructive" &&
                "bg-destructive text-white hover:bg-destructive/90",
            )}
          >
            {state?.confirmText ?? "确认"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
