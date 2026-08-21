import {
  createFileRoute,
  Outlet,
  redirect,
  useRouterState,
} from "@tanstack/react-router"
import { Wifi } from "lucide-react"
import { useState } from "react"

import { Logo } from "@/components/Common/Logo"
import { HeaderUserMenu } from "@/components/Navigation/HeaderUserMenu"
import { HorizontalNavigation } from "@/components/Navigation/HorizontalNavigation"
import {
  NAVIGATION_LAYOUT_STORAGE_KEY,
  type NavigationLayout,
  NavigationLayoutSwitch,
} from "@/components/Navigation/NavigationLayoutSwitch"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { isLoggedIn } from "@/hooks/useAuth"
import { cn } from "@/lib/utils"

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

function getInitialNavigationLayout(): NavigationLayout {
  if (typeof window === "undefined") return "horizontal"

  return window.localStorage.getItem(NAVIGATION_LAYOUT_STORAGE_KEY) ===
    "sidebar"
    ? "sidebar"
    : "horizontal"
}

function Layout() {
  const [navigationLayout, setNavigationLayout] = useState<NavigationLayout>(
    getInitialNavigationLayout,
  )
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })
  const section = pathname.startsWith("/douyin-accounts")
    ? "账号与风控"
    : pathname.startsWith("/douyin-browsers")
      ? "浏览器监控"
      : pathname.startsWith("/douyin-tracks")
        ? "赛道管理"
        : pathname.startsWith("/douyin-comments")
          ? "评论管理"
          : pathname.startsWith("/douyin-interactions")
            ? "互动任务"
            : pathname.startsWith("/developer-tools")
              ? "开发者中心"
              : pathname.startsWith("/douyin-tags")
                ? "标签管理"
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

  const handleNavigationLayoutChange = (layout: NavigationLayout) => {
    setNavigationLayout(layout)
    window.localStorage.setItem(NAVIGATION_LAYOUT_STORAGE_KEY, layout)
  }

  const usesSidebar = navigationLayout === "sidebar"

  return (
    <SidebarProvider>
      <a
        href="#main-content"
        className="fixed top-2 left-2 z-[100] -translate-y-20 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-lg transition-transform focus:translate-y-0"
      >
        跳到主要内容
      </a>
      {usesSidebar && <AppSidebar />}
      <SidebarInset className="h-svh overflow-hidden">
        <header className="z-40 flex h-14 shrink-0 items-center justify-between gap-2 border-b border-border/60 bg-background/90 px-3 backdrop-blur-xl md:px-4">
          <div className="flex min-w-0 items-center gap-2">
            {usesSidebar ? (
              <SidebarTrigger className="-ml-1 text-muted-foreground" />
            ) : (
              <Logo variant="icon" className="size-8" />
            )}
            <div className="h-5 w-px bg-border" />
            <div className="hidden min-w-0 sm:block">
              <p className="text-sm font-semibold text-foreground">{section}</p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <NavigationLayoutSwitch
              value={navigationLayout}
              onChange={handleNavigationLayoutChange}
            />
            <div className="hidden items-center gap-2 rounded-full border border-emerald-200/70 bg-emerald-50/80 px-2.5 py-1.5 text-xs font-medium text-emerald-700 shadow-sm dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-300 sm:flex md:px-3">
              <span className="status-pulse size-2 rounded-full bg-emerald-500" />
              <Wifi className="size-3.5" />
              <span className="hidden lg:inline">服务运行正常</span>
              <span className="lg:hidden">正常</span>
            </div>
            {!usesSidebar && <HeaderUserMenu />}
          </div>
        </header>
        {!usesSidebar && <HorizontalNavigation />}
        <main
          id="main-content"
          className={cn(
            "min-w-0 flex-1 overflow-y-auto",
            usesSidebar ? "p-3 md:p-4 xl:p-5" : "p-2 sm:p-3 lg:px-4",
          )}
        >
          <div
            data-testid="page-content-container"
            className={cn(
              "mx-auto w-full",
              usesSidebar ? "max-w-[1600px]" : "max-w-none",
            )}
          >
            <Outlet />
          </div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}

export default Layout
