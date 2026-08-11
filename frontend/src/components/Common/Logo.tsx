import { Link } from "@tanstack/react-router"
import { Music2 } from "lucide-react"

import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const content =
    variant === "responsive" ? (
      <>
        <div
          className={cn(
            "flex items-center gap-3 group-data-[collapsible=icon]:hidden",
            className,
          )}
        >
          <span className="flex size-10 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-600 via-primary to-blue-500 text-primary-foreground shadow-lg shadow-primary/25">
            <Music2 className="size-5" />
          </span>
          <span>
            <span className="block text-sm font-semibold tracking-tight">
              灵感采集台
            </span>
            <span className="block text-[10px] tracking-[0.12em] text-muted-foreground">
              内容运营工作台
            </span>
          </span>
        </div>
        <span
          className={cn(
            "hidden size-10 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-600 via-primary to-blue-500 text-primary-foreground shadow-lg shadow-primary/20 group-data-[collapsible=icon]:flex",
            className,
          )}
        >
          <Music2 className="size-5" />
        </span>
      </>
    ) : (
      <div className={cn("flex items-center gap-2 font-semibold", className)}>
        <span className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-violet-600 via-primary to-blue-500 text-primary-foreground shadow-md shadow-primary/20">
          <Music2 className="size-5" />
        </span>
        {variant === "full" && <span>灵感采集台</span>}
      </div>
    )

  if (!asLink) {
    return content
  }

  return <Link to="/">{content}</Link>
}
