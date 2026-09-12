import { Link as RouterLink, useRouterState } from "@tanstack/react-router"
import type { LucideIcon } from "lucide-react"

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"

export type Item = {
  icon: LucideIcon
  title: string
  path: string
}

export type NavGroup = {
  id?: string
  label: string
  description?: string
  items: Item[]
}

interface MainProps {
  groups: NavGroup[]
}

export function Main({ groups }: MainProps) {
  const { isMobile, setOpenMobile } = useSidebar()
  // 只订阅 pathname：不传 select 会订阅整个 router state，
  // 任何路由状态微变都会重渲染侧边栏（而全站每页都挂着它）。
  const currentPath = useRouterState({
    select: (state) => state.location.pathname,
  })

  const handleMenuClick = () => {
    if (isMobile) {
      setOpenMobile(false)
    }
  }

  return (
    <>
      {groups.map((group) => (
        <SidebarGroup
          key={group.label}
          className="py-2"
          data-testid={group.id ? `sidebar-group-${group.id}` : undefined}
        >
          <SidebarGroupLabel className="justify-between gap-2 px-3 text-[10px] font-semibold tracking-[0.16em] text-sidebar-foreground/45">
            <span>{group.label}</span>
            {group.description && (
              <span className="truncate text-[9px] font-normal tracking-normal text-sidebar-foreground/35">
                {group.description}
              </span>
            )}
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {group.items.map((item) => {
                const isActive =
                  currentPath === item.path ||
                  (item.path !== "/" && currentPath.startsWith(`${item.path}/`))

                return (
                  <SidebarMenuItem key={item.title}>
                    <SidebarMenuButton
                      tooltip={item.title}
                      isActive={isActive}
                      asChild
                      className="h-10 rounded-xl px-3 font-medium transition-all data-[active=true]:bg-sidebar-primary/12 data-[active=true]:text-sidebar-primary data-[active=true]:shadow-sm"
                    >
                      <RouterLink to={item.path} onClick={handleMenuClick}>
                        <item.icon className="size-[18px]" />
                        <span>{item.title}</span>
                      </RouterLink>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      ))}
    </>
  )
}
