import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ChevronDown,
  Copy,
  Download,
  ExternalLink,
  Film,
  Heart,
  ImageIcon,
  ListFilter,
  MessageCircle,
  MessageSquareReply,
  RefreshCw,
  Search,
  SlidersHorizontal,
} from "lucide-react"
import { useState } from "react"

import {
  type CrawlTaskPublic,
  type DouyinCommentLibraryItemPublic,
  DouyinService,
  OpenAPI,
} from "@/client"
import {
  FilterPanel,
  MetricCard,
  PageHero,
} from "@/components/Common/PageShell"
import {
  usePersistentViewMode,
  ViewModeToggle,
} from "@/components/Common/ViewModeToggle"
import { CreatorAvatar } from "@/components/Douyin/CreatorAvatar"
import { InteractionComposerDialog } from "@/components/Douyin/InteractionComposerDialog"
import { allTracksValue, TrackSelect } from "@/components/Douyin/TrackSelect"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import useCustomToast from "@/hooks/useCustomToast"
import { getDouyinVideoUrl } from "@/utils"

export const Route = createFileRoute("/_layout/douyin-comments")({
  component: DouyinCommentManagement,
  head: () => ({ meta: [{ title: "评论管理 - 灵感采集台" }] }),
})

const pageSize = 50

type CommentType = "all" | "top_level" | "reply"
type PictureFilter = "all" | "yes" | "no"
type SortValue =
  | "published_at:desc"
  | "published_at:asc"
  | "like_count:desc"
  | "sub_comment_count:desc"
  | "fetched_at:desc"

type Filters = {
  trackId: string
  commentContent: string
  search: string
  taskId: string
  awemeId: string
  videoCreator: string
  sourceKeyword: string
  commentType: CommentType
  hasPictures: PictureFilter
  minLikes: string
  maxLikes: string
  publishedFrom: string
  publishedTo: string
  sort: SortValue
}

const initialFilters: Filters = {
  trackId: allTracksValue,
  commentContent: "",
  search: "",
  taskId: "all",
  awemeId: "",
  videoCreator: "",
  sourceKeyword: "",
  commentType: "all",
  hasPictures: "all",
  minLikes: "",
  maxLikes: "",
  publishedFrom: "",
  publishedTo: "",
  sort: "published_at:desc",
}

