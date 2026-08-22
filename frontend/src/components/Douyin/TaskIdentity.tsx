import type { CrawlTaskPublic } from "@/client"
import { cn } from "@/lib/utils"

export function TaskIdentity({
  task,
  showCreatedAt = false,
  className,
}: {
  task: CrawlTaskPublic
  showCreatedAt?: boolean
  className?: string
}) {
  const identity = getTaskIdentityText(task)
  return (
    <div className={cn("min-w-0", className)}>
      <p className="truncate font-medium" title={identity}>
        <span className="text-muted-foreground">
          【{getTaskTypeLabel(task)}】
        </span>
        {getTaskDisplayTitle(task)}
      </p>
      {showCreatedAt && (
        <p className="mt-1 text-xs text-muted-foreground">
          {formatTaskDate(task.created_at)}
        </p>
      )}
    </div>
  )
}

export function getTaskIdentityText(task: CrawlTaskPublic) {
  return `【${getTaskTypeLabel(task)}】${getTaskDisplayTitle(task)}`
}

function getTaskTypeLabel(task: CrawlTaskPublic) {
  if (task.crawl_type === "search") return "关键词"
  if (task.crawl_type === "detail") return "指定作品"
  if (["creator", "creator_from_aweme"].includes(task.crawl_type)) return "达人"
  if (task.crawl_type === "liked") return "点赞"
  return "收藏"
}

export function getTaskDisplayTitle(task: CrawlTaskPublic) {
  const targets = taskTargets(task)
  if (task.crawl_type === "search" && targets.length) {
    return targets[0] ?? "未命名关键词"
  }
  if (task.crawl_type === "detail") {
    const title = task.display_title?.trim()
    if (title) return title
    return "未命名作品"
  }
  if (["creator", "creator_from_aweme"].includes(task.crawl_type)) {
    const author = getTaskDisplayAuthor(task)
    if (author) return author
    const creatorName = task.creator_names?.find((name) => name.trim())?.trim()
    if (creatorName) return creatorName.replace(/^@/, "")
    return "未命名达人"
  }
  if (task.crawl_type === "liked") return "账号点赞内容"
  if (task.crawl_type === "collected") return "账号收藏内容"
  return "内容采集任务"
}

export function getTaskSearchValues(task: CrawlTaskPublic) {
  const values = [
    getTaskDisplayTitle(task),
    task.source_label ?? "",
    ...(task.source_names ?? []),
    ...taskTargets(task),
  ]
  const author = getTaskDisplayAuthor(task)
  if (author) values.push(author)
  if (task.crawl_type === "detail") {
    values.push(task.display_aweme_id ?? "")
  }
  return values
}

export function getTaskDisplayAuthor(task: CrawlTaskPublic) {
  if (!["detail", "creator", "creator_from_aweme"].includes(task.crawl_type)) {
    return null
  }
  return task.display_author?.trim().replace(/^@/, "") || null
}

export function shortTaskReference(taskId: string) {
  const compact = taskId.replace(/-/g, "")
  return `任务 #${compact.slice(-6).toUpperCase()}`
}

function taskTargets(task: CrawlTaskPublic) {
  const candidates = [
    task.request.keywords,
    task.request.video_ids,
    task.request.creator_ids,
  ]
  for (const candidate of candidates) {
    if (Array.isArray(candidate) && candidate.length > 0) {
      return candidate.map(String)
    }
  }
  return []
}

function formatTaskDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value))
}
