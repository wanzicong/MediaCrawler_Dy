import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { ChevronDown, Plus, SlidersHorizontal, Sparkles } from "lucide-react"
import { type FormEvent, useState } from "react"

import {
  type CrawlTaskCreate,
  DouyinAccountsService,
  type DouyinBrowserMode,
  type DouyinCrawlType,
  type DouyinLoginType,
  type DouyinRequestDelayLevel,
  DouyinService,
  type MediaProcessingMode,
  type MediaStorageBackend,
} from "@/client"
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
  crawlType: DouyinCrawlType
  loginType: DouyinLoginType
  browserMode: DouyinBrowserMode | "default"
  targets: string
  cookies: string
  startPage: number
  maxAwemes: number
  fetchComments: boolean
  fetchSubComments: boolean
  maxComments: number
  concurrency: number
  delayLevel: DouyinRequestDelayLevel
  publishTime: number
  downloadMedia: boolean
  translateSubtitles: boolean
  mediaProcessingMode: Exclude<MediaProcessingMode, "none">
  mediaStorage: MediaStorageBackend | "default"
  transcriptionLanguage: string
  accountChoice: string
  accountStrategy: "least_loaded" | "round_robin" | "weighted_round_robin"
}

const initialForm: FormState = {
  crawlType: "search",
  loginType: "qrcode",
  browserMode: "remote",
  targets: "",
  cookies: "",
  startPage: 1,
  maxAwemes: 10,
  fetchComments: true,
  fetchSubComments: false,
  maxComments: 10,
  concurrency: 1,
  delayLevel: "steady",
  publishTime: 0,
  downloadMedia: false,
  translateSubtitles: false,
  mediaProcessingMode: "immediate",
  mediaStorage: "minio",
  transcriptionLanguage: "auto",
  accountChoice: "adhoc",
  accountStrategy: "least_loaded",
}

const targetConfig: Partial<
  Record<DouyinCrawlType, { label: string; placeholder: string }>
> = {
  search: {
    label: "搜索关键词",
    placeholder: "每行一个关键词，例如：\nFastAPI\nPython 爬虫",
  },
  detail: {
    label: "作品链接或 ID",
    placeholder: "每行一个作品链接、短链或纯数字作品 ID",
  },
  creator: {
    label: "创作者主页或 sec_user_id",
    placeholder: "每行一个创作者主页链接或 sec_user_id",
  },
}

