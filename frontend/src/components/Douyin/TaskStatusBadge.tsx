import type { CrawlTaskStatus } from "@/client"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

const statusConfig: Record<
  CrawlTaskStatus,
  { label: string; className: string }
> = {
  queued: {
    label: "排队中",
    className: "bg-slate-500/15 text-slate-700 dark:text-slate-300",
  },
  waiting_login: {
    label: "等待扫码",
    className: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  },
  running: {
    label: "运行中",
    className: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  },
  cancelling: {
    label: "取消中",
    className: "bg-orange-500/15 text-orange-700 dark:text-orange-300",
  },
  succeeded: {
    label: "已完成",
    className: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  },
  failed: {
    label: "失败",
    className: "bg-red-500/15 text-red-700 dark:text-red-300",
  },
  cancelled: {
    label: "已取消",
    className: "bg-zinc-500/15 text-zinc-700 dark:text-zinc-300",
  },
  interrupted: {
    label: "已中断",
    className: "bg-purple-500/15 text-purple-700 dark:text-purple-300",
  },
}

export const activeTaskStatuses: CrawlTaskStatus[] = [
  "queued",
  "waiting_login",
  "running",
  "cancelling",
]

export function TaskStatusBadge({ status }: { status: CrawlTaskStatus }) {
  const config = statusConfig[status]

  return (
    <Badge
      variant="outline"
      className={cn("border-transparent", config.className)}
    >
      {config.label}
    </Badge>
  )
}
