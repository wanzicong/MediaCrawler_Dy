import type {
  DouyinAccountPublic,
  DouyinBrowserMode,
  DouyinBrowserSlotPublic,
  DouyinCreatorPublic,
} from "@/client"

export function creatorNameLabel(
  creator: Pick<DouyinCreatorPublic, "nickname">,
) {
  return creator.nickname.trim() || "未命名达人"
}

/**
 * 账号状态的内置默认文案。
 *
 * 页面先用它渲染，再按 GET /douyin/ui-labels（config.yaml 的 ui.labels）覆盖；
 * 接口失败或缺键时保持这里的文案，页面不会因此不可用。
 */
export const DEFAULT_ACCOUNT_STATUS_LABELS: Record<
  DouyinAccountPublic["status"],
  string
> = {
  login_required: "待登录",
  verifying: "待验证",
  ready: "可用",
  busy: "执行中",
  cooldown: "冷却中",
  unhealthy: "异常",
  disabled: "已停用",
}

export function browserSlotLabel(
  slot: Pick<DouyinBrowserSlotPublic, "is_default" | "label">,
) {
  return slot.is_default ? "云端默认槽位" : slot.label
}

/** 浏览器位置的模式文案：本机浏览器 / 云端浏览器。 */
export function browserModeLabel(browserMode: DouyinBrowserMode) {
  return browserMode === "local" ? "本机浏览器" : "云端浏览器"
}

/** 账号行展示的浏览器位置：远程为槽位名或云端默认槽位，本机为槽位标签。 */
export function accountBrowserLabel(
  account: Pick<DouyinAccountPublic, "browser_mode" | "slot">,
  slots: DouyinBrowserSlotPublic[] = [],
) {
  if (account.browser_mode === "remote") {
    return account.slot || "云端默认槽位"
  }
  const matched = slots.find(
    (slot) => slot.browser_mode === "local" && slot.name === account.slot,
  )
  return matched?.label ?? (account.slot || "本机专属浏览器")
}
