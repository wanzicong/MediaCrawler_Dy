import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  Download,
  Laptop,
  LogIn,
  MoreHorizontal,
  Plus,
  Server,
  ShieldCheck,
  Trash2,
  UsersRound,
} from "lucide-react"
import { type FormEvent, type ReactNode, useMemo, useState } from "react"

import {
  type ApiError,
  type DouyinAccountCreate,
  type DouyinAccountPoolStrategy,
  type DouyinAccountPublic,
  DouyinAccountsService,
  type DouyinBrowserMode,
  type DouyinBrowserSlotPublic,
} from "@/client"
import { confirmDialog } from "@/components/Common/confirm-dialog"
import { EmptyState } from "@/components/Common/EmptyState"
import { PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { RefreshIndicator } from "@/components/Common/RefreshIndicator"
import { TableColumnMenu } from "@/components/Common/TableColumnMenu"
import { TimeAgo } from "@/components/Common/TimeAgo"
import {
  type ListViewMode,
  usePersistentViewMode,
  ViewModeToggle,
} from "@/components/Common/ViewModeToggle"
import { browserSlotLabel } from "@/components/Douyin/presentation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useCustomToast from "@/hooks/useCustomToast"
import { useHighlightedRows } from "@/hooks/useHighlightedRows"
import { type TableColumnDef, useTableColumns } from "@/hooks/useTableColumns"
import { downloadCsv } from "@/lib/csv"
import { compactSearch, readEnumParam } from "@/lib/search-params"
import { cn } from "@/lib/utils"
import { handleError } from "@/utils"

// 报告 O4：筛选上 URL —— 本页没有搜索/状态/赛道筛选项，唯一的列表级 UI 状态
// 是「账号管理 / 账号池管理」标签页。把它纳入 URL 后，刷新、把链接分享给别人、
// 收藏都能回到同一个标签页。白名单用于挡住手改 URL 传进来的脏值。
const ACCOUNT_TAB_VALUES = ["accounts", "pools"] as const

type AccountTabValue = (typeof ACCOUNT_TAB_VALUES)[number]

// tab 声明为可选：等于默认值（accounts）的键不写进 URL，
// 所以地址栏未筛选时就是干净的 /douyin-accounts，类型也必须允许缺省。
type AccountsTabSearch = { tab?: AccountTabValue }

export const Route = createFileRoute("/_layout/douyin-accounts")({
  // 报告 O4：筛选上 URL —— 从 URL 安全读取标签页，不在白名单内返回 undefined
  validateSearch: (search: Record<string, unknown>): AccountsTabSearch => ({
    tab: readEnumParam(search, "tab", ACCOUNT_TAB_VALUES),
  }),
  component: DouyinAccountsPage,
  head: () => ({ meta: [{ title: "抖音账号池 - 灵感采集台" }] }),
})

const statusLabels: Record<DouyinAccountPublic["status"], string> = {
  login_required: "待登录",
  verifying: "待验证",
  ready: "可用",
  busy: "执行中",
  cooldown: "冷却中",
  unhealthy: "异常",
  disabled: "已停用",
}

// 报告 A1：列可见性 —— 账号表（table 视图）的列清单，key 与表头一一对应。
// 必须是模块级稳定常量：放进组件体内的话每次渲染都会新建一份新数组，
// useTableColumns 里的 useMemo 依赖失效、隐藏状态会被反复重置。
const ACCOUNT_COLUMNS = [
  { key: "name", title: "账号别名" },
  { key: "browser", title: "浏览器" },
  { key: "status", title: "状态" },
  { key: "tasks", title: "今日任务" },
  { key: "load", title: "并发 / 权重" },
  { key: "verified", title: "最后验证" },
  // 操作列藏掉用户就没法登录/验证/删除账号，永远可见、不进列设置菜单
  { key: "actions", title: "操作", alwaysVisible: true },
] as const satisfies readonly TableColumnDef[]

function DouyinAccountsPage() {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [loginPendingIds, setLoginPendingIds] = useState<Set<string>>(
    () => new Set(),
  )
  const [verifyPendingIds, setVerifyPendingIds] = useState<Set<string>>(
    () => new Set(),
  )
  const [viewMode, setViewMode] = usePersistentViewMode("douyin-accounts-view")
  // 报告 A1：列可见性 —— 只作用于 table 视图；cards / rows 视图不是表格，
  // 不读也不包 isVisible。storageKey 本页唯一。
  const { isVisible, visibleCount, menuProps } = useTableColumns({
    storageKey: "douyin-accounts-columns",
    columns: ACCOUNT_COLUMNS,
  })
  // 报告 O4：筛选上 URL —— 标签页以 URL 为唯一真源（初值即来自 URL），
  // 因此不需要额外的 useState + useEffect 去回写，也就没有 URL 与本地状态
  // 互相追赶、越写越多的死循环风险。
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  const changeTab = (value: string) => {
    // Radix 只会回传已声明的 value，这里再兜一层，挡住脏值写进 URL
    if (!(ACCOUNT_TAB_VALUES as readonly string[]).includes(value)) return
    // 白名单校验已在上方兜底，这里把 string 收窄回 AccountTabValue。
    // 不收窄的话 { tab: string } 会推出 tab: string，与 search 类型的
    // 字面量联合不兼容；也不该把 search 类型放宽成 string，那样会丢校验价值。
    const nextTab: AccountsTabSearch = compactSearch(
      { tab: value as AccountTabValue },
      { tab: "accounts" },
    )
    // 报告 O4：筛选上 URL —— 用 replace: true。不用 replace 的话，用户每切一次
    // 标签页就多一条浏览器历史，按十次后退才能离开这个页面；用 replace 后刷新、
    // 分享、深链、收藏都生效，但浏览器「后退」是回到上一个页面而不是上一个标签页。
    // 这是有意的取舍。
    void navigate({ to: "/douyin-accounts", replace: true, search: nextTab })
  }
  const accountsQuery = useQuery({
    queryKey: ["douyin-accounts"],
    queryFn: () => DouyinAccountsService.listAccounts({ limit: 100 }),
    retry: false,
    // 原为固定 5s 轮询，无活跃任务时也一直空转；改为仅当有账号执行中
    // （busy 或持有活跃租约）才轮询，全部空闲即停止，切回页面时 TanStack 会补刷一次。
    refetchInterval: (query) => {
      const rows = query.state.data?.data ?? []
      return rows.some(
        (item) => item.status === "busy" || item.active_leases > 0,
      )
        ? 5_000
        : false
    },
  })
  const poolsQuery = useQuery({
    queryKey: ["douyin-account-pools"],
    queryFn: () => DouyinAccountsService.listPools(),
    retry: false,
  })
  const slotsQuery = useQuery({
    queryKey: ["douyin-browser-slots"],
    queryFn: () => DouyinAccountsService.listBrowserSlots(),
    retry: false,
    refetchInterval: 5_000,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["douyin-accounts"] }),
      queryClient.invalidateQueries({ queryKey: ["douyin-account-pools"] }),
      queryClient.invalidateQueries({ queryKey: ["douyin-browser-slots"] }),
    ])
  }
  const login = useMutation({
    mutationFn: (accountId: string) =>
      DouyinAccountsService.startAccountLogin({ accountId }),
    onMutate: (accountId) => {
      setLoginPendingIds((current) => new Set(current).add(accountId))
    },
    onSuccess: async (result) => {
      const navigationMessage = result.viewer_url
        ? "已尝试在新窗口打开浏览器；若未出现，请允许本站弹出窗口。"
        : "浏览器已启动，请完成登录后回到本页验证。"
      if (result.viewer_url) {
        window.open(result.viewer_url, "_blank", "noopener,noreferrer")
      }
      showSuccessToast(
        [result.message?.trim(), navigationMessage].filter(Boolean).join(" "),
      )
      await invalidate()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
    onSettled: (_data, _error, accountId) => {
      setLoginPendingIds((current) => {
        const next = new Set(current)
        next.delete(accountId)
        return next
      })
    },
  })
  const verify = useMutation({
    mutationFn: (accountId: string) =>
      DouyinAccountsService.verifyAccountLogin({ accountId }),
    onMutate: (accountId) => {
      setVerifyPendingIds((current) => new Set(current).add(accountId))
    },
    onSuccess: async () => {
      showSuccessToast("登录验证成功，账号已进入可用池")
      await invalidate()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
    onSettled: (_data, _error, accountId) => {
      setVerifyPendingIds((current) => {
        const next = new Set(current)
        next.delete(accountId)
        return next
      })
    },
  })
  const toggle = useMutation({
    mutationFn: (account: DouyinAccountPublic) =>
      DouyinAccountsService.editAccount({
        accountId: account.id,
        requestBody: { enabled: !account.enabled },
      }),
    onSuccess: invalidate,
    onError: handleError.bind(showErrorToast),
  })
  const remove = useMutation({
    mutationFn: (accountId: string) =>
      DouyinAccountsService.deleteAccount({ accountId }),
    onSuccess: async () => {
      showSuccessToast("账号和专属浏览器空间已删除")
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const removePool = useMutation({
    mutationFn: (poolId: string) =>
      DouyinAccountsService.deletePool({ poolId }),
    onSuccess: async () => {
      showSuccessToast("账号池已删除，账号与登录状态不受影响")
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const accounts = accountsQuery.data?.data ?? []
  const browserSlots = slotsQuery.data?.data ?? []
  // 顶部统计是派生值，原为每次 render 重算（账号/槽位多时纯属白跑），用 useMemo 收敛
  const ready = useMemo(
    () =>
      (accountsQuery.data?.data ?? []).filter((item) => item.status === "ready")
        .length,
    [accountsQuery.data],
  )
  const busy = useMemo(
    () =>
      (accountsQuery.data?.data ?? []).filter((item) => item.status === "busy")
        .length,
    [accountsQuery.data],
  )
  const availableSlots = useMemo(
    () => (slotsQuery.data?.data ?? []).filter((item) => item.available).length,
    [slotsQuery.data],
  )
  // 报告 A6：轮询刷新后数据真正变化的账号行闪一下；指纹取 status + last_used_at，
  // 只有这两个字段变化才代表账号状态/使用情况变了（列表顺序变动不闪）。
  const highlightedAccountIds = useHighlightedRows(
    accounts,
    (account) => account.id,
    (account) => `${account.status}:${account.last_used_at ?? ""}`,
  )
  // 报告 A12：只导出当前已加载的账号（接口 limit 100，属于小数据量即时导出）
  const exportAccounts = () => {
    downloadCsv("抖音账号池", accounts, [
      { header: "账号别名", value: (row) => row.name },
      {
        header: "浏览器",
        value: (row) =>
          row.browser_mode === "remote"
            ? row.remote_slot || "云端默认槽位"
            : "本机专属浏览器",
      },
      { header: "状态", value: (row) => statusLabels[row.status] },
      { header: "今日任务", value: (row) => row.tasks_today },
      { header: "每日任务上限", value: (row) => row.daily_task_limit },
      { header: "活跃租约", value: (row) => row.active_leases },
      { header: "并发上限", value: (row) => row.concurrency_limit },
      { header: "权重", value: (row) => row.weight },
      { header: "连续失败次数", value: (row) => row.failure_streak },
      { header: "最后验证", value: (row) => row.last_verified_at ?? "" },
      { header: "最后使用", value: (row) => row.last_used_at ?? "" },
    ])
  }

  return (
    <div className="page-stack">
      <PageHero
        compact
        title="抖音账号池"
        actions={
          <div className="flex flex-wrap gap-1.5">
            {/* 报告 A14：刷新指示器 —— 本页此前没有任何手动刷新入口，
                补上「上次更新时间 + 手动刷新」；自动刷新仍由 accountsQuery 的
                refetchInterval（仅账号执行中轮询）决定，故不暴露自动刷新开关。 */}
            <RefreshIndicator
              updatedAt={accountsQuery.dataUpdatedAt}
              refreshing={accountsQuery.isFetching}
              onRefresh={() => void accountsQuery.refetch()}
            />
            <CreatePoolDialog accounts={accounts} onCreated={invalidate} />
            <CreateAccountDialog
              slots={browserSlots}
              slotsLoading={slotsQuery.isLoading}
              onCreated={invalidate}
            />
          </div>
        }
      >
        <p className="text-xs text-muted-foreground">
          账号{" "}
          <strong className="text-foreground">
            {accountsQuery.isError ? "—" : accounts.length}
          </strong>{" "}
          · 可用{" "}
          <strong className="text-foreground">
            {accountsQuery.isError ? "—" : ready}
          </strong>{" "}
          · 执行中{" "}
          <strong className="text-foreground">
            {accountsQuery.isError ? "—" : busy}
          </strong>{" "}
          · 远程槽位{" "}
          <strong className="text-foreground">
            {slotsQuery.isError
              ? "—"
              : `${availableSlots}/${browserSlots.length}`}
          </strong>
        </p>
      </PageHero>

      <Tabs
        // 报告 O4：筛选上 URL —— 受控标签页，值来自 URL；URL 未带 tab 时回落到
        // 默认的「账号管理」，于是未筛选时地址栏仍是干净的 /douyin-accounts
        value={search.tab ?? "accounts"}
        onValueChange={changeTab}
        className="space-y-2"
      >
        <TabsList className="grid h-9 w-full max-w-sm grid-cols-2">
          <TabsTrigger value="accounts">
            账号管理（{accounts.length}）
          </TabsTrigger>
          <TabsTrigger value="pools">
            账号池管理（{poolsQuery.data?.count ?? 0}）
          </TabsTrigger>
        </TabsList>

        <TabsContent value="accounts" className="space-y-2">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-3 p-3">
              <CardTitle className="text-base">账号与专属浏览器</CardTitle>
              <div className="flex items-center gap-1">
                {/* 报告 A12：导出当前页账号（含配额、并发、失败次数等数值列） */}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={exportAccounts}
                  disabled={!accounts.length}
                  aria-label="导出账号 CSV"
                >
                  <Download /> 导出
                </Button>
                {/* 报告 A1：列可见性 —— 列设置入口只在 table 视图出现，
                    cards / rows 视图没有列的概念 */}
                {viewMode === "table" && <TableColumnMenu {...menuProps} />}
                <ViewModeToggle value={viewMode} onChange={setViewMode} />
              </div>
            </CardHeader>
            <CardContent className="px-3 pb-3">
              {/* 已知重复实现：table 视图把「错误/加载/空」三态内联进表格行（见下方
                  TableBody），cards/rows 视图又在同一三元里重复写了一遍三态。本次
                  刻意不合并以控制改动风险，后续应抽出统一的 AccountsListBody 组件，
                  让两种视图共用同一份三态渲染。 */}
              {viewMode === "table" ? (
                <div className="overflow-x-auto rounded-xl border">
                  {/* 报告 O21：列多（7 列且操作列含三个按钮），窄屏靠外层
                      overflow-x-auto 横滚；给表格一个最小宽度，避免列被压扁挤爆 */}
                  <Table className="min-w-[900px]">
                    <TableHeader>
                      <TableRow>
                        {/* 报告 A1：列可见性 —— 表头与下方每一行的单元格必须
                            用同一个 isVisible(key) 判断，漏一处列就会整体错位 */}
                        {isVisible("name") && <TableHead>账号别名</TableHead>}
                        {isVisible("browser") && <TableHead>浏览器</TableHead>}
                        {isVisible("status") && <TableHead>状态</TableHead>}
                        {isVisible("tasks") && <TableHead>今日任务</TableHead>}
                        {isVisible("load") && (
                          <TableHead>并发 / 权重</TableHead>
                        )}
                        {isVisible("verified") && (
                          <TableHead>最后验证</TableHead>
                        )}
                        {/* 操作列 alwaysVisible，恒渲染 */}
                        <TableHead className="text-right">操作</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {accountsQuery.isError ? (
                        <TableRow>
                          {/* 报告 A1：列可见性 —— 错误/加载/空三态行的 colSpan
                              必须用 visibleCount，写死 7 的话隐藏列后只占一半宽度 */}
                          <TableCell colSpan={visibleCount} className="p-4">
                            <QueryErrorState
                              title="账号列表读取失败"
                              description="暂时无法获取账号数据，请检查服务连接后重试。"
                              onRetry={() => void accountsQuery.refetch()}
                              retrying={accountsQuery.isFetching}
                              className="border-0 bg-transparent py-6"
                            />
                          </TableCell>
                        </TableRow>
                      ) : accountsQuery.isLoading ? (
                        <TableRow>
                          <TableCell
                            colSpan={visibleCount}
                            className="h-36 text-center text-muted-foreground"
                          >
                            正在加载账号…
                          </TableCell>
                        </TableRow>
                      ) : accounts.length ? (
                        accounts.map((account) => (
                          <TableRow
                            key={account.id}
                            // 报告 A6：数据变化（状态/最后使用时间）时该行闪一下
                            className={cn(
                              highlightedAccountIds.has(account.id) &&
                                "row-highlight",
                            )}
                          >
                            {/* 报告 A1：列可见性 —— 每个单元格与上方表头同键判断 */}
                            {isVisible("name") && (
                              <TableCell>
                                <p className="font-medium">{account.name}</p>
                                {[
                                  "login_required",
                                  "verifying",
                                  "unhealthy",
                                ].includes(account.status) &&
                                  account.last_error && (
                                    <p className="mt-1 max-w-72 truncate text-xs text-destructive">
                                      {account.last_error}
                                    </p>
                                  )}
                              </TableCell>
                            )}
                            {isVisible("browser") && (
                              <TableCell>
                                <span className="inline-flex items-center gap-1.5">
                                  {/* 报告 20：只读装饰图标对读屏隐藏，文案已说明浏览器位置 */}
                                  {account.browser_mode === "remote" ? (
                                    <Server
                                      className="size-4"
                                      aria-hidden="true"
                                    />
                                  ) : (
                                    <Laptop
                                      className="size-4"
                                      aria-hidden="true"
                                    />
                                  )}
                                  {account.browser_mode === "remote"
                                    ? account.remote_slot || "云端默认槽位"
                                    : "本机专属浏览器"}
                                </span>
                              </TableCell>
                            )}
                            {isVisible("status") && (
                              <TableCell>
                                <Badge
                                  variant={
                                    ["unhealthy", "disabled"].includes(
                                      account.status,
                                    )
                                      ? "destructive"
                                      : account.status === "ready"
                                        ? "default"
                                        : "secondary"
                                  }
                                >
                                  {statusLabels[account.status]}
                                </Badge>
                              </TableCell>
                            )}
                            {isVisible("tasks") && (
                              <TableCell>
                                {account.tasks_today} /{" "}
                                {account.daily_task_limit}
                              </TableCell>
                            )}
                            {isVisible("load") && (
                              <TableCell>
                                {account.active_leases}/
                                {account.concurrency_limit} · ×{account.weight}
                              </TableCell>
                            )}
                            {isVisible("verified") && (
                              <TableCell className="whitespace-nowrap text-muted-foreground">
                                {/* 报告 A16：时间点改为相对时间，悬停看绝对时间 */}
                                <TimeAgo
                                  value={account.last_verified_at}
                                  neverText="从未"
                                />
                              </TableCell>
                            )}
                            <TableCell>
                              <div className="flex justify-end gap-1">
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => login.mutate(account.id)}
                                  disabled={
                                    loginPendingIds.has(account.id) ||
                                    verifyPendingIds.has(account.id) ||
                                    account.active_leases > 0
                                  }
                                >
                                  <LogIn /> 登录
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => verify.mutate(account.id)}
                                  disabled={
                                    loginPendingIds.has(account.id) ||
                                    verifyPendingIds.has(account.id) ||
                                    account.active_leases > 0
                                  }
                                >
                                  <ShieldCheck /> 验证
                                </Button>
                                {/* 报告 O10：低频操作收进「更多」菜单，操作列只留
                                    「登录」「验证」两个高频入口 */}
                                <DropdownMenu>
                                  <DropdownMenuTrigger asChild>
                                    <Button
                                      size="icon-sm"
                                      variant="ghost"
                                      aria-label="更多账号操作"
                                    >
                                      <MoreHorizontal />
                                    </Button>
                                  </DropdownMenuTrigger>
                                  <DropdownMenuContent align="end">
                                    <DropdownMenuItem
                                      onSelect={() => toggle.mutate(account)}
                                      disabled={
                                        toggle.isPending ||
                                        account.active_leases > 0
                                      }
                                    >
                                      {account.enabled
                                        ? "停用账号"
                                        : "启用账号"}
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                      variant="destructive"
                                      disabled={
                                        remove.isPending ||
                                        account.active_leases > 0
                                      }
                                      // 报告 O15：改用统一确认框
                                      onSelect={async () => {
                                        const ok = await confirmDialog({
                                          title: `删除账号“${account.name}”？`,
                                          description:
                                            "账号及其专属浏览器空间会一并删除，操作不可撤销。",
                                          confirmText: "删除",
                                          variant: "destructive",
                                        })
                                        if (ok) remove.mutate(account.id)
                                      }}
                                    >
                                      <Trash2 /> 删除账号
                                    </DropdownMenuItem>
                                  </DropdownMenuContent>
                                </DropdownMenu>
                              </div>
                            </TableCell>
                          </TableRow>
                        ))
                      ) : (
                        <TableRow>
                          <TableCell
                            colSpan={visibleCount}
                            className="h-36 text-center text-muted-foreground"
                          >
                            尚未添加账号。先创建账号，再打开它的独立浏览器完成登录。
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </div>
              ) : accountsQuery.isError ? (
                <QueryErrorState
                  title="账号列表读取失败"
                  description="暂时无法获取账号数据，请检查服务连接后重试。"
                  onRetry={() => void accountsQuery.refetch()}
                  retrying={accountsQuery.isFetching}
                />
              ) : accountsQuery.isLoading ? (
                <p className="py-14 text-center text-sm text-muted-foreground">
                  正在加载账号…
                </p>
              ) : accounts.length ? (
                <div
                  className={
                    viewMode === "cards"
                      ? "grid gap-3 md:grid-cols-2 xl:grid-cols-3"
                      : "space-y-2"
                  }
                >
                  {/* 已知重复：cards/rows 的三态渲染与 table 视图内联实现是两份代码，
                      本次刻意不合并（见 CardContent 顶部说明），后续统一。 */}
                  {accounts.map((account) => (
                    <AccountPreview
                      key={account.id}
                      account={account}
                      viewMode={viewMode}
                      loginPending={loginPendingIds.has(account.id)}
                      verifyPending={verifyPendingIds.has(account.id)}
                      actionPending={toggle.isPending || remove.isPending}
                      onLogin={() => login.mutate(account.id)}
                      onVerify={() => verify.mutate(account.id)}
                      onToggle={() => toggle.mutate(account)}
                      // 报告 O15：改用统一确认框
                      onDelete={async () => {
                        const ok = await confirmDialog({
                          title: `删除账号“${account.name}”？`,
                          description:
                            "账号及其专属浏览器空间会一并删除，操作不可撤销。",
                          confirmText: "删除",
                          variant: "destructive",
                        })
                        if (ok) remove.mutate(account.id)
                      }}
                    />
                  ))}
                </div>
              ) : (
                <p className="py-14 text-center text-sm text-muted-foreground">
                  尚未添加账号。先创建账号，再打开它的独立浏览器完成登录。
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="pools">
          {poolsQuery.isError ? (
            <QueryErrorState
              title="账号池列表读取失败"
              description="暂时无法获取账号池数据，请检查服务连接后重试。"
              onRetry={() => void poolsQuery.refetch()}
              retrying={poolsQuery.isFetching}
            />
          ) : poolsQuery.isLoading ? (
            // 报告 A4/O8：加载态由「正在加载…」纯文字改成骨架屏，占位高度贴近
            // 账号池卡片，数据到达时不会整块跳动
            <div className="grid gap-4 lg:grid-cols-2">
              {Array.from({ length: 2 }, (_, index) => (
                <Skeleton
                  key={`pool-skeleton-${index}`}
                  className="h-44 w-full rounded-2xl"
                  aria-hidden="true"
                />
              ))}
            </div>
          ) : poolsQuery.data?.data?.length ? (
            <div className="grid gap-4 lg:grid-cols-2">
              {(poolsQuery.data?.data ?? []).map((pool) => (
                <Card key={pool.id}>
                  <CardHeader>
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <CardTitle>{pool.name}</CardTitle>
                        <p className="mt-1 text-sm text-muted-foreground">
                          {pool.description || "账号轮换池"}
                        </p>
                      </div>
                      <div className="flex items-center gap-1">
                        <Badge variant="outline">
                          {pool.strategy === "least_loaded"
                            ? "最少负载"
                            : pool.strategy === "round_robin"
                              ? "顺序轮询"
                              : "加权轮询"}
                        </Badge>
                        <Button
                          size="icon-sm"
                          variant="ghost"
                          aria-label="删除账号池"
                          // 报告 O15：改用统一确认框
                          onClick={async () => {
                            const ok = await confirmDialog({
                              title: `删除账号池“${pool.name}”？`,
                              description:
                                "只删除池本身，池内账号与登录状态不受影响。",
                              confirmText: "删除",
                              variant: "destructive",
                            })
                            if (ok) removePool.mutate(pool.id)
                          }}
                        >
                          <Trash2 />
                        </Button>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm">
                      最多并行 {pool.max_parallel_accounts} 个账号 · 已加入{" "}
                      {pool.accounts.length} 个
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {pool.accounts.map((account) => (
                        <Badge key={account.id} variant="secondary">
                          {account.name} · {statusLabels[account.status]}
                        </Badge>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            // 原来这里没有空态，用户看到一片空白；补上说明与引导（报告 A4/O8）
            <EmptyState
              icon={UsersRound}
              title="还没有账号池"
              description="账号池把多个账号组合起来并行分片跑任务，能显著提升采集吞吐。先到「账号管理」添加并登录账号，再回到这里创建账号池。"
              // 报告 A4/O8：空态不能只给说明不给出口，复用同一个创建弹窗做引导
              action={
                <CreatePoolDialog
                  accounts={accounts}
                  onCreated={invalidate}
                  trigger={
                    <Button>
                      <Plus />
                      创建第一个账号池
                    </Button>
                  }
                />
              }
            />
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}

function AccountPreview({
  account,
  viewMode,
  loginPending,
  verifyPending,
  actionPending,
  onLogin,
  onVerify,
  onToggle,
  onDelete,
}: {
  account: DouyinAccountPublic
  viewMode: Exclude<ListViewMode, "table">
  loginPending: boolean
  verifyPending: boolean
  actionPending: boolean
  onLogin: () => void
  onVerify: () => void
  onToggle: () => void
  onDelete: () => void | Promise<void>
}) {
  const unavailable = loginPending || verifyPending || account.active_leases > 0
  return (
    <div
      className={`rounded-xl border bg-card p-4 ${
        viewMode === "rows" ? "flex flex-wrap items-center gap-4" : "space-y-4"
      }`}
    >
      <div className={viewMode === "rows" ? "min-w-48 flex-1" : "min-w-0"}>
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-medium">{account.name}</p>
          <Badge
            variant={
              ["unhealthy", "disabled"].includes(account.status)
                ? "destructive"
                : account.status === "ready"
                  ? "default"
                  : "secondary"
            }
          >
            {statusLabels[account.status]}
          </Badge>
        </div>
        <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
          {/* 报告 20：只读装饰图标对读屏隐藏，文案已说明浏览器位置 */}
          {account.browser_mode === "remote" ? (
            <Server className="size-3.5" aria-hidden="true" />
          ) : (
            <Laptop className="size-3.5" aria-hidden="true" />
          )}
          {account.browser_mode === "remote"
            ? account.remote_slot || "云端默认槽位"
            : "本机专属浏览器"}
        </p>
        {["login_required", "verifying", "unhealthy"].includes(
          account.status,
        ) &&
          account.last_error && (
            <p className="mt-1 line-clamp-2 text-xs text-destructive">
              {account.last_error}
            </p>
          )}
      </div>
      <div className="grid shrink-0 grid-cols-3 gap-4 text-xs">
        <div>
          <p className="text-muted-foreground">今日任务</p>
          <p className="mt-1 font-medium">
            {account.tasks_today} / {account.daily_task_limit}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground">并发 / 权重</p>
          <p className="mt-1 font-medium">
            {account.active_leases}/{account.concurrency_limit} · ×
            {account.weight}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground">最后验证</p>
          <p className="mt-1 whitespace-nowrap font-medium">
            {/* 报告 A16：时间点改为相对时间，悬停看绝对时间 */}
            <TimeAgo value={account.last_verified_at} neverText="从未" />
          </p>
        </div>
      </div>
      <div className="ml-auto flex flex-wrap justify-end gap-1">
        <Button
          size="sm"
          variant="outline"
          onClick={onLogin}
          disabled={unavailable}
        >
          <LogIn /> 登录
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={onVerify}
          disabled={unavailable}
        >
          <ShieldCheck /> 验证
        </Button>
        {/* 报告 O10：低频操作收进「更多」菜单，只留「登录」「验证」在行内 */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon-sm" variant="ghost" aria-label="更多账号操作">
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem
              onSelect={onToggle}
              disabled={actionPending || account.active_leases > 0}
            >
              {account.enabled ? "停用账号" : "启用账号"}
            </DropdownMenuItem>
            <DropdownMenuItem
              variant="destructive"
              onSelect={() => void onDelete()}
              disabled={actionPending || account.active_leases > 0}
            >
              <Trash2 /> 删除账号
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  )
}

function CreateAccountDialog({
  slots,
  slotsLoading,
  onCreated,
}: {
  slots: DouyinBrowserSlotPublic[]
  slotsLoading: boolean
  onCreated: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [mode, setMode] = useState<DouyinBrowserMode>("remote")
  const [slot, setSlot] = useState("__auto__")
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const mutation = useMutation({
    mutationFn: (requestBody: DouyinAccountCreate) =>
      DouyinAccountsService.addAccount({ requestBody }),
    onSuccess: async () => {
      showSuccessToast("账号已创建，请继续执行登录和验证")
      setOpen(false)
      setName("")
      setSlot("__auto__")
      await onCreated()
    },
    onError: handleError.bind(showErrorToast),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const selectedSlot =
      slot === "__auto__"
        ? slots.find((item) => item.available)
        : slots.find((item) => (item.name ?? "__default__") === slot)
    mutation.mutate({
      name: name.trim(),
      browser_mode: mode,
      remote_slot:
        mode === "remote" ? (selectedSlot?.name ?? undefined) : undefined,
    })
  }
  const availableSlots = slots.filter((item) => item.available)
  const noRemoteSlot =
    mode === "remote" && !slotsLoading && !availableSlots.length
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus />
          添加账号
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={submit} className="space-y-5">
          <DialogHeader>
            <DialogTitle>添加托管账号</DialogTitle>
            <DialogDescription>
              账号别名仅用于后台识别，不需要填写抖音号。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="account-name">账号别名</Label>
            <Input
              id="account-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label>浏览器位置</Label>
            <Select
              value={mode}
              onValueChange={(value) => setMode(value as DouyinBrowserMode)}
            >
              {/* 报告 20：下拉触发器补可访问名称 */}
              <SelectTrigger className="w-full" aria-label="浏览器位置">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="remote">云端托管浏览器</SelectItem>
                <SelectItem value="local">本机专属浏览器</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {mode === "remote" && (
            <div className="space-y-2">
              <Label htmlFor="remote-slot">远程浏览器槽位</Label>
              <Select
                value={slot}
                onValueChange={setSlot}
                disabled={slotsLoading || !slots.length}
              >
                <SelectTrigger id="remote-slot" className="w-full">
                  <SelectValue
                    placeholder={slotsLoading ? "读取槽位…" : "选择槽位"}
                  />
                </SelectTrigger>
                <SelectContent>
                  {availableSlots.length > 0 && (
                    <SelectItem value="__auto__">
                      自动分配（{browserSlotLabel(availableSlots[0])}）
                    </SelectItem>
                  )}
                  {slots.map((item) => (
                    <SelectItem
                      key={item.name ?? "__default__"}
                      value={item.name ?? "__default__"}
                      disabled={!item.available}
                    >
                      {browserSlotLabel(item)}
                      {!item.configured
                        ? " · 配置异常"
                        : item.occupied_account_name
                          ? ` · 已绑定 ${item.occupied_account_name}`
                          : " · 可用"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                留在“自动分配”即可；系统会选择第一个可用槽位，不需要手填名称。
              </p>
              {noRemoteSlot && (
                <p className="text-xs text-destructive">
                  当前没有可用远程槽位。可删除占用账号、改用本机模式，或启动更多
                  云端浏览器槽位。
                </p>
              )}
            </div>
          )}
          <DialogFooter>
            <Button
              type="submit"
              disabled={mutation.isPending || !name.trim() || noRemoteSlot}
            >
              创建账号
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function CreatePoolDialog({
  accounts,
  onCreated,
  trigger,
}: {
  accounts: DouyinAccountPublic[]
  onCreated: () => Promise<void>
  /** 自定义触发按钮：空态里需要换成「创建第一个账号池」的引导文案 */
  trigger?: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  // 用 Set 承载勾选：原数组 includes / filter 每次都是 O(n)，账号多时明显
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [strategy, setStrategy] =
    useState<DouyinAccountPoolStrategy>("least_loaded")
  const [maxParallel, setMaxParallel] = useState(2)
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const mutation = useMutation({
    mutationFn: () =>
      DouyinAccountsService.addPool({
        requestBody: {
          name: name.trim(),
          account_ids: [...selected],
          strategy,
          max_parallel_accounts: Math.max(
            1,
            Math.min(maxParallel, selected.size),
          ),
        },
      }),
    onSuccess: async () => {
      showSuccessToast("账号池已创建")
      setOpen(false)
      setName("")
      setSelected(new Set())
      setStrategy("least_loaded")
      setMaxParallel(2)
      await onCreated()
    },
    onError: handleError.bind(showErrorToast),
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button variant="outline">
            <UsersRound />
            创建账号池
          </Button>
        )}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>创建并行账号池</DialogTitle>
          <DialogDescription>
            任务会按最少负载选择账号；不同目标可并行分片。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          {/* 报告 20：输入框此前没有可访问名称，视觉上的 Label 未与控件关联 */}
          <Label htmlFor="pool-name">账号池名称</Label>
          <Input
            id="pool-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label>加入账号</Label>
          <div className="max-h-56 space-y-2 overflow-y-auto rounded-lg border p-3">
            {accounts.map((account) => (
              <div key={account.id} className="flex items-center gap-2 text-sm">
                <Checkbox
                  // 报告 20：行选择框要能听出勾的是哪个账号
                  aria-label={`选择账号 ${account.name}`}
                  checked={selected.has(account.id)}
                  onCheckedChange={(checked) =>
                    setSelected((current) => {
                      const next = new Set(current)
                      if (checked) next.add(account.id)
                      else next.delete(account.id)
                      return next
                    })
                  }
                />
                {account.name}{" "}
                <span className="text-muted-foreground">
                  {statusLabels[account.status]}
                </span>
              </div>
            ))}
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label>调度策略</Label>
            <Select
              value={strategy}
              onValueChange={(value) =>
                setStrategy(value as DouyinAccountPoolStrategy)
              }
            >
              {/* 报告 20：下拉触发器补可访问名称 */}
              <SelectTrigger className="w-full" aria-label="调度策略">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="least_loaded">最少负载</SelectItem>
                <SelectItem value="round_robin">顺序轮询</SelectItem>
                <SelectItem value="weighted_round_robin">加权轮询</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="pool-parallel">最大并行账号</Label>
            <Input
              id="pool-parallel"
              type="number"
              min={1}
              max={20}
              value={maxParallel}
              onChange={(event) => setMaxParallel(Number(event.target.value))}
            />
          </div>
        </div>
        <DialogFooter>
          <Button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || !name.trim() || selected.size === 0}
          >
            创建账号池
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