function parseTargets(value: string) {
  return value
    .split(/[\n,，]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

export function CreateTaskDialog() {
  const [open, setOpen] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [form, setForm] = useState<FormState>(initialForm)
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

  const mutation = useMutation({
    mutationFn: (requestBody: CrawlTaskCreate) =>
      DouyinService.createTask({ requestBody }),
    onSuccess: async (task) => {
      await queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] })
      showSuccessToast("抖音任务已创建")
      setOpen(false)
      setForm(initialForm)
      setShowAdvanced(false)
      navigate({ to: "/douyin/$taskId", params: { taskId: task.id } })
    },
    onError: handleError.bind(showErrorToast),
  })

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }))
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const targets = parseTargets(form.targets)
    const target = targetConfig[form.crawlType]
    if (target && targets.length === 0) {
      showErrorToast(`请填写${target.label}`)
      return
    }
    if (
      form.accountChoice === "adhoc" &&
      form.loginType === "cookie" &&
      !form.cookies.trim()
    ) {
      showErrorToast("Cookie 登录必须填写 Cookies")
      return
    }

    const request: CrawlTaskCreate = {
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
      publish_time: form.publishTime,
      download_media: form.downloadMedia || form.translateSubtitles,
      translate_subtitles: form.translateSubtitles,
      media_processing_mode:
        form.downloadMedia || form.translateSubtitles
          ? form.mediaProcessingMode
          : "none",
      media_storage:
        form.mediaStorage === "default" ? undefined : form.mediaStorage,
      transcription_language: form.transcriptionLanguage,
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
    if (form.crawlType === "search") request.keywords = targets
    if (form.crawlType === "detail") request.video_ids = targets
    if (form.crawlType === "creator") request.creator_ids = targets
    mutation.mutate(request)
  }

  const target = targetConfig[form.crawlType]

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="brand">
          <Plus />
          创建任务
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
                浏览器始终通过 CDP 连接；Cookie
                只在当前任务内存中使用，不会入库。
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
                        <SelectItem value="cookie">Cookie 登录</SelectItem>
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
                        <SelectItem value="local">本机 Chrome</SelectItem>
                        <SelectItem value="remote">
                          Docker 远程 Chrome
                        </SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </>
              )}
            </div>

            {target && (
              <div className="space-y-2">
                <Label htmlFor="douyin-targets">{target.label}</Label>
                <Textarea
                  id="douyin-targets"
                  value={form.targets}
                  placeholder={target.placeholder}
                  onChange={(event) => update("targets", event.target.value)}
                />
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
                账号池会按目标拆分任务并使用独立 CDP Profile
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
                <Label htmlFor="douyin-cookies">Cookies</Label>
                <Textarea
                  id="douyin-cookies"
                  value={form.cookies}
                  placeholder="sessionid=...; LOGIN_STATUS=1"
                  autoComplete="off"
                  onChange={(event) => update("cookies", event.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  不要在共享环境粘贴私人账号 Cookie。
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

                <div className="space-y-4 rounded-xl border bg-card/80 p-4">
                  <div>
                    <p className="font-medium">视频下载与字幕</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      字幕调用服务端配置的远程 Whisper
                      API；失败时记录错误，不回退本地模型。
                    </p>
                  </div>
                  <CheckField
                    checked={form.downloadMedia || form.translateSubtitles}
                    disabled={form.translateSubtitles}
                    label="下载视频"
                    onChange={(checked) => update("downloadMedia", checked)}
                  />
                  <CheckField
                    checked={form.translateSubtitles}
                    label="生成并翻译字幕"
                    onChange={(checked) => {
                      update("translateSubtitles", checked)
                      if (checked) update("downloadMedia", true)
                    }}
                  />
                  {(form.downloadMedia || form.translateSubtitles) && (
                    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                      <div className="space-y-2">
                        <Label>处理策略</Label>
                        <Select
                          value={form.mediaProcessingMode}
                          onValueChange={(value) =>
                            update(
                              "mediaProcessingMode",
                              value as Exclude<MediaProcessingMode, "none">,
                            )
                          }
                        >
                          <SelectTrigger className="w-full">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="immediate">
                              逐条异步处理
                            </SelectItem>
                            <SelectItem value="batch">
                              爬取完成后批量处理
                            </SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label>视频存储</Label>
                        <Select
                          value={form.mediaStorage}
                          onValueChange={(value) =>
                            update(
                              "mediaStorage",
                              value as MediaStorageBackend | "default",
                            )
                          }
                        >
                          <SelectTrigger className="w-full">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="default">
                              跟随服务配置
                            </SelectItem>
                            <SelectItem value="local">本地服务器</SelectItem>
                            <SelectItem value="minio">
                              MinIO 对象存储
                            </SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      {form.translateSubtitles && (
                        <div className="space-y-2">
                          <Label htmlFor="transcription-language">
                            视频语言
                          </Label>
                          <Input
                            id="transcription-language"
                            value={form.transcriptionLanguage}
                            placeholder="auto、zh、en"
                            onChange={(event) =>
                              update(
                                "transcriptionLanguage",
                                event.target.value,
                              )
                            }
                          />
                        </div>
                      )}
                    </div>
                  )}
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
            <Button type="submit" variant="brand" disabled={mutation.isPending}>
              {mutation.isPending ? "创建中…" : "创建并运行"}
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
