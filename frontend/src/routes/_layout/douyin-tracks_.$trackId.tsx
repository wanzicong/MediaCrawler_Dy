import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ArrowLeft,
  FileText,
  Film,
  MessageCircle,
  Pencil,
  Plus,
  Search,
  Target,
  Trash2,
} from "lucide-react"
import { type FormEvent, useEffect, useRef, useState } from "react"

import {
  ApiError,
  type DouyinKeywordPublic,
  type DouyinKeywordStatus,
  DouyinKeywordsService,
  type DouyinTrackDetailPublic,
  DouyinTracksService,
} from "@/client"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { TaskStatusBadge } from "@/components/Douyin/TaskStatusBadge"
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

function DouyinTrackDetailPage() {
  const { trackId } = Route.useParams()
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [search, setSearch] = useState("")
  const [addOpen, setAddOpen] = useState(false)
  const [editingKeyword, setEditingKeyword] =
    useState<DouyinKeywordPublic | null>(null)
  const [removingKeyword, setRemovingKeyword] =
    useState<DouyinKeywordPublic | null>(null)

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
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["douyin-track", trackId] }),
      queryClient.invalidateQueries({
        queryKey: ["douyin-track-keywords", trackId],
      }),
      queryClient.invalidateQueries({ queryKey: ["douyin-tracks"] }),
      queryClient.invalidateQueries({ queryKey: ["douyin-keywords"] }),
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
  const term = search.trim().toLocaleLowerCase("zh-CN")
  const visibleKeywords = term
    ? keywords.filter(
        (item) =>
          item.keyword.toLocaleLowerCase("zh-CN").includes(term) ||
          item.notes.toLocaleLowerCase("zh-CN").includes(term),
      )
    : keywords

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
            <Button size="sm" asChild>
              <Link to="/douyin-tracks" search={{ run: track.id }}>
                启动赛道采集
              </Link>
            </Button>
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

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.65fr)_minmax(320px,0.75fr)]">
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
                            variant={keyword.enabled ? "outline" : "secondary"}
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

        <TrackEditor key={track.id} track={track} onSaved={refresh} />
      </div>

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
    </div>
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
