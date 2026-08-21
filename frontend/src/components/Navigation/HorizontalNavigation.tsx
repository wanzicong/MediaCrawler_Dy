import { Link as RouterLink, useRouterState } from "@tanstack/react-router"

import useAuth from "@/hooks/useAuth"
import { cn } from "@/lib/utils"
import {
  findActiveNavigation,
  getNavigationModules,
  isNavigationItemActive,
} from "./navigation"

export function HorizontalNavigation() {
  const { user } = useAuth()
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })
  const modules = getNavigationModules(Boolean(user?.is_superuser))
  const activeNavigation = findActiveNavigation(
    pathname,
    Boolean(user?.is_superuser),
  )

  return (
    <nav
      aria-label="横向导航"
      data-testid="horizontal-navigation"
      className="shrink-0 border-b border-border/60 bg-background/95 shadow-[0_8px_24px_-24px_rgb(15_23_42/0.45)] backdrop-blur-xl"
    >
      <div className="overflow-x-auto px-3 py-1.5 [scrollbar-width:none] md:px-4 [&::-webkit-scrollbar]:hidden">
        <div className="flex min-w-max items-center gap-1 rounded-xl bg-muted/55 p-1">
          {modules.map((module) => {
            const active = activeNavigation?.module.id === module.id
            const destination = module.items[0]?.path ?? "/"

            return (
              <RouterLink
                key={module.id}
                to={destination}
                data-testid={`horizontal-module-${module.id}`}
                data-active={active || undefined}
                className={cn(
                  "flex min-h-9 items-center rounded-lg px-3 text-sm font-medium text-muted-foreground outline-none transition-colors hover:bg-background/80 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/60 motion-reduce:transition-none",
                  active &&
                    "bg-background text-primary shadow-sm ring-1 ring-border/60",
                )}
              >
                {module.topLabel}
              </RouterLink>
            )
          })}
        </div>
      </div>

      {activeNavigation && (
        <div className="overflow-x-auto border-t border-border/45 px-3 py-1.5 [scrollbar-width:none] md:px-4 [&::-webkit-scrollbar]:hidden">
          <div className="flex min-w-max items-center gap-1">
            {activeNavigation.module.items.map((item) => {
              const active = isNavigationItemActive(pathname, item.path)

              return (
                <RouterLink
                  key={item.path}
                  to={item.path}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex min-h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/60 motion-reduce:transition-none",
                    active && "bg-primary/10 text-primary",
                  )}
                >
                  <item.icon className="size-4" aria-hidden="true" />
                  {item.title}
                </RouterLink>
              )
            })}
          </div>
        </div>
      )}
    </nav>
  )
}
