import { AlertTriangle, RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export function QueryErrorState({
  title,
  description,
  onRetry,
  retrying = false,
  className,
}: {
  title: string
  description: string
  onRetry: () => void
  retrying?: boolean
  className?: string
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-2xl border border-destructive/25 bg-destructive/5 px-5 py-10 text-center",
        className,
      )}
    >
      <span className="flex size-10 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
        <AlertTriangle className="size-5" />
      </span>
      <div>
        <p className="font-medium text-foreground">{title}</p>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={retrying}
        onClick={onRetry}
      >
        <RefreshCw className={cn(retrying && "animate-spin")} />
        {retrying ? "正在重试…" : "重试"}
      </Button>
    </div>
  )
}
