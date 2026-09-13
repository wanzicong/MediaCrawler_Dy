import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  Copy,
  ExternalLink,
  Laptop,
  LogIn,
  Maximize2,
  MonitorCog,
  RefreshCw,
  Server,
} from "lucide-react"
import { useEffect, useState } from "react"
import type { ApiError } from "@/client"
import { DouyinAccountsService, type DouyinBrowserSlotPublic } from "@/client"
import { PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import {
  browserModeLabel,
  browserSlotLabel,
} from "@/components/Douyin/presentation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/douyin-browsers")({
  component: BrowserManagementPage,
  head: () => ({ meta: [{ title: "浏览器管理 - 灵感采集台" }] }),
})

/** 浏览器管理页按运行模式分栏：本机槽位与云端槽位各自独立成一栏。 */
type SlotMode = "local" | "remote"

const SLOT_MODES: SlotMode[] = ["local", "remote"]

/** 各分栏的空态说明：告诉用户槽位从哪来、怎么开。 */
const EMPTY_STATES: Record<SlotMode, { title: string; description: string }> = {
  local: {
    title: "尚未启用本机槽位",
    description:
      "把 .env 或 config.yaml 的 DOUYIN_LOCAL_CDP_SLOT_COUNT 设为大于 0（默认 4）并重启服务后，本机槽位会出现在这里。",
  },
  remote: {
    title: "尚未配置云端槽位",
    description:
      "在 .env 的 DOUYIN_REMOTE_CDP_SLOTS 或 config.yaml 的 browser.slots.remote 中配置命名槽位（或直接使用 Docker 默认槽位）后，云端槽位会出现在这里。",
  },
}