function DouyinCommentManagement() {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [draft, setDraft] = useState<Filters>(initialFilters)
  const [filters, setFilters] = useState<Filters>(initialFilters)
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [exporting, setExporting] = useState(false)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [viewMode, changeViewMode] = usePersistentViewMode(
    "douyin-comments-view",
  )
  const [sortBy, sortOrder] = filters.sort.split(":") as [
    "published_at" | "like_count" | "sub_comment_count" | "fetched_at",
    "asc" | "desc",
  ]

  const tasks = useQuery({
    queryKey: ["douyin-comment-tasks", filters.trackId],
    queryFn: () =>
      DouyinService.listTasks({
        trackId:
          filters.trackId && filters.trackId !== allTracksValue
            ? filters.trackId
            : undefined,
        limit: 100,
      }),
    staleTime: 30_000,
  })
  const comments = useQuery({
    queryKey: ["douyin-comment-library", filters, page],
    queryFn: () =>
      DouyinService.listCommentLibrary({
        trackId:
          filters.trackId && filters.trackId !== allTracksValue
            ? filters.trackId
            : undefined,
        commentContent: optional(filters.commentContent),
        search: optional(filters.search),
        taskId: filters.taskId === "all" ? undefined : filters.taskId,
        awemeId: optional(filters.awemeId),
        videoCreator: optional(filters.videoCreator),
        sourceKeyword: optional(filters.sourceKeyword),
        commentType: filters.commentType,
        hasPictures: filters.hasPictures,
        minLikes: optionalNumber(filters.minLikes),
        maxLikes: optionalNumber(filters.maxLikes),
        publishedFrom: dateTimestamp(filters.publishedFrom),
        publishedTo: dateTimestamp(filters.publishedTo, true),
        sortBy,
        sortOrder,
        skip: page * pageSize,
        limit: pageSize,
      }),
    placeholderData: (previous) => previous,
  })
  const rows = comments.data?.data ?? []
  const summary = comments.data?.summary
  const visibleIds = rows.map((item) => item.comment.id)
  const allVisibleSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selected.has(id))
  const activeFilterCount = countActiveFilters(filters)

  const applyFilters = () => {
    if (
      optionalNumber(draft.minLikes) !== undefined &&
      optionalNumber(draft.maxLikes) !== undefined &&
      Number(draft.minLikes) > Number(draft.maxLikes)
    ) {
      showErrorToast("最小点赞数不能大于最大点赞数")
      return
    }
    if (
      draft.publishedFrom &&
      draft.publishedTo &&
      draft.publishedFrom > draft.publishedTo
    ) {
      showErrorToast("评论开始日期不能晚于结束日期")
      return
    }
    setFilters(draft)
    setPage(0)
    setSelected(new Set())
  }

  const resetFilters = () => {
    const reset = { ...initialFilters, trackId: filters.trackId }
    setDraft(reset)
    setFilters(reset)
    setPage(0)
    setSelected(new Set())
  }

  const exportSelected = async () => {
    if (!selected.size) return
    setExporting(true)
    try {
      await downloadSelectedComments([...selected])
      showSuccessToast(`已导出 ${selected.size} 条评论`)
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : "评论导出失败")
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageHero
        eyebrow="评论洞察"
        icon={MessageCircle}
        title="评论管理"
        description="按赛道集中查看已采集评论，通过内容、作品、作者、关键词、评论层级、点赞与时间组合筛选，并可回复或批量导出。"
        actions={
          <Button
            variant="outline"
            onClick={() => comments.refetch()}
            disabled={comments.isFetching}
          >
            <RefreshCw className={comments.isFetching ? "animate-spin" : ""} />
            刷新数据
          </Button>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <MetricCard
            icon={ListFilter}
            label="命中评论"
            value={compact(summary?.matched_count ?? 0)}
            detail="当前筛选结果"
            tone="violet"
            compact
          />
          <MetricCard
            icon={MessageCircle}
            label="主评论"
            value={compact(summary?.top_level_count ?? 0)}
            detail="一级评论"
            tone="blue"
            compact
          />
          <MetricCard
            icon={MessageSquareReply}
            label="回复"
            value={compact(summary?.reply_count ?? 0)}
            detail="子评论"
            tone="mint"
            compact
          />
          <MetricCard
            icon={ImageIcon}
            label="带图评论"
            value={compact(summary?.picture_count ?? 0)}
            detail="包含评论图片"
            tone="coral"
            compact
          />
          <MetricCard
            icon={Heart}
            label="累计点赞"
            value={compact(summary?.total_like_count ?? 0)}
            detail="命中评论点赞总和"
            tone="rose"
            compact
          />
        </div>
      </PageHero>

      <FilterPanel className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm font-semibold">赛道范围</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              任务、视频作者和评论结果都会限制在所选赛道内。
            </p>
          </div>
          <TrackSelect
            value={filters.trackId}
            onValueChange={(value) => {
              const next = { ...draft, trackId: value, taskId: "all" }
              setDraft(next)
              setFilters({ ...filters, trackId: value, taskId: "all" })
              setPage(0)
              setSelected(new Set())
            }}
            includeAll
            allowDisabled
            className="sm:w-64"
            ariaLabel="按赛道筛选评论"
          />
        </div>
        <button
          type="button"
          className="flex w-full items-center gap-3 border-t pt-4 text-left"
          aria-expanded={filtersOpen}
          onClick={() => setFiltersOpen((current) => !current)}
        >
          <span className="flex size-9 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <SlidersHorizontal className="size-4" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-2 text-sm font-semibold">
              多维筛选
              {activeFilterCount > 0 && (
                <Badge variant="secondary">已启用 {activeFilterCount} 项</Badge>
              )}
            </span>
            <span className="mt-0.5 block truncate text-xs text-muted-foreground">
              {activeFilterCount
                ? activeFilterSummary(filters)
                : "按评论正文、任务、作者、关键词、互动和时间组合筛选"}
            </span>
          </span>
          <ChevronDown
            className={`size-4 text-muted-foreground transition-transform ${
              filtersOpen ? "rotate-180" : ""
            }`}
          />
        </button>
        {filtersOpen && (
          <>
            <div className="grid gap-4 border-t pt-4 md:grid-cols-2 xl:grid-cols-4">
              <Field label="评论内容模糊搜索" className="xl:col-span-2">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={draft.commentContent}
                    onChange={(event) =>
                      setDraft({ ...draft, commentContent: event.target.value })
                    }
                    onKeyDown={(event) =>
                      event.key === "Enter" && applyFilters()
                    }
                    placeholder="仅模糊匹配评论正文内容"
                    className="pl-9"
                  />
                </div>
              </Field>
              <Field label="全文搜索" className="xl:col-span-2">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={draft.search}
                    onChange={(event) =>
                      setDraft({ ...draft, search: event.target.value })
                    }
                    onKeyDown={(event) =>
                      event.key === "Enter" && applyFilters()
                    }
                    placeholder="评论内容、评论人、评论号、视频标题或作品号"
                    className="pl-9"
                  />
                </div>
              </Field>
              <Field label="所属任务">
                <Select
                  value={draft.taskId}
                  onValueChange={(value) =>
                    setDraft({ ...draft, taskId: value })
                  }
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部任务</SelectItem>
                    {(tasks.data?.data ?? []).map((task) => (
                      <SelectItem key={task.id} value={task.id}>
                        {taskLabel(task)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="作品号">
                <Input
                  value={draft.awemeId}
                  onChange={(event) =>
                    setDraft({ ...draft, awemeId: event.target.value })
                  }
                  placeholder="支持部分匹配"
                />
              </Field>
              <Field label="视频作者">
                <Input
                  value={draft.videoCreator}
                  onChange={(event) =>
                    setDraft({ ...draft, videoCreator: event.target.value })
                  }
                  placeholder="输入作者昵称"
                />
              </Field>
              <Field label="来源关键词">
                <Input
                  value={draft.sourceKeyword}
                  onChange={(event) =>
                    setDraft({ ...draft, sourceKeyword: event.target.value })
                  }
                  placeholder="任务命中的关键词"
                />
              </Field>
              <Field label="评论层级">
                <Select
                  value={draft.commentType}
                  onValueChange={(value) =>
                    setDraft({ ...draft, commentType: value as CommentType })
                  }
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部层级</SelectItem>
                    <SelectItem value="top_level">仅主评论</SelectItem>
                    <SelectItem value="reply">仅回复</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              <Field label="评论图片">
                <Select
                  value={draft.hasPictures}
                  onValueChange={(value) =>
                    setDraft({ ...draft, hasPictures: value as PictureFilter })
                  }
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">不限</SelectItem>
                    <SelectItem value="yes">仅带图</SelectItem>
                    <SelectItem value="no">仅无图</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              <Field label="点赞区间">
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    min={0}
                    value={draft.minLikes}
                    onChange={(event) =>
                      setDraft({ ...draft, minLikes: event.target.value })
                    }
                    placeholder="最低"
                  />
                  <span className="text-muted-foreground">—</span>
                  <Input
                    type="number"
                    min={0}
                    value={draft.maxLikes}
                    onChange={(event) =>
                      setDraft({ ...draft, maxLikes: event.target.value })
                    }
                    placeholder="最高"
                  />
                </div>
              </Field>
              <Field label="评论日期">
                <div className="flex items-center gap-2">
                  <Input
                    type="date"
                    value={draft.publishedFrom}
                    onChange={(event) =>
                      setDraft({ ...draft, publishedFrom: event.target.value })
                    }
                    aria-label="评论开始日期"
                  />
                  <span className="text-muted-foreground">—</span>
                  <Input
                    type="date"
                    value={draft.publishedTo}
                    onChange={(event) =>
                      setDraft({ ...draft, publishedTo: event.target.value })
                    }
                    aria-label="评论结束日期"
                  />
                </div>
              </Field>
              <Field label="排序方式">
                <Select
                  value={draft.sort}
                  onValueChange={(value) =>
                    setDraft({ ...draft, sort: value as SortValue })
                  }
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="published_at:desc">
                      评论时间从新到旧
                    </SelectItem>
                    <SelectItem value="published_at:asc">
                      评论时间从旧到新
                    </SelectItem>
                    <SelectItem value="like_count:desc">点赞数最多</SelectItem>
                    <SelectItem value="sub_comment_count:desc">
                      回复数最多
                    </SelectItem>
                    <SelectItem value="fetched_at:desc">最近采集</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
            </div>
            <div className="flex flex-wrap justify-end gap-2 border-t pt-4">
              <Button variant="outline" onClick={resetFilters}>
                重置条件
              </Button>
              <Button onClick={applyFilters}>
                <Search />
                查询评论
              </Button>
            </div>
          </>
        )}
      </FilterPanel>

      <Card>
        <CardContent className="p-0">
          <div className="flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-center">
            <div>
              <p className="font-medium">评论明细</p>
              <p className="text-xs text-muted-foreground">
                共 {comments.data?.count ?? 0} 条 · 已选择 {selected.size} 条
              </p>
            </div>
            <div className="flex flex-wrap gap-2 sm:ml-auto">
              <ViewModeToggle
                value={viewMode}
                onChange={changeViewMode}
                label="切换评论展示方式"
              />
              <CommentExportDialog filters={filters} />
              <Button
                size="sm"
                variant="outline"
                disabled={!selected.size || exporting}
                onClick={exportSelected}
              >
                {exporting ? "正在导出…" : `导出已选（${selected.size}）`}
              </Button>
              {selected.size > 0 && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setSelected(new Set())}
                >
                  清空选择
                </Button>
              )}
            </div>
          </div>
          {rows.length && viewMode !== "table" ? (
            <div
              className={
                viewMode === "cards"
                  ? "grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3"
                  : "space-y-2 p-4"
              }
            >
              {rows.map((item) => (
                <CommentPreviewCard
                  key={item.comment.id}
                  item={item}
                  compact={viewMode === "rows"}
                  checked={selected.has(item.comment.id)}
                  onCheckedChange={(checked) =>
                    setSelected((current) => {
                      const next = new Set(current)
                      if (checked) next.add(item.comment.id)
                      else next.delete(item.comment.id)
                      return next
                    })
                  }
                />
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table className="min-w-[1120px]">
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10">
                      <Checkbox
                        checked={allVisibleSelected}
                        aria-label="选择本页评论"
                        onCheckedChange={(checked) => {
                          setSelected((current) => {
                            const next = new Set(current)
                            for (const id of visibleIds) {
                              if (checked) next.add(id)
                              else next.delete(id)
                            }
                            return next
                          })
                        }}
                      />
                    </TableHead>
                    <TableHead className="min-w-44">视频 / 主播</TableHead>
                    <TableHead className="min-w-24">关键词</TableHead>
                    <TableHead className="min-w-48">视频标题</TableHead>
                    <TableHead className="min-w-72">评论内容</TableHead>
                    <TableHead className="min-w-32">评论人</TableHead>
                    <TableHead>互动数据</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.length ? (
                    rows.map((item) => (
                      <CommentRow
                        key={item.comment.id}
                        item={item}
                        checked={selected.has(item.comment.id)}
                        onCheckedChange={(checked) =>
                          setSelected((current) => {
                            const next = new Set(current)
                            if (checked) next.add(item.comment.id)
                            else next.delete(item.comment.id)
                            return next
                          })
                        }
                      />
                    ))
                  ) : (
                    <TableRow>
                      <TableCell
                        colSpan={8}
                        className="h-44 text-center text-muted-foreground"
                      >
                        {comments.isLoading
                          ? "正在加载评论…"
                          : "没有符合当前条件的评论"}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
          <div className="flex items-center justify-end gap-2 border-t p-4">
            <span className="mr-auto text-sm text-muted-foreground">
              第 {page + 1} 页 · 每页 {pageSize} 条
            </span>
            <Button
              variant="outline"
              disabled={page === 0}
              onClick={() => setPage((value) => value - 1)}
            >
              上一页
            </Button>
            <Button
              variant="outline"
              disabled={(page + 1) * pageSize >= (comments.data?.count ?? 0)}
              onClick={() => setPage((value) => value + 1)}
            >
              下一页
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function CommentRow({
  item,
  checked,
  onCheckedChange,
}: {
  item: DouyinCommentLibraryItemPublic
  checked: boolean
  onCheckedChange: (checked: boolean) => void
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const { comment, aweme } = item
  const isReply = !["", "0"].includes(comment.parent_comment_id)
  const copyContent = async () => {
    try {
      await navigator.clipboard.writeText(comment.content || "")
      showSuccessToast("评论内容已复制")
    } catch {
      showErrorToast("复制失败，请手动选择文本复制")
    }
  }
  return (
    <TableRow data-state={checked ? "selected" : undefined}>
      <TableCell>
        <Checkbox
          checked={checked}
          aria-label={`选择评论 ${comment.comment_id}`}
          onCheckedChange={(value) => onCheckedChange(Boolean(value))}
        />
      </TableCell>
      <TableCell className="align-top">
        <div className="flex items-center gap-2.5">
          <div className="relative aspect-video w-20 shrink-0 overflow-hidden rounded-md bg-muted">
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
          <div className="flex min-w-0 flex-col items-start gap-1">
            <CreatorAvatar
              name={aweme.nickname}
              seed={aweme.creator_hash || aweme.aweme_id}
            />
            <span
              className="max-w-20 truncate text-xs"
              title={aweme.nickname || "匿名作者"}
            >
              {aweme.nickname || "匿名作者"}
            </span>
          </div>
        </div>
      </TableCell>
      <TableCell className="align-top">
        {aweme.source_keyword ? (
          <Badge variant="secondary">{aweme.source_keyword}</Badge>
        ) : (
          <span className="text-xs text-muted-foreground">-</span>
        )}
      </TableCell>
      <TableCell className="align-top">
        <Tooltip>
          <TooltipTrigger asChild>
            <p className="line-clamp-2 cursor-default font-medium">
              {aweme.title || aweme.aweme_id}
            </p>
          </TooltipTrigger>
          <TooltipContent className="max-w-sm">
            {aweme.title || aweme.aweme_id}
          </TooltipContent>
        </Tooltip>
        <p className="mt-1 text-xs text-muted-foreground">
          发布 {formatUnix(aweme.create_time)}
        </p>
        <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
          {aweme.aweme_id}
        </p>
      </TableCell>
      <TableCell className="align-top">
        <div className="flex items-start gap-1.5">
          <Tooltip>
            <TooltipTrigger asChild>
              <p className="line-clamp-3 flex-1 cursor-default whitespace-pre-wrap break-words text-sm leading-6">
                {comment.content || "（无文本内容）"}
              </p>
            </TooltipTrigger>
            <TooltipContent className="max-w-md whitespace-pre-wrap break-words">
              {comment.content || "（无文本内容）"}
            </TooltipContent>
          </Tooltip>
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="复制评论内容"
            disabled={!comment.content}
            onClick={copyContent}
          >
            <Copy />
          </Button>
        </div>
        <p className="mt-1.5 font-mono text-[11px] text-muted-foreground">
          {comment.comment_id}
        </p>
      </TableCell>
      <TableCell className="align-top">
        <p className="truncate font-medium">{comment.nickname || "匿名用户"}</p>
        <div className="mt-1 flex flex-wrap gap-1">
          <Badge variant={isReply ? "secondary" : "outline"}>
            {isReply ? "回复" : "主评论"}
          </Badge>
          {comment.pictures && (
            <Badge variant="outline">
              <ImageIcon />
              带图
            </Badge>
          )}
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          {formatUnix(comment.create_time)}
        </p>
      </TableCell>
      <TableCell className="align-top">
        <p className="font-medium">{compact(comment.like_count)} 赞</p>
        <p className="mt-1 text-xs text-muted-foreground">
          {compact(comment.sub_comment_count)} 条回复
        </p>
      </TableCell>
      <TableCell className="align-top text-right">
        <div className="flex justify-end gap-1">
          <InteractionComposerDialog
            taskId={comment.task_id}
            aweme={aweme}
            interactionType="comment_reply"
            targetComment={comment}
            compact
          />
          <Button size="sm" variant="ghost" asChild>
            <Link to="/douyin/$taskId" params={{ taskId: comment.task_id }}>
              任务
            </Link>
          </Button>
          <Button size="sm" variant="ghost" asChild>
            <a
              href={getDouyinVideoUrl(aweme.aweme_id)}
              target="_blank"
              rel="noreferrer"
            >
              视频
              <ExternalLink />
            </a>
          </Button>
        </div>
      </TableCell>
    </TableRow>
  )
}

function CommentPreviewCard({
  item,
  checked,
  compact: compactLayout,
  onCheckedChange,
}: {
  item: DouyinCommentLibraryItemPublic
  checked: boolean
  compact: boolean
  onCheckedChange: (checked: boolean) => void
}) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const { comment, aweme } = item
  const isReply = !["", "0"].includes(comment.parent_comment_id)
  const copyContent = async () => {
    try {
      await navigator.clipboard.writeText(comment.content || "")
      showSuccessToast("评论内容已复制")
    } catch {
      showErrorToast("复制失败，请手动选择文本复制")
    }
  }
  return (
    <Card data-state={checked ? "selected" : undefined} className="gap-0 py-0">
      <CardContent
        className={
          compactLayout
            ? "flex flex-col gap-3 p-3 lg:flex-row lg:items-center"
            : "space-y-3 p-4"
        }
      >
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center">
            <Checkbox
              checked={checked}
              aria-label={`选择评论 ${comment.comment_id}`}
              onCheckedChange={(value) => onCheckedChange(Boolean(value))}
            />
          </div>
          <CreatorAvatar
            name={aweme.nickname}
            seed={aweme.creator_hash || aweme.aweme_id}
          />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">
              {aweme.title || aweme.aweme_id}
            </p>
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              {aweme.nickname || "匿名作者"} · {formatUnix(aweme.create_time)}
            </p>
          </div>
        </div>
        <div className={compactLayout ? "min-w-0 flex-[1.5]" : ""}>
          <p className="line-clamp-3 whitespace-pre-wrap break-words text-sm leading-6">
            {comment.content || "（无文本内容）"}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <Badge variant={isReply ? "secondary" : "outline"}>
              {isReply ? "回复" : "主评论"}
            </Badge>
            {aweme.source_keyword && (
              <Badge variant="secondary">{aweme.source_keyword}</Badge>
            )}
            {comment.pictures && (
              <Badge variant="outline">
                <ImageIcon /> 带图
              </Badge>
            )}
            <span>{comment.nickname || "匿名用户"}</span>
            <span>{compact(comment.like_count)} 赞</span>
            <span>{compact(comment.sub_comment_count)} 条回复</span>
            <span>{formatUnix(comment.create_time)}</span>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-1">
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="复制评论内容"
            disabled={!comment.content}
            onClick={copyContent}
          >
            <Copy />
          </Button>
          <InteractionComposerDialog
            taskId={comment.task_id}
            aweme={aweme}
            interactionType="comment_reply"
            targetComment={comment}
            compact
          />
          <Button size="sm" variant="ghost" asChild>
            <Link to="/douyin/$taskId" params={{ taskId: comment.task_id }}>
              任务
            </Link>
          </Button>
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
        </div>
      </CardContent>
    </Card>
  )
}

const commentExportFields: Array<{
  key: string
  label: string
  value: (item: DouyinCommentLibraryItemPublic) => string
}> = [
  {
    key: "content",
    label: "评论内容",
    value: (item) => item.comment.content || "",
  },
  {
    key: "nickname",
    label: "评论人",
    value: (item) => item.comment.nickname || "匿名用户",
  },
  {
    key: "level",
    label: "评论层级",
    value: (item) =>
      ["", "0"].includes(item.comment.parent_comment_id) ? "主评论" : "回复",
  },
  {
    key: "like_count",
    label: "点赞数",
    value: (item) => String(item.comment.like_count),
  },
  {
    key: "create_time",
    label: "评论时间",
    value: (item) => formatUnix(item.comment.create_time),
  },
  {
    key: "aweme_title",
    label: "视频标题",
    value: (item) => item.aweme.title || item.aweme.aweme_id,
  },
  {
    key: "aweme_nickname",
    label: "视频作者",
    value: (item) => item.aweme.nickname || "匿名作者",
  },
  {
    key: "source_keyword",
    label: "来源关键词",
    value: (item) => item.aweme.source_keyword || "",
  },
]

function CommentExportDialog({ filters }: { filters: Filters }) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [open, setOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [sortBy, sortOrder] = filters.sort.split(":") as [
    "published_at" | "like_count" | "sub_comment_count" | "fetched_at",
    "asc" | "desc",
  ]
  const exportTxt = async () => {
    setExporting(true)
    try {
      const request = {
        trackId:
          filters.trackId && filters.trackId !== allTracksValue
            ? filters.trackId
            : undefined,
        commentContent: optional(filters.commentContent),
        search: optional(filters.search),
        taskId: filters.taskId === "all" ? undefined : filters.taskId,
        awemeId: optional(filters.awemeId),
        videoCreator: optional(filters.videoCreator),
        sourceKeyword: optional(filters.sourceKeyword),
        commentType: filters.commentType,
        hasPictures: filters.hasPictures,
        minLikes: optionalNumber(filters.minLikes),
        maxLikes: optionalNumber(filters.maxLikes),
        publishedFrom: dateTimestamp(filters.publishedFrom),
        publishedTo: dateTimestamp(filters.publishedTo, true),
        sortBy,
        sortOrder,
        limit: 100 as const,
      }
      const first = await DouyinService.listCommentLibrary({
        ...request,
        skip: 0,
      })
      const total = first.count ?? 0
      if (
        total > 1000 &&
        !window.confirm(
          `当前筛选条件命中 ${total} 条评论，导出可能需要较长时间。确认继续导出全部结果？`,
        )
      ) {
        return
      }
      const items = [...(first.data ?? [])]
      while (items.length < total) {
        const page = await DouyinService.listCommentLibrary({
          ...request,
          skip: items.length,
        })
        if (!page.data?.length) break
        items.push(...page.data)
      }
      if (!items.length) {
        showErrorToast("当前筛选结果没有评论可导出")
        return
      }
      const lines = [
        `导出时间\t${new Date().toLocaleString("zh-CN")}`,
        `筛选摘要\t${activeFilterSummary(filters)}`,
        "",
        commentExportFields.map((field) => field.label).join("\t"),
        ...items.map((item) =>
          commentExportFields
            .map((field) => txtCell(field.value(item)))
            .join("\t"),
        ),
      ]
      const content = `\uFEFF${lines.join("\r\n")}\r\n`
      const url = URL.createObjectURL(
        new Blob([content], {
          type: "text/plain;charset=utf-8",
        }),
      )
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = `douyin-comments-${Date.now()}.txt`
      anchor.click()
      URL.revokeObjectURL(url)
      showSuccessToast(`已按筛选条件导出 ${items.length} 条评论`)
      setOpen(false)
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : "评论导出失败")
    } finally {
      setExporting(false)
    }
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <Download />
          导出筛选结果
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>导出筛选结果</DialogTitle>
          <DialogDescription>
            导出当前全部筛选结果为
            TXT，仅包含评论、用户、视频、关键词和时间等关键字段；超过 1000
            条时会再次确认。
          </DialogDescription>
        </DialogHeader>
        <p className="rounded-lg bg-muted/50 p-3 text-sm text-muted-foreground">
          导出字段：{commentExportFields.map((field) => field.label).join("、")}
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button onClick={exportTxt} disabled={exporting}>
            <Download />
            {exporting ? "正在导出…" : "确认导出 TXT"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function txtCell(value: string) {
  return value.replace(/[\t\r\n]+/g, " ").trim()
}

function Field({
  label,
  children,
  className,
}: {
  label: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={className}>
      <Label className="mb-2 block text-xs text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  )
}

function optional(value: string) {
  return value.trim() || undefined
}

function countActiveFilters(filters: Filters) {
  return [
    filters.commentContent,
    filters.search,
    filters.taskId !== "all" ? filters.taskId : "",
    filters.awemeId,
    filters.videoCreator,
    filters.sourceKeyword,
    filters.commentType !== "all" ? filters.commentType : "",
    filters.hasPictures !== "all" ? filters.hasPictures : "",
    filters.minLikes,
    filters.maxLikes,
    filters.publishedFrom,
    filters.publishedTo,
    filters.sort !== initialFilters.sort ? filters.sort : "",
  ].filter(Boolean).length
}

function activeFilterSummary(filters: Filters) {
  const labels = [
    filters.commentContent && `正文“${filters.commentContent}”`,
    filters.search && `全文“${filters.search}”`,
    filters.taskId !== "all" && "指定任务",
    filters.videoCreator && `作者“${filters.videoCreator}”`,
    filters.sourceKeyword && `关键词“${filters.sourceKeyword}”`,
    filters.commentType !== "all" &&
      (filters.commentType === "top_level" ? "仅主评论" : "仅回复"),
    filters.hasPictures !== "all" &&
      (filters.hasPictures === "yes" ? "仅带图" : "仅无图"),
  ].filter(Boolean)
  return labels.slice(0, 4).join(" · ") || "已应用高级筛选条件"
}

function optionalNumber(value: string) {
  if (!value.trim()) return undefined
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

function dateTimestamp(value: string, endOfDay = false) {
  if (!value) return undefined
  const suffix = endOfDay ? "T23:59:59" : "T00:00:00"
  return Math.floor(new Date(`${value}${suffix}`).getTime() / 1_000)
}

function taskLabel(task: CrawlTaskPublic) {
  const keywords = task.request.keywords
  const target =
    Array.isArray(keywords) && keywords.length
      ? keywords.join("、")
      : shortId(task.id)
  return `${target} · ${formatDate(task.created_at)}`
}

function shortId(value: string) {
  return value.slice(0, 8)
}

function formatUnix(value: number | null) {
  return value ? formatDate(new Date(value * 1_000).toISOString()) : "未知"
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value))
}

function compact(value: number) {
  return new Intl.NumberFormat("zh-CN", { notation: "compact" }).format(value)
}

async function downloadSelectedComments(commentIds: string[]) {
  const token = localStorage.getItem("access_token")
  const response = await fetch(
    `${browserApiBase()}/api/v1/douyin/comments/export`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ comment_ids: commentIds }),
    },
  )
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string
    } | null
    throw new Error(payload?.detail || `评论导出失败 (${response.status})`)
  }
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement("a")
  anchor.href = url
  const disposition = response.headers.get("Content-Disposition") || ""
  const match =
    disposition.match(/filename\*=UTF-8''([^;]+)/i) ||
    disposition.match(/filename="?([^";]+)"?/i)
  anchor.download = match
    ? decodeURIComponent(match[1])
    : "douyin-selected-comments.txt"
  anchor.click()
  URL.revokeObjectURL(url)
}

function browserApiBase() {
  if (import.meta.env.DEV) return window.location.origin
  return new URL(OpenAPI.BASE || window.location.origin, window.location.origin)
    .toString()
    .replace(/\/$/, "")
}
