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
  const accountsQuery = useQuery({
    queryKey: ["douyin-accounts"],
    queryFn: () => DouyinAccountsService.listAccounts({ limit: 100 }),
    refetchInterval: 5_000,
  })
  const poolsQuery = useQuery({
    queryKey: ["douyin-account-pools"],
    queryFn: () => DouyinAccountsService.listPools(),
  })
  const slotsQuery = useQuery({
    queryKey: ["douyin-browser-slots"],
    queryFn: () => DouyinAccountsService.listBrowserSlots(),
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
      if (result.viewer_url) {
        window.open(result.viewer_url, "_blank", "noopener,noreferrer")
      }
      showSuccessToast(
        result.viewer_url
          ? "远程浏览器已打开；登录后回到本页点击“验证”"
          : "本机浏览器已打开；登录后回到本页点击“验证”",
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
      showSuccessToast("账号和独立浏览器 Profile 已删除")
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
        description="每个账号使用独立 CDP Profile。平台账号标识只做不可逆摘要，Cookie 不进入数据库、日志或 API 响应。"
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
          value={accounts.length}
          tone="violet"
          compact
        />
        <MetricCard
          icon={ShieldCheck}
          label="当前可用"
          value={ready}
          tone="mint"
          compact
        />
        <MetricCard
          icon={CircleGauge}
          label="执行中"
          value={busy}
          tone="blue"
          compact
        />
        <MetricCard
          icon={Server}
          label="远程槽位可用"
          value={`${availableSlots} / ${browserSlots.length}`}
          tone="coral"
          compact
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>远程浏览器槽位</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            一个远程槽位对应一个独立 Docker Chrome 和持久化
            Profile，只能绑定一个账号。本机模式会自动创建独立
            Profile，不需要选择槽位。
          </p>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {browserSlots.map((slot) => (
              <div
                key={slot.name ?? "__default__"}
                className="rounded-xl border bg-muted/20 p-4"
              >
                <div className="flex items-center justify-between gap-3">
                  <p className="font-medium">{slot.label}</p>
                  <Badge variant={slot.available ? "default" : "secondary"}>
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
                      ? "支持 noVNC 登录"
                      : "未配置可视化登录地址"}
                </p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>账号与浏览器 Profile</CardTitle>
        </CardHeader>
        <CardContent>
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
                {accounts.length ? (
                  accounts.map((account) => (
                    <TableRow key={account.id}>
                      <TableCell>
                        <p className="font-medium">{account.name}</p>
                        {account.last_error && (
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
                            ? account.remote_slot || "Docker 默认槽位"
                            : "本机独立 Profile"}
                        </span>
                      </TableCell>
                      <TableCell>
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
                      </TableCell>
                      <TableCell>
                        {account.tasks_today} / {account.daily_task_limit}
                      </TableCell>
                      <TableCell>
                        {account.active_leases}/{account.concurrency_limit} · ×
                        {account.weight}
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
                              toggle.isPending || account.active_leases > 0
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
                                  `确认删除账号“${account.name}”及其 Profile？`,
                                )
                              ) {
                                remove.mutate(account.id)
                              }
                            }}
                            disabled={
                              remove.isPending || account.active_leases > 0
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
        </CardContent>
      </Card>

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
                    {pool.strategy === "least_loaded" ? "最少负载" : "加权轮询"}
                  </Badge>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    aria-label="删除账号池"
                    onClick={() => {
                      if (window.confirm(`确认删除账号池“${pool.name}”？`)) {
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
                <SelectItem value="remote">Docker 远程浏览器</SelectItem>
                <SelectItem value="local">本机 Chrome 独立 Profile</SelectItem>
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
                      自动分配（{availableSlots[0].label}）
                    </SelectItem>
                  )}
                  {slots.map((item) => (
                    <SelectItem
                      key={item.name ?? "__default__"}
                      value={item.name ?? "__default__"}
                      disabled={!item.available}
                    >
                      {item.label}
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
                  Docker 浏览器槽位。
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
