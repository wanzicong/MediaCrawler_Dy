import { useQuery } from "@tanstack/react-query"
import {
  createFileRoute,
  Outlet,
  redirect,
  useRouterState,
} from "@tanstack/react-router"
import { AlertTriangle, Wifi } from "lucide-react"
import { useState } from "react"

import { UtilsService } from "@/client"
import { ConfirmDialogHost } from "@/components/Common/confirm-dialog"
import { Logo } from "@/components/Common/Logo"
import { NotificationCenter } from "@/components/Common/NotificationCenter"
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
import { readStorage, writeStorage } from "@/lib/storage"
import { cn } from "@/lib/utils"

/**
 * pathname 前缀 → 顶栏标题。
 * 此前是 27 行嵌套三元，且漏了 /douyin-creators 与 /douyin-request-logs，
 * 导致这两个页面顶栏错误地回退成「运营工作台」。
 */
const SECTION_BY_PREFIX: Array<[prefix: string, label: string]> = [
  ["/douyin-accounts", "账号与风控"],
  ["/douyin-browsers", "浏览器管理"],
  ["/douyin-tracks", "赛道管理"],
  ["/douyin-comments", "评论管理"],
  ["/douyin-interactions", "互动任务"],
  ["/douyin-creators", "达人列表"],
  ["/douyin-request-logs", "请求日志"],
  ["/douyin-tags", "标签管理"],
  ["/douyin-keywords", "关键词管理"],
  ["/douyin-library", "视频资源库"],
  ["/developer-tools", "开发者中心"],
  ["/settings", "个人设置"],
  ["/admin", "用户管理"],
]

function resolveSection(pathname: string): string {
  const matched = SECTION_BY_PREFIX.find(([prefix]) =>
    pathname.startsWith(prefix),
  )
  if (matched) return matched[1]
  if (pathname.startsWith("/douyin/")) return "任务详情"
  if (pathname === "/douyin") return "爬取任务"
  return "运营工作台"
}

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

/** 顶栏的服务状态徽标：由真实健康检查驱动，而不是写死的绿色。 */
function ServiceHealthBadge({ status }: { status: "loading" | "ok" | "down" }) {
  const styles = {
    ok: "border-emerald-200/70 bg-emerald-50/80 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-300",
    loading: "border-border bg-muted/60 text-muted-foreground",
    down: "border-destructive/30 bg-destructive/10 text-destructive",
  }[status]

  const dot = {
    ok: "status-pulse bg-emerald-500",
    loading: "bg-muted-foreground/50",
    down: "bg-destructive",
  }[status]

  const fullText = {
    ok: "服务运行正常",
    loading: "正在检测服务…",
    down: "服务连接异常",
  }[status]

  const shortText = { ok: "正常", loading: "检测中", down: "异常" }[status]

  return (
    <div
      className={cn(
        "hidden items-center gap-2 rounded-full border px-2.5 py-1.5 text-xs font-medium shadow-sm sm:flex md:px-3",
        styles,
      )}
    >
      <span className={cn("size-2 rounded-full", dot)} />
      {status === "down" ? (
        <AlertTriangle className="size-3.5" />
      ) : (
        <Wifi className="size-3.5" />
      )}
      <span className="hidden lg:inline">{fullText}</span>
      <span className="lg:hidden">{shortText}</span>
    </div>
  )
}

function getInitialNavigationLayout(): NavigationLayout {
  if (typeof window === "undefined") return "horizontal"

  return readStorage(NAVIGATION_LAYOUT_STORAGE_KEY) === "sidebar"
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
  const section = resolveSection(pathname)

  // 真实健康检查：此前这里是硬编码的绿色「服务运行正常」，
  // 后端挂掉时仍然显示正常，会误导排查方向。
  const healthQuery = useQuery({
    queryKey: ["service-health"],
    queryFn: () => UtilsService.healthCheck(),
    refetchInterval: 60_000,
    retry: 0,
  })

  const handleNavigationLayoutChange = (layout: NavigationLayout) => {
    setNavigationLayout(layout)
    writeStorage(NAVIGATION_LAYOUT_STORAGE_KEY, layout)
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
            <NotificationCenter />
            <NavigationLayoutSwitch
              value={navigationLayout}
              onChange={handleNavigationLayoutChange}
            />
            <ServiceHealthBadge
              status={
                healthQuery.isError
                  ? "down"
                  : healthQuery.isSuccess
                    ? "ok"
                    : "loading"
              }
            />
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
      {/* 承诺式确认对话框宿主：全站 window.confirm 的统一替代（报告 O15） */}
      <ConfirmDialogHost />
    </SidebarProvider>
  )
}

export default Layout
