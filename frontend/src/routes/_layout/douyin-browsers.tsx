import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  Copy,
  Download,
  ExternalLink,
  Laptop,
  LogIn,
  Maximize2,
  MonitorCog,
  Pencil,
  Plus,
  RefreshCw,
  Server,
  Trash2,
} from "lucide-react"
import { type ReactNode, useMemo, useState } from "react"
import type { ApiError } from "@/client"
import {
  DouyinAccountsService,
  type DouyinBrowserSlotPublic,
  type DouyinLocalBrowserPublic,
} from "@/client"
import { confirmDialog } from "@/components/Common/confirm-dialog"
import { PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { TableColumnMenu } from "@/components/Common/TableColumnMenu"
import { TimeAgo } from "@/components/Common/TimeAgo"
import { browserSlotLabel } from "@/components/Douyin/presentation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import useCustomToast from "@/hooks/useCustomToast"
import { type TableColumnDef, useTableColumns } from "@/hooks/useTableColumns"
import { downloadCsv } from "@/lib/csv"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/douyin-browsers")({
  component: BrowserManagementPage,
  head: () => ({ meta: [{ title: "浏览器管理 - 灵感采集台" }] }),
})

/** 浏览器管理页按运行模式分栏：本机槽位与云端槽位各自一张列表。 */
type SlotMode = "local" | "remote"

const SLOT_MODES: SlotMode[] = ["local", "remote"]

