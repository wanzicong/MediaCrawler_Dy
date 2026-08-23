import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router"
import {
  Activity,
  Check,
  ChevronRight,
  LayoutGrid,
  List,
  MoreHorizontal,
  Play,
  Plus,
  RefreshCw,
  Search,
  Table2,
  Target,
  Trash2,
} from "lucide-react"
import { type FormEvent, useEffect, useState } from "react"

import {
  ApiError,
  DouyinAccountsService,
  type DouyinBrowserMode,
  type DouyinLoginType,
  type DouyinTrackPublic,
  DouyinTracksService,
} from "@/client"
import { PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { creatorNameLabel } from "@/components/Douyin/presentation"
import { TaskStatusBadge } from "@/components/Douyin/TaskStatusBadge"
import { DOUYIN_TASK_PARAMETER_DEFAULTS } from "@/components/Douyin/taskParameters"
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
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
  const [viewMode, setViewMode] = useState<"table" | "rows" | "cards">(() => {
    try {
      const saved = localStorage.getItem("douyin-tracks-view")
      return saved === "rows" || saved === "cards" ? saved : "table"
    } catch {
      return "table"
    }
  })
  const changeViewMode = (mode: "table" | "rows" | "cards") => {
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
    onSuccess: async (result) => {
      showSuccessToast(result.message)
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
        compact
        title="赛道管理"
        actions={<CreateTrackDialog onCreated={invalidate} />}
      >
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm">
          <InlineSummary
            label="赛道"
            value={tracksQuery.isError ? "—" : tracks.length}
          />
          <InlineSummary
            label="运行"
            value={tracksQuery.isError ? "—" : active}
          />
          <InlineSummary
            label="关键词"
            value={tracksQuery.isError ? "—" : keywordCount}
          />
          <InlineSummary
            label="作品"
            value={tracksQuery.isError ? "—" : compact(works)}
          />
          <InlineSummary
            label="评论"
            value={tracksQuery.isError ? "—" : compact(comments)}
          />
        </div>
      </PageHero>

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
              variant={viewMode === "table" ? "secondary" : "ghost"}
              className="h-8 gap-1.5 px-2.5 text-xs"
              aria-pressed={viewMode === "table"}
              onClick={() => changeViewMode("table")}
            >
              <Table2 className="size-4" /> 表格
            </Button>
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
      ) : viewMode === "table" ? (
        <Card className="overflow-hidden py-0">
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>赛道</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">关键词</TableHead>
                  <TableHead className="text-right">任务</TableHead>
                  <TableHead className="text-right">作品</TableHead>
                  <TableHead className="text-right">评论</TableHead>
                  <TableHead>最近采集</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tracks.map((track) => (
                  <TableRow key={track.id}>
                    <TableCell className="max-w-72">
                      <Link
                        to="/douyin-tracks/$trackId"
                        params={{ trackId: track.id }}
                        className="font-medium hover:text-primary hover:underline"
                      >
                        {track.name}
                      </Link>
                      <p className="mt-0.5 truncate text-xs text-muted-foreground">
                        {track.description || "尚未填写赛道描述"}
                      </p>
                    </TableCell>
                    <TableCell>
                      <Badge variant={track.enabled ? "default" : "secondary"}>
                        {track.enabled ? "启用" : "停用"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {track.keyword_count}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {track.task_count}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {compact(track.aweme_count)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {compact(track.comment_count)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {track.last_run_at
                        ? formatDate(track.last_run_at)
                        : "尚未运行"}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        disabled={!track.enabled}
                        onClick={() => setSelectedTrack(track)}
                      >
                        <Play /> 运行
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
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
              系统会先停止运行中的任务，再永久删除该赛道以及对应的关键词、达人、任务、视频、评论、互动和请求日志。此操作无法撤销。
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
              {remove.isPending ? "正在停止并删除…" : "确认全部删除"}
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
  const mutation = useMutation({
    mutationFn: () =>
      DouyinTracksService.addTrack({
        requestBody: {
          name,
          description,
          prompt,
          keywords: parseKeywords(keywords),
        },
      }),
    onSuccess: async () => {
      showSuccessToast("赛道已创建，关键词已归入新赛道")
      setOpen(false)
      setName("")
      setDescription("")
      setPrompt("")
      setKeywords("")
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
  const [excludedCreatorIds, setExcludedCreatorIds] = useState<Set<string>>(
    new Set(),
  )
  const [keywordSearch, setKeywordSearch] = useState("")
  const [maxAwemes, setMaxAwemes] = useState(
    String(DOUYIN_TASK_PARAMETER_DEFAULTS.maxAwemes),
  )
  const [maxComments, setMaxComments] = useState(
    String(DOUYIN_TASK_PARAMETER_DEFAULTS.maxComments),
  )
  const [fetchComments, setFetchComments] = useState<boolean>(
    DOUYIN_TASK_PARAMETER_DEFAULTS.fetchComments,
  )
  const [fetchSubComments, setFetchSubComments] = useState<boolean>(
    DOUYIN_TASK_PARAMETER_DEFAULTS.fetchSubComments,
  )
  const [startPage, setStartPage] = useState(
    String(DOUYIN_TASK_PARAMETER_DEFAULTS.startPage),
  )
  const [concurrency, setConcurrency] = useState(
    String(DOUYIN_TASK_PARAMETER_DEFAULTS.concurrency),
  )
  const [requestDelayLevel, setRequestDelayLevel] = useState<
    "fast" | "steady" | "ultra_steady"
  >(DOUYIN_TASK_PARAMETER_DEFAULTS.delayLevel)
  const [taskInterval, setTaskInterval] = useState("")
  const [publishTime, setPublishTime] = useState(
    String(DOUYIN_TASK_PARAMETER_DEFAULTS.publishTime),
  )
  const [downloadMedia, setDownloadMedia] = useState<boolean>(
    DOUYIN_TASK_PARAMETER_DEFAULTS.downloadMedia,
  )
  const [translateSubtitles, setTranslateSubtitles] = useState<boolean>(
    DOUYIN_TASK_PARAMETER_DEFAULTS.translateSubtitles,
  )
  const [loginType, setLoginType] = useState<DouyinLoginType>("qrcode")
  const [browserMode, setBrowserMode] = useState<DouyinBrowserMode | "default">(
    "remote",
  )
  const [cookies, setCookies] = useState("")
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
  const creatorsQuery = useQuery({
    queryKey: ["douyin-track-creators", track.id],
    queryFn: () => DouyinTracksService.listTrackCreators({ trackId: track.id }),
    enabled: open,
    retry: false,
  })
  const keywords = keywordsQuery.data?.data ?? []
  const creators = creatorsQuery.data?.data ?? []
  const selectableCreators = creators.filter(
    (creator) => creator.enabled && !creator.is_placeholder,
  )
  const selectedCreatorIds = selectableCreators
    .filter((creator) => !excludedCreatorIds.has(creator.id))
    .map((creator) => creator.id)
  const allCreatorsSelected =
    selectableCreators.length > 0 &&
    selectedCreatorIds.length === selectableCreators.length
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
  // 始终提交显式勾选列表：空数组表示本次不采集关键词（不再以空数组传达全选），
  // 后端仅在关键词与达人都为空时才回退为运行全部已启用关键词。
  const keywordIdsForRequest = selectedKeywordIds
  const explicitSelectionLimitExceeded =
    !allKeywordsSelected && selectedKeywordIds.length > 200

  useEffect(() => {
    if (!open) return
    // A newly opened run workspace always starts from the safe, explicit
    // default: every enabled keyword participates in this run. Keeping the
    // exclusions instead of the selections also means newly added keywords
    // become selected without undoing deliberate deselections.
    setExcludedKeywordIds(new Set())
    setExcludedCreatorIds(new Set())
    // Keep the run workspace compatible with tracks created before default
    // task configuration was introduced (and with temporarily stale clients).
    const defaults = track.default_task_config ?? {}
    setStartPage(String(defaults.start_page ?? 1))
    setMaxAwemes(
      String(defaults.max_awemes ?? DOUYIN_TASK_PARAMETER_DEFAULTS.maxAwemes),
    )
    setFetchComments(defaults.fetch_comments ?? true)
    setFetchSubComments(defaults.fetch_sub_comments ?? false)
    setMaxComments(String(defaults.max_comments_per_aweme ?? 10))
    setConcurrency(String(defaults.concurrency ?? 1))
    setRequestDelayLevel(defaults.request_delay_level ?? "steady")
    setTaskInterval(
      defaults.task_interval_seconds == null
        ? ""
        : String(defaults.task_interval_seconds),
    )
    setPublishTime(String(defaults.publish_time ?? 0))
    setDownloadMedia(defaults.download_media ?? false)
    setTranslateSubtitles(defaults.translate_subtitles ?? false)
    setLoginType("qrcode")
    setBrowserMode(defaults.browser_mode ?? "remote")
    setCookies("")
    setAccountStrategy(defaults.account_strategy ?? "least_loaded")
    setAccountChoice(
      defaults.account_id
        ? `account:${defaults.account_id}`
        : defaults.account_pool_id
          ? `pool:${defaults.account_pool_id}`
          : defaults.account_ids?.length
            ? `accounts:${defaults.account_ids.join(",")}`
            : "adhoc",
    )
  }, [open, track])
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
        creator_ids: selectedCreatorIds,
        mode: "separate",
        start_page: Number(startPage),
        max_awemes: Number(maxAwemes),
        max_comments_per_aweme: Number(maxComments),
        fetch_comments: fetchComments,
        fetch_sub_comments: fetchComments && fetchSubComments,
        concurrency: Number(concurrency),
        request_delay_level: requestDelayLevel,
        request_interval_seconds:
          requestDelayLevel === "fast"
            ? 1
            : requestDelayLevel === "steady"
              ? 3
              : 6,
        ...(taskInterval.trim()
          ? { task_interval_seconds: Number(taskInterval) }
          : {}),
        publish_time: Number(publishTime),
        login_type: loginType,
        browser_mode: browserMode === "default" ? undefined : browserMode,
        cookies: loginType === "cookie" ? cookies.trim() : undefined,
        download_media: downloadMedia || translateSubtitles,
        translate_subtitles: translateSubtitles,
        media_processing_mode:
          downloadMedia || translateSubtitles ? "immediate" : "none",
      }
      if (accountChoice.startsWith("account:")) {
        requestBody.account_id = accountChoice.slice(8)
        requestBody.login_type = "qrcode"
        requestBody.browser_mode = undefined
        requestBody.cookies = undefined
      }
      if (accountChoice.startsWith("pool:")) {
        requestBody.account_pool_id = accountChoice.slice(5)
        requestBody.account_strategy = accountStrategy
        requestBody.login_type = "qrcode"
        requestBody.browser_mode = undefined
        requestBody.cookies = undefined
      }
      if (accountChoice.startsWith("accounts:")) {
        requestBody.account_ids = accountChoice.slice(9).split(",")
        requestBody.login_type = "qrcode"
        requestBody.browser_mode = undefined
        requestBody.cookies = undefined
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
  const startRun = () => {
    if (
      accountChoice === "adhoc" &&
      loginType === "cookie" &&
      !cookies.trim()
    ) {
      showErrorToast("临时凭据登录必须填写登录凭据")
      return
    }
    run.mutate()
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="h-[calc(100vh-2rem)] max-h-[calc(100vh-2rem)] w-[calc(100vw-2rem)] max-w-none overflow-y-auto sm:max-w-none">
        <DialogHeader>
          <DialogTitle>{track.name} · 运营工作区</DialogTitle>
        </DialogHeader>

        <div className="grid gap-4 xl:grid-cols-[380px_minmax(0,1fr)]">
          <div className="order-2 min-w-0 space-y-3 xl:order-2">
            <div className="rounded-xl border bg-muted/20 p-2.5">
              <div className="flex gap-2">
                <Input
                  value={newKeywords}
                  onChange={(event) => setNewKeywords(event.target.value)}
                  placeholder="添加关键词，逗号或换行分隔"
                  aria-label="添加关键词"
                  className="h-9"
                />
                <Button
                  variant="outline"
                  size="sm"
                  className="h-9 shrink-0"
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
              className="rounded-xl border bg-card p-3"
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
                <div className="mt-3 space-y-2">
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
                    <fieldset className="m-0 grid max-h-[46vh] gap-1.5 overflow-y-auto pr-1 sm:grid-cols-3 2xl:grid-cols-4">
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
                                ? "flex min-h-9 items-center gap-2 rounded-lg border border-primary/60 bg-primary/5 px-2 py-1.5 text-left shadow-sm transition-colors"
                                : "flex min-h-9 items-center gap-2 rounded-lg border bg-background px-2 py-1.5 text-left transition-colors hover:border-primary/35 hover:bg-muted/40"
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
                              <span className="block break-words text-xs font-medium leading-4">
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
                          className="flex min-h-9 items-center gap-2 rounded-lg border border-dashed bg-muted/20 px-2 py-1.5 text-muted-foreground"
                        >
                          <span className="min-w-0 flex-1 break-words text-xs leading-4">
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

            <section
              className="rounded-xl border bg-card p-3"
              aria-labelledby={`run-creators-title-${track.id}`}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p
                    id={`run-creators-title-${track.id}`}
                    className="font-medium"
                  >
                    本次采集达人
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant="secondary" aria-live="polite">
                    已选择 {selectedCreatorIds.length} /{" "}
                    {selectableCreators.length}
                  </Badge>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    aria-label="全选本次采集达人"
                    disabled={allCreatorsSelected}
                    onClick={() => setExcludedCreatorIds(new Set())}
                  >
                    全选
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    aria-label="清空本次采集达人选择"
                    disabled={selectedCreatorIds.length === 0}
                    onClick={() =>
                      setExcludedCreatorIds(
                        new Set(
                          selectableCreators.map((creator) => creator.id),
                        ),
                      )
                    }
                  >
                    清空
                  </Button>
                </div>
              </div>

              {creatorsQuery.isLoading ? (
                <output
                  className="block w-full py-8 text-center text-sm text-muted-foreground"
                  aria-live="polite"
                >
                  正在加载本次采集达人…
                </output>
              ) : creatorsQuery.isError ? (
                <div
                  className="mt-4 flex flex-col gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive sm:flex-row sm:items-center sm:justify-between"
                  role="alert"
                >
                  <span>达人读取失败，本次运行将只采集关键词。</span>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={creatorsQuery.isFetching}
                    onClick={() => void creatorsQuery.refetch()}
                  >
                    {creatorsQuery.isFetching ? "正在重试…" : "重新加载"}
                  </Button>
                </div>
              ) : creators.length === 0 ? (
                <output
                  className="mt-4 block w-full rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground"
                  aria-live="polite"
                >
                  当前赛道还没有达人，本次运行只采集关键词。
                </output>
              ) : selectableCreators.length === 0 ? (
                <output
                  className="mt-4 block w-full rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground"
                  aria-live="polite"
                >
                  当前赛道没有可采集的达人（全部停用或待补全）。
                </output>
              ) : (
                <div className="mt-4">
                  <fieldset className="m-0 grid max-h-[30vh] gap-1.5 overflow-y-auto pr-1 sm:grid-cols-3 2xl:grid-cols-4">
                    <legend className="sr-only">选择本次采集达人</legend>
                    {selectableCreators.map((creator) => {
                      const selected = !excludedCreatorIds.has(creator.id)
                      return (
                        <button
                          key={creator.id}
                          type="button"
                          aria-pressed={selected}
                          aria-label={`选择采集达人 ${creatorNameLabel(creator)}`}
                          onClick={() =>
                            setExcludedCreatorIds((current) => {
                              const next = new Set(current)
                              if (selected) next.add(creator.id)
                              else next.delete(creator.id)
                              return next
                            })
                          }
                          className={
                            selected
                              ? "flex min-h-9 items-center gap-2 rounded-lg border border-primary/60 bg-primary/5 px-2 py-1.5 text-left shadow-sm transition-colors"
                              : "flex min-h-9 items-center gap-2 rounded-lg border bg-background px-2 py-1.5 text-left transition-colors hover:border-primary/35 hover:bg-muted/40"
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
                            <span className="block break-words text-xs font-medium leading-4">
                              {creatorNameLabel(creator)}
                            </span>
                            <span className="block text-[11px] text-muted-foreground">
                              {creator.task_count} 任务 ·{" "}
                              {compact(creator.aweme_count)} 作品
                            </span>
                          </span>
                        </button>
                      )
                    })}
                  </fieldset>
                  {creators.length > selectableCreators.length && (
                    <p className="mt-2 text-xs text-muted-foreground">
                      另有 {creators.length - selectableCreators.length}
                      个已停用或待补全达人，不会加入本次任务。
                    </p>
                  )}
                </div>
              )}
            </section>
          </div>

          <div className="order-1 min-w-0 space-y-3 xl:order-1">
            <div className="rounded-xl border bg-card p-3">
              <p className="font-medium">任务参数</p>
              <div className="mt-3 space-y-3">
                <div>
                  <Label>执行账号</Label>
                  <Select
                    value={accountChoice}
                    onValueChange={setAccountChoice}
                  >
                    <SelectTrigger
                      className="mt-2 w-full"
                      aria-label="赛道任务执行账号"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="adhoc">临时浏览器登录</SelectItem>
                      {accountChoice.startsWith("accounts:") && (
                        <SelectItem value={accountChoice}>
                          赛道默认 · 多账号并行
                        </SelectItem>
                      )}
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
                {accountChoice === "adhoc" && (
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <Label>登录方式</Label>
                      <Select
                        value={loginType}
                        onValueChange={(value) =>
                          setLoginType(value as DouyinLoginType)
                        }
                      >
                        <SelectTrigger
                          className="mt-2 w-full"
                          aria-label="赛道任务登录方式"
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="qrcode">扫码登录</SelectItem>
                          <SelectItem value="cookie">临时凭据登录</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div>
                      <Label>浏览器</Label>
                      <Select
                        value={browserMode}
                        onValueChange={(value) =>
                          setBrowserMode(value as DouyinBrowserMode | "default")
                        }
                      >
                        <SelectTrigger
                          className="mt-2 w-full"
                          aria-label="赛道任务浏览器"
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="default">跟随服务配置</SelectItem>
                          <SelectItem value="local">本机浏览器</SelectItem>
                          <SelectItem value="remote">云端托管浏览器</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                )}
                {accountChoice === "adhoc" && loginType === "cookie" && (
                  <div>
                    <Label htmlFor="track-runtime-cookies">临时登录凭据</Label>
                    <Textarea
                      id="track-runtime-cookies"
                      value={cookies}
                      placeholder="sessionid=...; LOGIN_STATUS=1"
                      autoComplete="off"
                      onChange={(event) => setCookies(event.target.value)}
                      className="mt-2"
                    />
                    <p className="mt-1 text-xs text-muted-foreground">
                      只在本次赛道运行中使用，不会保存到赛道配置或任务记录。
                    </p>
                  </div>
                )}
                {accountChoice.startsWith("pool:") && (
                  <div>
                    <Label>调度策略</Label>
                    <Select
                      value={accountStrategy}
                      onValueChange={(value) =>
                        setAccountStrategy(value as typeof accountStrategy)
                      }
                    >
                      <SelectTrigger
                        className="mt-2 w-full"
                        aria-label="赛道任务账号池调度策略"
                      >
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
                <div>
                  <Label htmlFor="track-max-awemes">最大作品数</Label>
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
                <div className="flex items-start gap-2 rounded-lg border p-3 text-sm">
                  <Checkbox
                    id="track-fetch-comments"
                    checked={fetchComments}
                    onCheckedChange={(checked) =>
                      setFetchComments(checked === true)
                    }
                  />
                  <Label htmlFor="track-fetch-comments" className="font-normal">
                    <span className="block font-medium">同时抓取评论</span>
                    <span className="text-xs text-muted-foreground">
                      关闭后只采集作品，评论参数自动忽略。
                    </span>
                  </Label>
                </div>
                <details className="rounded-lg border bg-muted/20">
                  <summary className="cursor-pointer px-3 py-2.5 text-sm font-medium">
                    高级爬取参数（按需修改）
                  </summary>
                  <div className="grid gap-3 border-t p-3 sm:grid-cols-2">
                    <div>
                      <Label htmlFor="track-start-page">起始页</Label>
                      <Input
                        id="track-start-page"
                        type="number"
                        min={1}
                        value={startPage}
                        onChange={(event) => setStartPage(event.target.value)}
                        className="mt-2"
                      />
                    </div>
                    <div>
                      <Label htmlFor="track-concurrency">并发数</Label>
                      <Input
                        id="track-concurrency"
                        type="number"
                        min={1}
                        max={5}
                        value={concurrency}
                        onChange={(event) => setConcurrency(event.target.value)}
                        className="mt-2"
                      />
                    </div>
                    <div>
                      <Label>风控节奏</Label>
                      <Select
                        value={requestDelayLevel}
                        onValueChange={(value) =>
                          setRequestDelayLevel(
                            value as typeof requestDelayLevel,
                          )
                        }
                      >
                        <SelectTrigger
                          className="mt-2 w-full"
                          aria-label="赛道任务请求风控档位"
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="fast">快 · 随机 1–2 秒</SelectItem>
                          <SelectItem value="steady">
                            稳 · 随机 3–6 秒
                          </SelectItem>
                          <SelectItem value="ultra_steady">
                            超级稳 · 随机 6–12 秒
                          </SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div>
                      <Label htmlFor="track-task-interval">
                        任务完成后间隔（秒）
                      </Label>
                      <Input
                        id="track-task-interval"
                        type="number"
                        min={0}
                        max={3600}
                        step={1}
                        value={taskInterval}
                        onChange={(event) =>
                          setTaskInterval(event.target.value)
                        }
                        placeholder="跟随请求风控节奏"
                        className="mt-2"
                      />
                      <p className="mt-1 text-xs text-muted-foreground">
                        批量任务按完成顺序执行；留空沿用请求风控区间，填 0
                        表示不额外等待。
                      </p>
                    </div>
                    <div>
                      <Label>发布时间</Label>
                      <Select
                        value={publishTime}
                        onValueChange={setPublishTime}
                      >
                        <SelectTrigger
                          className="mt-2 w-full"
                          aria-label="赛道任务发布时间"
                        >
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
                    {fetchComments && (
                      <div className="grid gap-3 rounded-lg border bg-background p-3 sm:col-span-2 sm:grid-cols-2">
                        <div className="flex items-center gap-2 text-sm">
                          <Checkbox
                            id="track-fetch-sub-comments"
                            checked={fetchSubComments}
                            onCheckedChange={(checked) =>
                              setFetchSubComments(checked === true)
                            }
                          />
                          <Label htmlFor="track-fetch-sub-comments">
                            抓取子评论
                          </Label>
                        </div>
                        <div>
                          <Label htmlFor="track-max-comments">
                            每个作品最大评论数
                          </Label>
                          <Input
                            id="track-max-comments"
                            type="number"
                            min={1}
                            max={1000}
                            value={maxComments}
                            onChange={(event) =>
                              setMaxComments(event.target.value)
                            }
                            className="mt-2"
                          />
                        </div>
                      </div>
                    )}
                  </div>
                </details>
                <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
                  <label
                    htmlFor="track-download-media"
                    className="flex cursor-pointer items-center gap-2 rounded-lg border p-2.5 text-sm"
                  >
                    <Checkbox
                      id="track-download-media"
                      checked={downloadMedia}
                      onCheckedChange={(checked) =>
                        setDownloadMedia(checked === true)
                      }
                    />
                    采集完成后下载视频
                  </label>
                  <label
                    htmlFor="track-translate-subtitles"
                    className="flex cursor-pointer items-center gap-2 rounded-lg border p-2.5 text-sm"
                  >
                    <Checkbox
                      id="track-translate-subtitles"
                      checked={translateSubtitles}
                      onCheckedChange={(checked) => {
                        const enabled = checked === true
                        setTranslateSubtitles(enabled)
                        if (enabled) setDownloadMedia(true)
                      }}
                    />
                    下载后生成字幕
                  </label>
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
            {explicitSelectionLimitExceeded && (
              <div
                className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
                role="alert"
              >
                部分选择一次最多 200
                个关键词；请继续减少选择，或全选后运行全部关键词。
              </div>
            )}

            <Button
              onClick={startRun}
              size="lg"
              className="h-12 w-full text-base shadow-lg shadow-primary/20"
              disabled={
                keywordsQuery.isLoading ||
                keywordsQuery.isError ||
                !track.enabled ||
                (selectedKeywordIds.length === 0 &&
                  selectedCreatorIds.length === 0) ||
                explicitSelectionLimitExceeded ||
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
            <DropdownMenuContent
              align="end"
              onClick={(event) => event.stopPropagation()}
            >
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

function InlineSummary({
  label,
  value,
}: {
  label: string
  value: string | number
}) {
  return (
    <span className="whitespace-nowrap text-muted-foreground">
      {label} <strong className="font-semibold text-foreground">{value}</strong>
    </span>
  )
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
