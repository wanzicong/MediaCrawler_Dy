import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  CheckCircle2,
  Clock3,
  Database,
  History,
  ListFilter,
  LoaderCircle,
  Play,
  Plus,
  Search,
  Tags,
  Trash2,
  XCircle,
} from "lucide-react"
import {
  type FormEvent,
  type ReactNode,
  useEffect,
  useMemo,
  useState,
} from "react"

import {
  DouyinAccountsService,
  type DouyinKeywordPublic,
  type DouyinKeywordStatus,
  DouyinKeywordsService,
} from "@/client"
import { MetricCard, PageHero } from "@/components/Common/PageShell"
import { TaskStatusBadge } from "@/components/Douyin/TaskStatusBadge"
import {
  TrackBadge,
  TrackSelect,
  useTrackCatalog,
} from "@/components/Douyin/TrackSelect"
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

export const Route = createFileRoute("/_layout/douyin-keywords")({
  component: DouyinKeywordsPage,
  head: () => ({ meta: [{ title: "关键词管理 - 灵感采集台" }] }),
})

const pageSize = 50
const statusLabels: Record<DouyinKeywordStatus, string> = {
  unprocessed: "未爬取",
  active: "进行中",
  crawled: "已爬取",
  failed: "需要重试",
}

function DouyinKeywordsPage() {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [page, setPage] = useState(0)
  const [trackId, setTrackId] = useState("")
  const [search, setSearch] = useState("")
  const [status, setStatus] = useState<DouyinKeywordStatus | "all">("all")
  const [enabled, setEnabled] = useState<"all" | "true" | "false">("all")
  const [sort, setSort] = useState("last_crawled_at:desc")
  const [selected, setSelected] = useState<string[]>([])
  const tracksQuery = useTrackCatalog()
  const selectedTrack = tracksQuery.data?.data.find(
    (track) => track.id === trackId,
  )
  const [sortBy, sortOrder] = sort.split(":") as [
    (
      | "keyword"
      | "status"
      | "task_count"
      | "aweme_count"
      | "last_crawled_at"
      | "created_at"
    ),
    "asc" | "desc",
  ]
  const query = useQuery({
    queryKey: ["douyin-keywords", trackId, page, search, status, enabled, sort],
    queryFn: () =>
      DouyinKeywordsService.listKeywords({
        trackId: trackId || undefined,
        search: search.trim() || undefined,
        status: status === "all" ? undefined : status,
        enabled: enabled === "all" ? undefined : enabled === "true",
        sortBy,
        sortOrder,
        skip: page * pageSize,
        limit: pageSize,
      }),
    placeholderData: (previous) => previous,
    enabled: Boolean(trackId),
    refetchInterval: 5_000,
  })
  const overviewQuery = useQuery({
    queryKey: ["douyin-keywords-overview", trackId],
    queryFn: () =>
      DouyinKeywordsService.listKeywords({
        trackId: trackId || undefined,
        limit: 500,
      }),
    enabled: Boolean(trackId),
    refetchInterval: 10_000,
  })
  const rows = query.data?.data ?? []
  const allRows = overviewQuery.data?.data ?? []
  const metrics = useMemo(
    () => ({
      total: overviewQuery.data?.count ?? 0,
      unprocessed: allRows.filter((item) => item.status === "unprocessed")
        .length,
      active: allRows.filter((item) => item.status === "active").length,
      crawled: allRows.filter((item) => item.status === "crawled").length,
      failed: allRows.filter((item) => item.status === "failed").length,
    }),
    [allRows, overviewQuery.data?.count],
  )
  const pageIds = rows.map((item) => item.id)
  const allPageSelected =
    pageIds.length > 0 && pageIds.every((id) => selected.includes(id))
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["douyin-keywords"] }),
      queryClient.invalidateQueries({ queryKey: ["douyin-keywords-overview"] }),
    ])
  }
  const historySync = useMutation({
    mutationFn: () => DouyinKeywordsService.syncHistoricalKeywords(),
    onSuccess: async (result) => {
      showSuccessToast(
        `已扫描 ${result.task_count} 个任务，新增 ${result.created_count} 个关键词、${result.binding_count} 个绑定`,
      )
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const toggle = useMutation({
    mutationFn: (item: DouyinKeywordPublic) =>
      DouyinKeywordsService.editKeyword({
        keywordId: item.id,
        requestBody: { enabled: !item.enabled },
      }),
    onSuccess: invalidate,
    onError: handleError.bind(showErrorToast),
  })
  const remove = useMutation({
    mutationFn: (id: string) =>
      DouyinKeywordsService.deleteKeyword({ keywordId: id }),
    onSuccess: async () => {
      showSuccessToast("关键词已删除，历史任务和作品未受影响")
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const bulkRemove = useMutation({
    mutationFn: (ids: string[]) =>
      DouyinKeywordsService.bulkDeleteKeywords({ requestBody: { ids } }),
    onSuccess: async () => {
      showSuccessToast(`已删除 ${selected.length} 个关键词，历史数据已保留`)
      setSelected([])
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })

  return (
    <div className="page-stack">
      <PageHero
        eyebrow="选题与采集词库"
        icon={Tags}
        title="关键词管理"
        description="以赛道为一级归属沉淀手工词和任务词，跟踪每个关键词的采集状态，并在同一赛道内批量发起下一轮任务。"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              disabled={historySync.isPending}
              onClick={() => historySync.mutate()}
            >
              <History
                className={historySync.isPending ? "animate-spin" : ""}
              />
              同步历史任务
            </Button>
            <CreateKeywordsDialog
              initialTrackId={trackId}
              onCreated={invalidate}
            />
            <BatchTaskDialog
              keywordIds={selected}
              trackId={trackId}
              trackName={selectedTrack?.name ?? "当前赛道"}
              onCreated={() => {
                setSelected([])
                void invalidate()
              }}
            />
            <Button
              variant="destructive"
              disabled={!selected.length || bulkRemove.isPending}
              onClick={() => {
                if (
                  window.confirm(
                    `确定删除选中的 ${selected.length} 个关键词吗？历史任务和作品不会被删除。`,
                  )
                )
                  bulkRemove.mutate(selected)
              }}
            >
              <Trash2 />
              批量删除
            </Button>
          </div>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <MetricCard
            icon={Database}
            label="关键词总数"
            value={metrics.total}
            tone="violet"
            compact
          />
          <MetricCard
            icon={Clock3}
            label="未爬取"
            value={metrics.unprocessed}
            tone="slate"
            compact
          />
          <MetricCard
            icon={LoaderCircle}
            label="进行中"
            value={metrics.active}
            tone="blue"
            compact
          />
          <MetricCard
            icon={CheckCircle2}
            label="已爬取"
            value={metrics.crawled}
            tone="mint"
            compact
          />
          <MetricCard
            icon={XCircle}
            label="需要重试"
            value={metrics.failed}
            tone="rose"
            compact
          />
        </div>
      </PageHero>

      <Card>
        <CardContent className="space-y-4 p-4 md:p-6">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <div className="relative md:col-span-2">
              <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value)
                  setPage(0)
                }}
                placeholder="搜索关键词或备注"
                className="pl-9"
              />
            </div>
            <TrackSelect
              value={trackId}
              onValueChange={(value) => {
                setTrackId(value)
                setSelected([])
                setPage(0)
              }}
              ariaLabel="按赛道筛选关键词"
              allowDisabled
            />
            <Select
              value={status}
              onValueChange={(value) => {
                setStatus(value as typeof status)
                setPage(0)
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部状态</SelectItem>
                {Object.entries(statusLabels).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={enabled}
              onValueChange={(value) => {
                setEnabled(value as typeof enabled)
                setPage(0)
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部启用状态</SelectItem>
                <SelectItem value="true">已启用</SelectItem>
                <SelectItem value="false">已停用</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={sort}
              onValueChange={(value) => {
                setSort(value)
                setPage(0)
              }}
            >
              <SelectTrigger>
                <ListFilter />
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="last_crawled_at:desc">最近爬取</SelectItem>
                <SelectItem value="created_at:desc">最近创建</SelectItem>
                <SelectItem value="keyword:asc">关键词 A-Z</SelectItem>
                <SelectItem value="task_count:desc">关联任务最多</SelectItem>
                <SelectItem value="aweme_count:desc">作品最多</SelectItem>
                <SelectItem value="status:asc">优先处理状态</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-muted/20 p-3 text-sm">
            <span className="text-muted-foreground">
              已选择 {selected.length} 个关键词
            </span>
            <span className="text-xs text-muted-foreground">
              合并任务每 20 个词自动分组；独立任务一次最多 20 个。
            </span>
          </div>

          <div className="overflow-x-auto rounded-xl border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">
                    <Checkbox
                      checked={allPageSelected}
                      aria-label="选择本页关键词"
                      onCheckedChange={(checked) =>
                        setSelected((current) =>
                          checked
                            ? Array.from(new Set([...current, ...pageIds]))
                            : current.filter((id) => !pageIds.includes(id)),
                        )
                      }
                    />
                  </TableHead>
                  <TableHead>关键词</TableHead>
                  <TableHead>所属赛道</TableHead>
                  <TableHead>爬取状态</TableHead>
                  <TableHead>任务表现</TableHead>
                  <TableHead>来源作品</TableHead>
                  <TableHead>最近爬取</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.length ? (
                  rows.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell>
                        <Checkbox
                          checked={selected.includes(item.id)}
                          aria-label={`选择关键词 ${item.keyword}`}
                          onCheckedChange={(checked) =>
                            setSelected((current) =>
                              checked
                                ? [...new Set([...current, item.id])]
                                : current.filter((id) => id !== item.id),
                            )
                          }
                        />
                      </TableCell>
                      <TableCell className="min-w-64">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{item.keyword}</span>
                          {!item.enabled && (
                            <Badge variant="secondary">已停用</Badge>
                          )}
                        </div>
                        {item.notes && (
                          <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                            {item.notes}
                          </p>
                        )}
                      </TableCell>
                      <TableCell>
                        <TrackBadge
                          trackId={item.track_id}
                          trackName={item.track_name}
                          isDefault={item.track_is_default}
                        />
                      </TableCell>
                      <TableCell>
                        <KeywordStatusBadge status={item.status} />
                      </TableCell>
                      <TableCell className="min-w-40 text-sm">
                        <p>{item.task_count} 个任务</p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          成功 {item.success_task_count} · 失败{" "}
                          {item.failed_task_count} · 运行{" "}
                          {item.active_task_count}
                        </p>
                      </TableCell>
                      <TableCell>{item.aweme_count}</TableCell>
                      <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                        {formatDate(item.last_crawled_at)}
                      </TableCell>
                      <TableCell>
                        <div className="flex min-w-max justify-end gap-1">
                          <KeywordTasksDialog item={item} />
                          <MoveKeywordDialog item={item} onMoved={invalidate} />
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => toggle.mutate(item)}
                          >
                            {item.enabled ? "停用" : "启用"}
                          </Button>
                          <DeleteKeywordDialog
                            item={item}
                            pending={remove.isPending}
                            onConfirm={() => remove.mutate(item.id)}
                          />
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell
                      colSpan={8}
                      className="h-40 text-center text-muted-foreground"
                    >
                      {query.isLoading
                        ? "正在加载关键词…"
                        : "没有符合筛选条件的关键词"}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          <Pager
            page={page}
            count={query.data?.count ?? 0}
            onChange={setPage}
          />
        </CardContent>
      </Card>
    </div>
  )
}

function CreateKeywordsDialog({
  onCreated,
  initialTrackId,
}: {
  onCreated: () => Promise<void>
  initialTrackId: string
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState("")
  const [notes, setNotes] = useState("")
  const [trackId, setTrackId] = useState(initialTrackId)
  useEffect(() => {
    if (open && initialTrackId) setTrackId(initialTrackId)
  }, [initialTrackId, open])
  const mutation = useMutation({
    mutationFn: () =>
      DouyinKeywordsService.bulkCreateKeywords({
        requestBody: {
          keywords: parseKeywords(value),
          notes,
          track_id: trackId,
        },
      }),
    onSuccess: async (result) => {
      showSuccessToast(
        `新增 ${result.created_count} 个，已存在 ${result.existing_count} 个`,
      )
      setValue("")
      setNotes("")
      setOpen(false)
      await onCreated()
    },
    onError: handleError.bind(showErrorToast),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!trackId) return showErrorToast("请选择关键词所属赛道")
    if (!parseKeywords(value).length)
      return showErrorToast("请填写至少一个关键词")
    mutation.mutate()
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus />
          添加关键词
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit} className="space-y-5">
          <DialogHeader>
            <DialogTitle>批量添加关键词</DialogTitle>
            <DialogDescription>
              每行或逗号分隔一个关键词；系统会自动清理空格并忽略大小写重复。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label>所属赛道</Label>
            <TrackSelect
              value={trackId}
              onValueChange={setTrackId}
              enabled={open}
            />
            <p className="text-xs text-muted-foreground">
              新关键词会直接归入所选赛道，后续任务和内容筛选会沿用该归属。
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="keyword-values">关键词</Label>
            <Textarea
              id="keyword-values"
              value={value}
              rows={8}
              placeholder={"FastAPI\nPython 爬虫\n短视频运营"}
              onChange={(event) => setValue(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="keyword-notes">统一备注（可选）</Label>
            <Input
              id="keyword-notes"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
            >
              取消
            </Button>
            <Button type="submit" disabled={mutation.isPending || !trackId}>
              保存关键词
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function BatchTaskDialog({
  keywordIds,
  trackId,
  trackName,
  onCreated,
}: {
  keywordIds: string[]
  trackId: string
  trackName: string
  onCreated: () => void
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<"combined" | "separate">("combined")
  const [maxAwemes, setMaxAwemes] = useState(10)
  const [fetchComments, setFetchComments] = useState(true)
  const [maxComments, setMaxComments] = useState(10)
  const [delayLevel, setDelayLevel] = useState<
    "fast" | "steady" | "ultra_steady"
  >("steady")
  const [downloadMedia, setDownloadMedia] = useState(false)
  const [translate, setTranslate] = useState(false)
  const [storage, setStorage] = useState<"local" | "minio">("minio")
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
  const mutation = useMutation({
    mutationFn: () => {
      const requestBody: Parameters<
        typeof DouyinKeywordsService.createKeywordTasks
      >[0]["requestBody"] = {
        keyword_ids: keywordIds,
        track_id: trackId,
        mode,
        max_awemes: maxAwemes,
        fetch_comments: fetchComments,
        max_comments_per_aweme: maxComments,
        request_delay_level: delayLevel,
        download_media: downloadMedia || translate,
        translate_subtitles: translate,
        media_processing_mode: downloadMedia || translate ? "batch" : "none",
        media_storage: storage,
      }
      if (accountChoice.startsWith("account:"))
        requestBody.account_id = accountChoice.slice(8)
      if (accountChoice.startsWith("pool:")) {
        requestBody.account_pool_id = accountChoice.slice(5)
        requestBody.account_strategy = accountStrategy
      }
      return DouyinKeywordsService.createKeywordTasks({ requestBody })
    },
    onSuccess: (result) => {
      showSuccessToast(`已创建 ${result.count} 个关键词任务`)
      setOpen(false)
      onCreated()
    },
    onError: handleError.bind(showErrorToast),
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="secondary" disabled={!keywordIds.length}>
          <Play />
          批量创建任务
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>从 {keywordIds.length} 个关键词创建任务</DialogTitle>
          <DialogDescription>
            合并模式请求更少；独立模式便于逐词看结果，但会增加账号负载。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2 rounded-xl border bg-muted/30 p-3">
          <p className="text-xs font-medium text-muted-foreground">所属赛道</p>
          <p className="text-sm font-medium">{trackName}</p>
          <p className="text-xs text-muted-foreground">
            已选关键词会在该赛道内创建任务，不允许跨赛道混合运行。
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="任务组织">
            <Select
              value={mode}
              onValueChange={(value) => setMode(value as typeof mode)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="combined">合并任务（推荐）</SelectItem>
                <SelectItem value="separate">每词独立任务</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label="执行账号">
            <Select value={accountChoice} onValueChange={setAccountChoice}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="adhoc">临时浏览器登录</SelectItem>
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
          </Field>
          {accountChoice.startsWith("pool:") && (
            <Field label="账号池调度策略">
              <Select
                value={accountStrategy}
                onValueChange={(value) =>
                  setAccountStrategy(value as typeof accountStrategy)
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="least_loaded">最少负载</SelectItem>
                  <SelectItem value="round_robin">顺序轮询</SelectItem>
                  <SelectItem value="weighted_round_robin">加权轮询</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          )}
          <Field label="每任务最大作品">
            <Input
              type="number"
              min={1}
              max={1000}
              value={maxAwemes}
              onChange={(event) => setMaxAwemes(Number(event.target.value))}
            />
          </Field>
          <Field label="每作品最大评论">
            <Input
              type="number"
              min={1}
              max={1000}
              disabled={!fetchComments}
              value={maxComments}
              onChange={(event) => setMaxComments(Number(event.target.value))}
            />
          </Field>
          <Field label="风控节奏">
            <Select
              value={delayLevel}
              onValueChange={(value) =>
                setDelayLevel(value as typeof delayLevel)
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="fast">快 · 1–2 秒随机</SelectItem>
                <SelectItem value="steady">稳 · 3–6 秒随机</SelectItem>
                <SelectItem value="ultra_steady">
                  超级稳 · 6–12 秒随机
                </SelectItem>
              </SelectContent>
            </Select>
          </Field>
        </div>
        <div className="space-y-3 rounded-xl border p-4">
          <Check
            checked={fetchComments}
            label="抓取评论"
            onChange={setFetchComments}
          />
          <Check
            checked={downloadMedia || translate}
            disabled={translate}
            label="下载视频"
            onChange={setDownloadMedia}
          />
          <Check
            checked={translate}
            label="远程生成并翻译字幕"
            onChange={(checked) => {
              setTranslate(checked)
              if (checked) setDownloadMedia(true)
            }}
          />
          {(downloadMedia || translate) && (
            <Field label="存储位置">
              <Select
                value={storage}
                onValueChange={(value) => setStorage(value as typeof storage)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="minio">云端存储</SelectItem>
                  <SelectItem value="local">本地服务器</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button
            disabled={mutation.isPending || !keywordIds.length || !trackId}
            onClick={() => mutation.mutate()}
          >
            确认创建并运行
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function KeywordTasksDialog({ item }: { item: DouyinKeywordPublic }) {
  const [open, setOpen] = useState(false)
  const query = useQuery({
    queryKey: ["douyin-keyword-tasks", item.id],
    queryFn: () =>
      DouyinKeywordsService.listKeywordTasks({ keywordId: item.id }),
    enabled: open,
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          任务 {item.task_count}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{item.keyword} · 关联任务</DialogTitle>
          <DialogDescription>
            任务绑定会永久保留，删除关键词也不会删除任务或作品。
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[55vh] space-y-2 overflow-y-auto">
          {query.data?.map((task) => (
            <div
              key={task.id}
              className="flex items-center gap-3 rounded-xl border p-3"
            >
              <TaskStatusBadge status={task.status} />
              <span className="text-sm text-muted-foreground">
                {formatDate(task.created_at)}
              </span>
              <span className="ml-auto text-sm">{task.aweme_count} 作品</span>
              <Button size="sm" variant="ghost" asChild>
                <Link to="/douyin/$taskId" params={{ taskId: task.id }}>
                  查看
                </Link>
              </Button>
            </div>
          ))}
          {!query.isLoading && !query.data?.length && (
            <p className="py-10 text-center text-muted-foreground">
              暂无关联任务
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function MoveKeywordDialog({
  item,
  onMoved,
}: {
  item: DouyinKeywordPublic
  onMoved: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [trackId, setTrackId] = useState(item.track_id)
  const { showErrorToast, showSuccessToast } = useCustomToast()
  useEffect(() => {
    if (open) setTrackId(item.track_id)
  }, [item.track_id, open])
  const mutation = useMutation({
    mutationFn: () =>
      DouyinKeywordsService.editKeyword({
        keywordId: item.id,
        requestBody: { track_id: trackId },
      }),
    onSuccess: async () => {
      setOpen(false)
      showSuccessToast("关键词赛道归属已更新")
      await onMoved()
    },
    onError: handleError.bind(showErrorToast),
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          移动
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>移动关键词“{item.keyword}”</DialogTitle>
          <DialogDescription>
            只调整关键词的主赛道归属；历史任务和已采集内容仍保留原始赛道。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label>目标赛道</Label>
          <TrackSelect
            value={trackId}
            onValueChange={setTrackId}
            enabled={open}
            autoSelectDefault={false}
            ariaLabel={`选择“${item.keyword}”的目标赛道`}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button
            disabled={
              !trackId || trackId === item.track_id || mutation.isPending
            }
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "正在移动…" : "确认移动"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function DeleteKeywordDialog({
  item,
  pending,
  onConfirm,
}: {
  item: DouyinKeywordPublic
  pending: boolean
  onConfirm: () => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="icon-sm" variant="ghost" aria-label="删除关键词">
          <Trash2 />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>删除关键词“{item.keyword}”？</DialogTitle>
          <DialogDescription>
            只会删除关键词库记录和绑定关系，历史任务、作品与评论不会被删除。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button
            variant="destructive"
            disabled={pending}
            onClick={() => {
              onConfirm()
              setOpen(false)
            }}
          >
            确认删除
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function KeywordStatusBadge({ status }: { status: DouyinKeywordStatus }) {
  return (
    <Badge
      variant={
        status === "failed"
          ? "destructive"
          : status === "crawled"
            ? "default"
            : "outline"
      }
    >
      {status === "active" && <LoaderCircle className="animate-spin" />}
      {statusLabels[status]}
    </Badge>
  )
}
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      {children}
    </div>
  )
}
function Check({
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
function Pager({
  page,
  count,
  onChange,
}: {
  page: number
  count: number
  onChange: (page: number) => void
}) {
  const pages = Math.max(1, Math.ceil(count / pageSize))
  if (pages <= 1) return null
  return (
    <div className="flex items-center justify-end gap-3">
      <span className="text-sm text-muted-foreground">
        第 {page + 1}/{pages} 页 · 共 {count} 条
      </span>
      <Button
        size="sm"
        variant="outline"
        disabled={page === 0}
        onClick={() => onChange(page - 1)}
      >
        上一页
      </Button>
      <Button
        size="sm"
        variant="outline"
        disabled={page + 1 >= pages}
        onClick={() => onChange(page + 1)}
      >
        下一页
      </Button>
    </div>
  )
}
function parseKeywords(value: string) {
  return value
    .split(/[\n,，]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}
function formatDate(value: string | null) {
  return value
    ? new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "short",
        timeStyle: "short",
      }).format(new Date(value))
    : "从未"
}
