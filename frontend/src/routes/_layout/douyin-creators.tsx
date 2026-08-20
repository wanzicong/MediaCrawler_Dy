import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  CheckCircle2,
  Clock3,
  CloudDownload,
  Database,
  Film,
  History,
  ListFilter,
  LoaderCircle,
  Pencil,
  Play,
  Plus,
  Search,
  Trash2,
  Users,
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
  type ApiError,
  DouyinAccountsService,
  type DouyinCreatorPublic,
  type DouyinCreatorStatus,
  DouyinCreatorsService,
} from "@/client"
import { MetricCard, PageHero } from "@/components/Common/PageShell"
import { CreatorAvatar } from "@/components/Douyin/CreatorAvatar"
import {
  allTracksValue,
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
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/douyin-creators")({
  component: DouyinCreatorDirectory,
  head: () => ({ meta: [{ title: "达人列表 - 灵感采集台" }] }),
})

const pageLimit = 200
const statusLabels: Record<DouyinCreatorStatus, string> = {
  unprocessed: "未爬取",
  active: "进行中",
  crawled: "已爬取",
  failed: "需要重试",
}

function DouyinCreatorDirectory() {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [trackId, setTrackId] = useState(allTracksValue)
  const [search, setSearch] = useState("")
  const [status, setStatus] = useState<DouyinCreatorStatus | "all">("all")
  const [enabled, setEnabled] = useState<"all" | "true" | "false">("all")
  const [sort, setSort] = useState("last_crawled_at:desc")
  const [selected, setSelected] = useState<string[]>([])
  const tracksQuery = useTrackCatalog()
  const selectedTrack = tracksQuery.data?.data.find(
    (track) => track.id === trackId,
  )
  const [sortBy, sortOrder] = sort.split(":") as [
    (
      | "nickname"
      | "status"
      | "task_count"
      | "aweme_count"
      | "last_crawled_at"
      | "created_at"
    ),
    "asc" | "desc",
  ]

  const creatorsQuery = useQuery({
    queryKey: ["douyin-creators", trackId, search, status, enabled, sort],
    queryFn: () =>
      DouyinCreatorsService.listCreators({
        trackId: trackId && trackId !== allTracksValue ? trackId : undefined,
        search: search.trim() || undefined,
        status: status === "all" ? undefined : status,
        enabled: enabled === "all" ? undefined : enabled === "true",
        sortBy,
        sortOrder,
        limit: pageLimit,
      }),
    placeholderData: (previous) => previous,
    refetchInterval: 10_000,
  })
  const overviewQuery = useQuery({
    queryKey: ["douyin-creators-overview", trackId, enabled],
    queryFn: () =>
      DouyinCreatorsService.listCreators({
        trackId: trackId && trackId !== allTracksValue ? trackId : undefined,
        enabled: enabled === "all" ? undefined : enabled === "true",
        limit: 500,
      }),
    placeholderData: (previous) => previous,
    refetchInterval: 15_000,
  })
  const creators = creatorsQuery.data?.data ?? []
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
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["douyin-creators"] }),
      queryClient.invalidateQueries({
        queryKey: ["douyin-creators-overview"],
      }),
    ])
  }
  const historySync = useMutation({
    mutationFn: () => DouyinCreatorsService.syncHistoricalCreators(),
    onSuccess: async (result) => {
      showSuccessToast(
        `已扫描 ${result.task_count} 个任务，新增 ${result.created_count} 位达人、${result.binding_count} 个绑定`,
      )
      await invalidate()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const awemeSync = useMutation({
    mutationFn: () => DouyinCreatorsService.syncCreatorsFromAwemes(),
    onSuccess: async (result) => {
      showSuccessToast(
        `已聚合 ${result.total_count} 位达人，导入 ${result.created_count} 位（已存在 ${result.existing_count} 位）`,
      )
      await invalidate()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const toggle = useMutation({
    mutationFn: (item: DouyinCreatorPublic) =>
      DouyinCreatorsService.editCreator({
        creatorId: item.id,
        requestBody: { enabled: !item.enabled },
      }),
    onSuccess: invalidate,
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const remove = useMutation({
    mutationFn: (id: string) =>
      DouyinCreatorsService.deleteCreator({ creatorId: id }),
    onSuccess: async () => {
      showSuccessToast("达人已删除，历史任务和作品未受影响")
      await invalidate()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const bulkRemove = useMutation({
    mutationFn: (ids: string[]) =>
      DouyinCreatorsService.bulkDeleteCreators({ requestBody: { ids } }),
    onSuccess: async () => {
      showSuccessToast(`已删除 ${selected.length} 位达人，历史数据已保留`)
      setSelected([])
      await invalidate()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })

  return (
    <div className="page-stack">
      <PageHero
        eyebrow="内容资产中心"
        icon={Users}
        title="达人列表"
        description="以赛道为一级归属沉淀人工维护的达人名单，跟踪每位达人的采集状态，并在同一赛道内批量发起任务。"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              disabled={awemeSync.isPending}
              onClick={() => {
                if (
                  window.confirm(
                    "将根据历史采集作品聚合达人名单：带真实标识的新作品直接导入正式达人，仅含脱敏数据的历史作品导入为“待补全”占位达人。确定继续吗？",
                  )
                )
                  awemeSync.mutate()
              }}
            >
              <CloudDownload
                className={awemeSync.isPending ? "animate-spin" : ""}
              />
              从历史作品同步
            </Button>
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
            <CreateCreatorsDialog
              initialTrackId={trackId}
              onCreated={invalidate}
            />
            <BatchCreatorTaskDialog
              creatorIds={selected}
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
                    `确定删除选中的 ${selected.length} 位达人吗？历史任务和作品不会被删除。`,
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
            label="达人总数"
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
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索昵称、sec_user_id 或备注"
                className="pl-9"
              />
            </div>
            <TrackSelect
              value={trackId}
              onValueChange={(value) => {
                setTrackId(value)
                setSelected([])
              }}
              ariaLabel="按赛道筛选达人"
              includeAll
              allowDisabled
            />
            <Select
              value={status}
              onValueChange={(value) => setStatus(value as typeof status)}
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
              onValueChange={(value) => setEnabled(value as typeof enabled)}
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
            <Select value={sort} onValueChange={(value) => setSort(value)}>
              <SelectTrigger aria-label="达人排序方式">
                <ListFilter />
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="last_crawled_at:desc">最近爬取</SelectItem>
                <SelectItem value="created_at:desc">最近创建</SelectItem>
                <SelectItem value="nickname:asc">昵称 A-Z</SelectItem>
                <SelectItem value="task_count:desc">关联任务最多</SelectItem>
                <SelectItem value="aweme_count:desc">作品最多</SelectItem>
                <SelectItem value="status:asc">优先处理状态</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-muted/20 p-3 text-sm">
            <span className="text-muted-foreground">
              已选择 {selected.length} 位达人
            </span>
            <span className="text-xs text-muted-foreground">
              达人任务固定按每位独立创建，一次最多 20 个。
            </span>
          </div>

          {creatorsQuery.isError ? (
            <div className="rounded-xl border border-dashed py-16 text-center text-sm text-muted-foreground">
              达人列表读取失败，请检查服务连接后重试。
            </div>
          ) : creators.length ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
              {creators.map((creator) => (
                <CreatorCard
                  key={creator.id}
                  creator={creator}
                  selected={selected.includes(creator.id)}
                  onToggleSelect={(checked) =>
                    setSelected((current) =>
                      checked
                        ? [...new Set([...current, creator.id])]
                        : current.filter((id) => id !== creator.id),
                    )
                  }
                  onToggle={toggle.mutate}
                  onRemove={remove.mutate}
                  onSaved={invalidate}
                />
              ))}
            </div>
          ) : (
            <div className="rounded-3xl border border-dashed py-24 text-center text-muted-foreground">
              <Users className="mx-auto mb-4 size-10 opacity-40" />
              {creatorsQuery.isLoading
                ? "正在加载达人…"
                : search.trim() || status !== "all" || enabled !== "all"
                  ? "没有符合筛选条件的达人"
                  : "当前赛道还没有达人：点击“添加达人”粘贴主页链接或 sec_user_id"}
            </div>
          )}
          {creatorsQuery.data &&
            (creatorsQuery.data.count ?? 0) > pageLimit && (
              <p className="text-center text-xs text-muted-foreground">
                仅显示前 {pageLimit} 位达人，共 {creatorsQuery.data.count} 位
              </p>
            )}
        </CardContent>
      </Card>
    </div>
  )
}

function CreatorCard({
  creator,
  selected,
  onToggleSelect,
  onToggle,
  onRemove,
  onSaved,
}: {
  creator: DouyinCreatorPublic
  selected: boolean
  onToggleSelect: (checked: boolean) => void
  onToggle: (item: DouyinCreatorPublic) => void
  onRemove: (id: string) => void
  onSaved: () => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  return (
    <Card className="transition hover:shadow-md">
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          <Checkbox
            checked={selected}
            disabled={creator.is_placeholder}
            aria-label={`选择达人 ${creator.nickname || creator.sec_uid}`}
            className="mt-2"
            onCheckedChange={(checked) => onToggleSelect(checked === true)}
          />
          <CreatorAvatar
            name={creator.nickname}
            seed={creator.creator_hash}
            className="size-12"
            initialClassName="text-base"
          />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p
                className="truncate font-medium"
                title={creator.nickname || "未命名达人"}
              >
                {creator.nickname || "未命名达人"}
              </p>
              {!creator.enabled && <Badge variant="secondary">已停用</Badge>}
              {creator.is_placeholder && (
                <Badge
                  variant="outline"
                  className="border-amber-400/60 bg-amber-50 text-amber-700"
                >
                  待补全
                </Badge>
              )}
              <CreatorStatusBadge status={creator.status} />
            </div>
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              {creator.is_placeholder
                ? "脱敏身份 · 补全主页链接后可创建任务"
                : creator.sec_uid.slice(-12)}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {creator.task_count} 个任务 · {creator.aweme_count} 个作品
            </p>
            {creator.notes && (
              <p className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">
                {creator.notes}
              </p>
            )}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap justify-end gap-1">
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2"
            aria-label={`编辑达人 ${creator.nickname || creator.sec_uid}`}
            onClick={() => setEditing(true)}
          >
            <Pencil /> {creator.is_placeholder ? "补全" : "编辑"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2"
            onClick={() => onToggle(creator)}
          >
            {creator.enabled ? "停用" : "启用"}
          </Button>
          <Button size="sm" variant="outline" asChild>
            <Link
              to="/douyin-library"
              search={{
                track: undefined,
                q: undefined,
                task: undefined,
                creator: creator.creator_hash,
                tag: undefined,
                storage: undefined,
                subtitle: undefined,
                sort: undefined,
              }}
              aria-label={`查看 ${creator.nickname || "该达人"} 的作品`}
            >
              <Film />
              作品
            </Link>
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-destructive"
            aria-label={`删除达人 ${creator.nickname || creator.sec_uid}`}
            onClick={() => {
              if (
                window.confirm(
                  `确定删除达人“${creator.nickname || creator.sec_uid}”吗？历史任务和作品不会被删除。`,
                )
              )
                onRemove(creator.id)
            }}
          >
            <Trash2 />
          </Button>
        </div>
      </CardContent>
      {editing && (
        <EditCreatorDialog
          item={creator}
          open
          onOpenChange={(open) => !open && setEditing(false)}
          onSaved={async () => {
            setEditing(false)
            await onSaved()
          }}
        />
      )}
    </Card>
  )
}

function CreatorStatusBadge({ status }: { status: DouyinCreatorStatus }) {
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

function CreateCreatorsDialog({
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
    if (open && initialTrackId && initialTrackId !== allTracksValue)
      setTrackId(initialTrackId)
  }, [initialTrackId, open])
  const mutation = useMutation({
    mutationFn: () =>
      DouyinCreatorsService.bulkCreateCreators({
        requestBody: {
          creators: parseCreatorTargets(value),
          notes,
          track_id: trackId,
        },
      }),
    onSuccess: async (result) => {
      showSuccessToast(
        `新增 ${result.created_count} 位，已存在 ${result.existing_count} 位`,
      )
      setValue("")
      setNotes("")
      setOpen(false)
      await onCreated()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!trackId || trackId === allTracksValue)
      return showErrorToast("请选择达人所属赛道")
    if (!parseCreatorTargets(value).length)
      return showErrorToast("请填写至少一位达人")
    mutation.mutate()
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus />
          添加达人
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit} className="space-y-5">
          <DialogHeader>
            <DialogTitle>批量添加达人</DialogTitle>
            <DialogDescription>
              每行或逗号分隔一位达人，支持粘贴主页链接或 sec_user_id；
              已存在的达人会保持原归属不动。
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
              新达人会直接归入所选赛道，后续任务和内容筛选会沿用该归属。
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="creator-values">达人主页链接或 sec_user_id</Label>
            <Textarea
              id="creator-values"
              value={value}
              rows={8}
              placeholder={
                "https://www.douyin.com/user/MS4wLjABAAAA…\nMS4wLjABAAAAa2jK7…"
              }
              onChange={(event) => setValue(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="creator-notes">统一备注（可选）</Label>
            <Input
              id="creator-notes"
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
              保存达人
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function BatchCreatorTaskDialog({
  creatorIds,
  trackId,
  trackName,
  onCreated,
}: {
  creatorIds: string[]
  trackId: string
  trackName: string
  onCreated: () => void
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [open, setOpen] = useState(false)
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
        typeof DouyinCreatorsService.createCreatorTasks
      >[0]["requestBody"] = {
        creator_ids: creatorIds,
        track_id: trackId,
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
      return DouyinCreatorsService.createCreatorTasks({ requestBody })
    },
    onSuccess: (result) => {
      showSuccessToast(`已创建 ${result.count} 个达人任务`)
      setOpen(false)
      onCreated()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="secondary" disabled={!creatorIds.length}>
          <Play />
          批量创建任务
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>从 {creatorIds.length} 位达人创建任务</DialogTitle>
          <DialogDescription>
            每位达人独立一个任务，便于逐人看结果；一次最多创建 20 个。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2 rounded-xl border bg-muted/30 p-3">
          <p className="text-xs font-medium text-muted-foreground">所属赛道</p>
          {trackId === allTracksValue ? (
            <p className="text-sm font-medium text-destructive">
              请先在上方按赛道筛选达人，再创建批量任务
            </p>
          ) : (
            <>
              <p className="text-sm font-medium">{trackName}</p>
              <p className="text-xs text-muted-foreground">
                已选达人会在该赛道内创建任务，不允许跨赛道混合运行。
              </p>
            </>
          )}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
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
            disabled={
              mutation.isPending ||
              !creatorIds.length ||
              creatorIds.length > 20 ||
              !trackId ||
              trackId === allTracksValue
            }
            onClick={() => mutation.mutate()}
          >
            确认创建并运行
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function EditCreatorDialog({
  item,
  open,
  onOpenChange,
  onSaved,
}: {
  item: DouyinCreatorPublic
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => Promise<void>
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [nickname, setNickname] = useState(item.nickname)
  const [notes, setNotes] = useState(item.notes)
  const [enabled, setEnabled] = useState(item.enabled)
  const [trackId, setTrackId] = useState(item.track_id)
  const [completionUid, setCompletionUid] = useState("")
  useEffect(() => {
    if (open) {
      setNickname(item.nickname)
      setNotes(item.notes)
      setEnabled(item.enabled)
      setTrackId(item.track_id)
      setCompletionUid("")
    }
  }, [item, open])
  const mutation = useMutation({
    mutationFn: () =>
      DouyinCreatorsService.editCreator({
        creatorId: item.id,
        requestBody: {
          nickname,
          notes,
          enabled,
          track_id: trackId && trackId !== item.track_id ? trackId : null,
          ...(item.is_placeholder && completionUid.trim()
            ? { sec_uid: completionUid.trim() }
            : {}),
        },
      }),
    onSuccess: async () => {
      showSuccessToast(
        item.is_placeholder && completionUid.trim()
          ? "补全成功，该达人已可创建任务"
          : "达人信息已更新",
      )
      onOpenChange(false)
      await onSaved()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (item.is_placeholder && !completionUid.trim())
      return showErrorToast("请填写该达人的主页链接或 sec_user_id 完成补全")
    mutation.mutate()
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>
              {item.is_placeholder ? "补全达人" : "编辑达人"}
            </DialogTitle>
            <DialogDescription>
              {item.is_placeholder
                ? "该达人来自历史采集作品，粘贴主页链接完成补全后即可创建任务；昵称与备注可一并调整。"
                : "调整昵称、备注、启用状态与赛道归属；历史任务仍保留原赛道。"}
            </DialogDescription>
          </DialogHeader>
          {item.is_placeholder && (
            <div className="space-y-2">
              <Label htmlFor="edit-creator-completion">
                补全主页链接或 sec_user_id
              </Label>
              <Input
                id="edit-creator-completion"
                value={completionUid}
                placeholder="https://www.douyin.com/user/MS4wLjABAAAA…"
                onChange={(event) => setCompletionUid(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                系统会校验链接与历史采集数据的脱敏身份一致，避免补全到错误的人。
              </p>
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="edit-creator-nickname">昵称</Label>
            <Input
              id="edit-creator-nickname"
              value={nickname}
              onChange={(event) => setNickname(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="edit-creator-notes">备注</Label>
            <Textarea
              id="edit-creator-notes"
              rows={3}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label>所属赛道</Label>
            <TrackSelect
              value={trackId}
              onValueChange={setTrackId}
              enabled={open}
              autoSelectDefault={false}
              ariaLabel={`选择“${item.nickname || item.sec_uid}”的所属赛道`}
            />
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Checkbox
              id="edit-creator-enabled"
              checked={enabled}
              onCheckedChange={(checked) => setEnabled(checked === true)}
            />
            <Label htmlFor="edit-creator-enabled">启用该达人</Label>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              取消
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending
                ? "保存中…"
                : item.is_placeholder
                  ? "补全并保存"
                  : "保存修改"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
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

function parseCreatorTargets(value: string) {
  return value
    .split(/[\n,，]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}
