import type { DouyinInteractionPublic, DouyinInteractionStatus } from "@/client"
import { Badge } from "@/components/ui/badge"

const labels: Record<DouyinInteractionStatus, string> = {
  pending_confirmation: "待确认",
  queued: "排队中",
  running: "发送中",
  succeeded: "已成功",
  failed: "失败",
  blocked: "已暂停",
  needs_review: "待人工核对",
  cancelled: "已取消",
}

export function InteractionStatusBadge({
  status,
}: {
  status: DouyinInteractionStatus
}) {
  const variant =
    status === "failed" || status === "blocked"
      ? "destructive"
      : status === "succeeded"
        ? "default"
        : "outline"
  return <Badge variant={variant}>{labels[status]}</Badge>
}

export const interactionTypeLabels = {
  video_comment: "视频评论",
  comment_reply: "评论回复",
  creator_message: "作者私信",
} as const

export function isInteractionRetryCandidateStatus(
  status: DouyinInteractionStatus,
) {
  return status !== "running" && status !== "succeeded"
}

export function canShowInteractionRetry(
  interaction: Pick<DouyinInteractionPublic, "can_retry" | "status">,
) {
  return (
    interaction.can_retry &&
    isInteractionRetryCandidateStatus(interaction.status)
  )
}
