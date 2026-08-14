import { Link } from "@tanstack/react-router"
import { useId } from "react"

import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

function BrandMark({ className }: { className?: string }) {
  const instanceId = useId().replace(/:/g, "")
  const surfaceId = `brand-surface-${instanceId}`
  const nodeId = `brand-node-${instanceId}`

  return (
    <svg
      viewBox="0 0 64 64"
      aria-hidden="true"
      className={cn("shrink-0", className)}
    >
      <defs>
        <linearGradient
          id={surfaceId}
          x1="9"
          y1="7"
          x2="56"
          y2="58"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#8B5CF6" />
          <stop offset="0.52" stopColor="#6D28D9" />
          <stop offset="1" stopColor="#2563EB" />
        </linearGradient>
        <linearGradient
          id={nodeId}
          x1="42"
          y1="42"
          x2="52"
          y2="52"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#A5F3FC" />
          <stop offset="1" stopColor="#22D3EE" />
        </linearGradient>
      </defs>
      <rect
        x="2"
        y="2"
        width="60"
        height="60"
        rx="18"
        fill={`url(#${surfaceId})`}
      />
      <path
        d="M42.5 17.5a19 19 0 1 0 4.8 27.4"
        fill="none"
        stroke="white"
        strokeWidth="5"
        strokeLinecap="round"
      />
      <path d="M27 21.5 45 32 27 42.5Z" fill="white" />
      <circle
        cx="47.5"
        cy="46.5"
        r="4.5"
        fill={`url(#${nodeId})`}
        stroke="white"
        strokeWidth="2"
      />
    </svg>
  )
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
          <BrandMark className="size-10 drop-shadow-[0_8px_14px_oklch(0.5_0.24_285/0.28)]" />
          <span>
            <span className="block text-sm font-semibold tracking-tight">
              灵感采集台
            </span>
            <span className="block text-[10px] tracking-[0.12em] text-muted-foreground">
              内容运营工作台
            </span>
          </span>
        </div>
        <BrandMark
          className={cn(
            "hidden size-10 drop-shadow-[0_8px_14px_oklch(0.5_0.24_285/0.24)] group-data-[collapsible=icon]:block",
            className,
          )}
        />
      </>
    ) : (
      <div className={cn("flex items-center gap-2 font-semibold", className)}>
        <BrandMark className="size-9 drop-shadow-[0_6px_10px_oklch(0.5_0.24_285/0.24)]" />
        {variant === "full" && <span>灵感采集台</span>}
      </div>
    )

  if (!asLink) {
    return content
  }

  return (
    <Link to="/" aria-label={variant === "full" ? undefined : "灵感采集台首页"}>
      {content}
    </Link>
  )
}
