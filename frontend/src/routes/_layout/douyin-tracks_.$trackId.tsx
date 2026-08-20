import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ArrowLeft,
  ArrowRight,
  FileText,
  Film,
  MessageCircle,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Target,
  Trash2,
} from "lucide-react"
import { type FormEvent, useEffect, useRef, useState } from "react"

import {
  ApiError,
  type CrawlTaskPublic,
  type DouyinCreatorPublic,
  type DouyinCreatorStatus,
  DouyinCreatorsService,
  type DouyinKeywordPublic,
  type DouyinKeywordStatus,
  DouyinKeywordsService,
  DouyinService,
  type DouyinTrackDetailPublic,
  DouyinTracksService,
} from "@/client"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { CreateTaskDialog } from "@/components/Douyin/CreateTaskDialog"
import { TaskIdentity } from "@/components/Douyin/TaskIdentity"
import {
  activeTaskStatuses,
  TaskStatusBadge,
} from "@/components/Douyin/TaskStatusBadge"
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
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/douyin-tracks_/$trackId")({
  component: DouyinTrackDetailPage,
  head: () => ({ meta: [{ title: "赛道详情 - 灵感采集台" }] }),
})

const keywordStatusLabels: Record<DouyinKeywordStatus, string> = {
  unprocessed: "未爬取",
  active: "进行中",
  crawled: "已爬取",
  failed: "需重试",
}

const creatorStatusLabels: Record<DouyinCreatorStatus, string> = {
  unprocessed: "未爬取",
  active: "进行中",
  crawled: "已爬取",
  failed: "需重试",
}

