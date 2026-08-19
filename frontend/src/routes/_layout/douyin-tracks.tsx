import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router"
import {
  Activity,
  Check,
  ChevronRight,
  Film,
  LayoutGrid,
  List,
  MessageCircle,
  MoreHorizontal,
  Play,
  Plus,
  RefreshCw,
  Search,
  Tags,
  Target,
  Trash2,
} from "lucide-react"
import { type FormEvent, useEffect, useState } from "react"

import {
  ApiError,
  DouyinAccountsService,
  type DouyinKeywordPublic,
  DouyinKeywordsService,
  type DouyinTrackPublic,
  DouyinTracksService,
} from "@/client"
import { MetricCard, PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
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
  const [viewMode, setViewMode] = useState<"rows" | "cards">(() => {
    try {
      return localStorage.getItem("douyin-tracks-view") === "cards"
        ? "cards"
        : "rows"
    } catch {
      return "rows"
    }
  })
  const changeViewMode = (mode: "rows" | "cards") => {
    setViewMode(mode)
    try {
      localStorage.setItem("douyin-tracks-view", mode)
    } catch {
      /* 隐私模式下忽略存储异常 */
    }
  }
  const [selectedTrack, setSelectedTrack] = useState<DouyinTrackPublic | null>(
    null,
  )
  const [editing, setEditing] = useState<DouyinTrackPublic | null>(null)
  const [deleting, setDeleting] = useState<DouyinTrackPublic | null>(null)
  const tracksQuery = useQuery({
    queryKey: ["douyin-tracks", search],
    queryFn: () =>
      DouyinTracksService.listTracks({ search: search.trim() || undefined }),
    retry: false,
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
    const unavailable =
      requestedTrackQuery.error instanceof ApiError &&
      [403, 404].includes(requestedTrackQuery.error.status)
    showErrorToast(
      unavailable
        ? "赛道不存在或当前账号无权访问"
        : "赛道详情读取失败，请重新打开后重试",
    )
    void navigate({ search: { run: undefined }, replace: true })
  }, [
    navigate,
    requestedTrackQuery.error,
    requestedTrackQuery.isError,
    run,
    showErrorToast,
  ])
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["douyin-tracks"] })
  const remove = useMutation({
    mutationFn: (track: DouyinTrackPublic) => {
      if (track.is_default) throw new Error("默认赛道不能删除")
      return DouyinTracksService.deleteTrack({ trackId: track.id })
    },
    onSuccess: async () => {
      showSuccessToast("赛道已删除，关键词和任务已迁移到默认赛道")
      setDeleting(null)
      await invalidate()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const toggle = useMutation({
    mutationFn: (track: DouyinTrackPublic) => {
      if (track.is_default) throw new Error("默认赛道必须保持启用")
      return DouyinTracksService.editTrack({
        trackId: track.id,
        requestBody: { enabled: !track.enabled },
      })
    },
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
        eyebrow="私域增长"
        icon={Target}
        title="赛道管理"
        description="把市场方向沉淀为唯一归属的关键词组合，持续创建采集任务，并从作品量、评论量和运行状态衡量赛道产出。"
        actions={<CreateTrackDialog onCreated={invalidate} />}
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          icon={Target}
          label="运营赛道"
          value={tracksQuery.isError ? "—" : tracks.length}
          detail={
            tracksQuery.isError ? "赛道数据读取失败" : `${active} 个正在运行`
          }
          tone="violet"
          compact
        />
        <MetricCard
          icon={Tags}
          label="关键词资产"
          value={tracksQuery.isError ? "—" : keywordCount}
          detail="每个关键词唯一归属"
          tone="blue"
          compact
        />
        <MetricCard
          icon={Film}
          label="赛道作品"
          value={tracksQuery.isError ? "—" : compact(works)}
          detail="由赛道任务采集"
          tone="mint"
          compact
        />
        <MetricCard
          icon={MessageCircle}
          label="目标评论"
          value={tracksQuery.isError ? "—" : compact(comments)}
          detail="用于用户洞察"
          tone="coral"
          compact
        />
      </div>

      <Card>
        <CardContent className="flex items-center gap-2 p-3">
          <div className="relative max-w-xl flex-1">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索赛道名称或描述"
              aria-label="搜索赛道"
              className="h-9 pl-9"
            />
          </div>
          <fieldset className="m-0 flex shrink-0 items-center rounded-lg border p-0.5">
            <legend className="sr-only">切换赛道展示方式</legend>
            <Button
              size="sm"
              variant={viewMode === "rows" ? "secondary" : "ghost"}
              className="h-8 gap-1.5 px-2.5 text-xs"
              aria-pressed={viewMode === "rows"}
              onClick={() => changeViewMode("rows")}
            >
              <List className="size-4" /> 横条
            </Button>
            <Button
              size="sm"
              variant={viewMode === "cards" ? "secondary" : "ghost"}
              className="h-8 gap-1.5 px-2.5 text-xs"
              aria-pressed={viewMode === "cards"}
              onClick={() => changeViewMode("cards")}
            >
              <LayoutGrid className="size-4" /> 卡片
            </Button>
          </fieldset>
        </CardContent>
      </Card>

      {tracksQuery.isError ? (
        <QueryErrorState
          title="赛道列表读取失败"
          description="暂时无法获取赛道数据，请检查服务连接后重试。"
          onRetry={() => void tracksQuery.refetch()}
          retrying={tracksQuery.isFetching}
        />
      ) : viewMode === "rows" ? (
        <div className="space-y-2">
          {tracks.map((track) => (
            <TrackRow
              key={track.id}
              track={track}
              onOperate={() => setSelectedTrack(track)}
              onEdit={() => setEditing(track)}
              onToggle={() => toggle.mutate(track)}
              onDelete={() => setDeleting(track)}
            />
          ))}
        </div>
      ) : (
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
                        配置：{track.enabled ? "启用" : "停用"}
                      </Badge>
                      {track.is_default && (
                        <Badge
                          variant="outline"
                          className="h-5 shrink-0 px-1.5 text-[10px]"
                        >
                          默认
                        </Badge>
                      )}
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
                      <DropdownMenuItem
                        disabled={track.is_default}
                        onClick={() => toggle.mutate(track)}
                      >
                        {track.is_default
                          ? "默认赛道必须启用"
                          : track.enabled
                            ? "停用赛道"
                            : "启用赛道"}
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        className="text-destructive"
                        disabled={track.is_default}
                        onClick={() => setDeleting(track)}
                      >
                        <Trash2 />
                        {track.is_default ? "默认赛道不可删除" : "删除赛道"}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>

                <div className="mt-2.5 grid grid-cols-4 gap-1 rounded-lg bg-muted/30 px-2 py-1.5 text-center">
                  <SmallMetric label="关键词" value={track.keyword_count} />
                  <SmallMetric label="任务" value={track.task_count} />
                  <SmallMetric
                    label="作品"
                    value={compact(track.aweme_count)}
                  />
                  <SmallMetric
                    label="评论"
                    value={compact(track.comment_count)}
                  />
                </div>

                <div className="mt-2.5 flex min-h-7 flex-wrap items-center gap-1.5 border-t pt-2.5">
                  <span className="text-[11px] font-medium text-muted-foreground">
                    最近采集：
                  </span>
                  {track.last_task_status ? (
                    <TaskStatusBadge status={track.last_task_status} />
                  ) : (
                    <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
                      尚未运行
                    </Badge>
                  )}
                  {track.last_run_at && (
                    <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
                      {formatDate(track.last_run_at)}
                    </span>
                  )}
                  {!track.last_run_at && <span className="flex-1" />}
                  <Button
                    size="sm"
                    className="h-7 gap-1 px-2 text-xs"
                    disabled={!track.enabled}
                    title={track.enabled ? undefined : "请先启用赛道再启动采集"}
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
      )}

      {!tracks.length && !tracksQuery.isLoading && !tracksQuery.isError && (
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
          key={selected.id}
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
              赛道删除后无法恢复；其关键词、采集任务和内容数据都会完整迁移到默认赛道。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={!deleting || remove.isPending}
              onClick={() => deleting && remove.mutate(deleting)}
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
      showSuccessToast("赛道已创建，关键词已归入新赛道")
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
    if (
      existingKeywords.size > 0 &&
      !window.confirm(
        `已选的 ${existingKeywords.size} 个现有关键词会从原赛道移动到新赛道“${name.trim()}”。是否继续？`,
      )
    )
      return
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
            targetTrackId=""
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
  const [excludedKeywordIds, setExcludedKeywordIds] = useState<Set<string>>(
    new Set(),
  )
  const [keywordSearch, setKeywordSearch] = useState("")
  const [mode, setMode] = useState<"combined" | "separate">("separate")
  const [maxAwemes, setMaxAwemes] = useState("30")
  const [maxComments, setMaxComments] = useState("100")
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
    retry: false,
  })
  const keywords = keywordsQuery.data?.data ?? []
  const enabledKeywords = keywords.filter((keyword) => keyword.enabled)
  const disabledKeywords = keywords.filter((keyword) => !keyword.enabled)
  const keywordTerm = keywordSearch.trim().toLocaleLowerCase("zh-CN")
  const matchedEnabled = keywordTerm
    ? enabledKeywords.filter((keyword) =>
        keyword.keyword.toLocaleLowerCase("zh-CN").includes(keywordTerm),
      )
    : enabledKeywords
  const matchedDisabled = keywordTerm
    ? disabledKeywords.filter((keyword) =>
        keyword.keyword.toLocaleLowerCase("zh-CN").includes(keywordTerm),
      )
    : disabledKeywords
  const selectedKeywordIds = enabledKeywords
    .filter((keyword) => !excludedKeywordIds.has(keyword.id))
    .map((keyword) => keyword.id)
  const freshKeywordIds = enabledKeywords
    .filter((keyword) => keyword.task_count === 0)
    .map((keyword) => keyword.id)
  const allKeywordsSelected =
    enabledKeywords.length > 0 &&
    selectedKeywordIds.length === enabledKeywords.length
  const keywordIdsForRequest = allKeywordsSelected ? [] : selectedKeywordIds
  const explicitSelectionLimitExceeded =
    !allKeywordsSelected && selectedKeywordIds.length > 200
  const separateLimitExceeded =
    mode === "separate" && selectedKeywordIds.length > 20

  useEffect(() => {
    if (!open) return
    // A newly opened run workspace always starts from the safe, explicit
    // default: every enabled keyword participates in this run. Keeping the
    // exclusions instead of the selections also means newly added keywords
    // become selected without undoing deliberate deselections.
    setExcludedKeywordIds(new Set())
  }, [open])
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
      showSuccessToast("关键词已归入当前赛道")
      await refresh()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const run = useMutation({
    mutationFn: () => {
      const requestBody: Parameters<
        typeof DouyinTracksService.createTrackTasks
      >[0]["requestBody"] = {
        keyword_ids: keywordIdsForRequest,
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
    onError: async (error) => {
      const apiError = error as ApiError
      handleError.call(showErrorToast, apiError)
      if ([404, 409].includes(apiError.status)) {
        await refresh()
        onOpenChange(false)
      }
    },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>{track.name} · 运营工作区</DialogTitle>
          <DialogDescription>
            维护搜索词并以稳定风控档创建可追踪的赛道任务。
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="min-w-0 space-y-4">
            <div className="rounded-xl border bg-muted/20 p-4">
              <p className="font-medium">添加关键词</p>
              <div className="mt-3 flex gap-2">
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
            </div>

            <section
              className="rounded-xl border bg-card p-4"
              aria-labelledby={`run-keywords-title-${track.id}`}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p
                    id={`run-keywords-title-${track.id}`}
                    className="font-medium"
                  >
                    本次采集关键词
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    默认选择全部启用关键词；点击卡片即可切换选择。
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="secondary" aria-live="polite">
                    已选择 {selectedKeywordIds.length} /{" "}
                    {enabledKeywords.length}
                  </Badge>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    aria-label="刷新本次采集关键词"
                    disabled={keywordsQuery.isFetching}
                    onClick={() => void keywordsQuery.refetch()}
                  >
                    <RefreshCw
                      aria-hidden="true"
                      className={keywordsQuery.isFetching ? "animate-spin" : ""}
                    />
                    刷新
                  </Button>
                </div>
              </div>

              {keywordsQuery.isLoading ? (
                <output
                  className="block w-full py-8 text-center text-sm text-muted-foreground"
                  aria-live="polite"
                >
                  正在加载本次采集关键词…
                </output>
              ) : keywordsQuery.isError ? (
                <div
                  className="mt-4 flex flex-col gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive sm:flex-row sm:items-center sm:justify-between"
                  role="alert"
                >
                  <span>关键词读取失败，暂时不能启动采集。</span>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={keywordsQuery.isFetching}
                    onClick={() => void keywordsQuery.refetch()}
                  >
                    {keywordsQuery.isFetching ? "正在重试…" : "重新加载"}
                  </Button>
                </div>
              ) : keywords.length === 0 ? (
                <output
                  className="mt-4 block w-full rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground"
                  aria-live="polite"
                >
                  当前赛道还没有关键词，请先在上方创建关键词。
                </output>
              ) : enabledKeywords.length === 0 ? (
                <output
                  className="mt-4 block w-full rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground"
                  aria-live="polite"
                >
                  当前赛道没有已启用的关键词，请先启用至少一个关键词。
                </output>
              ) : (
                <div className="mt-4 space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="relative min-w-52 flex-1">
                      <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                      <Input
                        value={keywordSearch}
                        onChange={(event) =>
                          setKeywordSearch(event.target.value)
                        }
                        placeholder="搜索本次要采集的关键词"
                        aria-label="搜索本次要采集的关键词"
                        className="h-9 pl-9"
                      />
                    </div>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      aria-label="全选本次采集关键词"
                      disabled={allKeywordsSelected}
                      onClick={() => setExcludedKeywordIds(new Set())}
                    >
                      全选
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      aria-label="仅选择从未采集过的关键词"
                      disabled={freshKeywordIds.length === 0}
                      onClick={() =>
                        setExcludedKeywordIds(
                          new Set(
                            enabledKeywords
                              .filter((keyword) => keyword.task_count > 0)
                              .map((keyword) => keyword.id),
                          ),
                        )
                      }
                    >
                      仅选未采集
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      aria-label="清空本次采集关键词选择"
                      disabled={selectedKeywordIds.length === 0}
                      onClick={() =>
                        setExcludedKeywordIds(
                          new Set(enabledKeywords.map((keyword) => keyword.id)),
                        )
                      }
                    >
                      清空
                    </Button>
                  </div>
                  {matchedEnabled.length === 0 ? (
                    <p className="rounded-lg border border-dashed py-6 text-center text-sm text-muted-foreground">
                      没有匹配“{keywordSearch.trim()}”的启用关键词
                    </p>
                  ) : (
                    <fieldset className="m-0 grid max-h-64 gap-2 overflow-y-auto pr-1 sm:grid-cols-2 xl:grid-cols-3">
                      <legend className="sr-only">选择本次采集关键词</legend>
                      {matchedEnabled.map((keyword) => {
                        const selected = !excludedKeywordIds.has(keyword.id)
                        return (
                          <button
                            key={keyword.id}
                            type="button"
                            aria-pressed={selected}
                            aria-label={`选择采集关键词 ${keyword.keyword}`}
                            onClick={() =>
                              setExcludedKeywordIds((current) => {
                                const next = new Set(current)
                                if (selected) next.add(keyword.id)
                                else next.delete(keyword.id)
                                return next
                              })
                            }
                            className={
                              selected
                                ? "flex min-h-12 items-center gap-2.5 rounded-lg border border-primary/60 bg-primary/5 px-3 text-left shadow-sm transition-colors"
                                : "flex min-h-12 items-center gap-2.5 rounded-lg border bg-background px-3 text-left transition-colors hover:border-primary/35 hover:bg-muted/40"
                            }
                          >
                            <span
                              aria-hidden="true"
                              className={
                                selected
                                  ? "flex size-4.5 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground"
                                  : "flex size-4.5 shrink-0 items-center justify-center rounded-full border border-muted-foreground/40 text-transparent"
                              }
                            >
                              <Check className="size-3" />
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-sm font-medium">
                                {keyword.keyword}
                              </span>
                              <span className="block text-[11px] text-muted-foreground">
                                {keyword.task_count} 任务 ·{" "}
                                {compact(keyword.aweme_count)} 作品
                              </span>
                            </span>
                          </button>
                        )
                      })}
                      {matchedDisabled.map((keyword) => (
                        <div
                          key={keyword.id}
                          className="flex min-h-12 items-center gap-2.5 rounded-lg border border-dashed bg-muted/20 px-3 text-muted-foreground"
                        >
                          <span className="min-w-0 flex-1 truncate text-sm">
                            {keyword.keyword}
                          </span>
                          <Badge variant="secondary" className="shrink-0">
                            已停用
                          </Badge>
                        </div>
                      ))}
                    </fieldset>
                  )}
                  {keywords.length > enabledKeywords.length && (
                    <p className="text-xs text-muted-foreground">
                      另有 {keywords.length - enabledKeywords.length}
                      个已停用关键词，不会加入本次任务。
                    </p>
                  )}
                </div>
              )}
            </section>
          </div>

          <div className="min-w-0 space-y-4">
            <div className="rounded-xl border bg-card p-4">
              <p className="font-medium">任务参数</p>
              <div className="mt-3 space-y-3">
                <div>
                  <Label>任务组织方式</Label>
                  <Select
                    value={mode}
                    onValueChange={(value) => setMode(value as typeof mode)}
                  >
                    <SelectTrigger
                      className="mt-2 w-full"
                      aria-label="任务组织方式"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="separate">
                        每词独立任务（推荐）
                      </SelectItem>
                      <SelectItem value="combined">组合任务</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {mode === "separate"
                      ? "每个关键词各建一个任务，便于逐个跟踪结果。"
                      : "全部选中关键词合并为一个任务，请求更少。"}
                  </p>
                </div>
                <div>
                  <Label>执行账号</Label>
                  <Select
                    value={accountChoice}
                    onValueChange={setAccountChoice}
                  >
                    <SelectTrigger className="mt-2 w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="adhoc">临时浏览器登录</SelectItem>
                      {(accounts.data?.data ?? [])
                        .filter(
                          (item) =>
                            item.enabled &&
                            ["ready", "busy"].includes(item.status),
                        )
                        .map((item) => (
                          <SelectItem
                            key={item.id}
                            value={`account:${item.id}`}
                          >
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
                        <SelectItem value="weighted_round_robin">
                          加权轮询
                        </SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                )}
                <div className="grid grid-cols-2 gap-3">
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
              </div>
            </div>

            {!track.enabled && (
              <div
                className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
                role="alert"
              >
                当前赛道已停用，请先启用赛道再启动采集任务。
              </div>
            )}
            {separateLimitExceeded && (
              <div
                className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
                role="alert"
              >
                <p>
                  每词独立任务一次最多选择 20
                  个关键词；请减少选择，或改用组合任务。
                </p>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="mt-2"
                  onClick={() => setMode("combined")}
                >
                  改用组合任务
                </Button>
              </div>
            )}
            {explicitSelectionLimitExceeded && (
              <div
                className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
                role="alert"
              >
                部分选择一次最多 200
                个关键词；请继续减少选择，或全选后运行全部关键词。
              </div>
            )}

            <div className="rounded-xl border border-amber-200/70 bg-amber-50/60 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
              默认使用云端托管浏览器、云端存储和“稳 · 随机 3–6
              秒”风控档；任务启动后可在任务列表查看实时进度。
            </div>
            <Button
              onClick={() => run.mutate()}
              className="w-full"
              disabled={
                keywordsQuery.isLoading ||
                keywordsQuery.isError ||
                !track.enabled ||
                selectedKeywordIds.length === 0 ||
                explicitSelectionLimitExceeded ||
                separateLimitExceeded ||
                run.isPending
              }
            >
              <Activity aria-hidden="true" />
              {run.isPending ? "正在创建任务…" : "启动赛道采集"}
            </Button>
          </div>
        </div>
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

function TrackRow({
  track,
  onOperate,
  onEdit,
  onToggle,
  onDelete,
}: {
  track: DouyinTrackPublic
  onOperate: () => void
  onEdit: () => void
  onToggle: () => void
  onDelete: () => void
}) {
  const navigate = useNavigate()
  const openDetail = () =>
    void navigate({
      to: "/douyin-tracks/$trackId",
      params: { trackId: track.id },
    })
  return (
    <Card
      role="link"
      tabIndex={0}
      aria-label={`查看赛道 ${track.name} 详情`}
      onClick={(event) => {
        if ((event.target as HTMLElement).closest("[data-row-actions]")) return
        openDetail()
      }}
      onKeyDown={(event) => {
        if ((event.target as HTMLElement).closest("[data-row-actions]")) return
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault()
          openDetail()
        }
      }}
      className="group cursor-pointer transition hover:border-primary/30 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <CardContent className="flex items-center gap-3 p-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-violet-500/12 text-violet-700 dark:text-violet-300">
          <Target className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-sm font-semibold transition-colors group-hover:text-primary">
              {track.name}
            </h2>
            <Badge
              variant={track.enabled ? "default" : "secondary"}
              className="h-5 shrink-0 px-1.5 text-[10px]"
            >
              配置：{track.enabled ? "启用" : "停用"}
            </Badge>
            {track.is_default && (
              <Badge
                variant="outline"
                className="h-5 shrink-0 px-1.5 text-[10px]"
              >
                默认
              </Badge>
            )}
          </div>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {track.description || "尚未填写赛道描述"}
          </p>
        </div>
        <div className="hidden shrink-0 items-center gap-5 md:flex">
          <RowMetric label="关键词" value={track.keyword_count} />
          <RowMetric label="任务" value={track.task_count} />
          <RowMetric label="作品" value={compact(track.aweme_count)} />
          <RowMetric label="评论" value={compact(track.comment_count)} />
        </div>
        <div className="hidden w-48 shrink-0 items-center gap-1.5 lg:flex">
          <span className="shrink-0 text-[11px] text-muted-foreground">
            最近采集
          </span>
          {track.last_task_status ? (
            <TaskStatusBadge status={track.last_task_status} />
          ) : (
            <Badge variant="outline" className="h-5 px-1.5 text-[10px]">
              尚未运行
            </Badge>
          )}
          {track.last_run_at && (
            <span className="truncate text-[11px] text-muted-foreground">
              {formatDate(track.last_run_at)}
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1" data-row-actions>
          <Button
            size="sm"
            className="h-8 gap-1 px-2.5 text-xs"
            disabled={!track.enabled}
            title={track.enabled ? undefined : "请先启用赛道再启动采集"}
            onClick={onOperate}
          >
            <Play className="size-3.5" /> 运营这个赛道
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className="size-8"
                aria-label="赛道操作"
              >
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={onEdit}>编辑赛道</DropdownMenuItem>
              <DropdownMenuItem disabled={track.is_default} onClick={onToggle}>
                {track.is_default
                  ? "默认赛道必须启用"
                  : track.enabled
                    ? "停用赛道"
                    : "启用赛道"}
              </DropdownMenuItem>
              <DropdownMenuItem
                className="text-destructive"
                disabled={track.is_default}
                onClick={onDelete}
              >
                <Trash2 />
                {track.is_default ? "默认赛道不可删除" : "删除赛道"}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <ChevronRight
            aria-hidden="true"
            className="size-4 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5 group-hover:text-primary"
          />
        </div>
      </CardContent>
    </Card>
  )
}

function RowMetric({
  label,
  value,
}: {
  label: string
  value: string | number
}) {
  return (
    <div className="w-14 text-center">
      <p className="text-sm font-semibold leading-none tabular-nums">{value}</p>
      <p className="mt-1 text-[10px] text-muted-foreground">{label}</p>
    </div>
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
  targetTrackId,
  selected,
  excludedIds,
  onToggle,
}: {
  targetTrackId: string
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
          <p className="text-sm font-medium">移动已有关键词</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            搜索其他赛道的关键词；确认后会将唯一归属迁移到当前赛道。
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
              {keyword.track_id === targetTrackId
                ? "当前赛道"
                : keyword.track_name}
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
