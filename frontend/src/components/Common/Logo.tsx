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
          <span className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-lg shadow-primary/20">
            <Music2 className="size-5" />
          </span>
          <span>
            <span className="block text-sm font-semibold tracking-tight">
              Douyin Ops
            </span>
            <span className="block text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              crawler studio
            </span>
          </span>
        </div>
        <span
          className={cn(
            "hidden size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground group-data-[collapsible=icon]:flex",
            className,
          )}
        >
          <Music2 className="size-5" />
        </span>
      </>
    ) : (
      <div className={cn("flex items-center gap-2 font-semibold", className)}>
        <span className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground">
          <Music2 className="size-5" />
        </span>
        {variant === "full" && <span>Douyin Ops</span>}
      </div>
    )

  if (!asLink) {
    return content
  }

  return <Link to="/">{content}</Link>
}
