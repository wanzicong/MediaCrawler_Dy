import type { DouyinBrowserSlotPublic, DouyinCreatorPublic } from "@/client"

export function creatorNameLabel(
  creator: Pick<DouyinCreatorPublic, "nickname">,
) {
  return creator.nickname.trim() || "未命名达人"
}

export function browserSlotLabel(
  slot: Pick<DouyinBrowserSlotPublic, "is_default" | "label">,
) {
  return slot.is_default ? "云端默认槽位" : slot.label
}
