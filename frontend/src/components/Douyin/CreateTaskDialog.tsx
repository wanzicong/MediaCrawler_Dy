import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { Plus } from "lucide-react"
import { type FormEvent, useState } from "react"

import {
  type CrawlTaskCreate,
  type DouyinCrawlType,
  type DouyinLoginType,
  DouyinService,
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
  targets: string
  cookies: string
  startPage: number
  maxAwemes: number
  fetchComments: boolean
  fetchSubComments: boolean
  maxComments: number
  concurrency: number
  interval: number
  publishTime: number
}

const initialForm: FormState = {
  crawlType: "search",
  loginType: "qrcode",
  targets: "",
  cookies: "",
  startPage: 1,
  maxAwemes: 10,
  fetchComments: true,
  fetchSubComments: false,
  maxComments: 10,
  concurrency: 1,
  interval: 1,
  publishTime: 0,
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
  const [form, setForm] = useState<FormState>(initialForm)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()

  const mutation = useMutation({
    mutationFn: (requestBody: CrawlTaskCreate) =>
      DouyinService.createTask({ requestBody }),
    onSuccess: async (task) => {
      await queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] })
      showSuccessToast("抖音任务已创建")
      setOpen(false)
      setForm(initialForm)
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
    if (form.loginType === "cookie" && !form.cookies.trim()) {
      showErrorToast("Cookie 登录必须填写 Cookies")
      return
    }

    const request: CrawlTaskCreate = {
      crawl_type: form.crawlType,
      login_type: form.loginType,
      cookies: form.loginType === "cookie" ? form.cookies.trim() : undefined,
      start_page: form.startPage,
      max_awemes: form.maxAwemes,
      fetch_comments: form.fetchComments,
      fetch_sub_comments: form.fetchComments && form.fetchSubComments,
      max_comments_per_aweme: form.maxComments,
      concurrency: form.concurrency,
      request_interval_seconds: form.interval,
      publish_time: form.publishTime,
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
        <Button>
          <Plus />
          创建任务
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <form onSubmit={submit} className="space-y-6">
          <DialogHeader>
            <DialogTitle>创建抖音爬取任务</DialogTitle>
            <DialogDescription>
              浏览器始终通过 CDP 连接；Cookie 只在当前任务内存中使用，不会入库。
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 sm:grid-cols-2">
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

          {form.loginType === "cookie" && (
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

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {form.crawlType === "search" && (
              <NumberField
                label="起始页"
                value={form.startPage}
                min={1}
                onChange={(value) => update("startPage", value)}
              />
            )}
            <NumberField
              label="最大作品数"
              value={form.maxAwemes}
              min={1}
              max={1000}
              onChange={(value) => update("maxAwemes", value)}
            />
            <NumberField
              label="并发数"
              value={form.concurrency}
              min={1}
              max={5}
              onChange={(value) => update("concurrency", value)}
            />
            <NumberField
              label="请求间隔（秒）"
              value={form.interval}
              min={0.2}
              max={60}
              step={0.2}
              onChange={(value) => update("interval", value)}
            />
          </div>

          {form.crawlType === "search" && (
            <div className="space-y-2">
              <Label>发布时间</Label>
              <Select
                value={String(form.publishTime)}
                onValueChange={(value) => update("publishTime", Number(value))}
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

          <div className="rounded-lg border p-4 space-y-4">
            <CheckField
              checked={form.fetchComments}
              label="抓取评论"
              onChange={(checked) => update("fetchComments", checked)}
            />
            <CheckField
              checked={form.fetchComments && form.fetchSubComments}
              disabled={!form.fetchComments}
              label="抓取子评论"
              onChange={(checked) => update("fetchSubComments", checked)}
            />
            {form.fetchComments && (
              <div className="max-w-48">
                <NumberField
                  label="每个作品最大评论数"
                  value={form.maxComments}
                  min={1}
                  max={1000}
                  onChange={(value) => update("maxComments", value)}
                />
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
            >
              取消
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
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
