import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  CircleGauge,
  Laptop,
  LogIn,
  Plus,
  Server,
  ShieldCheck,
  Trash2,
  UsersRound,
} from "lucide-react"
import { type FormEvent, useState } from "react"

import {
  type ApiError,
  type DouyinAccountCreate,
  type DouyinAccountPoolStrategy,
  type DouyinAccountPublic,
  DouyinAccountsService,
  type DouyinBrowserMode,
  type DouyinBrowserSlotPublic,
} from "@/client"
import { MetricCard, PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
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
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/douyin-accounts")({
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
  const accountsQuery = useQuery({
    queryKey: ["douyin-accounts"],
    queryFn: () => DouyinAccountsService.listAccounts({ limit: 100 }),
    retry: false,
    refetchInterval: 5_000,
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
  const ready = accounts.filter((item) => item.status === "ready").length
  const busy = accounts.filter((item) => item.status === "busy").length
  const browserSlots = slotsQuery.data?.data ?? []
  const availableSlots = browserSlots.filter((item) => item.available).length

  return (
    <div className="page-stack">
      <PageHero
        eyebrow="账号与浏览器身份"
        icon={ShieldCheck}
        title="抖音账号池"
        description="每个账号使用独立的浏览器空间。平台账号标识经过不可逆脱敏，敏感登录信息不会在内容数据、操作日志或页面中暴露。"
        actions={
          <div className="flex flex-wrap gap-2">
            <CreatePoolDialog accounts={accounts} onCreated={invalidate} />
            <CreateAccountDialog
              slots={browserSlots}
              slotsLoading={slotsQuery.isLoading}
              onCreated={invalidate}
            />
          </div>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          icon={UsersRound}
          label="托管账号"
          value={accountsQuery.isError ? "—" : accounts.length}
          tone="violet"
          compact
        />
        <MetricCard
          icon={ShieldCheck}
          label="当前可用"
          value={accountsQuery.isError ? "—" : ready}
          tone="mint"
          compact
        />
        <MetricCard
          icon={CircleGauge}
          label="执行中"
          value={accountsQuery.isError ? "—" : busy}
          tone="blue"
          compact
        />
        <MetricCard
          icon={Server}
          label="远程槽位可用"
          value={
            slotsQuery.isError
              ? "—"
              : `${availableSlots} / ${browserSlots.length}`
          }
          tone="coral"
          compact
        />
      </div>

      <Tabs defaultValue="accounts" className="space-y-4">
        <TabsList className="grid w-full max-w-md grid-cols-2">
          <TabsTrigger value="accounts">
            账号管理（{accounts.length}）
          </TabsTrigger>
          <TabsTrigger value="pools">
            账号池管理（{poolsQuery.data?.count ?? 0}）
          </TabsTrigger>
        </TabsList>

        <TabsContent value="accounts" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>远程浏览器槽位</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">
                一个远程槽位对应一个独立的云端浏览器和持久化登录空间，只能绑定一个账号。本机模式会自动创建专属登录空间，不需要选择槽位。
              </p>
              {slotsQuery.isError ? (
                <QueryErrorState
                  title="浏览器槽位读取失败"
                  description="暂时无法获取远程浏览器状态，请检查服务连接后重试。"
                  onRetry={() => void slotsQuery.refetch()}
                  retrying={slotsQuery.isFetching}
                  className="py-8"
                />
              ) : slotsQuery.isLoading ? (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  正在读取浏览器槽位…
                </p>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {browserSlots.map((slot) => (
                    <div
                      key={slot.name ?? "__default__"}
                      className="rounded-xl border bg-muted/20 p-4"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <p className="font-medium">{browserSlotLabel(slot)}</p>
                        <Badge
                          variant={slot.available ? "default" : "secondary"}
                        >
                          {!slot.configured
                            ? "配置异常"
                            : slot.available
                              ? "可用"
                              : "已占用"}
                        </Badge>
                      </div>
                      <p className="mt-2 text-xs text-muted-foreground">
                        {slot.occupied_account_name
                          ? `已绑定：${slot.occupied_account_name}`
                          : slot.viewer_available
                            ? "支持可视化登录"
                            : "未配置可视化登录地址"}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-3">
              <CardTitle>账号与专属浏览器</CardTitle>
              <ViewModeToggle value={viewMode} onChange={setViewMode} />
            </CardHeader>
            <CardContent>
              {viewMode === "table" ? (
                <div className="overflow-x-auto rounded-xl border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>账号别名</TableHead>
                        <TableHead>浏览器</TableHead>
                        <TableHead>状态</TableHead>
                        <TableHead>今日任务</TableHead>
                        <TableHead>并发 / 权重</TableHead>
                        <TableHead>最后验证</TableHead>
                        <TableHead className="text-right">操作</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {accountsQuery.isError ? (
                        <TableRow>
                          <TableCell colSpan={7} className="p-4">
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
                            colSpan={7}
                            className="h-36 text-center text-muted-foreground"
                          >
                            正在加载账号…
                          </TableCell>
                        </TableRow>
                      ) : accounts.length ? (
                        accounts.map((account) => (
                          <TableRow key={account.id}>
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
                            <TableCell>
                              <span className="inline-flex items-center gap-1.5">
                                {account.browser_mode === "remote" ? (
                                  <Server className="size-4" />
                                ) : (
                                  <Laptop className="size-4" />
                                )}
                                {account.browser_mode === "remote"
                                  ? account.remote_slot || "云端默认槽位"
                                  : "本机专属浏览器"}
                              </span>
                            </TableCell>
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
                            <TableCell>
                              {account.tasks_today} / {account.daily_task_limit}
                            </TableCell>
                            <TableCell>
                              {account.active_leases}/
                              {account.concurrency_limit} · ×{account.weight}
                            </TableCell>
                            <TableCell className="whitespace-nowrap text-muted-foreground">
                              {formatDate(account.last_verified_at)}
                            </TableCell>
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
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => toggle.mutate(account)}
                                  disabled={
                                    toggle.isPending ||
                                    account.active_leases > 0
                                  }
                                >
                                  {account.enabled ? "停用" : "启用"}
                                </Button>
                                <Button
                                  size="icon-sm"
                                  variant="ghost"
                                  aria-label="删除账号"
                                  onClick={() => {
                                    if (
                                      window.confirm(
                                        `确认删除账号“${account.name}”及其专属浏览器空间？`,
                                      )
                                    ) {
                                      remove.mutate(account.id)
                                    }
                                  }}
                                  disabled={
                                    remove.isPending ||
                                    account.active_leases > 0
                                  }
                                >
                                  <Trash2 />
                                </Button>
                              </div>
                            </TableCell>
                          </TableRow>
                        ))
                      ) : (
                        <TableRow>
                          <TableCell
                            colSpan={7}
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
                      onDelete={() => {
                        if (
                          window.confirm(
                            `确认删除账号“${account.name}”及其专属浏览器空间？`,
                          )
                        ) {
                          remove.mutate(account.id)
                        }
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
            <div className="rounded-2xl border bg-card py-10 text-center text-sm text-muted-foreground">
              正在加载账号池…
            </div>
          ) : (
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
                          onClick={() => {
                            if (
                              window.confirm(`确认删除账号池“${pool.name}”？`)
                            ) {
                              removePool.mutate(pool.id)
                            }
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
  onDelete: () => void
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
          {account.browser_mode === "remote" ? (
            <Server className="size-3.5" />
          ) : (
            <Laptop className="size-3.5" />
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
            {formatDate(account.last_verified_at)}
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
        <Button
          size="sm"
          variant="ghost"
          onClick={onToggle}
          disabled={actionPending || account.active_leases > 0}
        >
          {account.enabled ? "停用" : "启用"}
        </Button>
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label="删除账号"
          onClick={onDelete}
          disabled={actionPending || account.active_leases > 0}
        >
          <Trash2 />
        </Button>
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
              <SelectTrigger className="w-full">
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
}: {
  accounts: DouyinAccountPublic[]
  onCreated: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [selected, setSelected] = useState<string[]>([])
  const [strategy, setStrategy] =
    useState<DouyinAccountPoolStrategy>("least_loaded")
  const [maxParallel, setMaxParallel] = useState(2)
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const mutation = useMutation({
    mutationFn: () =>
      DouyinAccountsService.addPool({
        requestBody: {
          name: name.trim(),
          account_ids: selected,
          strategy,
          max_parallel_accounts: Math.max(
            1,
            Math.min(maxParallel, selected.length),
          ),
        },
      }),
    onSuccess: async () => {
      showSuccessToast("账号池已创建")
      setOpen(false)
      setName("")
      setSelected([])
      setStrategy("least_loaded")
      setMaxParallel(2)
      await onCreated()
    },
    onError: handleError.bind(showErrorToast),
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <UsersRound />
          创建账号池
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>创建并行账号池</DialogTitle>
          <DialogDescription>
            任务会按最少负载选择账号；不同目标可并行分片。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label>账号池名称</Label>
          <Input
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
                  checked={selected.includes(account.id)}
                  onCheckedChange={(checked) =>
                    setSelected((current) =>
                      checked
                        ? [...current, account.id]
                        : current.filter((id) => id !== account.id),
                    )
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
              <SelectTrigger className="w-full">
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
            disabled={
              mutation.isPending || !name.trim() || selected.length === 0
            }
          >
            创建账号池
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function formatDate(value: string | null) {
  return value
    ? new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "short",
        timeStyle: "short",
      }).format(new Date(value))
    : "-"
}
