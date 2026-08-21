import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  Outlet,
  useRouterState,
} from "@tanstack/react-router"
import {
  Captions,
  Database,
  Download,
  ExternalLink,
  Film,
  FolderSearch2,
  HardDrive,
  Heart,
  Languages,
  LayoutGrid,
  List,
  ListFilter,
  MessageCircle,
  PlaySquare,
  RefreshCw,
  RotateCcw,
  Search,
  Share2,
  Star,
  Table2,
  UploadCloud,
  UserRound,
} from "lucide-react"
import { useMemo, useState } from "react"

import {
  type CrawlTaskPublic,
  type DouyinMediaAssetPublic,
  DouyinService,
  DouyinTagsService,
  type DouyinWorkPublic,
} from "@/client"
import { PageHero } from "@/components/Common/PageShell"
import { AwemeActions } from "@/components/Douyin/AwemeActions"
import { SubtitleDialog } from "@/components/Douyin/SubtitlePanel"
import {
  allTracksValue,
  TrackBadge,
  TrackSelect,
} from "@/components/Douyin/TrackSelect"
import { downloadMedia } from "@/components/Douyin/UnifiedWorksPanel"
import { VideoPreviewDialog } from "@/components/Douyin/VideoPreviewDialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
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
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import useCustomToast from "@/hooks/useCustomToast"
import { getDouyinVideoUrl, handleError } from "@/utils"

const pageSize = 32
const activeStatuses = new Set([
  "queued",
  "running",
  "waiting_login",
  "processing_media",
])

type SortValue =
  | "downloaded_at:desc"
  | "published_at:desc"
  | "published_at:asc"
  | "liked_count:desc"
  | "comment_count:desc"
  | "collected_count:desc"
  | "persisted_comment_count:desc"
  | "file_size:desc"

const sortValues = new Set<SortValue>([
  "downloaded_at:desc",
  "published_at:desc",
  "published_at:asc",
  "liked_count:desc",
  "comment_count:desc",
  "collected_count:desc",
  "persisted_comment_count:desc",
  "file_size:desc",
])

export type LibraryFeedSearch = {
  start?: string
  track: string | undefined
  q: string | undefined
  task: string | undefined
  creator: string | undefined
  tag: string | undefined
  storage: "all" | "local" | "minio" | undefined
  subtitle: "all" | "pending" | "running" | "completed" | "failed" | undefined
  sort: SortValue | undefined
}

export const Route = createFileRoute("/_layout/douyin-library")({
  validateSearch: (search: Record<string, unknown>) => ({
    track: typeof search.track === "string" ? search.track : undefined,
    q: typeof search.q === "string" ? search.q : undefined,
    task: typeof search.task === "string" ? search.task : undefined,
    creator: typeof search.creator === "string" ? search.creator : undefined,
    tag: typeof search.tag === "string" ? search.tag : undefined,
    storage: ["all", "local", "minio"].includes(String(search.storage))
      ? (search.storage as LibraryFeedSearch["storage"])
      : undefined,
    subtitle: ["all", "pending", "running", "completed", "failed"].includes(
      String(search.subtitle),
    )
      ? (search.subtitle as LibraryFeedSearch["subtitle"])
      : undefined,
    sort:
      typeof search.sort === "string" &&
      sortValues.has(search.sort as SortValue)
        ? (search.sort as SortValue)
        : undefined,
  }),
  component: DouyinVideoLibrary,
  head: () => ({ meta: [{ title: "视频资源库 - 灵感采集台" }] }),
})

