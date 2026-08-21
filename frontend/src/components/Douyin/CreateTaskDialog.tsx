import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { ChevronDown, Plus, SlidersHorizontal, Sparkles } from "lucide-react"
import { type FormEvent, useEffect, useState } from "react"

import {
  type ApiError,
  type CrawlTaskCreate,
  DouyinAccountsService,
  type DouyinBrowserMode,
  type DouyinCrawlType,
  DouyinCreatorsService,
  type DouyinLoginType,
  type DouyinRequestDelayLevel,
  DouyinService,
} from "@/client"
import { creatorNameLabel } from "@/components/Douyin/presentation"
import { TrackSelect } from "@/components/Douyin/TrackSelect"
import { DOUYIN_TASK_PARAMETER_DEFAULTS } from "@/components/Douyin/taskParameters"
import { Button } from "@/components/ui/button"
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
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

type FormState = {
  trackId: string
  crawlType: DouyinCrawlType
  loginType: DouyinLoginType
  browserMode: DouyinBrowserMode | "default"
  targets: string
  selectedCreatorIds: string[]
  manualCreatorTargets: string
  cookies: string
  startPage: number
  maxAwemes: number
  fetchComments: boolean
  fetchSubComments: boolean
  maxComments: number
  concurrency: number
  delayLevel: DouyinRequestDelayLevel
  requestInterval: number
  publishTime: number
  accountChoice: string
  accountStrategy: "least_loaded" | "round_robin" | "weighted_round_robin"
}

const initialForm: FormState = {
  trackId: "",
  crawlType: "search",
  loginType: "qrcode",
  browserMode: "remote",
  targets: "",
  selectedCreatorIds: [],
  manualCreatorTargets: "",
  cookies: "",
  startPage: DOUYIN_TASK_PARAMETER_DEFAULTS.startPage,
  maxAwemes: DOUYIN_TASK_PARAMETER_DEFAULTS.maxAwemes,
  fetchComments: DOUYIN_TASK_PARAMETER_DEFAULTS.fetchComments,
  fetchSubComments: DOUYIN_TASK_PARAMETER_DEFAULTS.fetchSubComments,
  maxComments: DOUYIN_TASK_PARAMETER_DEFAULTS.maxComments,
  concurrency: DOUYIN_TASK_PARAMETER_DEFAULTS.concurrency,
  delayLevel: DOUYIN_TASK_PARAMETER_DEFAULTS.delayLevel,
  requestInterval: DOUYIN_TASK_PARAMETER_DEFAULTS.requestInterval,
  publishTime: DOUYIN_TASK_PARAMETER_DEFAULTS.publishTime,
  accountChoice: "adhoc",
  accountStrategy: "least_loaded",
}

const targetConfig: Partial<
  Record<DouyinCrawlType, { label: string; placeholder: string }>
> = {
  search: {
    label: "搜索关键词",
    placeholder: "输入一个关键词，例如：FastAPI",
  },
  detail: {
    label: "作品链接或 ID",
    placeholder: "每行一个作品链接、短链或纯数字作品 ID",
  },
  creator: {
    label: "创作者主页或平台达人标识",
    placeholder: "每行一个创作者主页链接或平台达人标识",
  },
}