function BrowserManagementPage() {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [copiedEndpoint, copyEndpoint] = useCopyToClipboard()
  // 用户没有手动切过栏时跟随数据：没有本机槽位就直接落在云端栏
  const [requestedMode, setRequestedMode] = useState<SlotMode | null>(null)
  // 两栏各自记住选中的槽位，切来切去不会互相覆盖
  const [selectedByMode, setSelectedByMode] = useState<
    Record<SlotMode, string | null>
  >({ local: null, remote: null })
  const slotsQuery = useQuery({
    queryKey: ["douyin-browser-monitor"],
    queryFn: () => DouyinAccountsService.listBrowserSlots(),
    retry: false,
    refetchInterval: 5_000,
  })
  const slots = slotsQuery.data?.data ?? []
  const slotsByMode: Record<SlotMode, DouyinBrowserSlotPublic[]> = {
    local: slots.filter((slot) => slot.browser_mode === "local"),
    remote: slots.filter((slot) => slot.browser_mode === "remote"),
  }
  const mode: SlotMode =
    requestedMode ?? (slotsByMode.local.length ? "local" : "remote")
  // 轮询每 5 秒都会返回全新的数组引用，若直接把 slots 写进依赖，effect 每轮都会重跑并重置选中项，
  // 造成选中态抖动；这里改依赖「槽位名拼成的稳定字符串」，只有槽位集合真正变化时才重新校验选中项。
  const localSignature = slotsByMode.local.map(slotKey).join("|")
  const remoteSignature = slotsByMode.remote.map(slotKey).join("|")
  useEffect(() => {
    setSelectedByMode((current) => {
      const next = { ...current }
      let changed = false
      const signatures: [SlotMode, string][] = [
        ["local", localSignature],
        ["remote", remoteSignature],
      ]
      for (const [key, signature] of signatures) {
        const names = signature ? signature.split("|") : []
        if (!names.includes(next[key] ?? "")) {
          const fallback = names[0] ?? null
          if (next[key] !== fallback) {
            next[key] = fallback
            changed = true
          }
        }
      }
      return changed ? next : current
    })
  }, [localSignature, remoteSignature])

  // 管理动作：在指定槽位对应的账号上发起登录（后端会拉起该槽位浏览器）
  const login = useMutation({
    mutationFn: (accountId: string) =>
      DouyinAccountsService.startAccountLogin({ accountId }),
    onSuccess: async (result) => {
      if (result.viewer_url) {
        window.open(result.viewer_url, "_blank", "noopener,noreferrer")
      }
      showSuccessToast(
        result.message?.trim() || "浏览器已启动，请完成登录后到账号管理页验证",
      )
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["douyin-browser-monitor"] }),
        queryClient.invalidateQueries({ queryKey: ["douyin-accounts"] }),
      ])
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })

  const onlineCount = slots.filter((slot) => slot.cdp_healthy).length
  const boundCount = slots.filter((slot) => slot.occupied_account_id).length
  const freeCount = slots.filter((slot) => slot.available).length

  const selectSlot = (target: SlotMode, name: string) => {
    setSelectedByMode((current) => ({ ...current, [target]: name }))
  }

  return (
    <div className="page-stack">
      <PageHero
        eyebrow="浏览器资源"
        icon={MonitorCog}
        title="浏览器管理"
        description="按「本机」与「云端」两类槽位管理常驻浏览器：查看连接与账号占用、就地发起登录、打开实时画面或复制 CDP 端点。"
        actions={
          <Button
            variant="outline"
            onClick={() => slotsQuery.refetch()}
            disabled={slotsQuery.isFetching}
          >
            <RefreshCw
              className={slotsQuery.isFetching ? "animate-spin" : ""}
            />
            刷新状态
          </Button>
        }
      >
        <p className="text-xs text-muted-foreground">
          槽位{" "}
          <strong className="text-foreground">
            {slotsQuery.isError ? "—" : slots.length}
          </strong>{" "}
          · 在线{" "}
          <strong className="text-foreground">
            {slotsQuery.isError ? "—" : onlineCount}
          </strong>{" "}
          · 已绑定{" "}
          <strong className="text-foreground">
            {slotsQuery.isError ? "—" : boundCount}
          </strong>{" "}
          · 可绑定{" "}
          <strong className="text-foreground">
            {slotsQuery.isError ? "—" : freeCount}
          </strong>
        </p>
      </PageHero>

      {slotsQuery.isError ? (
        <QueryErrorState
          title="浏览器槽位读取失败"
          description="暂时无法获取浏览器连接与页面状态，请检查服务连接后重试。"
          onRetry={() => void slotsQuery.refetch()}
          retrying={slotsQuery.isFetching}
        />
      ) : (
        <Tabs
          value={mode}
          onValueChange={(value) => setRequestedMode(value as SlotMode)}
          className="gap-4"
        >
          <TabsList className="grid h-9 w-full max-w-sm grid-cols-2">
            {SLOT_MODES.map((slotMode) => (
              <TabsTrigger
                key={slotMode}
                value={slotMode}
                data-testid={`browser-slot-tab-${slotMode}`}
              >
                {slotMode === "local" ? (
                  <Laptop aria-hidden="true" />
                ) : (
                  <Server aria-hidden="true" />
                )}
                {browserModeLabel(slotMode)}（{slotsByMode[slotMode].length}）
              </TabsTrigger>
            ))}
          </TabsList>

          {SLOT_MODES.map((slotMode) => (
            <TabsContent key={slotMode} value={slotMode}>
              <SlotWorkspace
                mode={slotMode}
                slots={slotsByMode[slotMode]}
                loading={slotsQuery.isLoading}
                selectedName={selectedByMode[slotMode]}
                onSelect={(name) => selectSlot(slotMode, name)}
                onLogin={(accountId) => login.mutate(accountId)}
                loginPendingAccountId={
                  login.isPending ? (login.variables ?? null) : null
                }
                copiedEndpoint={copiedEndpoint}
                onCopyEndpoint={(text) => void copyEndpoint(text)}
              />
            </TabsContent>
          ))}
        </Tabs>
      )}
    </div>
  )
}

