import { Link as RouterLink, useRouterState } from "@tanstack/react-router"
import { Check, ChevronDown, LayoutGrid } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import useAuth from "@/hooks/useAuth"
import { cn } from "@/lib/utils"
import {
  findActiveNavigation,
  getNavigationModules,
  isNavigationItemActive,
  type NavigationItem,
  type NavigationModule,
} from "./navigation"

function ModuleMenuItems({
  module,
  pathname,
}: {
  module: NavigationModule
  pathname: string
}) {
  return (
    <>
      <DropdownMenuLabel className="flex items-center gap-2 px-2.5 py-2 text-xs font-semibold text-foreground">
        <span className="flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <LayoutGrid className="size-3.5" />
        </span>
        {module.topLabel}
      </DropdownMenuLabel>
      <DropdownMenuSeparator />
      {module.items.map((item) => {
        const active = isNavigationItemActive(pathname, item.path)
        return (
          <DropdownMenuItem
            key={item.path}
            asChild
            className={cn(
              "my-0.5 rounded-lg p-0 focus:bg-primary/8",
              active && "bg-primary/8 text-primary",
            )}
          >
            <RouterLink
              to={item.path}
              aria-current={active ? "page" : undefined}
              className="flex min-h-11 w-full items-center gap-3 px-2.5 py-2 outline-none"
            >
              <span
                className={cn(
                  "flex size-8 shrink-0 items-center justify-center rounded-lg border border-border/70 bg-background text-muted-foreground shadow-xs",
                  active && "border-primary/20 bg-primary/10 text-primary",
                )}
              >
                <item.icon className="size-4" />
              </span>
              <span className="min-w-0 flex-1 font-medium">{item.title}</span>
              {active && <Check className="size-4 shrink-0 text-primary" />}
            </RouterLink>
          </DropdownMenuItem>
        )
      })}
    </>
  )
}

function DesktopModule({
  module,
  pathname,
}: {
  module: NavigationModule
  pathname: string
}) {
  const active = module.items.some((item) =>
    isNavigationItemActive(pathname, item.path),
  )

  if (module.items.length === 1) {
    const item = module.items[0] as NavigationItem
    return (
      <Button
        asChild
        variant="ghost"
        size="sm"
        className={cn(
          "h-9 rounded-lg px-3 font-medium text-muted-foreground hover:bg-accent hover:text-foreground",
          active &&
            "bg-primary/10 text-primary hover:bg-primary/12 hover:text-primary",
        )}
      >
        <RouterLink to={item.path} aria-current={active ? "page" : undefined}>
          <item.icon className="size-4" />
          {module.topLabel}
        </RouterLink>
      </Button>
    )
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          data-testid={`top-module-trigger-${module.id}`}
          className={cn(
            "group h-9 rounded-lg px-3 font-medium text-muted-foreground hover:bg-accent hover:text-foreground data-[state=open]:bg-accent data-[state=open]:text-foreground",
            active &&
              "bg-primary/10 text-primary hover:bg-primary/12 hover:text-primary data-[state=open]:bg-primary/12 data-[state=open]:text-primary",
          )}
        >
          {module.topLabel}
          <ChevronDown className="size-3.5 transition-transform duration-200 group-data-[state=open]:rotate-180 motion-reduce:transition-none" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        sideOffset={8}
        className="w-64 rounded-xl border-border/70 p-1.5 shadow-xl"
      >
        <ModuleMenuItems module={module} pathname={pathname} />
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function TopModuleNav() {
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
    <>
      <nav
        aria-label="模块导航"
        data-testid="top-module-navigation"
        className="hidden min-w-0 items-center gap-1 xl:flex"
      >
        {modules.map((module) => (
          <DesktopModule key={module.id} module={module} pathname={pathname} />
        ))}
      </nav>

      <div className="xl:hidden">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              data-testid="top-module-compact-trigger"
              className="group h-9 max-w-[11rem] gap-2 rounded-lg border-border/70 bg-background/80 px-2.5 shadow-xs"
            >
              <LayoutGrid className="size-4 shrink-0 text-primary" />
              <span className="truncate">
                {activeNavigation?.module.topLabel ?? "模块导航"}
              </span>
              <ChevronDown className="size-3.5 shrink-0 text-muted-foreground transition-transform duration-200 group-data-[state=open]:rotate-180 motion-reduce:transition-none" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="start"
            sideOffset={8}
            className="max-h-[min(70vh,34rem)] w-[min(22rem,calc(100vw-2rem))] rounded-xl border-border/70 p-1.5 shadow-xl"
          >
            {modules.map((module, index) => (
              <div key={module.id}>
                {index > 0 && <DropdownMenuSeparator className="my-1.5" />}
                <ModuleMenuItems module={module} pathname={pathname} />
              </div>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </>
  )
}