function parseTargets(value: string) {
  return value
    .split(/[\n,，]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

export function CreateTaskDialog({
  initialTrackId,
  initialCrawlType,
  triggerLabel = "创建任务",
  triggerVariant = "brand",
}: {
  initialTrackId?: string
  initialCrawlType?: DouyinCrawlType
  triggerLabel?: string
  triggerVariant?: React.ComponentProps<typeof Button>["variant"]
}) {
  const [open, setOpen] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [showManualCreator, setShowManualCreator] = useState(false)
  const [isPreparing, setIsPreparing] = useState(false)
  const [form, setForm] = useState<FormState>(() => ({
    ...initialForm,
    trackId: initialTrackId ?? "",
    crawlType: initialCrawlType ?? initialForm.crawlType,
  }))
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const accountsQuery = useQuery({
    queryKey: ["douyin-accounts"],
    queryFn: () => DouyinAccountsService.listAccounts({ limit: 100 }),
    enabled: open,
  })
  const poolsQuery = useQuery({
    queryKey: ["douyin-account-pools"],
    queryFn: () => DouyinAccountsService.listPools(),
    enabled: open,
  })
  const creatorsQuery = useQuery({
    queryKey: ["douyin-creators", form.trackId],
    queryFn: () =>
      DouyinCreatorsService.listCreators({
        trackId: form.trackId || undefined,
        enabled: true,
        limit: 200,
      }),
    enabled: open && form.crawlType === "creator",
  })

  useEffect(() => {
    if (!open) return
    // Every opening re-applies the surrounding scope. When the task list is
    // showing all tracks, clear a stale previous choice so TrackSelect can
    // select the default track again.
    setForm((current) => ({
      ...current,
      trackId: initialTrackId ?? "",
      crawlType: initialCrawlType ?? initialForm.crawlType,
      selectedCreatorIds: [],
      manualCreatorTargets: "",
    }))
    setShowManualCreator(false)
  }, [initialTrackId, initialCrawlType, open])

  const mutation = useMutation({
    mutationFn: (requestBody: CrawlTaskCreate) =>
      DouyinService.createTask({ requestBody }),
    onSuccess: async (task) => {
      await queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] })
      showSuccessToast("抖音任务已创建")
      setOpen(false)
      setForm({
        ...initialForm,
        trackId: initialTrackId ?? "",
        crawlType: initialCrawlType ?? initialForm.crawlType,
      })
      setShowAdvanced(false)
      navigate({ to: "/douyin/$taskId", params: { taskId: task.id } })
    },
    onError: handleError.bind(showErrorToast),
  })

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }))
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!form.trackId) {
      showErrorToast("请选择任务所属赛道")
      return
    }
    const targets = parseTargets(form.targets)
    const target = targetConfig[form.crawlType]
    if (target && form.crawlType !== "creator" && targets.length === 0) {
      showErrorToast(`请填写${target.label}`)
      return
    }
    if (form.crawlType === "search" && targets.length !== 1) {
      showErrorToast("每个关键词采集任务只能填写一个关键词")
      return
    }
    if (
      form.accountChoice === "adhoc" &&
      form.loginType === "cookie" &&
      !form.cookies.trim()
    ) {
      showErrorToast("临时凭据登录必须填写登录凭据")
      return
    }

    if (form.crawlType === "creator" && !form.manualCreatorTargets.trim()) {
      const selected = (creatorsQuery.data?.data ?? []).filter((item) =>
        form.selectedCreatorIds.includes(item.id),
      )
      if (selected.length === 0) {
        showErrorToast("请从达人名单中选择，或手动输入主页链接")
        return
      }
    }

    const request: CrawlTaskCreate = {
      track_id: form.trackId,
      crawl_type: form.crawlType,
      login_type: form.loginType,
      browser_mode:
        form.browserMode === "default" ? undefined : form.browserMode,
      cookies: form.loginType === "cookie" ? form.cookies.trim() : undefined,
      start_page: form.startPage,
      max_awemes: form.maxAwemes,
      fetch_comments: form.fetchComments,
      fetch_sub_comments: form.fetchComments && form.fetchSubComments,
      max_comments_per_aweme: form.maxComments,
      concurrency: form.concurrency,
      request_delay_level: form.delayLevel,
      request_interval_seconds: form.requestInterval,
      publish_time: form.publishTime,
      download_media: false,
      translate_subtitles: false,
      media_processing_mode: "none",
    }
    if (form.accountChoice.startsWith("account:")) {
      request.account_id = form.accountChoice.slice("account:".length)
      request.login_type = "qrcode"
      request.cookies = undefined
      request.browser_mode = undefined
    }
    if (form.accountChoice.startsWith("pool:")) {
      request.account_pool_id = form.accountChoice.slice("pool:".length)
      request.account_strategy = form.accountStrategy
      request.login_type = "qrcode"
      request.cookies = undefined
      request.browser_mode = undefined
    }
    if (form.crawlType === "search") request.keywords = [targets[0]]
    if (form.crawlType === "detail") request.video_ids = targets
    if (form.crawlType === "creator") {
      // 名单选中达人 → sec_uid；手动输入 → 先写入达人名单（归属当前赛道）再取回 sec_uid
      const selected = (creatorsQuery.data?.data ?? []).filter((item) =>
        form.selectedCreatorIds.includes(item.id),
      )
      let manualSecUids: string[] = []
      if (form.manualCreatorTargets.trim()) {
        setIsPreparing(true)
        try {
          const created = await DouyinCreatorsService.bulkCreateCreators({
            requestBody: {
              creators: parseTargets(form.manualCreatorTargets),
              track_id: form.trackId,
              notes: "",
            },
          })
          manualSecUids = created.data.map((item) => item.sec_uid)
          await queryClient.invalidateQueries({
            queryKey: ["douyin-creators"],
          })
        } catch (error) {
          handleError.call(showErrorToast, error as ApiError)
          return
        } finally {
          setIsPreparing(false)
        }
      }
      request.creator_ids = [
        ...selected.map((item) => item.sec_uid),
        ...manualSecUids,
      ]
    }
    mutation.mutate(request)
  }

  const target = targetConfig[form.crawlType]

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant={triggerVariant}>
          <Plus />
          {triggerLabel}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[92vh] overflow-hidden p-0 sm:max-w-3xl">
        <form onSubmit={submit} className="flex max-h-[92vh] flex-col">
          <DialogHeader className="border-b bg-gradient-to-r from-violet-500/[0.07] to-blue-500/[0.05] px-6 py-5 text-left">
            <DialogTitle className="flex items-center gap-3 text-xl">
              <span className="flex size-10 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                <Sparkles className="size-5" />
              </span>
              创建抖音采集任务
            </DialogTitle>
            <DialogDescription>
              先完成目标和账号等必要设置；运行参数与媒体处理已收纳到高级设置中。
            </DialogDescription>
          </DialogHeader>

          <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-6 py-5">
            <div>
              <p className="text-sm font-semibold">基础设置</p>
              <p className="mt-1 text-xs text-muted-foreground">
                浏览器会复用已登录账号；临时登录凭据只在当前任务内存中使用，不会保存。
              </p>
            </div>

            <div className="space-y-2 rounded-xl border border-primary/15 bg-primary/[0.035] p-4">
              <Label>所属赛道</Label>
              <TrackSelect
                value={form.trackId}
                onValueChange={(value) => {
                  update("trackId", value)
                  // 赛道切换后旧勾选可能不属于新赛道，重置避免提交校验失败
                  setForm((current) => ({
                    ...current,
                    selectedCreatorIds: [],
                  }))
                }}
                enabled={open}
              />
              <p className="text-xs text-muted-foreground">
                任务、关键词和后续采集内容都会归入该赛道；未手动切换时使用默认赛道。
              </p>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              <div className="space-y-2">
                <Label>任务类型</Label>
                <Select
                  value={form.crawlType}
                  onValueChange={(value) =>
                    update("crawlType", value as DouyinCrawlType)
                  }
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="search">关键词搜索</SelectItem>
                    <SelectItem value="detail">指定作品</SelectItem>
                    <SelectItem value="creator">创作者作品</SelectItem>
                    <SelectItem value="liked">当前账号点赞</SelectItem>
                    <SelectItem value="collected">当前账号收藏</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {form.accountChoice === "adhoc" && (
                <>
                  <div className="space-y-2">
                    <Label>登录方式</Label>
                    <Select
                      value={form.loginType}
                      onValueChange={(value) =>
                        update("loginType", value as DouyinLoginType)
                      }
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="qrcode">扫码登录</SelectItem>
                        <SelectItem value="cookie">临时凭据登录</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>浏览器</Label>
                    <Select
                      value={form.browserMode}
                      onValueChange={(value) =>
                        update(
                          "browserMode",
                          value as DouyinBrowserMode | "default",
                        )
                      }
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="default">跟随服务配置</SelectItem>
                        <SelectItem value="local">本机浏览器</SelectItem>
                        <SelectItem value="remote">云端托管浏览器</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </>
              )}
            </div>

            {target && form.crawlType !== "creator" && (
              <div className="space-y-2">
                <Label htmlFor="douyin-targets">{target.label}</Label>
                {form.crawlType === "search" ? (
                  <>
                    <Input
                      id="douyin-targets"
                      value={form.targets}
                      maxLength={200}
                      placeholder={target.placeholder}
                      onChange={(event) =>
                        update("targets", event.target.value)
                      }
                    />
                    <p className="text-xs text-muted-foreground">
                      每个任务只采集一个关键词；批量采集请在关键词管理或赛道中选择多个词，系统会分别创建任务。
                    </p>
                  </>
                ) : (
                  <Textarea
                    id="douyin-targets"
                    value={form.targets}
                    placeholder={target.placeholder}
                    onChange={(event) => update("targets", event.target.value)}
                  />
                )}
              </div>
            )}

            {form.crawlType === "creator" && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label>从达人名单选择</Label>
                  <span className="text-xs text-muted-foreground">
                    已选 {form.selectedCreatorIds.length} 位
                  </span>
                </div>
                <div className="max-h-64 overflow-y-auto rounded-xl border bg-card/60 p-2">
                  {creatorsQuery.isLoading ? (
                    <p className="px-2 py-3 text-sm text-muted-foreground">
                      正在加载达人名单…
                    </p>
                  ) : (creatorsQuery.data?.data ?? []).filter(
                      (item) => !item.is_placeholder,
                    ).length === 0 ? (
                    <p className="px-2 py-3 text-sm text-muted-foreground">
                      当前赛道还没有启用状态的达人，可在下方手动输入主页链接
                    </p>
                  ) : (
                    (creatorsQuery.data?.data ?? [])
                      .filter((item) => !item.is_placeholder)
                      .map((item) => {
                        const checked = form.selectedCreatorIds.includes(
                          item.id,
                        )
                        return (
                          <div
                            key={item.id}
                            className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-muted/60"
                          >
                            <Checkbox
                              id={`creator-option-${item.id}`}
                              checked={checked}
                              onCheckedChange={() => {
                                const next = checked
                                  ? form.selectedCreatorIds.filter(
                                      (id) => id !== item.id,
                                    )
                                  : [...form.selectedCreatorIds, item.id]
                                update("selectedCreatorIds", next)
                              }}
                              aria-label={`选择达人 ${creatorNameLabel(item)}`}
                            />
                            <Label
                              htmlFor={`creator-option-${item.id}`}
                              className="min-w-0 flex-1 cursor-pointer"
                            >
                              <span className="block truncate text-sm">
                                {creatorNameLabel(item)}
                              </span>
                              <span className="block truncate text-xs text-muted-foreground">
                                {item.aweme_count} 个作品 · {item.track_name}
                              </span>
                            </Label>
                          </div>
                        )
                      })
                  )}
                </div>
                <button
                  type="button"
                  className="text-sm font-medium text-primary hover:underline"
                  onClick={() => setShowManualCreator((current) => !current)}
                >
                  {showManualCreator ? "收起手动输入" : "+ 手动输入新达人"}
                </button>
                {showManualCreator && (
                  <div className="space-y-2">
                    <Textarea
                      value={form.manualCreatorTargets}
                      placeholder="每行一个创作者主页链接或平台达人标识，例如：\nhttps://www.douyin.com/user/MS4wLjAB…"
                      onChange={(event) =>
                        update("manualCreatorTargets", event.target.value)
                      }
                    />
                    <p className="text-xs text-muted-foreground">
                      提交任务时这些达人会先加入当前赛道的达人名单，再创建任务。
                    </p>
                  </div>
                )}
              </div>
            )}

            <div className="space-y-2">
              <Label>执行账号</Label>
              <Select
                value={form.accountChoice}
                onValueChange={(value) => update("accountChoice", value)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="adhoc">临时登录（当前任务）</SelectItem>
                  {(accountsQuery.data?.data ?? [])
                    .filter((account) =>
                      ["ready", "busy"].includes(account.status),
                    )
                    .map((account) => (
                      <SelectItem
                        key={account.id}
                        value={`account:${account.id}`}
                      >
                        账号 · {account.name}
                      </SelectItem>
                    ))}
                  {(poolsQuery.data?.data ?? [])
                    .filter((pool) => pool.enabled && pool.accounts.length > 0)
                    .map((pool) => (
                      <SelectItem key={pool.id} value={`pool:${pool.id}`}>
                        账号池 · {pool.name}（{pool.accounts.length} 个）
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                账号池会按目标拆分任务并使用独立浏览器空间
                并行执行；单一目标保持单账号，避免重复数据。
              </p>
            </div>

            {form.accountChoice.startsWith("pool:") && (
              <div className="space-y-2">
                <Label>账号池调度策略</Label>
                <Select
                  value={form.accountStrategy}
                  onValueChange={(value) =>
                    update(
                      "accountStrategy",
                      value as FormState["accountStrategy"],
                    )
                  }
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="least_loaded">最少负载</SelectItem>
                    <SelectItem value="round_robin">顺序轮询</SelectItem>
                    <SelectItem value="weighted_round_robin">
                      加权轮询
                    </SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  最少负载优先空闲账号；顺序轮询保证均匀切换；加权轮询按账号权重分配。
                </p>
              </div>
            )}

            {form.accountChoice === "adhoc" && form.loginType === "cookie" && (
              <div className="space-y-2">
                <Label htmlFor="douyin-cookies">临时登录凭据</Label>
                <Textarea
                  id="douyin-cookies"
                  value={form.cookies}
                  placeholder="sessionid=...; LOGIN_STATUS=1"
                  autoComplete="off"
                  onChange={(event) => update("cookies", event.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  不要在共享环境粘贴私人账号的登录凭据。
                </p>
              </div>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              <NumberField
                label="最大作品数"
                value={form.maxAwemes}
                min={1}
                max={1000}
                onChange={(value) => update("maxAwemes", value)}
              />
              <div className="flex items-center rounded-xl border bg-muted/35 px-4 py-3">
                <CheckField
                  checked={form.fetchComments}
                  label="同时抓取评论"
                  onChange={(checked) => update("fetchComments", checked)}
                />
              </div>
            </div>

            <button
              type="button"
              className="flex w-full items-center justify-between rounded-2xl border bg-muted/30 px-4 py-3 text-left transition hover:border-primary/25 hover:bg-primary/5 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              aria-expanded={showAdvanced}
              onClick={() => setShowAdvanced((current) => !current)}
            >
              <span className="flex items-center gap-3">
                <span className="rounded-xl bg-primary/10 p-2 text-primary">
                  <SlidersHorizontal className="size-4" />
                </span>
                <span>
                  <span className="block text-sm font-semibold">高级设置</span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    并发、请求节奏、评论深度与视频字幕处理
                  </span>
                </span>
              </span>
              <ChevronDown
                className={`size-4 text-muted-foreground transition ${showAdvanced ? "rotate-180" : ""}`}
              />
            </button>

            {showAdvanced && (
              <div className="space-y-6 rounded-2xl border border-primary/15 bg-primary/[0.025] p-4 sm:p-5">
                <div>
                  <p className="text-sm font-semibold">运行参数</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    默认参数适合大多数场景，提高并发前请确认账号与网络承载能力。
                  </p>
                </div>
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {form.crawlType === "search" && (
                    <NumberField
                      label="起始页"
                      value={form.startPage}
                      min={1}
                      onChange={(value) => update("startPage", value)}
                    />
                  )}
                  <NumberField
                    label="并发数"
                    value={form.concurrency}
                    min={1}
                    max={5}
                    onChange={(value) => update("concurrency", value)}
                  />
                  <div className="space-y-2">
                    <Label>风控节奏</Label>
                    <Select
                      value={form.delayLevel}
                      onValueChange={(value) =>
                        update("delayLevel", value as DouyinRequestDelayLevel)
                      }
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="fast">快 · 随机 1–2 秒</SelectItem>
                        <SelectItem value="steady">稳 · 随机 3–6 秒</SelectItem>
                        <SelectItem value="ultra_steady">
                          超级稳 · 随机 6–12 秒
                        </SelectItem>
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">
                      每次请求独立随机等待；更慢只能降低请求密度，不能保证规避平台风控。
                    </p>
                  </div>
                  <NumberField
                    label="最小请求间隔（秒）"
                    value={form.requestInterval}
                    min={0.2}
                    max={60}
                    step={0.1}
                    onChange={(value) => update("requestInterval", value)}
                  />
                </div>

                {form.crawlType === "search" && (
                  <div className="space-y-2">
                    <Label>发布时间</Label>
                    <Select
                      value={String(form.publishTime)}
                      onValueChange={(value) =>
                        update("publishTime", Number(value))
                      }
                    >
                      <SelectTrigger className="w-full sm:w-52">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="0">不限</SelectItem>
                        <SelectItem value="1">一天内</SelectItem>
                        <SelectItem value="7">一周内</SelectItem>
                        <SelectItem value="180">半年内</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                )}

                {form.fetchComments && (
                  <div className="grid gap-4 rounded-xl border bg-card/80 p-4 sm:grid-cols-2">
                    <div className="flex items-center">
                      <CheckField
                        checked={form.fetchSubComments}
                        label="抓取子评论"
                        onChange={(checked) =>
                          update("fetchSubComments", checked)
                        }
                      />
                    </div>
                    <NumberField
                      label="每个作品最大评论数"
                      value={form.maxComments}
                      min={1}
                      max={1000}
                      onChange={(value) => update("maxComments", value)}
                    />
                  </div>
                )}

                <div className="rounded-xl border border-blue-200/70 bg-blue-50/60 p-4 text-sm text-blue-950 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-100">
                  <p className="font-medium">下载与字幕已独立管理</p>
                  <p className="mt-1 text-xs leading-5 opacity-80">
                    当前任务只负责采集数据。采集完成后，请到任务中心的“下载与字幕”页签创建关联处理任务。
                  </p>
                </div>
              </div>
            )}
          </div>

          <DialogFooter className="border-t bg-card px-6 py-4">
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
            >
              取消
            </Button>
            <Button
              type="submit"
              variant="brand"
              disabled={mutation.isPending || isPreparing || !form.trackId}
            >
              {mutation.isPending || isPreparing ? "创建中…" : "创建并运行"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function NumberField({
  label,
  value,
  onChange,
  ...props
}: {
  label: string
  value: number
  onChange: (value: number) => void
  min?: number
  max?: number
  step?: number
}) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <Input
        type="number"
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        {...props}
      />
    </div>
  )
}

function CheckField({
  checked,
  disabled,
  label,
  onChange,
}: {
  checked: boolean
  disabled?: boolean
  label: string
  onChange: (checked: boolean) => void
}) {
  return (
    <div className="flex items-center gap-2">
      <Checkbox
        checked={checked}
        disabled={disabled}
        onCheckedChange={(value) => onChange(value === true)}
      />
      <Label className="font-normal">{label}</Label>
    </div>
  )
}
