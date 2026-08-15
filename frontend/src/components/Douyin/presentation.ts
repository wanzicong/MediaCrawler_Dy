import type { DouyinBrowserSlotPublic } from "@/client"

export function browserSlotLabel(
  slot: Pick<DouyinBrowserSlotPublic, "is_default" | "label">,
) {
  return slot.is_default ? "云端默认槽位" : slot.label
}
