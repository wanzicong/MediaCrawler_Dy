import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

type Tone = "violet" | "blue" | "mint" | "coral" | "rose" | "slate"

const toneStyles: Record<Tone, { icon: string; glow: string }> = {
  violet: {
    icon: "bg-violet-500/12 text-violet-700 dark:text-violet-300",
    glow: "from-violet-500/16 via-violet-400/5 to-transparent",
  },
  blue: {
    icon: "bg-blue-500/12 text-blue-700 dark:text-blue-300",
    glow: "from-blue-500/16 via-sky-400/5 to-transparent",
  },
  mint: {
    icon: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300",
    glow: "from-emerald-500/16 via-teal-400/5 to-transparent",
  },
  coral: {
    icon: "bg-orange-500/12 text-orange-700 dark:text-orange-300",
    glow: "from-orange-500/16 via-amber-400/5 to-transparent",
  },
  rose: {
    icon: "bg-rose-500/12 text-rose-700 dark:text-rose-300",
    glow: "from-rose-500/16 via-pink-400/5 to-transparent",
  },
  slate: {
    icon: "bg-slate-500/10 text-slate-700 dark:text-slate-300",
    glow: "from-slate-500/12 via-slate-400/5 to-transparent",
  },
}

export function PageHero({
  eyebrow,
  icon: Icon,
  title,
  actions,
  children,
  compact = false,
  className,
}: {
  eyebrow?: string
  icon?: LucideIcon
  title: string
  description?: string
  actions?: ReactNode
  children?: ReactNode
  compact?: boolean
  className?: string
}) {
  return (
    <section className={cn("page-hero", compact && "p-3 sm:p-3", className)}>
      {!compact && (
        <>
          <div className="page-hero-glow page-hero-glow-primary" />
          <div className="page-hero-glow page-hero-glow-secondary" />
        </>
      )}
      <div
        className={cn(
          "relative flex flex-col gap-3 xl:flex-row xl:justify-between",
          compact ? "xl:items-center" : "xl:items-start",
        )}
      >
        <div className="min-w-0 max-w-3xl">
          {eyebrow && (
            <p className="eyebrow">
              {Icon && <Icon className="size-4" />}
              {eyebrow}
            </p>
          )}
          <h1
            className={cn(
              "font-semibold tracking-[-0.03em] text-balance",
              compact ? "text-lg" : "mt-1 text-xl sm:text-2xl",
            )}
          >
            {title}
          </h1>
        </div>
        {actions && (
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {actions}
          </div>
        )}
      </div>
      {children && (
        <div className={cn("relative", compact ? "mt-2" : "mt-4")}>
          {children}
        </div>
      )}
    </section>
  )
}

export function MetricCard({
  icon: Icon,
  label,
  value,
  detail,
  tone = "violet",
  compact = false,
}: {
  icon: LucideIcon
  label: string
  value: ReactNode
  detail?: ReactNode
  tone?: Tone
  compact?: boolean
}) {
  const styles = toneStyles[tone]
  return (
    <div
      className={cn(
        "group relative min-w-0 overflow-hidden rounded-2xl border bg-card shadow-[0_12px_32px_-24px_oklch(0.45_0.16_285/0.45)] transition duration-200 hover:-translate-y-0.5 hover:border-primary/25 hover:shadow-[0_18px_40px_-24px_oklch(0.45_0.16_285/0.5)] motion-reduce:transform-none",
        compact ? "p-3" : "p-4",
      )}
    >
      <div
        className={cn(
          "pointer-events-none absolute inset-x-0 top-0 h-20 bg-gradient-to-br opacity-80",
          styles.glow,
        )}
      />
      <div className="relative flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium tracking-wide text-muted-foreground">
            {label}
          </p>
          <div
            className={cn(
              "mt-1 font-semibold tracking-[-0.035em] text-foreground",
              compact ? "text-xl" : "text-2xl",
            )}
          >
            {value}
          </div>
          {detail && (
            <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
          )}
        </div>
        <span
          className={cn(
            "flex shrink-0 items-center justify-center rounded-2xl ring-1 ring-white/60 transition duration-200 group-hover:scale-105 motion-reduce:transform-none dark:ring-white/10",
            compact ? "size-9" : "size-10",
            styles.icon,
          )}
        >
          <Icon className="size-5" />
        </span>
      </div>
    </div>
  )
}

export function SectionHeading({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h2 className="text-lg font-semibold tracking-tight sm:text-xl">
          {title}
        </h2>
        {description && (
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            {description}
          </p>
        )}
      </div>
      {action}
    </div>
  )
}

export function FilterPanel({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return <div className={cn("filter-panel", className)}>{children}</div>
}