/** 列表列清单（报告 A1：key 稳定、操作列不允许隐藏，与表头/单元格一一对应）。 */
const SLOT_COLUMNS = [
  { key: "status", title: "连接状态" },
  { key: "slot", title: "槽位" },
  { key: "endpoint", title: "CDP 端点" },
  { key: "account", title: "绑定账号" },
  { key: "pages", title: "页面数" },
  { key: "page", title: "当前活动页面", defaultHidden: true },
  { key: "latency", title: "探测延迟", defaultHidden: true },
  { key: "checked", title: "最近探测" },
  { key: "actions", title: "操作", alwaysVisible: true },
] as const satisfies readonly TableColumnDef[]

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
  const [viewerSlot, setViewerSlot] = useState<DouyinBrowserSlotPublic | null>(
    null,
  )
  const { isVisible, visibleCount, menuProps } = useTableColumns({
    storageKey: "douyin-browser-slots-columns",
    columns: SLOT_COLUMNS,
  })
  const slotsQuery = useQuery({
    queryKey: ["douyin-browser-monitor"],
    queryFn: () => DouyinAccountsService.listBrowserSlots(),
    retry: false,
    // 槽位占用是账号的长期绑定状态，不代表有任务在跑；
    // 本页是管理视图，改为右上角手动刷新，不再后台轮询。
  })
  // 本机浏览器实例（可自助增删的本地槽位）：槽位表给「槽位名」，这张表给实例 id 与占用
  const localBrowsersQuery = useQuery({
    queryKey: ["douyin-local-browsers"],
    queryFn: () => DouyinAccountsService.listLocalBrowsersRoute(),
    retry: false,
  })
  const [browserEditor, setBrowserEditor] = useState<
    | { mode: "create" }
    | { mode: "edit"; target: DouyinLocalBrowserPublic }
    | null
  >(null)
  const localBrowsers = localBrowsersQuery.data?.data ?? []
  const localBrowserByName = useMemo(
    () => new Map(localBrowsers.map((item) => [item.name, item])),
    [localBrowsers],
  )

  const invalidateSlots = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["douyin-browser-monitor"] }),
      queryClient.invalidateQueries({ queryKey: ["douyin-local-browsers"] }),
    ])

  const removeLocalBrowser = useMutation({
    mutationFn: (browserId: string) =>
      DouyinAccountsService.deleteLocalBrowserRoute({ browserId }),
    onSuccess: async () => {
      showSuccessToast("本机浏览器已删除")
      await invalidateSlots()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const slots = slotsQuery.data?.data ?? []
  const localSlots = useMemo(
    () => slots.filter((slot) => slot.browser_mode === "local"),
    [slots],
  )
  const remoteSlots = useMemo(
    () => slots.filter((slot) => slot.browser_mode === "remote"),
    [slots],
  )
  const mode: SlotMode =
    requestedMode ?? (localSlots.length ? "local" : "remote")

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

  const exportSlots = () => {
    downloadCsv("抖音浏览器槽位", slots, [
      { header: "槽位", value: (row) => browserSlotLabel(row) },
      { header: "运行模式", value: (row) => row.browser_mode },
      { header: "CDP 端点", value: (row) => row.cdp_endpoint ?? "" },
      {
        header: "连接状态",
        value: (row) => (row.cdp_healthy ? "在线" : "离线"),
      },
      { header: "绑定账号", value: (row) => row.occupied_account_name ?? "" },
      {
        header: "是否可绑定",
        value: (row) => (row.available ? "可绑定" : "已占用"),
      },
      { header: "页面数", value: (row) => row.page_count },
      { header: "活动页面", value: (row) => row.active_page_title ?? "" },
      { header: "探测延迟(ms)", value: (row) => row.latency_ms ?? "" },
      { header: "最近探测", value: (row) => row.checked_at },
    ])
  }

  return (
    <div className="page-stack">
      <PageHero
        eyebrow="浏览器资源"
        icon={MonitorCog}
        title="浏览器管理"
        description="按「本机」与「云端」两类槽位管理常驻浏览器：查看连接与账号占用、就地发起登录、查看实时画面或复制 CDP 端点。"
        actions={
          <div className="flex flex-wrap gap-1.5">
            <Button
              variant="outline"
              onClick={exportSlots}
              disabled={!slots.length}
            >
              <Download />
              导出 CSV
            </Button>
            <Button onClick={() => setBrowserEditor({ mode: "create" })}>
              <Plus />
              新增本机浏览器
            </Button>
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
          </div>
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
                {slotMode === "local" ? "本机浏览器" : "云端浏览器"}（
                {slotMode === "local" ? localSlots.length : remoteSlots.length}
                ）
              </TabsTrigger>
            ))}
          </TabsList>

          {SLOT_MODES.map((slotMode) => (
            <TabsContent key={slotMode} value={slotMode}>
              <SlotTable
                mode={slotMode}
                slots={slotMode === "local" ? localSlots : remoteSlots}
                loading={slotsQuery.isLoading}
                isVisible={isVisible}
                visibleCount={visibleCount}
                columnMenu={<TableColumnMenu {...menuProps} />}
                onLogin={(accountId) => login.mutate(accountId)}
                loginPendingAccountId={
                  login.isPending ? (login.variables ?? null) : null
                }
                onOpenViewer={setViewerSlot}
                copiedEndpoint={copiedEndpoint}
                onCopyEndpoint={(text) => void copyEndpoint(text)}
                localBrowserByName={localBrowserByName}
                onEditLocal={(target) =>
                  setBrowserEditor({ mode: "edit", target })
                }
                onDeleteLocal={async (target) => {
                  const ok = await confirmDialog({
                    title: `删除本机浏览器「${target.label}」？`,
                    description:
                      "只会移除这个槽位记录，不会删除浏览器 Profile 目录；被账号绑定的实例需要先解绑。",
                    confirmText: "删除",
                    variant: "destructive",
                  })
                  if (!ok) return
                  removeLocalBrowser.mutate(target.id)
                }}
              />
            </TabsContent>
          ))}
        </Tabs>
      )}

      {browserEditor && (
        <LocalBrowserEditorDialog
          key={
            browserEditor.mode === "create"
              ? "create"
              : `edit-${browserEditor.target.id}`
          }
          state={browserEditor}
          onClose={() => setBrowserEditor(null)}
          onSaved={async () => {
            setBrowserEditor(null)
            await invalidateSlots()
          }}
          onError={showErrorToast}
        />
      )}

      <Dialog
        open={viewerSlot !== null}
        onOpenChange={(open) => {
          if (!open) setViewerSlot(null)
        }}
      >
        <DialogContent
          data-testid="browser-viewer-dialog"
          className="max-w-[min(1200px,95vw)] sm:max-w-[min(1200px,95vw)]"
        >
          <DialogHeader>
            <DialogTitle>
              {viewerSlot ? browserSlotLabel(viewerSlot) : "实时画面"}
            </DialogTitle>
            <DialogDescription>
              {viewerSlot?.occupied_account_name
                ? `当前绑定账号：${viewerSlot.occupied_account_name}`
                : "该槽位尚未绑定账号"}
            </DialogDescription>
          </DialogHeader>
          {viewerSlot?.viewer_url && (
            <iframe
              key={viewerSlot.viewer_url}
              src={viewerSlot.viewer_url}
              title={`${browserSlotLabel(viewerSlot)} 实时浏览器`}
              className="h-[70vh] w-full rounded-lg bg-slate-950"
              allow="clipboard-read; clipboard-write; fullscreen"
              // 远程画面需要在 iframe 内直接操作抖音页面，故放开脚本/同源/表单/弹窗；
              // 但不给 allow-top-navigation，避免被嵌入页面劫持顶层窗口跳转。
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
            />
          )}
          <div className="flex justify-end gap-2">
            {viewerSlot?.viewer_url && (
              <Button variant="outline" asChild>
                <a
                  href={viewerSlot.viewer_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  <Maximize2 />
                  新窗口操作
                </a>
              </Button>
            )}
            <Button variant="ghost" asChild>
              <Link to="/douyin-accounts">
                账号管理 <ExternalLink />
              </Link>
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

/** 单个分栏的槽位列表：一行一个槽位，行内完成登录、查看画面与复制端点。 */
function SlotTable({
  mode,
  slots,
  loading,
  isVisible,
  visibleCount,
  columnMenu,
  onLogin,
  loginPendingAccountId,
  onOpenViewer,
  copiedEndpoint,
  onCopyEndpoint,
  localBrowserByName,
  onEditLocal,
  onDeleteLocal,
}: {
  mode: SlotMode
  slots: DouyinBrowserSlotPublic[]
  loading: boolean
  isVisible: (key: string) => boolean
  visibleCount: number
  columnMenu: ReactNode
  onLogin: (accountId: string) => void
  loginPendingAccountId: string | null
  localBrowserByName: Map<string, DouyinLocalBrowserPublic>
  onEditLocal: (target: DouyinLocalBrowserPublic) => void
  onDeleteLocal: (target: DouyinLocalBrowserPublic) => void
  onOpenViewer: (slot: DouyinBrowserSlotPublic) => void
  copiedEndpoint: string | null
  onCopyEndpoint: (text: string) => void
}) {
  const onlineCount = slots.filter((slot) => slot.cdp_healthy).length
  const emptyState = EMPTY_STATES[mode]
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-3">
        <CardTitle className="text-base">
          {mode === "local" ? "本机浏览器槽位" : "云端浏览器槽位"}
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            共 {slots.length} 个 · {onlineCount} 个在线
          </span>
        </CardTitle>
        {columnMenu}
      </CardHeader>
      <CardContent className="px-3 pb-3">
        <div
          data-testid="browser-slot-table"
          data-browser-mode={mode}
          className="overflow-x-auto rounded-xl border"
        >
          <Table className="min-w-[1000px]">
            <TableHeader>
              <TableRow>
                {/* 报告 A1：表头与下方每一行的单元格必须用同一个 isVisible(key)
                    判断，漏一处列就会整体错位 */}
                {isVisible("status") && <TableHead>连接状态</TableHead>}
                {isVisible("slot") && <TableHead>槽位</TableHead>}
                {isVisible("endpoint") && <TableHead>CDP 端点</TableHead>}
                {isVisible("account") && <TableHead>绑定账号</TableHead>}
                {isVisible("pages") && <TableHead>页面数</TableHead>}
                {isVisible("page") && <TableHead>当前活动页面</TableHead>}
                {isVisible("latency") && <TableHead>探测延迟</TableHead>}
                {isVisible("checked") && <TableHead>最近探测</TableHead>}
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {slots.map((slot) => {
                // 本机槽位行需要拿到实例 id 才能重命名 / 删除
                const local =
                  mode === "local" && slot.name
                    ? localBrowserByName.get(slot.name)
                    : undefined
                return (
                  <TableRow key={slot.name ?? "__default__"}>
                    {isVisible("status") && (
                      <TableCell>
                        <span className="inline-flex items-center gap-1.5">
                          <span
                            role="img"
                            aria-label={
                              slot.cdp_healthy ? "浏览器在线" : "浏览器离线"
                            }
                            className={`size-2.5 rounded-full ${
                              slot.cdp_healthy
                                ? "bg-emerald-500"
                                : "bg-rose-500"
                            }`}
                          />
                          {slot.cdp_healthy ? "在线" : "离线"}
                        </span>
                      </TableCell>
                    )}
                    {isVisible("slot") && (
                      <TableCell>
                        <span className="flex items-center gap-1.5 font-medium">
                          {mode === "local" ? (
                            <Laptop className="size-4" aria-hidden="true" />
                          ) : (
                            <Server className="size-4" aria-hidden="true" />
                          )}
                          {browserSlotLabel(slot)}
                          {slot.is_default && (
                            <Badge variant="secondary">默认</Badge>
                          )}
                        </span>
                      </TableCell>
                    )}
                    {isVisible("endpoint") && (
                      <TableCell>
                        {slot.cdp_endpoint ? (
                          <span
                            data-testid="browser-cdp-endpoint"
                            className="flex items-center gap-1"
                          >
                            <code className="font-mono text-xs">
                              {slot.cdp_endpoint}
                            </code>
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              aria-label={`复制 ${browserSlotLabel(slot)} 的 CDP 端点`}
                              onClick={() =>
                                onCopyEndpoint(slot.cdp_endpoint as string)
                              }
                            >
                              <Copy />
                            </Button>
                            {copiedEndpoint === slot.cdp_endpoint && (
                              <span className="text-xs text-muted-foreground">
                                已复制
                              </span>
                            )}
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            未配置
                          </span>
                        )}
                      </TableCell>
                    )}
                    {isVisible("account") && (
                      <TableCell>
                        {slot.occupied_account_name ? (
                          <span className="inline-flex items-center gap-1.5">
                            {slot.occupied_account_name}
                            <Badge variant="secondary">已绑定</Badge>
                          </span>
                        ) : slot.available ? (
                          <Badge variant="outline">可绑定</Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            未绑定
                          </span>
                        )}
                      </TableCell>
                    )}
                    {isVisible("pages") && (
                      <TableCell className="text-sm text-muted-foreground">
                        {slot.page_count} 页
                      </TableCell>
                    )}
                    {isVisible("page") && (
                      <TableCell>
                        <span
                          data-testid="browser-active-page"
                          className="flex max-w-72 items-center gap-1"
                        >
                          <span className="truncate text-xs text-muted-foreground">
                            {slot.active_page_title ||
                              slot.active_page_url ||
                              "等待页面信息"}
                          </span>
                          {slot.active_page_url && (
                            <Button size="icon-sm" variant="ghost" asChild>
                              <a
                                href={slot.active_page_url}
                                target="_blank"
                                rel="noreferrer"
                                aria-label="打开当前活动页面"
                              >
                                <ExternalLink />
                              </a>
                            </Button>
                          )}
                        </span>
                      </TableCell>
                    )}
                    {isVisible("latency") && (
                      <TableCell className="text-sm text-muted-foreground">
                        {slot.latency_ms != null
                          ? `${slot.latency_ms} ms`
                          : "—"}
                      </TableCell>
                    )}
                    {isVisible("checked") && (
                      <TableCell className="text-sm text-muted-foreground">
                        <TimeAgo value={slot.checked_at} neverText="—" />
                      </TableCell>
                    )}
                    <TableCell>
                      <div
                        data-testid="browser-slot-actions"
                        className="flex items-center justify-end gap-1"
                      >
                        {slot.occupied_account_id && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() =>
                              onLogin(slot.occupied_account_id as string)
                            }
                            disabled={
                              loginPendingAccountId === slot.occupied_account_id
                            }
                          >
                            <LogIn />
                            {loginPendingAccountId === slot.occupied_account_id
                              ? "登录中…"
                              : "登录该账号"}
                          </Button>
                        )}
                        {slot.viewer_url && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => onOpenViewer(slot)}
                          >
                            <MonitorCog />
                            查看画面
                          </Button>
                        )}
                        {mode === "local" && local && (
                          <>
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              aria-label={`重命名本机浏览器 ${local.label}`}
                              onClick={() => onEditLocal(local)}
                            >
                              <Pencil />
                            </Button>
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              aria-label={`删除本机浏览器 ${local.label}`}
                              disabled={local.in_use}
                              title={
                                local.in_use
                                  ? "该实例已被账号绑定，请先在账号池解绑"
                                  : "删除该本机浏览器实例"
                              }
                              className="text-destructive hover:text-destructive disabled:text-muted-foreground"
                              onClick={() => onDeleteLocal(local)}
                            >
                              <Trash2 />
                            </Button>
                          </>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
              {!slots.length && loading && (
                <TableRow>
                  <TableCell
                    colSpan={visibleCount}
                    className="h-32 text-center text-sm text-muted-foreground"
                  >
                    正在读取浏览器槽位…
                  </TableCell>
                </TableRow>
              )}
              {!slots.length && !loading && (
                <TableRow>
                  <TableCell
                    colSpan={visibleCount}
                    className="h-32 text-center text-sm text-muted-foreground"
                  >
                    <p className="font-medium text-foreground">
                      {emptyState.title}
                    </p>
                    <p className="mt-1">{emptyState.description}</p>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

/**
 * 本机浏览器实例编辑器：新增（服务端自动分配槽位名与端口）或重命名 / 启停。
 *
 * 背景：本机槽位过去只能通过 config.yaml / 环境变量扩容，用户在页面上无法
 * 增加第 5 个浏览器。这里把增删改放到实例表里，新增时只需给个展示名称。
 */
function LocalBrowserEditorDialog({
  state,
  onClose,
  onSaved,
  onError,
}: {
  state: { mode: "create" } | { mode: "edit"; target: DouyinLocalBrowserPublic }
  onClose: () => void
  onSaved: () => Promise<void>
  onError: (message: string) => void
}) {
  const { showSuccessToast } = useCustomToast()
  const editing = state.mode === "edit" ? state.target : null
  const [label, setLabel] = useState(editing?.label ?? "")
  const [enabled, setEnabled] = useState(editing?.enabled ?? true)

  const save = useMutation({
    mutationFn: () => {
      if (editing) {
        return DouyinAccountsService.updateLocalBrowserRoute({
          browserId: editing.id,
          requestBody: { label: label.trim() || null, enabled },
        })
      }
      return DouyinAccountsService.createLocalBrowserRoute({
        requestBody: { label: label.trim() || null },
      })
    },
    onSuccess: async (result) => {
      showSuccessToast(
        editing
          ? `本机浏览器「${result.label}」已更新`
          : `已新增本机浏览器「${result.label}」（${result.cdp_endpoint}）`,
      )
      await onSaved()
    },
    onError: (error) => handleError.call(onError, error as ApiError),
  })

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="sm:max-w-md" data-testid="local-browser-dialog">
        <DialogHeader>
          <DialogTitle>
            {editing ? `编辑「${editing.label}」` : "新增本机浏览器"}
          </DialogTitle>
          <DialogDescription>
            {editing
              ? `槽位 ${editing.name} 与 CDP 端口 ${editing.port} 由系统分配，不可修改。`
              : "新增后系统会自动分配槽位名与 CDP 调试端口，Profile 目录按槽位名创建，首次使用时启动浏览器并登录账号即可。"}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="local-browser-label">展示名称（可选）</Label>
            <Input
              id="local-browser-label"
              value={label}
              maxLength={80}
              autoFocus
              placeholder="例如：贴片机 5 / 备用浏览器"
              onChange={(event) => setLabel(event.target.value)}
            />
          </div>
          {editing && (
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4"
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
              />
              启用该实例（停用后不出现在可绑定槽位列表里）
            </label>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button disabled={save.isPending} onClick={() => save.mutate()}>
            {editing ? "保存" : "创建"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
