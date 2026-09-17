import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query"
import { createRouter, RouterProvider } from "@tanstack/react-router"
import { StrictMode } from "react"
import ReactDOM from "react-dom/client"
import { ApiError, OpenAPI } from "./client"
import { ThemeProvider } from "./components/theme-provider"
import { Toaster } from "./components/ui/sonner"
import { TooltipProvider } from "./components/ui/tooltip"
import "./index.css"
import { clearAccessToken, getAccessToken } from "@/lib/auth-token"
import { pushNotification } from "./lib/notification-store"
import { routeTree } from "./routeTree.gen"

OpenAPI.BASE = import.meta.env.VITE_API_URL
OpenAPI.TOKEN = async () => {
  return getAccessToken()
}

/** 从 ApiError 里抽一句人能读懂的原因，用于通知中心。 */
const describeApiError = (error: ApiError): string => {
  const detail = (error.body as { detail?: unknown } | null)?.detail
  if (typeof detail === "string" && detail.trim()) return detail.trim()
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
  return `HTTP ${error.status ?? "未知"}`
}

const handleApiError = (error: Error) => {
  if (!(error instanceof ApiError)) return

  const detail =
    typeof error.body === "object" &&
    error.body !== null &&
    "detail" in error.body
      ? error.body.detail
      : undefined
  const sessionExpired =
    [401, 403].includes(error.status) ||
    (error.status === 404 && detail === "User not found")

  if (sessionExpired) {
    clearAccessToken()
    window.location.href = "/login"
    return
  }

  // 非会话失效的失败留一条记录：toast 一闪而过，错过就查不到发生过什么。
  // 相同内容 5 秒内会去重，接口重试不会刷屏。
  pushNotification({
    kind: "error",
    title: "请求失败",
    description: describeApiError(error),
  })
}
const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: handleApiError,
  }),
  mutationCache: new MutationCache({
    onError: handleApiError,
  }),
  // 全局缓存/轮询默认值：此前完全缺失，导致 34 处轮询点里只有 8 处设过 staleTime，
  // 且后台标签页仍在全速轮询（refetchIntervalInBackground 全仓为 0）。
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 300_000,
      // 后台标签页暂停轮询，切回时再刷新
      refetchIntervalInBackground: false,
      // 窗口重新聚焦不再无条件重拉（各页已有显式轮询）
      refetchOnWindowFocus: false,
      retry: 1,
    },
    mutations: {
      retry: 0,
    },
  },
})

const router = createRouter({ routeTree })
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider defaultTheme="light" storageKey="vite-ui-theme">
      <QueryClientProvider client={queryClient}>
        {/* 全应用共用一个 Tooltip Provider：Tooltip 默认不再自建 Provider，
            否则列表里每一行的每个 Tooltip 都会各挂一套 context 与 Popper。 */}
        <TooltipProvider>
          <RouterProvider router={router} />
          <Toaster richColors closeButton />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
