import {
  createFileRoute,
  Outlet,
  redirect,
  useRouterState,
} from "@tanstack/react-router"
import { Wifi } from "lucide-react"

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
    : pathname.startsWith("/douyin-interactions")
      ? "互动任务"
      : pathname.startsWith("/developer-tools")
        ? "开发者中心"
        : pathname.startsWith("/douyin-keywords")
          ? "关键词管理"
          : pathname.startsWith("/douyin-library")
            ? "视频资源库"
            : pathname.startsWith("/douyin/")
              ? "任务详情"
              : pathname === "/douyin"
                ? "爬取任务"
                : pathname.startsWith("/settings")
                  ? "个人设置"
                  : pathname.startsWith("/admin")
                    ? "用户管理"
                    : "运营工作台"
  return (
    <SidebarProvider>
      <a
        href="#main-content"
        className="fixed top-2 left-2 z-[100] -translate-y-20 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-lg transition-transform focus:translate-y-0"
      >
        跳到主要内容
      </a>
      <AppSidebar />
      <SidebarInset>
        <header className="sticky top-0 z-40 flex h-16 shrink-0 items-center justify-between gap-3 border-b border-border/60 bg-background/75 px-4 backdrop-blur-xl md:px-6">
          <div className="flex items-center gap-3">
            <SidebarTrigger className="-ml-1 text-muted-foreground" />
            <div className="h-5 w-px bg-border" />
            <div>
              <p className="text-sm font-semibold text-foreground">{section}</p>
              <p className="hidden text-[11px] text-muted-foreground sm:block">
                内容采集与运营管理
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 rounded-full border border-emerald-200/70 bg-emerald-50/80 px-3 py-1.5 text-xs font-medium text-emerald-700 shadow-sm dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-300">
            <span className="status-pulse size-2 rounded-full bg-emerald-500" />
            <Wifi className="size-3.5" />
            <span className="hidden sm:inline">服务运行正常</span>
            <span className="sm:hidden">正常</span>
          </div>
        </header>
        <main id="main-content" className="min-w-0 flex-1 p-4 md:p-6 xl:p-8">
          <div className="mx-auto max-w-[1600px]">
            <Outlet />
          </div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}

export default Layout
