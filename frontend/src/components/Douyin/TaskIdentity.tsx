import type { CrawlTaskPublic } from "@/client"
import { cn } from "@/lib/utils"

const crawlTypeLabels: Record<CrawlTaskPublic["crawl_type"], string> = {
  search: "关键词搜索",
  detail: "指定作品",
  creator: "创作者作品",
  creator_from_aweme: "视频作者作品",
  liked: "账号点赞",
  collected: "账号收藏",
}

export function TaskIdentity({
  task,
  showCreatedAt = false,
  className,
}: {
  task: CrawlTaskPublic
  showCreatedAt?: boolean
  className?: string
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <p className="truncate font-medium" title={getTaskDisplayTitle(task)}>
        {getTaskDisplayTitle(task)}
      </p>
      <p className="mt-1 truncate text-xs text-muted-foreground">
        {getTaskDisplayMeta(task, showCreatedAt)}
      </p>
    </div>
  )
}

export function getTaskDisplayTitle(task: CrawlTaskPublic) {
  const targets = taskTargets(task)
  if (task.crawl_type === "search" && targets.length) {
    return targets.join("、")
  }
  if (task.crawl_type === "detail") {
    const title = task.display_title?.trim()
    if (title) return title
    return `指定作品 · ${Math.max(targets.length, task.aweme_count, 1)} 条`
  }
  if (task.crawl_type === "creator") return "创作者作品采集"
  if (task.crawl_type === "creator_from_aweme") return "视频作者作品采集"
  if (task.crawl_type === "liked") return "账号点赞内容"
  if (task.crawl_type === "collected") return "账号收藏内容"
  return "内容采集任务"
}

export function getTaskDisplayMeta(
  task: CrawlTaskPublic,
  showCreatedAt = false,
) {
  const parts = [crawlTypeLabels[task.crawl_type]]
  const author = getTaskDisplayAuthor(task)
  if (author) parts.push(`@${author}`)
  if (showCreatedAt) parts.push(formatTaskDate(task.created_at))
  parts.push(shortTaskReference(task.id))
  return parts.join(" · ")
}

export function getTaskSearchValues(task: CrawlTaskPublic) {
  const values = [getTaskDisplayTitle(task), ...taskTargets(task)]
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
