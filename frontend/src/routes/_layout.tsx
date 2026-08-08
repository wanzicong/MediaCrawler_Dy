import {
  createFileRoute,
  Outlet,
  redirect,
  useRouterState,
} from "@tanstack/react-router"
import { Activity } from "lucide-react"

import AppSidebar from "@/components/Sidebar/AppSidebar"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({
        to: "/login",
      })
    }
  },
})

function Layout() {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })
  const section = pathname.startsWith("/douyin-accounts")
    ? "账号与风控"
    : pathname.startsWith("/douyin-library")
      ? "视频资源库"
      : pathname.startsWith("/douyin/")
        ? "任务详情"
        : pathname === "/douyin"
          ? "爬取任务"
          : pathname.startsWith("/settings")
            ? "个人设置"
            : "运营工作台"
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="sticky top-0 z-40 flex h-16 shrink-0 items-center justify-between gap-3 border-b bg-background/85 px-4 backdrop-blur-xl md:px-6">
          <div className="flex items-center gap-3">
            <SidebarTrigger className="-ml-1 text-muted-foreground" />
            <div className="h-5 w-px bg-border" />
            <div>
              <p className="text-sm font-medium">{section}</p>
              <p className="hidden text-[11px] text-muted-foreground sm:block">
                Douyin crawler operations
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 rounded-full border bg-card px-3 py-1.5 text-xs text-muted-foreground shadow-sm">
            <Activity className="size-3.5 text-emerald-500" />
            API 已连接
          </div>
        </header>
        <main className="flex-1 p-4 md:p-6 xl:p-8">
          <div className="mx-auto max-w-[1600px]">
            <Outlet />
          </div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}

export default Layout