function DouyinVideoLibrary() {
  const routeSearch = Route.useSearch()
  const feedRouteActive = useRouterState({
    select: (state) => state.location.pathname.endsWith("/feed"),
  })
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [page, setPage] = useState(0)
  const [search, setSearch] = useState(routeSearch.q ?? "")
  const [trackId, setTrackId] = useState(routeSearch.track ?? allTracksValue)
  const [taskId, setTaskId] = useState(routeSearch.task ?? "all")
  const [creatorHash, setCreatorHash] = useState(routeSearch.creator ?? "all")
  const [tagId, setTagId] = useState(routeSearch.tag ?? "all")
  const [storageBackend, setStorageBackend] = useState<
    "all" | "local" | "minio"
  >(routeSearch.storage ?? "all")
  const [downloadStatus, setDownloadStatus] = useState<
    "all" | "missing" | "queued" | "downloading" | "downloaded" | "failed"
  >("all")
  const [viewMode, setViewMode] = useState<"cards" | "rows" | "table">(() => {
    const saved = localStorage.getItem("douyin-library-view")
    return saved === "rows" || saved === "cards" ? saved : "table"
  })
  const changeViewMode = (mode: "cards" | "rows" | "table") => {
    setViewMode(mode)
    localStorage.setItem("douyin-library-view", mode)
  }
  const [subtitleStatus, setSubtitleStatus] = useState<
    "all" | "pending" | "running" | "completed" | "failed"
  >(routeSearch.subtitle ?? "all")
  const [sort, setSort] = useState<SortValue>(
    routeSearch.sort ?? "downloaded_at:desc",
  )
  const [sortBy, sortOrder] = sort.split(":") as [
    (
      | "downloaded_at"
      | "published_at"
      | "liked_count"
      | "comment_count"
      | "collected_count"
      | "persisted_comment_count"
      | "file_size"
    ),
    "asc" | "desc",
  ]

  const tasksQuery = useQuery({
    queryKey: ["douyin-library-tasks", trackId],
    queryFn: () =>
      DouyinService.listTasks({
        trackId: trackId && trackId !== allTracksValue ? trackId : undefined,
        limit: 100,
      }),
    staleTime: 30_000,
  })
  const creatorsQuery = useQuery({
    queryKey: ["douyin-library-creators", trackId, taskId],
    queryFn: () =>
      DouyinService.listLibraryCreators({
        trackId: trackId && trackId !== allTracksValue ? trackId : undefined,
        taskId: taskId === "all" ? undefined : taskId,
      }),
    staleTime: 30_000,
  })
  const tagsQuery = useQuery({
    queryKey: ["douyin-library-tags", trackId, taskId],
    queryFn: () =>
      DouyinTagsService.listTags({
        trackId: trackId && trackId !== allTracksValue ? trackId : undefined,
        taskId: taskId === "all" ? undefined : taskId,
        sortBy: "aweme_count",
        sortOrder: "desc",
        limit: 500,
      }),
    staleTime: 30_000,
  })
  const worksQuery = useQuery({
    queryKey: [
      "douyin-library-works",
      page,
      trackId,
      search,
      taskId,
      creatorHash,
      tagId,
      storageBackend,
      subtitleStatus,
      downloadStatus,
      sort,
    ],
    queryFn: () =>
      DouyinService.listLibraryWorks({
        trackId: trackId && trackId !== allTracksValue ? trackId : undefined,
        search: search.trim() || undefined,
        taskId: taskId === "all" ? undefined : taskId,
        creatorHash: creatorHash === "all" ? undefined : creatorHash,
        tagId: tagId === "all" ? undefined : tagId,
        downloadStatus,
        storageBackend,
        subtitleStatus,
        sortBy,
        sortOrder,
        skip: page * pageSize,
        limit: pageSize,
      }),
    placeholderData: (previous) => previous,
    refetchInterval: 5_000,
  })
  const taskMap = useMemo(
    () => new Map((tasksQuery.data?.data ?? []).map((task) => [task.id, task])),
    [tasksQuery.data?.data],
  )
  const rows = worksQuery.data?.data ?? []
  const [selectedAwemeIds, setSelectedAwemeIds] = useState<string[]>([])
  const selectedAwemeSet = useMemo(
    () => new Set(selectedAwemeIds),
    [selectedAwemeIds],
  )
  const pageAwemeIds = rows.map((row) => row.aweme.aweme_id)
  const selectedRows = rows.filter((row) =>
    selectedAwemeSet.has(row.aweme.aweme_id),
  )
  const allPageSelected =
    pageAwemeIds.length > 0 &&
    pageAwemeIds.every((awemeId) => selectedAwemeSet.has(awemeId))
  const somePageSelected = selectedRows.length > 0 && !allPageSelected
  const pageLocal = rows.filter(
    (row) => row.media?.storage_backend === "local",
  ).length
  const pageMinio = rows.filter(
    (row) => row.media?.storage_backend === "minio",
  ).length
  const pageUndownloaded = rows.filter((row) => !row.media).length

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["douyin-library-works"] })
  }
  const retry = useMutation({
    mutationFn: ({ taskId, assetId }: { taskId: string; assetId: string }) =>
      DouyinService.retryMedia({
        taskId,
        requestBody: {
          asset_ids: [assetId],
          retry_downloads: true,
          retry_subtitles: true,
        },
      }),
    onSuccess: async () => {
      showSuccessToast("资源已重新排队")
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const retranslate = useMutation({
    mutationFn: ({ taskId, assetId }: { taskId: string; assetId: string }) =>
      DouyinService.retranslateMedia({ taskId, assetId }),
    onSuccess: async () => {
      showSuccessToast("字幕已提交到远程翻译服务")
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const recrawlComments = useMutation({
    mutationFn: async (selectedWorks: DouyinWorkPublic[]) => {
      const taskCache = new Map(taskMap)
      let created = 0
      for (const work of selectedWorks) {
        const sourceTaskId = work.aweme.task_id
        let sourceTask = taskCache.get(sourceTaskId)
        if (!sourceTask) {
          sourceTask = await DouyinService.getTask({ taskId: sourceTaskId })
          taskCache.set(sourceTaskId, sourceTask)
        }
        await DouyinService.recrawlAwemeComments({
          taskId: sourceTaskId,
          awemeId: work.aweme.aweme_id,
          requestBody: {
            fetch_sub_comments: Boolean(sourceTask.request.fetch_sub_comments),
            max_comments_per_aweme: Number(
              sourceTask.request.max_comments_per_aweme ?? 10,
            ),
            request_delay_level:
              sourceTask.request.request_delay_level === "ultra_steady"
                ? "ultra_steady"
                : "steady",
            account_id: sourceTask.account_id ?? undefined,
          },
        })
        created += 1
      }
      return created
    },
    onSuccess: async (created) => {
      showSuccessToast(`已为 ${created} 个视频创建评论采集任务`)
      setSelectedAwemeIds([])
      await queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] })
    },
    onError: handleError.bind(showErrorToast),
  })
  const migrationFilters = {
    search: search.trim() || undefined,
    track_id: trackId && trackId !== allTracksValue ? trackId : undefined,
    task_id: taskId === "all" ? undefined : taskId,
    creator_hash: creatorHash === "all" ? undefined : creatorHash,
    tag_id: tagId === "all" ? undefined : tagId,
    subtitle_status: subtitleStatus,
  }
  const migrateLibrary = useMutation({
    mutationFn: () =>
      DouyinService.migrateLibraryMediaToMinio({
        requestBody: migrationFilters,
      }),
    onSuccess: async (result) => {
      showSuccessToast(
        result.queued
          ? `已将 ${result.queued} 个本地视频加入云端上传队列`
          : result.message,
      )
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })
  const [exportingSubtitles, setExportingSubtitles] = useState(false)
  const exportSubtitles = async () => {
    setExportingSubtitles(true)
    try {
      const loadPage = (skip: number) =>
        DouyinService.listLibraryWorks({
          trackId: trackId && trackId !== allTracksValue ? trackId : undefined,
          search: search.trim() || undefined,
          taskId: taskId === "all" ? undefined : taskId,
          creatorHash: creatorHash === "all" ? undefined : creatorHash,
          tagId: tagId === "all" ? undefined : tagId,
          downloadStatus,
          storageBackend,
          subtitleStatus,
          sortBy,
          sortOrder,
          skip,
          limit: 100,
        })
      const firstPage = await loadPage(0)
      const total = firstPage.count ?? firstPage.data?.length ?? 0
      if (
        total > 1000 &&
        !window.confirm(
          `当前筛选条件命中 ${total} 条作品，完整导出可能需要较长时间。确认继续导出吗？`,
        )
      ) {
        return
      }
      const works: DouyinWorkPublic[] = [...(firstPage.data ?? [])]
      while (works.length < total) {
        const nextPage = await loadPage(works.length)
        if (!nextPage.data?.length) break
        works.push(...nextPage.data)
      }
      const withSubtitle = works.filter((work) =>
        work.media?.subtitle?.full_text.trim(),
      )
      if (!withSubtitle.length) {
        showErrorToast("当前筛选结果中没有可导出的字幕")
        return
      }
      const exportedAt = new Date()
      const blocks = withSubtitle.map((work, index) => {
        const aweme = work.aweme
        const subtitle = work.media?.subtitle
        const meta = [
          `作品号：${aweme.aweme_id}`,
          `达人：${aweme.nickname || "匿名创作者"}`,
          `发布时间：${formatUnix(aweme.create_time)}`,
          subtitle?.language ? `字幕语言：${subtitle.language}` : "",
        ]
          .filter(Boolean)
          .join(" · ")
        return `【${index + 1}】${aweme.title || aweme.aweme_id}\n${meta}\n${subtitle?.full_text.trim()}`
      })
      const header = `抖音字幕导出（按当前筛选条件）\n导出时间：${formatDateTimeText(exportedAt)}\n筛选命中 ${total} 条作品，本次导出 ${withSubtitle.length} 条字幕`
      const content = `${header}\n\n${"=".repeat(56)}\n\n${blocks.join("\n\n")}\n`
      const url = URL.createObjectURL(
        new Blob([`\uFEFF${content}`], { type: "text/plain;charset=utf-8" }),
      )
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = `douyin-subtitles-${exportedAt.getFullYear()}${String(exportedAt.getMonth() + 1).padStart(2, "0")}${String(exportedAt.getDate()).padStart(2, "0")}-${String(exportedAt.getHours()).padStart(2, "0")}${String(exportedAt.getMinutes()).padStart(2, "0")}.txt`
      anchor.click()
      URL.revokeObjectURL(url)
      showSuccessToast(`已按筛选条件导出 ${withSubtitle.length} 条字幕`)
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : "字幕导出失败")
    } finally {
      setExportingSubtitles(false)
    }
  }
  const feedSearch: LibraryFeedSearch = {
    track: trackId && trackId !== allTracksValue ? trackId : undefined,
    q: search.trim() || undefined,
    task: taskId === "all" ? undefined : taskId,
    creator: creatorHash === "all" ? undefined : creatorHash,
    tag: tagId === "all" ? undefined : tagId,
    storage: storageBackend,
    subtitle: subtitleStatus,
    sort,
  }

  if (feedRouteActive) return <Outlet />

  const resetPage = () => {
    setPage(0)
    setSelectedAwemeIds([])
  }
  const toggleSelection = (awemeId: string, checked: boolean) => {
    setSelectedAwemeIds((current) =>
      checked
        ? current.includes(awemeId)
          ? current
          : [...current, awemeId]
        : current.filter((id) => id !== awemeId),
    )
  }
  const togglePageSelection = (checked: boolean) => {
    setSelectedAwemeIds(checked ? pageAwemeIds : [])
  }
  return (
    <div className="page-stack">
      <PageHero
        eyebrow="内容资产中心"
        icon={FolderSearch2}
        title="视频资源库"
        description="按赛道或任务查看全部已爬取作品（含未下载），互动数据、采集来源、文件与字幕信息一目了然，并直接播放或继续处理。"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button asChild disabled={!rows.length}>
              <Link to="/douyin-library/feed" search={feedSearch}>
                <PlaySquare />
                沉浸播放
              </Link>
            </Button>
            <Button
              variant="secondary"
              disabled={
                migrateLibrary.isPending ||
                storageBackend === "minio" ||
                !(worksQuery.data?.count ?? 0)
              }
              onClick={() => {
                if (
                  window.confirm(
                    "确认把当前筛选条件下的所有本地视频上传到云端？只有完整上传并校验成功后才会删除本地文件。",
                  )
                ) {
                  migrateLibrary.mutate()
                }
              }}
            >
              <UploadCloud />
              {migrateLibrary.isPending ? "正在加入队列…" : "本地视频转云端"}
            </Button>
            <Button
              variant="secondary"
              onClick={exportSubtitles}
              disabled={exportingSubtitles || !(worksQuery.data?.count ?? 0)}
            >
              <Captions />
              {exportingSubtitles ? "正在导出…" : "导出字幕"}
            </Button>
            <Button
              variant="outline"
              onClick={() => invalidate()}
              disabled={worksQuery.isFetching}
            >
              <RefreshCw
                className={worksQuery.isFetching ? "animate-spin" : ""}
              />
              刷新资源
            </Button>
          </div>
        }
      >
        <div className="flex flex-wrap gap-2">
          <SummaryPill
            icon={Film}
            label="匹配"
            value={worksQuery.data?.count ?? 0}
          />
          <SummaryPill
            icon={UserRound}
            label="创作者"
            value={creatorsQuery.data?.count ?? 0}
          />
          <SummaryPill icon={HardDrive} label="本页本地" value={pageLocal} />
          <SummaryPill icon={Database} label="本页云端" value={pageMinio} />
          <SummaryPill
            icon={Download}
            label="本页未下载"
            value={pageUndownloaded}
          />
        </div>
      </PageHero>

      <Card>
        <CardContent className="space-y-3 p-3 md:p-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-8">
            <div className="relative md:col-span-2 xl:col-span-2">
              <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value)
                  resetPage()
                }}
                placeholder="搜索标题、描述、创作者或作品号"
                className="pl-9"
              />
            </div>
            <TrackSelect
              value={trackId}
              onValueChange={(value) => {
                setTrackId(value)
                setTaskId("all")
                setCreatorHash("all")
                setTagId("all")
                resetPage()
              }}
              includeAll
              allowDisabled
              ariaLabel="按赛道筛选视频资源"
            />
            <Select
              value={taskId}
              onValueChange={(value) => {
                setTaskId(value)
                setCreatorHash("all")
                setTagId("all")
                resetPage()
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder="选择任务" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部任务</SelectItem>
                {(tasksQuery.data?.data ?? []).map((task) => (
                  <SelectItem key={task.id} value={task.id}>
                    {taskLabel(task)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={tagId}
              onValueChange={(value) => {
                setTagId(value)
                resetPage()
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder="选择标签" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部标签</SelectItem>
                {(tagsQuery.data?.data ?? []).map((tag) => (
                  <SelectItem key={tag.id} value={tag.id}>
                    #{tag.name}（{tag.aweme_count}）
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={creatorHash}
              onValueChange={(value) => {
                setCreatorHash(value)
                resetPage()
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder="选择创作者" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部创作者</SelectItem>
                {(creatorsQuery.data?.data ?? []).map((creator) => (
                  <SelectItem
                    key={creator.creator_hash}
                    value={creator.creator_hash}
                  >
                    {creator.nickname}（{creator.work_count}）
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={storageBackend}
              onValueChange={(value) => {
                setStorageBackend(value as "all" | "local" | "minio")
                resetPage()
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部存储</SelectItem>
                <SelectItem value="local">本地服务器</SelectItem>
                <SelectItem value="minio">云端存储</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={subtitleStatus}
              onValueChange={(value) => {
                setSubtitleStatus(value as typeof subtitleStatus)
                resetPage()
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部字幕</SelectItem>
                <SelectItem value="completed">字幕完成</SelectItem>
                <SelectItem value="running">字幕处理中</SelectItem>
                <SelectItem value="pending">字幕等待中</SelectItem>
                <SelectItem value="failed">字幕失败</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-2 border-t pt-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap items-center gap-3">
              <fieldset className="m-0 flex shrink-0 items-center rounded-lg border p-0.5">
                <legend className="sr-only">切换视频展示方式</legend>
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
              <p className="text-xs text-muted-foreground">
                每页展示 {pageSize} 条作品记录，含未下载。
              </p>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <Select
                value={downloadStatus}
                onValueChange={(value) => {
                  setDownloadStatus(value as typeof downloadStatus)
                  resetPage()
                }}
              >
                <SelectTrigger
                  className="w-full sm:w-36"
                  aria-label="按下载状态筛选"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部状态</SelectItem>
                  <SelectItem value="missing">未下载</SelectItem>
                  <SelectItem value="downloaded">已下载</SelectItem>
                  <SelectItem value="queued">排队中</SelectItem>
                  <SelectItem value="downloading">下载中</SelectItem>
                  <SelectItem value="failed">下载失败</SelectItem>
                </SelectContent>
              </Select>
              <Select
                value={sort}
                onValueChange={(value) => {
                  setSort(value as SortValue)
                  resetPage()
                }}
              >
                <SelectTrigger className="w-full sm:w-52">
                  <ListFilter />
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="downloaded_at:desc">最近下载</SelectItem>
                  <SelectItem value="published_at:desc">最新发布</SelectItem>
                  <SelectItem value="published_at:asc">最早发布</SelectItem>
                  <SelectItem value="liked_count:desc">点赞最多</SelectItem>
                  <SelectItem value="comment_count:desc">评论最多</SelectItem>
                  <SelectItem value="collected_count:desc">收藏最多</SelectItem>
                  <SelectItem value="persisted_comment_count:desc">
                    已保存评论最多
                  </SelectItem>
                  <SelectItem value="file_size:desc">文件最大</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="border-dashed">
        <CardContent className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center sm:justify-between md:p-4">
          <div className="flex items-center gap-3">
            <Checkbox
              id="select-library-page"
              aria-label="选择本页视频"
              checked={
                allPageSelected
                  ? true
                  : somePageSelected
                    ? "indeterminate"
                    : false
              }
              disabled={!rows.length}
              onCheckedChange={(checked) =>
                togglePageSelection(checked === true)
              }
            />
            <label
              htmlFor="select-library-page"
              className="cursor-pointer text-sm font-medium"
            >
              {selectedRows.length
                ? `已选择 ${selectedRows.length} 个视频`
                : "选择本页视频"}
            </label>
            <span className="text-xs text-muted-foreground">
              选择后可批量创建独立的评论采集任务
            </span>
          </div>
          <Button
            size="sm"
            disabled={!selectedRows.length || recrawlComments.isPending}
            onClick={() => {
              if (
                selectedRows.length <= 20 ||
                window.confirm(
                  `将为 ${selectedRows.length} 个视频分别创建评论采集任务，确认继续？`,
                )
              ) {
                recrawlComments.mutate(selectedRows)
              }
            }}
          >
            <MessageCircle />
            {recrawlComments.isPending ? "正在创建…" : "批量创建评论任务"}
          </Button>
        </CardContent>
      </Card>

      {rows.length ? (
        viewMode === "cards" ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {rows.map((row) => (
              <VideoCard
                key={row.aweme.id}
                row={row}
                task={taskMap.get(row.aweme.task_id)}
                retry={(asset) =>
                  retry.mutate({ taskId: row.aweme.task_id, assetId: asset.id })
                }
                retranslate={(asset) =>
                  retranslate.mutate({
                    taskId: row.aweme.task_id,
                    assetId: asset.id,
                  })
                }
                onDownload={(asset) =>
                  downloadMedia(row.aweme.task_id, asset, showErrorToast)
                }
                feedSearch={feedSearch}
                selected={selectedAwemeSet.has(row.aweme.aweme_id)}
                onSelectedChange={(checked) =>
                  toggleSelection(row.aweme.aweme_id, checked)
                }
              />
            ))}
          </div>
        ) : viewMode === "rows" ? (
          <div className="space-y-2">
            {rows.map((row) => (
              <VideoRow
                key={row.aweme.id}
                row={row}
                task={taskMap.get(row.aweme.task_id)}
                retry={(asset) =>
                  retry.mutate({ taskId: row.aweme.task_id, assetId: asset.id })
                }
                retranslate={(asset) =>
                  retranslate.mutate({
                    taskId: row.aweme.task_id,
                    assetId: asset.id,
                  })
                }
                onDownload={(asset) =>
                  downloadMedia(row.aweme.task_id, asset, showErrorToast)
                }
                selected={selectedAwemeSet.has(row.aweme.aweme_id)}
                onSelectedChange={(checked) =>
                  toggleSelection(row.aweme.aweme_id, checked)
                }
              />
            ))}
          </div>
        ) : (
          <VideoTable
            rows={rows}
            taskMap={taskMap}
            retry={(row, asset) =>
              retry.mutate({ taskId: row.aweme.task_id, assetId: asset.id })
            }
            onDownload={(row, asset) =>
              downloadMedia(row.aweme.task_id, asset, showErrorToast)
            }
            selectedAwemeSet={selectedAwemeSet}
            allPageSelected={allPageSelected}
            somePageSelected={somePageSelected}
            onTogglePage={togglePageSelection}
            onToggleRow={toggleSelection}
          />
        )
      ) : (
        <div className="rounded-3xl border border-dashed py-24 text-center text-muted-foreground">
          <Film className="mx-auto mb-4 size-10 opacity-40" />
          {worksQuery.isLoading
            ? "正在加载视频资源…"
            : "没有符合当前条件的视频作品"}
        </div>
      )}

      <Pager
        page={page}
        count={worksQuery.data?.count ?? 0}
        onChange={(nextPage) => {
          setPage(nextPage)
          setSelectedAwemeIds([])
        }}
      />
    </div>
  )
}

function mediaStateLabel(row: DouyinWorkPublic) {
  const asset = row.media
  if (!asset) return "未下载"
  if (asset.status === "failed") return "下载失败"
  if (asset.status !== "downloaded") return "下载中"
  return asset.storage_backend === "minio" ? "云端" : "本地"
}

function MediaStateBadge({
  row,
  onCover = false,
}: {
  row: DouyinWorkPublic
  onCover?: boolean
}) {
  const label = mediaStateLabel(row)
  if (onCover) {
    return (
      <Badge className="border-white/20 bg-black/35 text-white hover:bg-black/35">
        {label}
      </Badge>
    )
  }
  const variant =
    label === "未下载"
      ? "secondary"
      : label === "下载失败"
        ? "destructive"
        : "outline"
  return (
    <Badge variant={variant} className="shrink-0">
      {label}
    </Badge>
  )
}

function InlineStat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Heart
  label: string
  value: string
}) {
  return (
    <span className="flex items-center gap-1" title={label}>
      <Icon aria-hidden="true" className="size-3.5 text-muted-foreground" />
      <span className="font-semibold tabular-nums">{value}</span>
      <span className="sr-only">{label}</span>
    </span>
  )
}

function WorkActionButtons({
  row,
  task,
  retry,
  retranslate,
  onDownload,
  feedSearch,
}: {
  row: DouyinWorkPublic
  task?: CrawlTaskPublic
  retry: (asset: DouyinMediaAssetPublic) => void
  retranslate: (asset: DouyinMediaAssetPublic) => void
  onDownload: (asset: DouyinMediaAssetPublic) => void
  feedSearch?: LibraryFeedSearch
}) {
  const aweme = row.aweme
  const asset = row.media
  const active = task ? activeStatuses.has(task.status) : false
  return (
    <>
      {asset?.download_available && (
        <VideoPreviewDialog
          taskId={aweme.task_id}
          asset={asset}
          aweme={aweme}
        />
      )}
      {asset && (
        <SubtitleDialog asset={asset} title={aweme.title || aweme.aweme_id} />
      )}
      {asset?.download_available && (
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label="下载视频"
          onClick={() => onDownload(asset)}
        >
          <Download />
        </Button>
      )}
      {asset?.download_available && (
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label="重新翻译"
          onClick={() => retranslate(asset)}
        >
          <Languages />
        </Button>
      )}
      {asset &&
        (asset.status === "failed" || asset.subtitle?.status === "failed") && (
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="重试资源"
            onClick={() => retry(asset)}
          >
            <RotateCcw />
          </Button>
        )}
      <AwemeActions taskId={aweme.task_id} aweme={aweme} active={active} />
      <Button size="icon-sm" variant="ghost" asChild>
        <a
          href={getDouyinVideoUrl(aweme.aweme_id)}
          target="_blank"
          rel="noreferrer"
          aria-label="在抖音中打开视频"
        >
          <ExternalLink />
        </a>
      </Button>
      <Button size="icon-sm" variant="ghost" asChild>
        <Link
          to="/douyin/$taskId"
          params={{ taskId: aweme.task_id }}
          aria-label="进入任务"
        >
          <ExternalLink />
        </Link>
      </Button>
      {asset?.download_available && feedSearch && (
        <Button size="icon-sm" variant="ghost" asChild>
          <Link
            to="/douyin-library/feed"
            search={{ ...feedSearch, start: `video-${aweme.aweme_id}` }}
            aria-label="沉浸播放"
          >
            <PlaySquare />
          </Link>
        </Button>
      )}
    </>
  )
}

function VideoCard({
  row,
  task,
  retry,
  retranslate,
  onDownload,
  feedSearch,
  selected,
  onSelectedChange,
}: {
  row: DouyinWorkPublic
  task?: CrawlTaskPublic
  retry: (asset: DouyinMediaAssetPublic) => void
  retranslate: (asset: DouyinMediaAssetPublic) => void
  onDownload: (asset: DouyinMediaAssetPublic) => void
  feedSearch: LibraryFeedSearch
  selected: boolean
  onSelectedChange: (checked: boolean) => void
}) {
  const aweme = row.aweme
  const asset = row.media
  const subtitle = asset?.subtitle
  return (
    <Card className="group gap-0 overflow-hidden py-0 transition hover:-translate-y-0.5 hover:shadow-lg">
      <div className="relative aspect-video overflow-hidden bg-muted">
        <div className="absolute left-2 top-2 z-10 flex size-9 items-center justify-center rounded-lg bg-background/90 shadow-sm backdrop-blur">
          <Checkbox
            aria-label={`选择视频 ${aweme.title || aweme.aweme_id}`}
            checked={selected}
            onCheckedChange={(checked) => onSelectedChange(checked === true)}
          />
        </div>
        {aweme.cover_url ? (
          <img
            src={aweme.cover_url}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover transition duration-500 group-hover:scale-[1.03]"
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <Film className="size-12 opacity-25" />
          </div>
        )}
        <div className="absolute inset-x-0 bottom-0 flex items-end justify-between bg-gradient-to-t from-black/75 to-transparent p-3 pt-10 text-white">
          <span className="text-[11px]">
            发布 {formatUnix(aweme.create_time)}
          </span>
          <MediaStateBadge row={row} onCover />
        </div>
      </div>
      <CardContent className="space-y-2.5 p-3">
        <div>
          <h2 className="line-clamp-2 min-h-10 text-sm font-semibold leading-5">
            {aweme.title || aweme.aweme_id}
          </h2>
          <div className="mt-1.5 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
            <span className="truncate">{aweme.nickname || "匿名创作者"}</span>
            {aweme.source_keyword && (
              <span className="shrink-0 truncate">
                来源 {aweme.source_keyword}
              </span>
            )}
          </div>
          {(row.tags?.length ?? 0) > 0 && (
            <div className="mt-2 flex min-h-5 flex-wrap gap-1">
              {(row.tags ?? []).slice(0, 3).map((tag) => (
                <Badge key={tag.id} variant="outline" className="h-5 px-1.5">
                  #{tag.name}
                </Badge>
              ))}
              {(row.tags?.length ?? 0) > 3 && (
                <Badge variant="outline" className="h-5 px-1.5">
                  +{(row.tags?.length ?? 0) - 3}
                </Badge>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center justify-between rounded-lg bg-muted/45 px-3 py-2">
          <InlineStat
            icon={Heart}
            label="点赞"
            value={compact(aweme.liked_count)}
          />
          <InlineStat
            icon={MessageCircle}
            label="评论"
            value={compact(aweme.comment_count)}
          />
          <InlineStat
            icon={Star}
            label="收藏"
            value={compact(aweme.collected_count)}
          />
          <InlineStat
            icon={Share2}
            label="分享"
            value={compact(aweme.share_count)}
          />
          <InlineStat
            icon={Database}
            label="已存评论"
            value={compact(row.persisted_comment_count)}
          />
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          {task && (
            <TrackBadge
              trackId={task.track_id}
              trackName={task.track_name}
              isDefault={task.track_is_default}
              className="max-w-[45%]"
            />
          )}
          <Badge variant="outline" className="max-w-[58%] truncate">
            {task ? taskLabel(task) : "历史任务"}
          </Badge>
          <Badge variant="secondary" className="ml-auto shrink-0">
            {subtitle?.status === "completed" && <Captions />}
            {subtitleStatusLabel(subtitle?.status)}
          </Badge>
        </div>
        <div className="flex flex-wrap items-center gap-1 border-t pt-2">
          <WorkActionButtons
            row={row}
            task={task}
            retry={retry}
            retranslate={retranslate}
            onDownload={onDownload}
            feedSearch={feedSearch}
          />
        </div>
      </CardContent>
    </Card>
  )
}

function VideoRow({
  row,
  task,
  retry,
  retranslate,
  onDownload,
  selected,
  onSelectedChange,
}: {
  row: DouyinWorkPublic
  task?: CrawlTaskPublic
  retry: (asset: DouyinMediaAssetPublic) => void
  retranslate: (asset: DouyinMediaAssetPublic) => void
  onDownload: (asset: DouyinMediaAssetPublic) => void
  selected: boolean
  onSelectedChange: (checked: boolean) => void
}) {
  const aweme = row.aweme
  const title = aweme.title || aweme.aweme_id
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-3">
        <div className="flex size-9 shrink-0 items-center justify-center">
          <Checkbox
            aria-label={`选择视频 ${title}`}
            checked={selected}
            onCheckedChange={(checked) => onSelectedChange(checked === true)}
          />
        </div>
        <div className="relative aspect-video w-28 shrink-0 overflow-hidden rounded-md bg-muted">
          {aweme.cover_url ? (
            <img
              src={aweme.cover_url}
              alt=""
              loading="lazy"
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="flex h-full items-center justify-center">
              <Film className="size-6 opacity-25" />
            </div>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-sm font-medium" title={title}>
              {title}
            </h3>
            <MediaStateBadge row={row} />
          </div>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {aweme.nickname || "匿名创作者"} · 发布{" "}
            {formatUnix(aweme.create_time)}
            {aweme.source_keyword && ` · 来源 ${aweme.source_keyword}`}
          </p>
          <div className="mt-1.5 flex items-center gap-3">
            <InlineStat
              icon={Heart}
              label="点赞"
              value={compact(aweme.liked_count)}
            />
            <InlineStat
              icon={MessageCircle}
              label="评论"
              value={compact(aweme.comment_count)}
            />
            <InlineStat
              icon={Star}
              label="收藏"
              value={compact(aweme.collected_count)}
            />
            <InlineStat
              icon={Database}
              label="已存评论"
              value={compact(row.persisted_comment_count)}
            />
          </div>
        </div>
        <div className="hidden shrink-0 items-center gap-1.5 lg:flex">
          {task && (
            <TrackBadge
              trackId={task.track_id}
              trackName={task.track_name}
              isDefault={task.track_is_default}
              className="max-w-32"
            />
          )}
          <Badge variant="secondary" className="shrink-0">
            {subtitleStatusLabel(row.media?.subtitle?.status)}
          </Badge>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <WorkActionButtons
            row={row}
            task={task}
            retry={retry}
            retranslate={retranslate}
            onDownload={onDownload}
          />
        </div>
      </CardContent>
    </Card>
  )
}

function VideoTable({
  rows,
  taskMap,
  retry,
  onDownload,
  selectedAwemeSet,
  allPageSelected,
  somePageSelected,
  onTogglePage,
  onToggleRow,
}: {
  rows: DouyinWorkPublic[]
  taskMap: Map<string, CrawlTaskPublic>
  retry: (row: DouyinWorkPublic, asset: DouyinMediaAssetPublic) => void
  onDownload: (row: DouyinWorkPublic, asset: DouyinMediaAssetPublic) => void
  selectedAwemeSet: Set<string>
  allPageSelected: boolean
  somePageSelected: boolean
  onTogglePage: (checked: boolean) => void
  onToggleRow: (awemeId: string, checked: boolean) => void
}) {
  return (
    <Card>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">
                  <Checkbox
                    aria-label="选择本页视频"
                    checked={
                      allPageSelected
                        ? true
                        : somePageSelected
                          ? "indeterminate"
                          : false
                    }
                    onCheckedChange={(checked) =>
                      onTogglePage(checked === true)
                    }
                  />
                </TableHead>
                <TableHead className="min-w-64">作品</TableHead>
                <TableHead>创作者</TableHead>
                <TableHead>赛道</TableHead>
                <TableHead className="text-right">点赞</TableHead>
                <TableHead className="text-right">评论</TableHead>
                <TableHead className="text-right">已存评论</TableHead>
                <TableHead>发布时间</TableHead>
                <TableHead>下载</TableHead>
                <TableHead>字幕</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => {
                const aweme = row.aweme
                const asset = row.media
                const task = taskMap.get(aweme.task_id)
                const title = aweme.title || aweme.aweme_id
                return (
                  <TableRow key={aweme.id}>
                    <TableCell>
                      <Checkbox
                        aria-label={`选择视频 ${title}`}
                        checked={selectedAwemeSet.has(aweme.aweme_id)}
                        onCheckedChange={(checked) =>
                          onToggleRow(aweme.aweme_id, checked === true)
                        }
                      />
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2.5">
                        <div className="relative aspect-video w-16 shrink-0 overflow-hidden rounded bg-muted">
                          {aweme.cover_url ? (
                            <img
                              src={aweme.cover_url}
                              alt=""
                              loading="lazy"
                              className="h-full w-full object-cover"
                            />
                          ) : (
                            <div className="flex h-full items-center justify-center">
                              <Film className="size-5 opacity-25" />
                            </div>
                          )}
                        </div>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span className="line-clamp-2 max-w-56 cursor-default text-sm font-medium leading-5">
                              {title}
                            </span>
                          </TooltipTrigger>
                          <TooltipContent className="max-w-sm">
                            {title}
                          </TooltipContent>
                        </Tooltip>
                      </div>
                    </TableCell>
                    <TableCell className="max-w-28 truncate text-xs">
                      {aweme.nickname || "匿名创作者"}
                    </TableCell>
                    <TableCell>
                      {task ? (
                        <TrackBadge
                          trackId={task.track_id}
                          trackName={task.track_name}
                          isDefault={task.track_is_default}
                          className="max-w-32"
                        />
                      ) : (
                        <span className="text-xs text-muted-foreground">-</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {compact(aweme.liked_count)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {compact(aweme.comment_count)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {compact(row.persisted_comment_count)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs">
                      {formatUnix(aweme.create_time)}
                    </TableCell>
                    <TableCell>
                      <MediaStateBadge row={row} />
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs">
                      {subtitleStatusLabel(asset?.subtitle?.status)}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        {asset?.download_available && (
                          <VideoPreviewDialog
                            taskId={aweme.task_id}
                            asset={asset}
                            aweme={aweme}
                          />
                        )}
                        {asset && (
                          <SubtitleDialog
                            asset={asset}
                            title={aweme.title || aweme.aweme_id}
                          />
                        )}
                        {asset?.download_available && (
                          <Button
                            size="icon-sm"
                            variant="ghost"
                            aria-label="下载视频"
                            onClick={() => onDownload(row, asset)}
                          >
                            <Download />
                          </Button>
                        )}
                        {asset &&
                          (asset.status === "failed" ||
                            asset.subtitle?.status === "failed") && (
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              aria-label="重试资源"
                              onClick={() => retry(row, asset)}
                            >
                              <RotateCcw />
                            </Button>
                          )}
                        <Button size="icon-sm" variant="ghost" asChild>
                          <a
                            href={getDouyinVideoUrl(aweme.aweme_id)}
                            target="_blank"
                            rel="noreferrer"
                            aria-label="在抖音中打开视频"
                          >
                            <ExternalLink />
                          </a>
                        </Button>
                        <Button size="icon-sm" variant="ghost" asChild>
                          <Link
                            to="/douyin/$taskId"
                            params={{ taskId: aweme.task_id }}
                            aria-label="进入任务"
                          >
                            <ExternalLink />
                          </Link>
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

function SummaryPill({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Film
  label: string
  value: number
}) {
  return (
    <div className="flex items-center gap-2 rounded-lg border bg-card/75 px-3 py-1.5 text-xs shadow-sm">
      <Icon className="size-3.5 text-primary" />
      <span className="text-muted-foreground">{label}</span>
      <strong className="text-sm tabular-nums">{value}</strong>
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
    <div className="flex items-center justify-center gap-3 py-2">
      <Button
        variant="outline"
        disabled={page === 0}
        onClick={() => onChange(page - 1)}
      >
        上一页
      </Button>
      <span className="text-sm text-muted-foreground">
        第 {page + 1} / {pages} 页 · 共 {count} 条
      </span>
      <Button
        variant="outline"
        disabled={page + 1 >= pages}
        onClick={() => onChange(page + 1)}
      >
        下一页
      </Button>
    </div>
  )
}

function taskLabel(task: CrawlTaskPublic) {
  const request = task.request as { keywords?: string[]; video_ids?: string[] }
  const target = request.keywords?.[0] || request.video_ids?.[0]
  return target
    ? `${task.crawl_type} · ${target}`
    : `${task.crawl_type} · ${task.id.slice(0, 8)}`
}

function formatUnix(value: number | null) {
  if (!value) return "未知"
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium" }).format(
    new Date(value * 1_000),
  )
}

function formatDateTimeText(value: Date) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(value)
}

function subtitleStatusLabel(status: string | undefined) {
  const labels: Record<string, string> = {
    pending: "字幕排队",
    running: "字幕处理中",
    completed: "字幕完成",
    failed: "字幕失败",
  }
  return status ? (labels[status] ?? status) : "无字幕"
}

function compact(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value)
}