function DouyinTrackDetailPage() {
  const { trackId } = Route.useParams()
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [search, setSearch] = useState("")
  const [searchCreators, setSearchCreators] = useState("")
  const [addOpen, setAddOpen] = useState(false)
  const [addCreatorsOpen, setAddCreatorsOpen] = useState(false)
  const [editingKeyword, setEditingKeyword] =
    useState<DouyinKeywordPublic | null>(null)
  const [removingKeyword, setRemovingKeyword] =
    useState<DouyinKeywordPublic | null>(null)
  const [editingCreator, setEditingCreator] =
    useState<DouyinCreatorPublic | null>(null)
  const [removingCreator, setRemovingCreator] =
    useState<DouyinCreatorPublic | null>(null)

  const trackQuery = useQuery({
    queryKey: ["douyin-track", trackId],
    queryFn: () => DouyinTracksService.getTrack({ trackId }),
    retry: false,
    refetchInterval: 10_000,
  })
  const keywordsQuery = useQuery({
    queryKey: ["douyin-track-keywords", trackId],
    queryFn: () => DouyinTracksService.listTrackKeywords({ trackId }),
    retry: false,
    refetchInterval: 10_000,
  })
  const creatorsQuery = useQuery({
    queryKey: ["douyin-track-creators", trackId],
    queryFn: () => DouyinTracksService.listTrackCreators({ trackId }),
    retry: false,
    refetchInterval: 10_000,
  })
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["douyin-track", trackId] }),
      queryClient.invalidateQueries({
        queryKey: ["douyin-track-keywords", trackId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["douyin-track-creators", trackId],
      }),
      queryClient.invalidateQueries({ queryKey: ["douyin-tracks"] }),
      queryClient.invalidateQueries({ queryKey: ["douyin-keywords"] }),
      queryClient.invalidateQueries({ queryKey: ["douyin-creators"] }),
    ])
  }
  const unlink = useMutation({
    mutationFn: (keywordId: string) =>
      DouyinTracksService.removeTrackKeyword({ trackId, keywordId }),
    onSuccess: async () => {
      setRemovingKeyword(null)
      showSuccessToast("关键词已移回默认赛道，历史任务与内容数据已保留")
      await refresh()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const removeCreator = useMutation({
    mutationFn: (creatorId: string) =>
      DouyinTracksService.removeTrackCreator({ trackId, creatorId }),
    onSuccess: async () => {
      setRemovingCreator(null)
      showSuccessToast("达人已移回默认赛道，历史任务与内容数据已保留")
      await refresh()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })

  if (trackQuery.isLoading) {
    return (
      <Card>
        <CardContent className="py-20 text-center text-sm text-muted-foreground">
          正在加载赛道详情…
        </CardContent>
      </Card>
    )
  }
  if (!trackQuery.data || trackQuery.isError) {
    const unavailable =
      trackQuery.error instanceof ApiError &&
      [403, 404].includes(trackQuery.error.status)
    return (
      <Card>
        <CardContent className="space-y-4 py-16 text-center">
          <p className="font-medium">
            {unavailable ? "赛道不存在或当前账号无权访问" : "赛道详情读取失败"}
          </p>
          {!unavailable && (
            <p className="text-sm text-muted-foreground">
              暂时无法获取赛道详情，请检查服务连接后重试。
            </p>
          )}
          {!unavailable && (
            <Button
              type="button"
              variant="outline"
              disabled={trackQuery.isFetching}
              onClick={() => void trackQuery.refetch()}
            >
              {trackQuery.isFetching ? "正在重试…" : "重试"}
            </Button>
          )}
          <Button variant="outline" asChild>
            <Link to="/douyin-tracks" search={{ run: undefined }}>
              返回赛道列表
            </Link>
          </Button>
        </CardContent>
      </Card>
    )
  }

  const track = trackQuery.data
  const keywords = keywordsQuery.data?.data ?? []
  const creators = creatorsQuery.data?.data ?? []
  const term = search.trim().toLocaleLowerCase("zh-CN")
  const visibleKeywords = term
    ? keywords.filter(
        (item) =>
          item.keyword.toLocaleLowerCase("zh-CN").includes(term) ||
          item.notes.toLocaleLowerCase("zh-CN").includes(term),
      )
    : keywords
  const creatorTerm = searchCreators.trim().toLocaleLowerCase("zh-CN")
  const visibleCreators = creatorTerm
    ? creators.filter(
        (item) =>
          item.nickname.toLocaleLowerCase("zh-CN").includes(creatorTerm) ||
          item.sec_uid.toLocaleLowerCase("zh-CN").includes(creatorTerm) ||
          item.notes.toLocaleLowerCase("zh-CN").includes(creatorTerm),
      )
    : creators
  return (
    <div className="space-y-3">
      <Card className="overflow-hidden">
        <CardContent className="p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <Button variant="ghost" size="sm" className="-ml-2 h-7" asChild>
                <Link to="/douyin-tracks" search={{ run: undefined }}>
                  <ArrowLeft /> 返回赛道列表
                </Link>
              </Button>
              <div className="mt-2 flex items-center gap-2">
                <span className="flex size-8 items-center justify-center rounded-lg bg-violet-500/12 text-violet-700 dark:text-violet-300">
                  <Target className="size-4" />
                </span>
                <h1 className="truncate text-xl font-semibold">{track.name}</h1>
                <Badge variant={track.enabled ? "default" : "secondary"}>
                  配置：{track.enabled ? "启用" : "停用"}
                </Badge>
                {track.is_default && <Badge variant="outline">默认赛道</Badge>}
              </div>
              <p className="mt-1 max-w-3xl line-clamp-2 text-sm text-muted-foreground">
                {track.description || "尚未填写赛道定位与目标人群"}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span className="font-medium">最近一次采集</span>
                {track.last_task_status ? (
                  <TaskStatusBadge status={track.last_task_status} />
                ) : (
                  <Badge variant="outline">尚未运行</Badge>
                )}
                {track.last_run_at && (
                  <span>{formatDate(track.last_run_at)}</span>
                )}
                {track.last_task_id && (
                  <Link
                    to="/douyin/$taskId"
                    params={{ taskId: track.last_task_id }}
                    className="font-medium text-primary hover:underline"
                  >
                    查看任务
                  </Link>
                )}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <CreateTaskDialog
                initialTrackId={trackId}
                initialCrawlType="creator"
                triggerLabel="添加达人爬取"
                triggerVariant="outline"
              />
              <Button size="sm" asChild>
                <Link to="/douyin-tracks" search={{ run: track.id }}>
                  启动赛道采集
                </Link>
              </Button>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <CompactMetric
              icon={Target}
              label="可用关键词"
              value={`${track.enabled_keyword_count}/${track.keyword_count}`}
            />
            <CompactMetric
              icon={FileText}
              label="任务"
              value={track.task_count}
              detail={`${track.active_task_count} 运行中`}
            />
            <CompactMetric icon={Film} label="作品" value={track.aweme_count} />
            <CompactMetric
              icon={MessageCircle}
              label="评论"
              value={track.comment_count}
            />
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="keywords" className="space-y-3">
        <TabsList>
          <TabsTrigger value="keywords">
            关键词（{track.keyword_count}）
          </TabsTrigger>
          <TabsTrigger value="creators">达人（{creators.length}）</TabsTrigger>
          <TabsTrigger value="tasks">任务（{track.task_count}）</TabsTrigger>
          <TabsTrigger value="settings">赛道设置</TabsTrigger>
        </TabsList>
        <TabsContent value="keywords">
          <Card>
            <CardHeader className="space-y-0 p-4 pb-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <CardTitle className="text-base">赛道关键词</CardTitle>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    每个关键词唯一归属一个赛道；移动后，后续任务与筛选会使用新归属。
                  </p>
                </div>
                <Button
                  size="sm"
                  disabled={keywordsQuery.isError}
                  onClick={() => setAddOpen(true)}
                >
                  <Plus /> 添加或移动关键词
                </Button>
              </div>
            </CardHeader>
            <CardContent className="p-4 pt-2">
              <div className="relative mb-2 max-w-sm">
                <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="筛选当前赛道关键词"
                  aria-label="筛选当前赛道关键词"
                  className="h-8 pl-9"
                />
              </div>
              {keywordsQuery.isError ? (
                <QueryErrorState
                  title="赛道关键词读取失败"
                  description="暂时无法获取当前赛道的关键词，请检查服务连接后重试。"
                  onRetry={() => void keywordsQuery.refetch()}
                  retrying={keywordsQuery.isFetching}
                  className="py-8"
                />
              ) : (
                <div className="max-h-[560px] overflow-auto rounded-lg border">
                  <Table>
                    <TableHeader className="sticky top-0 z-10 bg-background">
                      <TableRow>
                        <TableHead className="h-9">关键词</TableHead>
                        <TableHead className="h-9">状态</TableHead>
                        <TableHead className="h-9">任务 / 作品</TableHead>
                        <TableHead className="h-9 text-right">操作</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {visibleKeywords.map((keyword) => (
                        <TableRow key={keyword.id}>
                          <TableCell className="max-w-60 py-2">
                            <p className="truncate font-medium">
                              {keyword.keyword}
                            </p>
                            {keyword.notes && (
                              <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                                {keyword.notes}
                              </p>
                            )}
                          </TableCell>
                          <TableCell className="py-2">
                            <Badge
                              variant={
                                keyword.enabled ? "outline" : "secondary"
                              }
                              className="whitespace-nowrap"
                            >
                              {keyword.enabled
                                ? keywordStatusLabels[keyword.status]
                                : "已停用"}
                            </Badge>
                          </TableCell>
                          <TableCell className="whitespace-nowrap py-2 text-xs text-muted-foreground">
                            {keyword.task_count} / {keyword.aweme_count}
                          </TableCell>
                          <TableCell className="py-2">
                            <div className="flex justify-end gap-1">
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 px-2"
                                aria-label={`编辑关键词 ${keyword.keyword}`}
                                onClick={() => setEditingKeyword(keyword)}
                              >
                                <Pencil /> 编辑
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 px-2 text-destructive"
                                aria-label={`移除关键词 ${keyword.keyword}`}
                                disabled={track.is_default}
                                title={
                                  track.is_default
                                    ? "默认赛道的关键词不能移除，请将它移动到其他赛道"
                                    : "移回默认赛道"
                                }
                                onClick={() => setRemovingKeyword(keyword)}
                              >
                                <Trash2 />
                                {track.is_default ? "默认归属" : "移回默认"}
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                      {!visibleKeywords.length && (
                        <TableRow>
                          <TableCell
                            colSpan={4}
                            className="h-28 text-center text-sm text-muted-foreground"
                          >
                            {keywordsQuery.isLoading
                              ? "正在加载关键词…"
                              : search.trim()
                                ? "没有匹配的赛道关键词"
                                : "当前赛道还没有关键词"}
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="creators">
          <Card>
            <CardHeader className="space-y-0 p-4 pb-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <CardTitle className="text-base">赛道达人</CardTitle>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    每位达人唯一归属一个赛道；移动后，后续任务与筛选会使用新归属。
                  </p>
                </div>
                <Button
                  size="sm"
                  disabled={creatorsQuery.isError}
                  onClick={() => setAddCreatorsOpen(true)}
                >
                  <Plus /> 添加或移动达人
                </Button>
              </div>
            </CardHeader>
            <CardContent className="p-4 pt-2">
              <div className="relative mb-2 max-w-sm">
                <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={searchCreators}
                  onChange={(event) => setSearchCreators(event.target.value)}
                  placeholder="筛选当前赛道达人"
                  aria-label="筛选当前赛道达人"
                  className="h-8 pl-9"
                />
              </div>
              {creatorsQuery.isError ? (
                <QueryErrorState
                  title="赛道达人读取失败"
                  description="暂时无法获取当前赛道的达人，请检查服务连接后重试。"
                  onRetry={() => void creatorsQuery.refetch()}
                  retrying={creatorsQuery.isFetching}
                  className="py-8"
                />
              ) : (
                <div className="max-h-[560px] overflow-auto rounded-lg border">
                  <Table>
                    <TableHeader className="sticky top-0 z-10 bg-background">
                      <TableRow>
                        <TableHead className="h-9">达人</TableHead>
                        <TableHead className="h-9">状态</TableHead>
                        <TableHead className="h-9">任务 / 作品</TableHead>
                        <TableHead className="h-9 text-right">操作</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {visibleCreators.map((creator) => (
                        <TableRow key={creator.id}>
                          <TableCell className="max-w-72 py-2">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <p className="truncate font-medium">
                                {creator.nickname || "未命名达人"}
                              </p>
                              {creator.is_placeholder && (
                                <Badge
                                  variant="outline"
                                  className="border-amber-400/60 bg-amber-50 text-amber-700"
                                >
                                  待补全
                                </Badge>
                              )}
                            </div>
                            <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                              {creator.is_placeholder
                                ? "脱敏身份 · 补全主页链接后可创建任务"
                                : creator.sec_uid.slice(-12)}
                            </p>
                            {creator.notes && (
                              <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                                {creator.notes}
                              </p>
                            )}
                          </TableCell>
                          <TableCell className="py-2">
                            <Badge
                              variant={
                                creator.enabled ? "outline" : "secondary"
                              }
                              className="whitespace-nowrap"
                            >
                              {creator.enabled
                                ? creatorStatusLabels[creator.status]
                                : "已停用"}
                            </Badge>
                          </TableCell>
                          <TableCell className="whitespace-nowrap py-2 text-xs text-muted-foreground">
                            {creator.task_count} / {creator.aweme_count}
                          </TableCell>
                          <TableCell className="py-2">
                            <div className="flex justify-end gap-1">
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 px-2"
                                aria-label={`编辑达人 ${creator.nickname || creator.sec_uid}`}
                                onClick={() => setEditingCreator(creator)}
                              >
                                <Pencil /> 编辑
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 px-2 text-destructive"
                                aria-label={`移除达人 ${creator.nickname || creator.sec_uid}`}
                                disabled={track.is_default}
                                title={
                                  track.is_default
                                    ? "默认赛道的达人不能移除，请将它移动到其他赛道"
                                    : "移回默认赛道"
                                }
                                onClick={() => setRemovingCreator(creator)}
                              >
                                <Trash2 />
                                {track.is_default ? "默认归属" : "移回默认"}
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                      {!visibleCreators.length && (
                        <TableRow>
                          <TableCell
                            colSpan={4}
                            className="h-28 text-center text-sm text-muted-foreground"
                          >
                            {creatorsQuery.isLoading
                              ? "正在加载达人…"
                              : search.trim()
                                ? "没有匹配的赛道达人"
                                : "当前赛道还没有达人"}
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="tasks">
          <TrackTasksPanel trackId={trackId} keywords={keywords} />
        </TabsContent>
        <TabsContent
          value="settings"
          forceMount
          className="data-[state=inactive]:hidden"
        >
          <div className="max-w-3xl">
            <TrackEditor key={track.id} track={track} onSaved={refresh} />
          </div>
        </TabsContent>
      </Tabs>

      <AddTrackKeywordsDialog
        trackId={trackId}
        trackName={track.name}
        linkedKeywords={keywords}
        open={addOpen}
        onOpenChange={setAddOpen}
        onAdded={refresh}
      />
      {editingKeyword && (
        <EditKeywordDialog
          item={editingKeyword}
          open
          onOpenChange={(open) => !open && setEditingKeyword(null)}
          onSaved={async () => {
            setEditingKeyword(null)
            await refresh()
          }}
        />
      )}
      <Dialog
        open={Boolean(removingKeyword)}
        onOpenChange={(open) => !open && setRemovingKeyword(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              从当前赛道移除“{removingKeyword?.keyword}”？
            </DialogTitle>
            <DialogDescription>
              关键词会迁移到默认赛道；历史任务、作品和评论不会被删除。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemovingKeyword(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={!removingKeyword || unlink.isPending}
              onClick={() =>
                removingKeyword && unlink.mutate(removingKeyword.id)
              }
            >
              {unlink.isPending ? "正在移除…" : "确认移除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AddTrackCreatorsDialog
        trackId={trackId}
        trackName={track.name}
        linkedCreators={creators}
        open={addCreatorsOpen}
        onOpenChange={setAddCreatorsOpen}
        onAdded={refresh}
      />
      {editingCreator && (
        <EditCreatorDialog
          item={editingCreator}
          open
          onOpenChange={(open) => !open && setEditingCreator(null)}
          onSaved={async () => {
            setEditingCreator(null)
            await refresh()
          }}
        />
      )}
      <Dialog
        open={Boolean(removingCreator)}
        onOpenChange={(open) => !open && setRemovingCreator(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              从当前赛道移除“
              {removingCreator?.nickname || removingCreator?.sec_uid}”？
            </DialogTitle>
            <DialogDescription>
              达人会迁移到默认赛道；历史任务、作品和评论不会被删除。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemovingCreator(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={!removingCreator || removeCreator.isPending}
              onClick={() =>
                removingCreator && removeCreator.mutate(removingCreator.id)
              }
            >
              {removeCreator.isPending ? "正在移除…" : "确认移除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

const crawlTypeLabels: Record<CrawlTaskPublic["crawl_type"], string> = {
  search: "关键词搜索",
  detail: "指定作品",
  creator: "创作者作品",
  creator_from_aweme: "视频作者作品",
  liked: "账号点赞",
  collected: "账号收藏",
}

const taskFilterTabs = [
  { key: "all", label: "全部" },
  { key: "active", label: "进行中" },
  { key: "attention", label: "需处理" },
  { key: "succeeded", label: "已完成" },
] as const
type TaskFilterKey = (typeof taskFilterTabs)[number]["key"]
const attentionStatuses = ["failed", "interrupted", "waiting_login"]

function taskKeywordNames(
  task: CrawlTaskPublic,
  keywordNameById: Map<string, string>,
) {
  const request = task.request as Record<string, unknown>
  const ids = Array.isArray(request.keyword_ids)
    ? request.keyword_ids.filter(
        (value): value is string => typeof value === "string",
      )
    : []
  if (ids.length) {
    const names = ids
      .map((id) => keywordNameById.get(id))
      .filter((value): value is string => Boolean(value))
    if (names.length) return [...new Set(names)]
  }
  const words = Array.isArray(request.keywords)
    ? request.keywords.filter(
        (value): value is string => typeof value === "string",
      )
    : []
  return [...new Set(words)]
}

function TrackTasksPanel({
  trackId,
  keywords,
}: {
  trackId: string
  keywords: DouyinKeywordPublic[]
}) {
  const [statusFilter, setStatusFilter] = useState<TaskFilterKey>("all")
  const [search, setSearch] = useState("")
  const tasksQuery = useQuery({
    queryKey: ["douyin-track-tasks", trackId],
    queryFn: () => DouyinService.listTasks({ trackId, skip: 0, limit: 100 }),
    retry: false,
    refetchInterval: 3_000,
  })
  const tasks = tasksQuery.data?.data ?? []
  const keywordNameById = new Map(
    keywords.map((item) => [item.id, item.keyword]),
  )
  const term = search.trim().toLocaleLowerCase("zh-CN")
  const filtered = tasks.filter((task) => {
    const matchesStatus =
      statusFilter === "all" ||
      (statusFilter === "active" && activeTaskStatuses.includes(task.status)) ||
      (statusFilter === "attention" &&
        attentionStatuses.includes(task.status)) ||
      (statusFilter === "succeeded" && task.status === "succeeded")
    if (!matchesStatus) return false
    if (!term) return true
    return [
      task.display_title ?? "",
      crawlTypeLabels[task.crawl_type],
      ...(task.creator_names ?? []),
      ...taskKeywordNames(task, keywordNameById),
    ].some((value) => value.toLocaleLowerCase("zh-CN").includes(term))
  })
  const groupMap = new Map<string, CrawlTaskPublic[]>()
  filtered.forEach((task) => {
    const names = taskKeywordNames(task, keywordNameById)
    const isCreatorTask = ["creator", "creator_from_aweme"].includes(
      task.crawl_type,
    )
    const creatorNames = task.creator_names?.length ? task.creator_names : []
    const buckets = creatorNames.length
      ? creatorNames
      : names.length
        ? names
        : [isCreatorTask ? "达人爬取" : "未指定关键词"]
    buckets.forEach((name) => {
      const list = groupMap.get(name) ?? []
      list.push(task)
      groupMap.set(name, list)
    })
  })
  const groups = [...groupMap.entries()]
    .map(([name, groupTasks]) => ({
      name,
      tasks: groupTasks.sort((a, b) =>
        b.created_at.localeCompare(a.created_at),
      ),
      latest: Math.max(
        ...groupTasks.map((task) => new Date(task.created_at).getTime()),
      ),
    }))
    .sort((a, b) => b.latest - a.latest)

  return (
    <Card>
      <CardHeader className="space-y-0 p-4 pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="text-base">赛道任务</CardTitle>
            <p className="mt-0.5 text-xs text-muted-foreground">
              按关键词 /
              达人分组展示；命中多个关键词或达人的任务会同时出现在对应分组。
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={tasksQuery.isFetching}
              onClick={() => void tasksQuery.refetch()}
            >
              <RefreshCw
                className={tasksQuery.isFetching ? "animate-spin" : ""}
              />
              刷新
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 p-4 pt-2">
        <div className="flex flex-wrap items-center gap-2">
          <fieldset className="m-0 flex items-center rounded-lg border p-0.5">
            <legend className="sr-only">按状态筛选任务</legend>
            {taskFilterTabs.map((tab) => (
              <Button
                key={tab.key}
                size="sm"
                variant={statusFilter === tab.key ? "secondary" : "ghost"}
                className="h-8 px-3 text-xs"
                aria-pressed={statusFilter === tab.key}
                onClick={() => setStatusFilter(tab.key)}
              >
                {tab.label}
              </Button>
            ))}
          </fieldset>
          <div className="relative min-w-52 flex-1">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索任务标题、类型或关键词"
              aria-label="搜索赛道任务"
              className="h-9 pl-9"
            />
          </div>
        </div>

        {tasksQuery.isError ? (
          <QueryErrorState
            title="赛道任务读取失败"
            description="暂时无法获取当前赛道的任务，请检查服务连接后重试。"
            onRetry={() => void tasksQuery.refetch()}
            retrying={tasksQuery.isFetching}
            className="py-8"
          />
        ) : tasksQuery.isLoading ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            正在加载赛道任务…
          </p>
        ) : groups.length === 0 ? (
          <p className="rounded-lg border border-dashed py-10 text-center text-sm text-muted-foreground">
            {tasks.length
              ? "没有匹配当前筛选条件的任务"
              : "当前赛道还没有任务：头部“添加达人爬取”可采集指定创作者主页，“启动赛道采集”按关键词批量创建任务"}
          </p>
        ) : (
          groups.map((group) => {
            const active = group.tasks.filter((task) =>
              activeTaskStatuses.includes(task.status),
            ).length
            const attention = group.tasks.filter((task) =>
              attentionStatuses.includes(task.status),
            ).length
            const done = group.tasks.filter(
              (task) => task.status === "succeeded",
            ).length
            const summary = [
              active ? `${active} 进行中` : "",
              attention ? `${attention} 需处理` : "",
              done ? `${done} 已完成` : "",
            ]
              .filter(Boolean)
              .join(" · ")
            return (
              <div key={group.name} className="rounded-xl border">
                <div className="flex flex-wrap items-center gap-2 border-b bg-muted/30 px-3 py-2">
                  <Badge variant="secondary">{group.name}</Badge>
                  <span className="text-xs text-muted-foreground">
                    {group.tasks.length} 个任务
                  </span>
                  <span className="flex-1" />
                  {summary && (
                    <span className="text-[11px] text-muted-foreground">
                      {summary}
                    </span>
                  )}
                </div>
                <div className="divide-y">
                  {group.tasks.map((task) => (
                    <div
                      key={task.id}
                      className="flex flex-wrap items-center gap-3 px-3 py-2.5"
                    >
                      <TaskStatusBadge status={task.status} />
                      <div className="min-w-0 flex-1">
                        <TaskIdentity task={task} className="text-sm" />
                        {task.error && (
                          <p className="mt-0.5 truncate text-[11px] text-destructive">
                            {task.error}
                          </p>
                        )}
                      </div>
                      <span className="whitespace-nowrap text-xs text-muted-foreground">
                        作品 {task.aweme_count} · 评论 {task.comment_count}
                      </span>
                      <span className="whitespace-nowrap text-xs text-muted-foreground">
                        {formatDate(task.created_at)}
                      </span>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2"
                        asChild
                      >
                        <Link to="/douyin/$taskId" params={{ taskId: task.id }}>
                          查看
                          <ArrowRight />
                        </Link>
                      </Button>
                    </div>
                  ))}
                </div>
              </div>
            )
          })
        )}
      </CardContent>
    </Card>
  )
}

function TrackEditor({
  track,
  onSaved,
}: {
  track: DouyinTrackDetailPublic
  onSaved: () => Promise<unknown>
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [name, setName] = useState(track.name)
  const [description, setDescription] = useState(track.description)
  const [prompt, setPrompt] = useState(track.prompt)
  const [enabled, setEnabled] = useState(track.enabled)
  const previousTrack = useRef(track)
  useEffect(() => {
    const previous = previousTrack.current
    const hasDraft =
      name !== previous.name ||
      description !== previous.description ||
      prompt !== previous.prompt ||
      enabled !== previous.enabled
    if (!hasDraft) {
      setName(track.name)
      setDescription(track.description)
      setPrompt(track.prompt)
      setEnabled(track.enabled)
    }
    previousTrack.current = track
  }, [description, enabled, name, prompt, track])
  const mutation = useMutation({
    mutationFn: () =>
      DouyinTracksService.editTrack({
        trackId: track.id,
        requestBody: { name, description, prompt, enabled },
      }),
    onSuccess: async (updated) => {
      setName(updated.name)
      setDescription(updated.description)
      setPrompt(updated.prompt)
      setEnabled(updated.enabled)
      showSuccessToast("赛道信息与提示词已保存")
      await onSaved()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const dirty =
    name !== track.name ||
    description !== track.description ||
    prompt !== track.prompt ||
    enabled !== track.enabled

  return (
    <Card>
      <CardHeader className="p-4 pb-2">
        <CardTitle className="text-base">赛道信息与提示词</CardTitle>
        <p className="text-xs text-muted-foreground">
          提示词作为赛道运营策略沉淀，暂不直接改变爬取参数。
        </p>
      </CardHeader>
      <CardContent className="space-y-3 p-4 pt-2">
        <div className="space-y-1">
          <Label htmlFor="detail-track-name" className="text-xs">
            赛道名称
          </Label>
          <Input
            id="detail-track-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="h-8"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="detail-track-description" className="text-xs">
            定位与目标人群
          </Label>
          <Textarea
            id="detail-track-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            rows={3}
            className="resize-y"
          />
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between gap-2">
            <Label htmlFor="detail-track-prompt" className="text-xs">
              赛道提示词
            </Label>
            <span className="text-[11px] text-muted-foreground">
              {prompt.length}/10000
            </span>
          </div>
          <Textarea
            id="detail-track-prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={9}
            maxLength={10000}
            placeholder="例如：分析该赛道评论中的用户需求、购买阻力、常见异议与可转化信号。"
            className="resize-y"
          />
        </div>
        <div className="flex items-center gap-2 text-sm">
          <Checkbox
            id="detail-track-enabled"
            checked={enabled}
            disabled={track.is_default}
            onCheckedChange={(checked) => setEnabled(checked === true)}
          />
          <Label htmlFor="detail-track-enabled">启用该赛道</Label>
        </div>
        {track.is_default && (
          <p className="text-xs text-muted-foreground">
            默认赛道用于承接未指定归属的数据，因此必须保持启用。
          </p>
        )}
        <div className="flex justify-end gap-2 border-t pt-3">
          <Button
            size="sm"
            variant="outline"
            disabled={!prompt || mutation.isPending}
            onClick={() => setPrompt("")}
          >
            清空提示词
          </Button>
          <Button
            size="sm"
            disabled={!dirty || !name.trim() || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "保存中…" : "保存修改"}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function AddTrackKeywordsDialog({
  trackId,
  trackName,
  linkedKeywords,
  open,
  onOpenChange,
  onAdded,
}: {
  trackId: string
  trackName: string
  linkedKeywords: DouyinKeywordPublic[]
  open: boolean
  onOpenChange: (open: boolean) => void
  onAdded: () => Promise<unknown>
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [newValues, setNewValues] = useState("")
  const [search, setSearch] = useState("")
  const [selected, setSelected] = useState<Map<string, string>>(new Map())
  const candidatesQuery = useQuery({
    queryKey: ["douyin-track-keyword-candidates", search],
    queryFn: () =>
      DouyinKeywordsService.listKeywords({
        search: search.trim() || undefined,
        enabled: true,
        sortBy: "task_count",
        sortOrder: "desc",
        limit: 100,
      }),
    enabled: open,
    placeholderData: (previous) => previous,
  })
  const linkedIds = new Set(linkedKeywords.map((item) => item.id))
  const candidates = (candidatesQuery.data?.data ?? []).filter(
    (item) => !linkedIds.has(item.id),
  )
  const mutation = useMutation({
    mutationFn: (keywords: string[]) =>
      DouyinTracksService.appendTrackKeywords({
        trackId,
        requestBody: { keywords },
      }),
    onSuccess: async () => {
      setNewValues("")
      setSearch("")
      setSelected(new Map())
      onOpenChange(false)
      showSuccessToast("关键词已归入当前赛道")
      await onAdded()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const submitNew = () => {
    const values = parseKeywords(newValues)
    if (!values.length) return showErrorToast("请填写至少一个关键词")
    mutation.mutate(values)
  }
  const submitExisting = () => {
    const values = [...selected.values()]
    if (!values.length) return showErrorToast("请至少选择一个关键词")
    if (
      window.confirm(
        `确认将已选的 ${values.length} 个关键词移动到“${trackName}”？后续任务和内容筛选会使用新的赛道归属。`,
      )
    )
      mutation.mutate(values)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>添加或移动赛道关键词</DialogTitle>
          <DialogDescription>
            新关键词会直接归入当前赛道；已有关键词会从原赛道迁移过来。
          </DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="existing">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="existing">移动已有关键词</TabsTrigger>
            <TabsTrigger value="new">新建关键词</TabsTrigger>
          </TabsList>
          <TabsContent value="existing" className="space-y-3 pt-2">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索现有关键词"
                aria-label="搜索可关联的现有关键词"
                className="pl-9"
              />
            </div>
            <div className="max-h-72 overflow-y-auto rounded-lg border p-1">
              {candidates.map((item) => (
                <div
                  key={item.id}
                  className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm hover:bg-muted/60"
                >
                  <Checkbox
                    id={`candidate-keyword-${item.id}`}
                    checked={selected.has(item.id)}
                    onCheckedChange={(checked) =>
                      setSelected((current) => {
                        const next = new Map(current)
                        if (checked === true) next.set(item.id, item.keyword)
                        else next.delete(item.id)
                        return next
                      })
                    }
                    aria-label={`选择关键词 ${item.keyword}`}
                  />
                  <Label
                    htmlFor={`candidate-keyword-${item.id}`}
                    className="min-w-0 flex-1 cursor-pointer truncate font-medium"
                  >
                    {item.keyword}
                  </Label>
                  <span className="text-xs text-muted-foreground">
                    {item.track_name}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {item.task_count} 任务 · {item.aweme_count} 作品
                  </span>
                </div>
              ))}
              {!candidates.length && (
                <p className="py-10 text-center text-sm text-muted-foreground">
                  {candidatesQuery.isLoading
                    ? "正在加载关键词库…"
                    : "没有可移动的关键词"}
                </p>
              )}
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                已选择 {selected.size} 个
              </span>
              <Button
                size="sm"
                disabled={!selected.size || mutation.isPending}
                onClick={submitExisting}
              >
                移动已选关键词
              </Button>
            </div>
          </TabsContent>
          <TabsContent value="new" className="space-y-3 pt-2">
            <div className="space-y-1">
              <Label htmlFor="new-track-keywords">新关键词</Label>
              <Textarea
                id="new-track-keywords"
                rows={8}
                value={newValues}
                onChange={(event) => setNewValues(event.target.value)}
                placeholder={
                  "一行一个，或使用逗号分隔\n例如：同城探店\n本地生活"
                }
              />
            </div>
            <div className="flex justify-end">
              <Button
                size="sm"
                disabled={
                  !parseKeywords(newValues).length || mutation.isPending
                }
                onClick={submitNew}
              >
                创建到当前赛道
              </Button>
            </div>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}

function EditKeywordDialog({
  item,
  open,
  onOpenChange,
  onSaved,
}: {
  item: DouyinKeywordPublic
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => Promise<unknown>
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [keyword, setKeyword] = useState(item.keyword)
  const [notes, setNotes] = useState(item.notes)
  const [enabled, setEnabled] = useState(item.enabled)
  const mutation = useMutation({
    mutationFn: () =>
      DouyinKeywordsService.editKeyword({
        keywordId: item.id,
        requestBody: {
          keyword: item.task_count ? undefined : keyword,
          notes,
          enabled,
        },
      }),
    onSuccess: async () => {
      showSuccessToast("关键词信息已更新")
      await onSaved()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    mutation.mutate()
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form className="space-y-4" onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>编辑关键词</DialogTitle>
            <DialogDescription>
              修改备注和启停状态不会改变该关键词的赛道归属。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1">
            <Label htmlFor="edit-track-keyword">关键词</Label>
            <Input
              id="edit-track-keyword"
              value={keyword}
              disabled={item.task_count > 0}
              onChange={(event) => setKeyword(event.target.value)}
            />
            {item.task_count > 0 && (
              <p className="text-xs text-muted-foreground">
                已关联历史任务，词面不可直接修改；可新建正确词并移除当前关联。
              </p>
            )}
          </div>
          <div className="space-y-1">
            <Label htmlFor="edit-track-keyword-notes">备注</Label>
            <Textarea
              id="edit-track-keyword-notes"
              rows={4}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Checkbox
              id="edit-global-keyword-enabled"
              checked={enabled}
              onCheckedChange={(checked) => setEnabled(checked === true)}
            />
            <Label htmlFor="edit-global-keyword-enabled">启用该关键词</Label>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              取消
            </Button>
            <Button
              type="submit"
              disabled={!keyword.trim() || mutation.isPending}
            >
              {mutation.isPending ? "保存中…" : "保存修改"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function CompactMetric({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: typeof Target
  label: string
  value: string | number
  detail?: string
}) {
  return (
    <div className="flex items-center gap-2 rounded-lg border bg-muted/20 px-2.5 py-2">
      <Icon className="size-4 shrink-0 text-primary" />
      <div className="min-w-0">
        <p className="truncate text-[11px] text-muted-foreground">{label}</p>
        <div className="flex items-baseline gap-1.5">
          <span className="font-semibold tabular-nums">{value}</span>
          {detail && (
            <span className="truncate text-[10px] text-muted-foreground">
              {detail}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value))
}

function parseKeywords(value: string) {
  return [
    ...new Set(
      value
        .split(/[\n,，;；]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ]
}

function parseCreatorTargets(value: string) {
  return [
    ...new Set(
      value
        .split(/[\n,，;；]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ]
}

function AddTrackCreatorsDialog({
  trackId,
  trackName,
  linkedCreators,
  open,
  onOpenChange,
  onAdded,
}: {
  trackId: string
  trackName: string
  linkedCreators: DouyinCreatorPublic[]
  open: boolean
  onOpenChange: (open: boolean) => void
  onAdded: () => Promise<unknown>
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [newValues, setNewValues] = useState("")
  const [search, setSearch] = useState("")
  const [selected, setSelected] = useState<Map<string, string>>(new Map())
  const candidatesQuery = useQuery({
    queryKey: ["douyin-track-creator-candidates", search],
    queryFn: () =>
      DouyinCreatorsService.listCreators({
        search: search.trim() || undefined,
        enabled: true,
        sortBy: "task_count",
        sortOrder: "desc",
        limit: 100,
      }),
    enabled: open,
    placeholderData: (previous) => previous,
  })
  const linkedIds = new Set(linkedCreators.map((item) => item.id))
  const candidates = (candidatesQuery.data?.data ?? []).filter(
    (item) => !linkedIds.has(item.id),
  )
  const mutation = useMutation({
    mutationFn: (creators: string[]) =>
      DouyinTracksService.appendTrackCreators({
        trackId,
        requestBody: { creators },
      }),
    onSuccess: async () => {
      setNewValues("")
      setSearch("")
      setSelected(new Map())
      onOpenChange(false)
      showSuccessToast("达人已归入当前赛道")
      await onAdded()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const submitNew = () => {
    const values = parseCreatorTargets(newValues)
    if (!values.length) return showErrorToast("请填写至少一个达人")
    mutation.mutate(values)
  }
  const submitExisting = () => {
    const values = [...selected.values()]
    if (!values.length) return showErrorToast("请至少选择一个达人")
    if (
      window.confirm(
        `确认将已选的 ${values.length} 位达人移动到“${trackName}”？后续任务和内容筛选会使用新的赛道归属。`,
      )
    )
      mutation.mutate(values)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>添加或移动赛道达人</DialogTitle>
          <DialogDescription>
            新达人会直接归入当前赛道；已有达人会从原赛道迁移过来。支持粘贴主页链接或
            sec_user_id。
          </DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="existing">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="existing">移动已有达人</TabsTrigger>
            <TabsTrigger value="new">新建达人</TabsTrigger>
          </TabsList>
          <TabsContent value="existing" className="space-y-3 pt-2">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索已有达人"
                aria-label="搜索可关联的已有达人"
                className="pl-9"
              />
            </div>
            <div className="max-h-72 overflow-y-auto rounded-lg border p-1">
              {candidates.map((item) => (
                <div
                  key={item.id}
                  className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm hover:bg-muted/60"
                >
                  <Checkbox
                    id={`candidate-creator-${item.id}`}
                    checked={selected.has(item.id)}
                    onCheckedChange={(checked) =>
                      setSelected((current) => {
                        const next = new Map(current)
                        if (checked === true) next.set(item.id, item.sec_uid)
                        else next.delete(item.id)
                        return next
                      })
                    }
                    aria-label={`选择达人 ${item.nickname || item.sec_uid}`}
                  />
                  <Label
                    htmlFor={`candidate-creator-${item.id}`}
                    className="min-w-0 flex-1 cursor-pointer truncate font-medium"
                  >
                    {item.nickname || "未命名达人"}
                  </Label>
                  <span className="truncate text-xs text-muted-foreground">
                    {item.sec_uid.slice(-12)}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {item.track_name}
                  </span>
                  <span className="whitespace-nowrap text-xs text-muted-foreground">
                    {item.task_count} 任务 · {item.aweme_count} 作品
                  </span>
                </div>
              ))}
              {!candidates.length && (
                <p className="py-10 text-center text-sm text-muted-foreground">
                  {candidatesQuery.isLoading
                    ? "正在加载达人库…"
                    : "没有可移动的达人"}
                </p>
              )}
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                已选择 {selected.size} 位
              </span>
              <Button
                size="sm"
                disabled={!selected.size || mutation.isPending}
                onClick={submitExisting}
              >
                移动已选达人
              </Button>
            </div>
          </TabsContent>
          <TabsContent value="new" className="space-y-3 pt-2">
            <div className="space-y-1">
              <Label htmlFor="new-track-creators">新达人</Label>
              <Textarea
                id="new-track-creators"
                rows={8}
                value={newValues}
                onChange={(event) => setNewValues(event.target.value)}
                placeholder={
                  "一行一个，或使用逗号分隔，粘贴主页链接或 sec_user_id\n例如：https://www.douyin.com/user/MS4wLjABAAAA…\nMS4wLjABAAAAa2jK7…"
                }
              />
            </div>
            <div className="flex justify-end">
              <Button
                size="sm"
                disabled={
                  !parseCreatorTargets(newValues).length || mutation.isPending
                }
                onClick={submitNew}
              >
                创建到当前赛道
              </Button>
            </div>
          </TabsContent>
        </Tabs>
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
  onSaved: () => Promise<unknown>
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [nickname, setNickname] = useState(item.nickname)
  const [notes, setNotes] = useState(item.notes)
  const [enabled, setEnabled] = useState(item.enabled)
  const mutation = useMutation({
    mutationFn: () =>
      DouyinCreatorsService.editCreator({
        creatorId: item.id,
        requestBody: { nickname, notes, enabled },
      }),
    onSuccess: async () => {
      showSuccessToast("达人信息已更新")
      await onSaved()
    },
    onError: (error) => handleError.call(showErrorToast, error as ApiError),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    mutation.mutate()
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form className="space-y-4" onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>编辑达人</DialogTitle>
            <DialogDescription>
              修改昵称、备注和启停状态不会改变该达人的赛道归属。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1">
            <Label htmlFor="edit-track-creator-nickname">昵称</Label>
            <Input
              id="edit-track-creator-nickname"
              value={nickname}
              onChange={(event) => setNickname(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="edit-track-creator-notes">备注</Label>
            <Textarea
              id="edit-track-creator-notes"
              rows={4}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Checkbox
              id="edit-track-creator-enabled"
              checked={enabled}
              onCheckedChange={(checked) => setEnabled(checked === true)}
            />
            <Label htmlFor="edit-track-creator-enabled">启用该达人</Label>
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
              {mutation.isPending ? "保存中…" : "保存修改"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