/** 单个分栏的工作区：左侧槽位列表 + 右侧槽位管理面板。 */
function SlotWorkspace({
  mode,
  slots,
  loading,
  selectedName,
  onSelect,
  onLogin,
  loginPendingAccountId,
  copiedEndpoint,
  onCopyEndpoint,
}: {
  mode: SlotMode
  slots: DouyinBrowserSlotPublic[]
  loading: boolean
  selectedName: string | null
  onSelect: (name: string) => void
  onLogin: (accountId: string) => void
  loginPendingAccountId: string | null
  copiedEndpoint: string | null
  onCopyEndpoint: (text: string) => void
}) {
  const selected =
    slots.find((slot) => slotKey(slot) === selectedName) ?? slots[0]
  const onlineCount = slots.filter((slot) => slot.cdp_healthy).length
  const emptyState = EMPTY_STATES[mode]
  return (
    <div
      data-testid="browser-monitor-workspace"
      data-browser-mode={mode}
      className="grid gap-5 xl:sticky xl:top-0 xl:z-10 xl:h-[calc(100svh-12rem)] xl:min-h-[620px] xl:grid-cols-[320px_minmax(0,1fr)] xl:items-stretch"
    >
      <Card
        data-testid="browser-slot-panel"
        className="min-h-0 overflow-hidden xl:h-full"
      >
        <CardHeader className="shrink-0 gap-1 border-b">
          <CardTitle>
            {mode === "local" ? "本机浏览器槽位" : "云端浏览器槽位"}
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            共 {slots.length} 个 · {onlineCount} 个在线
          </p>
        </CardHeader>
        <CardContent
          data-testid="browser-slot-list"
          className="min-h-0 max-h-80 flex-1 overflow-y-auto overscroll-contain px-3 pb-3 pr-2 [scrollbar-gutter:stable] xl:max-h-none"
        >
          <nav
            aria-label={`${browserModeLabel(mode)}槽位列表`}
            className="space-y-2"
          >
            {slots.map((slot) => {
              const active = slotKey(slot) === slotKey(selected)
              return (
                <button
                  type="button"
                  key={slotKey(slot)}
                  aria-pressed={active}
                  onClick={() => onSelect(slotKey(slot))}
                  className={`w-full rounded-xl border p-3 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-primary/60 motion-reduce:transition-none ${
                    active
                      ? "border-primary/40 bg-primary/8 shadow-sm"
                      : "bg-muted/15 hover:border-primary/20 hover:bg-muted/35"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-1.5 font-medium">
                      {mode === "local" ? (
                        <Laptop
                          className="size-4 shrink-0"
                          aria-hidden="true"
                        />
                      ) : (
                        <Server
                          className="size-4 shrink-0"
                          aria-hidden="true"
                        />
                      )}
                      {browserSlotLabel(slot)}
                    </span>
                    <span
                      role="img"
                      aria-label={
                        slot.cdp_healthy ? "浏览器在线" : "浏览器离线"
                      }
                      className={`size-2.5 rounded-full ${
                        slot.cdp_healthy ? "bg-emerald-500" : "bg-rose-500"
                      }`}
                    />
                  </div>
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    {slot.occupied_account_name
                      ? `已绑定 ${slot.occupied_account_name}`
                      : slot.available
                        ? "可绑定账号"
                        : "未绑定账号"}{" "}
                    · {slot.page_count} 页
                  </p>
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    {slot.active_page_title || "等待页面信息"}
                  </p>
                </button>
              )
            })}
            {!slots.length && loading && (
              <p className="py-8 text-center text-sm text-muted-foreground">
                正在读取浏览器槽位…
              </p>
            )}
            {!slots.length && !loading && (
              <div className="px-2 py-8 text-center text-sm text-muted-foreground">
                <p className="font-medium text-foreground">
                  {emptyState.title}
                </p>
                <p className="mt-1 leading-relaxed">{emptyState.description}</p>
              </div>
            )}
          </nav>
        </CardContent>
      </Card>

      <Card
        data-testid="browser-viewer-panel"
        className="flex min-h-0 min-w-0 flex-col gap-0 overflow-hidden py-0 xl:h-full"
      >
        <CardHeader className="shrink-0 border-b">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
            <div className="shrink-0">
              <CardTitle>
                {selected ? browserSlotLabel(selected) : "浏览器"}
              </CardTitle>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {selected && (
                  <Badge variant="outline">{browserModeLabel(mode)}</Badge>
                )}
                {selected && (
                  <Badge
                    variant={selected.cdp_healthy ? "default" : "destructive"}
                  >
                    {selected.cdp_healthy ? "浏览器在线" : "浏览器离线"}
                  </Badge>
                )}
                {selected?.latency_ms != null && (
                  <Badge variant="outline">{selected.latency_ms} ms</Badge>
                )}
                {selected?.is_default && <Badge>默认槽位</Badge>}
                {selected?.occupied_account_name && (
                  <Badge variant="secondary">
                    {selected.occupied_account_name}
                  </Badge>
                )}
              </div>
            </div>

            {selected?.cdp_endpoint && (
              <div
                data-testid="browser-cdp-endpoint"
                className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-border/70 bg-muted/25 px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium text-foreground">
                    CDP 调试端点
                  </p>
                  <p className="mt-0.5 truncate font-mono text-xs text-muted-foreground">
                    {selected.cdp_endpoint}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => onCopyEndpoint(selected.cdp_endpoint || "")}
                >
                  <Copy />
                  {copiedEndpoint === selected.cdp_endpoint ? "已复制" : "复制"}
                </Button>
              </div>
            )}
          </div>
        </CardHeader>

        <div
          data-testid="browser-slot-actions"
          className="flex shrink-0 flex-wrap items-center gap-2 border-b px-4 py-3"
        >
          <div className="mr-auto min-w-0">
            <p className="text-xs font-medium text-foreground">绑定账号</p>
            <p className="truncate text-sm text-muted-foreground">
              {selected?.occupied_account_name ??
                (selected?.available
                  ? "未绑定；可在账号管理页创建账号并绑定该槽位"
                  : "未绑定")}
            </p>
          </div>
          {selected?.occupied_account_id && (
            <Button
              size="sm"
              onClick={() => onLogin(selected.occupied_account_id as string)}
              disabled={loginPendingAccountId === selected.occupied_account_id}
            >
              <LogIn />
              {loginPendingAccountId === selected.occupied_account_id
                ? "登录中…"
                : "登录该账号"}
            </Button>
          )}
          <Button size="sm" variant="outline" asChild>
            <Link to="/douyin-accounts">
              账号管理 <ExternalLink />
            </Link>
          </Button>
          {selected?.viewer_url && (
            <Button size="sm" variant="outline" asChild>
              <a href={selected.viewer_url} target="_blank" rel="noreferrer">
                <Maximize2 />
                新窗口操作
              </a>
            </Button>
          )}
        </div>

        {selected?.active_page_url && (
          <div
            data-testid="browser-active-page"
            className="flex shrink-0 items-center gap-2 border-b border-border/70 bg-muted/15 px-4 py-2"
          >
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium text-foreground">
                当前活动页面
              </p>
              <p className="mt-0.5 truncate text-xs text-muted-foreground">
                {selected.active_page_title || selected.active_page_url}
              </p>
            </div>
            <Button size="sm" variant="ghost" asChild>
              <a
                href={selected.active_page_url}
                target="_blank"
                rel="noreferrer"
              >
                打开页面 <ExternalLink />
              </a>
            </Button>
          </div>
        )}

        <CardContent className="min-h-0 flex-1 p-0">
          {selected?.viewer_url ? (
            <iframe
              key={selected.viewer_url}
              src={selected.viewer_url}
              title={`${browserSlotLabel(selected)} 实时浏览器`}
              className="h-[72vh] min-h-[520px] w-full bg-slate-950 xl:h-full xl:min-h-0"
              allow="clipboard-read; clipboard-write; fullscreen"
              // 远程画面需要在 iframe 内直接操作抖音页面，故放开脚本/同源/表单/弹窗；
              // 但不给 allow-top-navigation，避免被嵌入页面劫持顶层窗口跳转。
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
            />
          ) : (
            <div className="flex h-full min-h-[520px] items-center justify-center p-8 text-center text-muted-foreground xl:min-h-0">
              <div>
                <MonitorCog className="mx-auto size-10 opacity-50" />
                <p className="mt-3 font-medium">
                  {mode === "local"
                    ? "本机浏览器没有远程画面"
                    : "该槽位暂未提供实时操作画面"}
                </p>
                <p className="mt-1 text-sm">
                  {mode === "local"
                    ? "浏览器开在运行服务的机器上，请直接在该机器的浏览器窗口操作；也可以点「登录该账号」在本机拉起该槽位的浏览器。"
                    : "浏览器连接状态仍会持续监控。"}
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function slotKey(slot: DouyinBrowserSlotPublic | undefined) {
  return slot?.name ?? "__default__"
}
