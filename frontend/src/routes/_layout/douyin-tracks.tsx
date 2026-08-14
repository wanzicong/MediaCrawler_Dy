import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  Activity,
  Film,
  MessageCircle,
  MoreHorizontal,
  Play,
  Plus,
  Search,
  Tags,
  Target,
  Trash2,
} from "lucide-react"
import { type FormEvent, useEffect, useState } from "react"

import {
  type ApiError,
  DouyinAccountsService,
  type DouyinKeywordPublic,
  DouyinKeywordsService,
  type DouyinTrackPublic,
  DouyinTracksService,
} from "@/client"
import { MetricCard, PageHero } from "@/components/Common/PageShell"
import { TaskStatusBadge } from "@/components/Douyin/TaskStatusBadge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
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
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/douyin-tracks")({
  component: DouyinTracksPage,
  head: () => ({ meta: [{ title: "赛道管理 - 灵感采集台" }] }),
  validateSearch: (search: Record<string, unknown>) => ({
    run: typeof search.run === "string" ? search.run : undefined,
  }),
})

function DouyinTracksPage() {
  const { run } = Route.useSearch()
  const navigate = Route.useNavigate()
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [search, setSearch] = useState("")
  const [selectedTrack, setSelectedTrack] = useState<DouyinTrackPublic | null>(
    null,
  )
  const [editing, setEditing] = useState<DouyinTrackPublic | null>(null)
  const [deleting, setDeleting] = useState<DouyinTrackPublic | null>(null)
  const tracksQuery = useQuery({
    queryKey: ["douyin-tracks", search],
    queryFn: () =>
      DouyinTracksService.listTracks({ search: search.trim() || undefined }),
    refetchInterval: 10_000,
  })
  const requestedTrackQuery = useQuery({
    queryKey: ["douyin-track", run],
    queryFn: () => DouyinTracksService.getTrack({ trackId: run as string }),
    enabled: Boolean(run),
    retry: false,
  })
  useEffect(() => {
    if (!run || !requestedTrackQuery.isError) return
    showErrorToast("赛道不存在或已不可用")
    void navigate({ search: { run: undefined }, replace: true })
  }, [navigate, requestedTrackQuery.isError, run, showErrorToast])
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["douyin-tracks"] })
  const remove = useMutation({
    mutationFn: (trackId: string) =>
      DouyinTracksService.deleteTrack({ trackId }),
    onSuccess: async () => {
      showSuccessToast("赛道已删除，关键词和历史任务已保留")
      setDeleting(null)
      await invalidate()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const toggle = useMutation({
    mutationFn: (track: DouyinTrackPublic) =>
      DouyinTracksService.editTrack({
        trackId: track.id,
        requestBody: { enabled: !track.enabled },
      }),
    onSuccess: invalidate,
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const tracks = tracksQuery.data?.data ?? []
  const selected = run ? (requestedTrackQuery.data ?? null) : selectedTrack
  const active = tracks.filter((item) => item.active_task_count > 0).length
  const keywordCount = tracks.reduce((sum, item) => sum + item.keyword_count, 0)
  const works = tracks.reduce((sum, item) => sum + item.aweme_count, 0)
  const comments = tracks.reduce((sum, item) => sum + item.comment_count, 0)

  return (
    <div className="page-stack">
      <PageHero
        eyebrow="Private domain growth"
        icon={Target}
        title="赛道管理"
        description="把市场方向沉淀为可复用的关键词组合，持续创建采集任务，并从作品量、评论量和运行状态衡量赛道产出。"
        actions={<CreateTrackDialog onCreated={invalidate} />}
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          icon={Target}
          label="运营赛道"
          value={tracks.length}
          detail={`${active} 个正在运行`}
          tone="violet"
          compact
        />
        <MetricCard
          icon={Tags}
          label="关键词资产"
          value={keywordCount}
          detail="允许跨赛道复用"
          tone="blue"
          compact
        />
        <MetricCard
          icon={Film}
          label="赛道作品"
          value={compact(works)}
          detail="由赛道任务采集"
          tone="mint"
          compact
        />
        <MetricCard
          icon={MessageCircle}
          label="目标评论"
          value={compact(comments)}
          detail="用于用户洞察"
          tone="coral"
          compact
        />
      </div>

      <Card>
        <CardContent className="p-3">
          <div className="relative max-w-xl">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索赛道名称或描述"
              aria-label="搜索赛道"
              className="h-9 pl-9"
            />
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {tracks.map((track) => (
          <Card
            key={track.id}
            className="group overflow-hidden transition hover:border-primary/25 hover:shadow-md"
          >
            <CardContent className="p-3">
              <div className="flex items-start gap-2.5">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-violet-500/12 text-violet-700 dark:text-violet-300">
                  <Target className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h2 className="min-w-0 truncate text-sm font-semibold">
                      <Link
                        to="/douyin-tracks/$trackId"
                        params={{ trackId: track.id }}
                        className="transition-colors hover:text-primary hover:underline focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                      >
                        {track.name}
                      </Link>
                    </h2>
                    <Badge
                      variant={track.enabled ? "default" : "secondary"}
                      className="h-5 shrink-0 px-1.5 text-[10px]"
                    >
                      {track.enabled ? "启用" : "停用"}
                    </Badge>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-muted-foreground">
                    {track.description || "尚未填写赛道描述"}
                  </p>
                </div>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="size-8 shrink-0"
                      aria-label="赛道操作"
                    >
                      <MoreHorizontal className="size-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => setEditing(track)}>
                      编辑赛道
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => toggle.mutate(track)}>
                      {track.enabled ? "停用赛道" : "启用赛道"}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      className="text-destructive"
                      onClick={() => setDeleting(track)}
                    >
                      <Trash2 /> 删除赛道
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>

              <div className="mt-2.5 grid grid-cols-4 gap-1 rounded-lg bg-muted/30 px-2 py-1.5 text-center">
                <SmallMetric label="关键词" value={track.keyword_count} />
                <SmallMetric label="任务" value={track.task_count} />
                <SmallMetric label="作品" value={compact(track.aweme_count)} />
                <SmallMetric
                  label="评论"
                  value={compact(track.comment_count)}
                />
              </div>

              <div className="mt-2.5 flex min-h-7 flex-wrap items-center gap-1.5 border-t pt-2.5">
                {track.last_task_status ? (
                  <TaskStatusBadge status={track.last_task_status} />
                ) : (
                  <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
                    尚未运行
                  </Badge>
                )}
                {track.last_run_at && (
                  <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
                    最近 {formatDate(track.last_run_at)}
                  </span>
                )}
                {!track.last_run_at && <span className="flex-1" />}
                <Button
                  size="sm"
                  className="h-7 gap-1 px-2 text-xs"
                  onClick={() => setSelectedTrack(track)}
                >
                  <Play className="size-3.5" /> 运营这个赛道
                </Button>
                {track.last_task_id && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 px-2 text-xs"
                    asChild
                  >
                    <Link
                      to="/douyin/$taskId"
                      params={{ taskId: track.last_task_id }}
                    >
                      最近任务
                    </Link>
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {!tracks.length && !tracksQuery.isLoading && (
        <Card>
          <CardContent className="py-16 text-center">
            <Target className="mx-auto size-10 text-muted-foreground/50" />
            <p className="mt-4 font-medium">还没有运营赛道</p>
            <p className="mt-1 text-sm text-muted-foreground">
              从一个细分市场和一组用户搜索词开始。
            </p>
          </CardContent>
        </Card>
      )}

      {selected && (
        <TrackWorkspaceDialog
          track={selected}
          open
          onOpenChange={(open) => {
            if (open) return
            setSelectedTrack(null)
            if (run)
              void navigate({ search: { run: undefined }, replace: true })
          }}
          onChanged={invalidate}
        />
      )}
      {editing && (
        <EditTrackDialog
          track={editing}
          open
          onOpenChange={(open) => !open && setEditing(null)}
          onChanged={invalidate}
        />
      )}
      <Dialog
        open={Boolean(deleting)}
        onOpenChange={(open) => !open && setDeleting(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除赛道“{deleting?.name}”？</DialogTitle>
            <DialogDescription>
              只删除赛道及其组织关系；关键词资产、采集任务、视频和评论都会保留。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={!deleting || remove.isPending}
              onClick={() => deleting && remove.mutate(deleting.id)}
            >
              {remove.isPending ? "正在删除…" : "确认删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function CreateTrackDialog({
  onCreated,
}: {
  onCreated: () => Promise<unknown>
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [prompt, setPrompt] = useState("")
  const [keywords, setKeywords] = useState("")
  const [existingKeywords, setExistingKeywords] = useState<Map<string, string>>(
    new Map(),
  )
  const mutation = useMutation({
    mutationFn: () =>
      DouyinTracksService.addTrack({
        requestBody: {
          name,
          description,
          prompt,
          keywords: uniqueKeywords([
            ...parseKeywords(keywords),
            ...existingKeywords.values(),
          ]),
        },
      }),
    onSuccess: async () => {
      showSuccessToast("赛道已创建，关键词已关联")
      setOpen(false)
      setName("")
      setDescription("")
      setPrompt("")
      setKeywords("")
      setExistingKeywords(new Map())
      await onCreated()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    mutation.mutate()
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus /> 创建赛道
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>创建运营赛道</DialogTitle>
            <DialogDescription>
              赛道用于组织目标市场、搜索词和后续采集任务。
            </DialogDescription>
          </DialogHeader>
          <div>
            <Label htmlFor="track-name">赛道名称</Label>
            <Input
              id="track-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：户外露营装备"
              className="mt-2"
              required
            />
          </div>
          <div>
            <Label htmlFor="track-description">目标与人群</Label>
            <Textarea
              id="track-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="描述目标用户、内容方向和你希望验证的商业假设"
              className="mt-2"
            />
          </div>
          <div>
            <Label htmlFor="track-keywords">创建新关键词</Label>
            <Textarea
              id="track-keywords"
              value={keywords}
              onChange={(event) => setKeywords(event.target.value)}
              placeholder="一行一个，或使用逗号分隔"
              className="mt-2"
            />
          </div>
          <div>
            <div className="flex items-center justify-between gap-2">
              <Label htmlFor="track-prompt">赛道提示词（可选）</Label>
              <span className="text-xs text-muted-foreground">
                {prompt.length}/10000
              </span>
            </div>
            <Textarea
              id="track-prompt"
              value={prompt}
              maxLength={10000}
              rows={4}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="沉淀该赛道的分析目标、用户画像和内容策略"
              className="mt-2"
            />
          </div>
          <ExistingKeywordPicker
            selected={existingKeywords}
            excludedIds={new Set()}
            onToggle={(keyword, checked) =>
              setExistingKeywords((current) =>
                toggleKeywordSelection(current, keyword, checked),
              )
            }
          />
          <DialogFooter>
            <Button type="submit" disabled={mutation.isPending || !name.trim()}>
              {mutation.isPending ? "正在创建…" : "创建赛道"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function TrackWorkspaceDialog({
  track,
  open,
  onOpenChange,
  onChanged,
}: {
  track: DouyinTrackPublic
  open: boolean
  onOpenChange: (open: boolean) => void
  onChanged: () => Promise<unknown>
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [newKeywords, setNewKeywords] = useState("")
  const [existingKeywords, setExistingKeywords] = useState<Map<string, string>>(
    new Map(),
  )
  const [mode, setMode] = useState<"combined" | "separate">("combined")
  const [maxAwemes, setMaxAwemes] = useState("30")
  const [maxComments, setMaxComments] = useState("10")
  const [accountChoice, setAccountChoice] = useState("adhoc")
  const [accountStrategy, setAccountStrategy] = useState<
    "least_loaded" | "round_robin" | "weighted_round_robin"
  >("least_loaded")
  const accounts = useQuery({
    queryKey: ["douyin-accounts"],
    queryFn: () => DouyinAccountsService.listAccounts({ limit: 100 }),
    enabled: open,
  })
  const pools = useQuery({
    queryKey: ["douyin-account-pools"],
    queryFn: () => DouyinAccountsService.listPools(),
    enabled: open,
  })
  const keywordsQuery = useQuery({
    queryKey: ["douyin-track-keywords", track.id],
    queryFn: () => DouyinTracksService.listTrackKeywords({ trackId: track.id }),
    enabled: open,
  })
  const refresh = async () => {
    await Promise.all([keywordsQuery.refetch(), onChanged()])
  }
  const addKeywords = useMutation({
    mutationFn: (values: string[]) =>
      DouyinTracksService.appendTrackKeywords({
        trackId: track.id,
        requestBody: { keywords: values },
      }),
    onSuccess: async () => {
      setNewKeywords("")
      setExistingKeywords(new Map())
      showSuccessToast("关键词已加入赛道")
      await refresh()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const run = useMutation({
    mutationFn: () => {
      const requestBody: Parameters<
        typeof DouyinTracksService.createTrackTasks
      >[0]["requestBody"] = {
        keyword_ids: [],
        mode,
        max_awemes: Number(maxAwemes),
        max_comments_per_aweme: Number(maxComments),
        fetch_comments: true,
        request_delay_level: "steady",
      }
      if (accountChoice.startsWith("account:"))
        requestBody.account_id = accountChoice.slice(8)
      if (accountChoice.startsWith("pool:")) {
        requestBody.account_pool_id = accountChoice.slice(5)
        requestBody.account_strategy = accountStrategy
      }
      return DouyinTracksService.createTrackTasks({
        trackId: track.id,
        requestBody,
      })
    },
    onSuccess: async (result) => {
      showSuccessToast(`已创建 ${result.count} 个赛道采集任务`)
      onOpenChange(false)
      await onChanged()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const keywords = keywordsQuery.data?.data ?? []
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{track.name} · 运营工作区</DialogTitle>
          <DialogDescription>
            维护搜索词并以稳定风控档创建可追踪的赛道任务。
          </DialogDescription>
        </DialogHeader>

        <div className="rounded-xl border bg-muted/20 p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="font-medium">关键词组合</p>
            <Badge variant="secondary">{keywords.length} 个</Badge>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {keywords.map((keyword: DouyinKeywordPublic) => (
              <Badge
                key={keyword.id}
                variant={keyword.enabled ? "outline" : "secondary"}
              >
                {keyword.keyword}
              </Badge>
            ))}
            {!keywords.length && (
              <span className="text-sm text-muted-foreground">
                还没有关键词，请先添加。
              </span>
            )}
          </div>
          <div className="mt-4 flex gap-2">
            <Input
              value={newKeywords}
              onChange={(event) => setNewKeywords(event.target.value)}
              placeholder="补充关键词，逗号或换行分隔"
            />
            <Button
              variant="outline"
              disabled={
                !parseKeywords(newKeywords).length || addKeywords.isPending
              }
              onClick={() => addKeywords.mutate(parseKeywords(newKeywords))}
            >
              创建并添加
            </Button>
          </div>
          <div className="mt-4 border-t pt-4">
            {keywordsQuery.isLoading ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                正在核对赛道已绑定关键词…
              </p>
            ) : (
              <ExistingKeywordPicker
                selected={existingKeywords}
                excludedIds={new Set(keywords.map((keyword) => keyword.id))}
                onToggle={(keyword, checked) =>
                  setExistingKeywords((current) =>
                    toggleKeywordSelection(current, keyword, checked),
                  )
                }
              />
            )}
            <div className="mt-3 flex justify-end">
              <Button
                variant="outline"
                disabled={!existingKeywords.size || addKeywords.isPending}
                onClick={() =>
                  addKeywords.mutate([...existingKeywords.values()])
                }
              >
                <Plus />
                添加已选关键词（{existingKeywords.size}）
              </Button>
            </div>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <div>
            <Label>任务组织方式</Label>
            <Select
              value={mode}
              onValueChange={(value) => setMode(value as typeof mode)}
            >
              <SelectTrigger className="mt-2 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="combined">组合任务（推荐）</SelectItem>
                <SelectItem value="separate">每词独立任务</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>执行账号</Label>
            <Select value={accountChoice} onValueChange={setAccountChoice}>
              <SelectTrigger className="mt-2 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="adhoc">临时 CDP 登录</SelectItem>
                {(accounts.data?.data ?? [])
                  .filter(
                    (item) =>
                      item.enabled && ["ready", "busy"].includes(item.status),
                  )
                  .map((item) => (
                    <SelectItem key={item.id} value={`account:${item.id}`}>
                      账号 · {item.name}
                    </SelectItem>
                  ))}
                {(pools.data?.data ?? [])
                  .filter((item) => item.enabled)
                  .map((item) => (
                    <SelectItem key={item.id} value={`pool:${item.id}`}>
                      账号池 · {item.name}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
          {accountChoice.startsWith("pool:") && (
            <div>
              <Label>调度策略</Label>
              <Select
                value={accountStrategy}
                onValueChange={(value) =>
                  setAccountStrategy(value as typeof accountStrategy)
                }
              >
                <SelectTrigger className="mt-2 w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="least_loaded">最少负载</SelectItem>
                  <SelectItem value="round_robin">顺序轮询</SelectItem>
                  <SelectItem value="weighted_round_robin">加权轮询</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}
          <div>
            <Label htmlFor="track-max-awemes">单任务作品上限</Label>
            <Input
              id="track-max-awemes"
              type="number"
              min={1}
              max={1000}
              value={maxAwemes}
              onChange={(event) => setMaxAwemes(event.target.value)}
              className="mt-2"
            />
          </div>
          <div>
            <Label htmlFor="track-max-comments">单作品评论上限</Label>
            <Input
              id="track-max-comments"
              type="number"
              min={1}
              max={1000}
              value={maxComments}
              onChange={(event) => setMaxComments(event.target.value)}
              className="mt-2"
            />
          </div>
        </div>

        <div className="rounded-xl border border-amber-200/70 bg-amber-50/60 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
          默认使用 Docker 浏览器、MinIO 存储和“稳 · 随机 3–6
          秒”风控档；任务启动后可在任务列表查看实时进度。
        </div>
        <DialogFooter>
          <Button
            onClick={() => run.mutate()}
            disabled={!keywords.some((item) => item.enabled) || run.isPending}
          >
            <Activity />
            {run.isPending ? "正在创建任务…" : "启动赛道采集"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function EditTrackDialog({
  track,
  open,
  onOpenChange,
  onChanged,
}: {
  track: DouyinTrackPublic
  open: boolean
  onOpenChange: (open: boolean) => void
  onChanged: () => Promise<unknown>
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [name, setName] = useState(track.name)
  const [description, setDescription] = useState(track.description)
  const mutation = useMutation({
    mutationFn: () =>
      DouyinTracksService.editTrack({
        trackId: track.id,
        requestBody: { name, description },
      }),
    onSuccess: async () => {
      showSuccessToast("赛道信息已更新")
      onOpenChange(false)
      await onChanged()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault()
            mutation.mutate()
          }}
        >
          <DialogHeader>
            <DialogTitle>编辑赛道</DialogTitle>
            <DialogDescription>
              调整赛道定位不会改动已关联的关键词与历史任务。
            </DialogDescription>
          </DialogHeader>
          <div>
            <Label htmlFor="edit-track-name">赛道名称</Label>
            <Input
              id="edit-track-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="mt-2"
              required
            />
          </div>
          <div>
            <Label htmlFor="edit-track-description">目标与人群</Label>
            <Textarea
              id="edit-track-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="mt-2"
            />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={!name.trim() || mutation.isPending}>
              {mutation.isPending ? "保存中…" : "保存修改"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function SmallMetric({
  label,
  value,
}: {
  label: string
  value: string | number
}) {
  return (
    <div className="flex min-w-0 items-baseline justify-center gap-1">
      <span className="text-sm font-semibold leading-none">{value}</span>
      <span className="truncate text-[10px] text-muted-foreground">
        {label}
      </span>
    </div>
  )
}

function ExistingKeywordPicker({
  selected,
  excludedIds,
  onToggle,
}: {
  selected: Map<string, string>
  excludedIds: Set<string>
  onToggle: (keyword: DouyinKeywordPublic, checked: boolean) => void
}) {
  const [search, setSearch] = useState("")
  const keywordsQuery = useQuery({
    queryKey: ["douyin-existing-keywords", search],
    queryFn: () =>
      DouyinKeywordsService.listKeywords({
        search: search.trim() || undefined,
        enabled: true,
        sortBy: "task_count",
        sortOrder: "desc",
        limit: 100,
      }),
    placeholderData: (previous) => previous,
  })
  const available = (keywordsQuery.data?.data ?? []).filter(
    (keyword) => !excludedIds.has(keyword.id),
  )

  return (
    <div className="rounded-xl border bg-background/70 p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium">从关键词库添加</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            搜索并多选已有关键词，不会创建重复资产。
          </p>
        </div>
        <Badge variant="secondary">已选 {selected.size}</Badge>
      </div>
      <div className="relative mt-3">
        <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="搜索现有关键词"
          aria-label="搜索现有关键词"
          className="pl-9"
        />
      </div>
      <div className="mt-3 max-h-48 space-y-1 overflow-y-auto pr-1">
        {available.map((keyword) => (
          <label
            key={keyword.id}
            htmlFor={`existing-keyword-${keyword.id}`}
            className="flex cursor-pointer items-center gap-3 rounded-lg px-2 py-2 text-sm transition hover:bg-muted/60"
          >
            <Checkbox
              id={`existing-keyword-${keyword.id}`}
              checked={selected.has(keyword.id)}
              onCheckedChange={(checked) => onToggle(keyword, checked === true)}
              aria-label={`选择关键词 ${keyword.keyword}`}
            />
            <span className="min-w-0 flex-1 truncate font-medium">
              {keyword.keyword}
            </span>
            <span className="shrink-0 text-xs text-muted-foreground">
              {keyword.task_count} 任务 · {compact(keyword.aweme_count)} 作品
            </span>
          </label>
        ))}
        {!available.length && (
          <p className="py-5 text-center text-sm text-muted-foreground">
            {keywordsQuery.isLoading
              ? "正在加载关键词库…"
              : search.trim()
                ? "没有匹配的可添加关键词"
                : "没有其他可添加的关键词"}
          </p>
        )}
      </div>
    </div>
  )
}

function toggleKeywordSelection(
  current: Map<string, string>,
  keyword: DouyinKeywordPublic,
  checked: boolean,
) {
  const next = new Map(current)
  if (checked) next.set(keyword.id, keyword.keyword)
  else next.delete(keyword.id)
  return next
}

function uniqueKeywords(values: string[]) {
  return [...new Set(values.map((item) => item.trim()).filter(Boolean))]
}

function parseKeywords(value: string) {
  return uniqueKeywords(value.split(/[\n,，;；]+/))
}

function compact(value: number) {
  return new Intl.NumberFormat("zh-CN", { notation: "compact" }).format(value)
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value))
}
