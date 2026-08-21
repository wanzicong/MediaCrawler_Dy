import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  Activity,
  ExternalLink,
  Maximize2,
  MonitorPlay,
  RefreshCw,
  Server,
  UsersRound,
} from "lucide-react"
import { useEffect, useState } from "react"

import { DouyinAccountsService, type DouyinBrowserSlotPublic } from "@/client"
import { MetricCard, PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { browserSlotLabel } from "@/components/Douyin/presentation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export const Route = createFileRoute("/_layout/douyin-browsers")({
  component: BrowserMonitorPage,
  head: () => ({ meta: [{ title: "浏览器监控中心 - 灵感采集台" }] }),
})

function BrowserMonitorPage() {
  const [selectedName, setSelectedName] = useState<string | null>(null)
  const slotsQuery = useQuery({
    queryKey: ["douyin-browser-monitor"],
    queryFn: () => DouyinAccountsService.listBrowserSlots(),
    retry: false,
    refetchInterval: 5_000,
  })
  const slots = slotsQuery.data?.data ?? []
  useEffect(() => {
    if (!slots.length) return
    const selectedStillExists = slots.some(
      (slot) => slotKey(slot) === selectedName,
    )
    if (!selectedStillExists) setSelectedName(slotKey(slots[0]))
  }, [selectedName, slots])
  const selected =
    slots.find((slot) => slotKey(slot) === selectedName) ?? slots[0]
  const healthy = slots.filter((slot) => slot.cdp_healthy).length
  const occupied = slots.filter((slot) => slot.occupied_account_id).length
  const totalPages = slots.reduce((sum, slot) => sum + slot.page_count, 0)

  return (
    <div className="page-stack">
      <PageHero
        eyebrow="浏览器实时运营"
        icon={MonitorPlay}
        title="浏览器监控中心"
        description="集中查看每个常驻托管浏览器的实时页面、连接状态与账号占用情况，并可直接在管理后台完成登录和人工操作。"
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
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          icon={Server}
          label="常驻浏览器"
          value={slotsQuery.isError ? "—" : slots.length}
          detail={slotsQuery.isError ? "浏览器状态读取失败" : "专属登录空间"}
          tone="violet"
          compact
        />
        <MetricCard
          icon={Activity}
          label="连接状态"
          value={slotsQuery.isError ? "—" : `${healthy} / ${slots.length}`}
          detail="每 5 秒自动探测"
          tone="mint"
          compact
        />
        <MetricCard
          icon={UsersRound}
          label="已绑定账号"
          value={slotsQuery.isError ? "—" : occupied}
          detail="槽位独占"
          tone="blue"
          compact
        />
        <MetricCard
          icon={MonitorPlay}
          label="活动页面"
          value={slotsQuery.isError ? "—" : totalPages}
          detail="所有浏览器标签页"
          tone="coral"
          compact
        />
      </div>

      {slotsQuery.isError ? (
        <QueryErrorState
          title="浏览器槽位读取失败"
          description="暂时无法获取浏览器连接与页面状态，请检查服务连接后重试。"
          onRetry={() => void slotsQuery.refetch()}
          retrying={slotsQuery.isFetching}
        />
      ) : (
        <div
          data-testid="browser-monitor-workspace"
          className="grid gap-5 xl:sticky xl:top-0 xl:z-10 xl:h-[calc(100svh-12rem)] xl:min-h-[620px] xl:grid-cols-[300px_minmax(0,1fr)] xl:items-stretch"
        >
          <Card
            data-testid="browser-slot-panel"
            className="min-h-0 overflow-hidden xl:h-full"
          >
            <CardHeader className="shrink-0 border-b">
              <CardTitle>浏览器槽位</CardTitle>
            </CardHeader>
            <CardContent
              data-testid="browser-slot-list"
              className="min-h-0 max-h-80 flex-1 overflow-y-auto overscroll-contain px-3 pb-3 pr-2 [scrollbar-gutter:stable] xl:max-h-none"
            >
              <nav aria-label="浏览器槽位列表" className="space-y-2">
                {slots.map((slot) => {
                  const active = slotKey(slot) === slotKey(selected)
                  return (
                    <button
                      type="button"
                      key={slotKey(slot)}
                      aria-pressed={active}
                      onClick={() => setSelectedName(slotKey(slot))}
                      className={`w-full rounded-xl border p-3 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-primary/60 motion-reduce:transition-none ${
                        active
                          ? "border-primary/40 bg-primary/8 shadow-sm"
                          : "bg-muted/15 hover:border-primary/20 hover:bg-muted/35"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium">
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
                        {slot.occupied_account_name || "未绑定账号"} ·{" "}
                        {slot.page_count} 页
                      </p>
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {slot.active_page_title || "等待页面信息"}
                      </p>
                    </button>
                  )
                })}
                {!slots.length && slotsQuery.isLoading && (
                  <p className="py-8 text-center text-sm text-muted-foreground">
                    正在读取浏览器槽位…
                  </p>
                )}
                {!slots.length && !slotsQuery.isLoading && (
                  <p className="py-8 text-center text-sm text-muted-foreground">
                    尚未配置浏览器槽位。
                  </p>
                )}
              </nav>
            </CardContent>
          </Card>

          <Card
            data-testid="browser-viewer-panel"
            className="min-h-0 min-w-0 gap-0 overflow-hidden py-0 xl:h-full"
          >
            <CardHeader className="shrink-0 border-b py-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
                <div className="shrink-0">
                  <CardTitle>
                    {selected ? browserSlotLabel(selected) : "浏览器实时画面"}
                  </CardTitle>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <Badge
                      variant={
                        selected?.cdp_healthy ? "default" : "destructive"
                      }
                    >
                      {selected?.cdp_healthy ? "浏览器在线" : "浏览器离线"}
                    </Badge>
                    {selected?.latency_ms != null && (
                      <Badge variant="outline">{selected.latency_ms} ms</Badge>
                    )}
                    {selected?.occupied_account_name && (
                      <Badge variant="secondary">
                        {selected.occupied_account_name}
                      </Badge>
                    )}
                  </div>
                </div>

                {selected?.active_page_url && (
                  <div
                    data-testid="browser-active-page"
                    className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-border/70 bg-muted/25 px-3 py-2"
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

                {selected?.viewer_url && (
                  <Button variant="outline" className="shrink-0" asChild>
                    <a
                      href={selected.viewer_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <Maximize2 />
                      新窗口操作
                    </a>
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent className="min-h-0 flex-1 p-0">
              {selected?.viewer_url ? (
                <iframe
                  key={selected.viewer_url}
                  src={selected.viewer_url}
                  title={`${browserSlotLabel(selected)} 实时浏览器`}
                  className="h-[72vh] min-h-[520px] w-full bg-slate-950 xl:h-full xl:min-h-0"
                  allow="clipboard-read; clipboard-write; fullscreen"
                />
              ) : (
                <div className="flex h-full min-h-[520px] items-center justify-center p-8 text-center text-muted-foreground xl:min-h-0">
                  <div>
                    <MonitorPlay className="mx-auto size-10 opacity-50" />
                    <p className="mt-3 font-medium">
                      该槽位暂未提供实时操作画面
                    </p>
                    <p className="mt-1 text-sm">浏览器连接状态仍会持续监控。</p>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}

function slotKey(slot: DouyinBrowserSlotPublic | undefined) {
  return slot?.name ?? "__default__"
}
