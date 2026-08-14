import type { DouyinInteractionType } from "@/client"

const outgoingContentLabels: Record<DouyinInteractionType, string> = {
  video_comment: "我的评论",
  comment_reply: "我的回复",
  creator_message: "私信内容",
}

export function InteractionContentSummary({
  interactionType,
  targetCommentId,
  targetCommentContent,
  content,
  compact = false,
}: {
  interactionType: DouyinInteractionType
  targetCommentId?: string | null
  targetCommentContent?: string | null
  content: string
  compact?: boolean
}) {
  const isReply = interactionType === "comment_reply"
  const targetContent =
    targetCommentContent?.trim() || "原评论没有文字内容或已不在本地数据中"

  return (
    <div className={compact ? "space-y-2" : "space-y-3"}>
      {isReply && targetCommentId && (
        <blockquote className="rounded-lg border-l-2 border-primary/40 bg-muted/55 px-3 py-2">
          <p className="text-[11px] font-medium tracking-wide text-muted-foreground">
            被回复的评论
          </p>
          <p
            className={
              compact
                ? "mt-1 line-clamp-2 text-sm"
                : "mt-1 whitespace-pre-wrap break-words text-sm leading-6"
            }
            title={compact ? targetContent : undefined}
          >
            {targetContent}
          </p>
        </blockquote>
      )}
      <div>
        <p className="text-[11px] font-medium tracking-wide text-muted-foreground">
          {outgoingContentLabels[interactionType]}
        </p>
        <p
          className={
            compact
              ? "mt-1 line-clamp-2 text-sm"
              : "mt-1 whitespace-pre-wrap break-words text-sm leading-6"
          }
          title={compact ? content : undefined}
        >
          {content}
        </p>
      </div>
    </div>
  )
}
