import { useMutation } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  Film,
  LoaderCircle,
  Pencil,
  Play,
  Trash2,
  UserRoundSearch,
} from "lucide-react"
import { type FormEvent, useEffect, useState } from "react"
import {
  type ApiError,
  type DouyinCreatorPublic,
  type DouyinCreatorStatus,
  DouyinCreatorsService,
} from "@/client"
import { confirmDialog } from "@/components/Common/confirm-dialog"
import { TimeAgo } from "@/components/Common/TimeAgo"
import type { ListViewMode } from "@/components/Common/ViewModeToggle"
import { CreateTaskDialog } from "@/components/Douyin/CreateTaskDialog"
import { CreatorAvatar } from "@/components/Douyin/CreatorAvatar"
import { creatorNameLabel } from "@/components/Douyin/presentation"
import { TrackSelect } from "@/components/Douyin/TrackSelect"
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
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import { cn } from "@/lib/utils"
import { handleError } from "@/utils"

/** 达人状态文案：达人列表与「我的关注」共用同一套口径 */
export const statusLabels: Record<DouyinCreatorStatus, string> = {
  unprocessed: "未爬取",
  active: "进行中",
  crawled: "已爬取",
  failed: "需要重试",
}

// 卡片视图的响应式网格。虚拟滚动按「一行 N 个」切块，N 必须与这里的断点一致，
// 否则窄屏会多出空列、宽屏会白占一行。
export const creatorCardGridClass =
  "grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"

// 与上面的 Tailwind 断点一一对应（sm 640 / xl 1280 / 2xl 1536）
const creatorGridBreakpoints = [
  { query: "(min-width: 1536px)", columns: 4 },
  { query: "(min-width: 1280px)", columns: 3 },
  { query: "(min-width: 640px)", columns: 2 },
] as const

/** 当前视口下卡片网格的列数，供虚拟滚动决定每行放几位达人 */
export function useCreatorGridColumns() {
  const [columns, setColumns] = useState(1)
  useEffect(() => {
    const lists = creatorGridBreakpoints.map((item) =>
      window.matchMedia(item.query),
    )
    const update = () =>
      setColumns(
        creatorGridBreakpoints.find((_, index) => lists[index].matches)
          ?.columns ?? 1,
      )
    update()
    for (const list of lists) list.addEventListener("change", update)
    return () => {
      for (const list of lists) list.removeEventListener("change", update)
    }
  }, [])
  return columns
}

/**
 * 达人卡片：达人列表与「我的关注」共用同一份渲染。
 *
 * 两处的展示、按钮与交互完全一致（编辑 / 详情 / 启用停用 / 采集作品 / 作品 /
 * 删除），差异只通过 props 传入（关注的额外信息用 ``extra`` 追加一行）。
 */
export function CreatorCard({
  creator,
  viewMode,
  highlighted,
  selected,
  onToggleSelect,
  onToggle,
  onRemove,
  onSaved,
  extra,
}: {
  creator: DouyinCreatorPublic
  viewMode: ListViewMode
  highlighted: boolean
  selected: boolean
  onToggleSelect: (checked: boolean) => void
  onToggle: (item: DouyinCreatorPublic) => void
  onRemove: (id: string) => void
  onSaved: () => Promise<void>
  /** 列表专属的补充信息（如关注列表的互关状态与采集时间） */
  extra?: React.ReactNode
}) {
  const [editing, setEditing] = useState(false)
  // 「采集作品」：打开统一的创建任务对话框（作者已预选）
  const [taskOpen, setTaskOpen] = useState(false)
  return (
    <Card
      className={cn(
        viewMode === "table"
          ? "rounded-none border-0 border-b shadow-none last:border-b-0"
          : "transition hover:shadow-md",
        // 报告 A6：状态 / 最近爬取时间变化的达人卡片闪一下
        highlighted && "row-highlight",
      )}
    >
      <CardContent
        className={
          viewMode === "cards" ? "p-4" : "flex flex-wrap items-center gap-3 p-3"
        }
      >
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <Checkbox
            checked={selected}
            disabled={creator.is_placeholder}
            aria-label={`选择达人 ${creatorNameLabel(creator)}`}
            className="mt-2"
            onCheckedChange={(checked) => onToggleSelect(checked === true)}
          />
          <CreatorAvatar
            name={creator.nickname}
            seed={creator.creator_hash}
            src={creator.avatar_url || undefined}
            className="size-12"
            initialClassName="text-base"
          />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p
                className="truncate font-medium"
                title={creatorNameLabel(creator)}
              >
                {creatorNameLabel(creator)}
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
            {creator.is_placeholder && (
              <p className="mt-0.5 truncate text-xs text-muted-foreground">
                脱敏身份 · 补全主页链接后可创建任务
              </p>
            )}
            <p className="mt-1 text-xs text-muted-foreground">
              {creator.task_count} 个任务 · {creator.aweme_count} 个作品
              {/* 报告 A16：时间点用相对时间展示，与「最近爬取」排序项对应 */}
              {" · 最近爬取 "}
              <TimeAgo value={creator.last_crawled_at} neverText="从未" />
            </p>
            {/* 主页基础信息：由「刷新达人信息」同步回填 */}
            <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
              {creator.profile_synced_at ? (
                <>
                  <span>粉丝 {compactCount(creator.follower_count)}</span>
                  <span>获赞 {compactCount(creator.total_favorited)}</span>
                  <span>
                    主页作品 {compactCount(creator.aweme_total_count)}
                  </span>
                  {creator.unique_id && <span>抖音号 {creator.unique_id}</span>}
                  {creator.ip_location && <span>{creator.ip_location}</span>}
                  <span>
                    更新于 <TimeAgo value={creator.profile_synced_at} />
                  </span>
                </>
              ) : (
                <span className="text-amber-600">
                  {creator.profile_error
                    ? `主页信息同步失败：${creator.profile_error}`
                    : "主页信息未同步（点上方「刷新达人信息」补全）"}
                </span>
              )}
            </p>
            {creator.signature && (
              <p className="mt-1 line-clamp-2 text-[10px] text-muted-foreground">
                {creator.signature}
              </p>
            )}
            {creator.notes && (
              <p className="mt-1 line-clamp-2 text-[10px] text-muted-foreground">
                {creator.notes}
              </p>
            )}
            {extra}
          </div>
        </div>
        <div
          className={`flex flex-wrap justify-end gap-1 ${
            viewMode === "cards" ? "mt-3" : "ml-auto"
          }`}
        >
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2"
            aria-label={`编辑达人 ${creatorNameLabel(creator)}`}
            onClick={() => setEditing(true)}
          >
            <Pencil /> {creator.is_placeholder ? "补全" : "编辑"}
          </Button>
          <Button size="sm" variant="outline" asChild>
            <Link
              to="/douyin-creators/$creatorId"
              params={{ creatorId: creator.id }}
              aria-label={`查看达人详情 ${creatorNameLabel(creator)}`}
            >
              <UserRoundSearch />
              详情
            </Link>
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2"
            onClick={() => onToggle(creator)}
          >
            {creator.enabled ? "停用" : "启用"}
          </Button>
          {/* 采集这位达人的作品：打开与任务中心完全一致的任务设置对话框 */}
          <Button
            size="sm"
            variant="outline"
            aria-label={`创建达人采集任务 ${creatorNameLabel(creator)}`}
            onClick={() => setTaskOpen(true)}
          >
            <Play /> 采集作品
          </Button>
          <Button size="sm" variant="outline" asChild>
            <Link
              to="/douyin-library"
              search={{
                track: undefined,
                source: undefined,
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
            aria-label={`删除达人 ${creatorNameLabel(creator)}`}
            onClick={async () => {
              // 报告 O15：改用统一确认框
              const ok = await confirmDialog({
                title: `删除达人“${creatorNameLabel(creator)}”？`,
                description: "历史任务和作品不会被删除。",
                confirmText: "删除",
                variant: "destructive",
              })
              if (!ok) return
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
      {taskOpen && (
        <CreateTaskDialog
          open={taskOpen}
          onOpenChange={setTaskOpen}
          initialTrackId={creator.track_id}
          initialCrawlType="creator"
          initialCreators={[creator]}
        />
      )}
    </Card>
  )
}

export function CreatorStatusBadge({
  status,
}: {
  status: DouyinCreatorStatus
}) {
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

/** 达人编辑 / 补全对话框：达人列表与「我的关注」共用 */
export function EditCreatorDialog({
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
      return showErrorToast("请填写该达人的主页链接或平台达人标识完成补全")
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
                补全主页链接或平台达人标识
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
              ariaLabel={`选择“${creatorNameLabel(item)}”的所属赛道`}
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

/** 主页指标压缩展示：1.2万 / 358万 之类，避免长数字撑开行 */
function compactCount(value: number): string {
  if (!value) return "0"
  if (value < 10000) return String(value)
  if (value < 100000000) {
    return `${(value / 10000).toFixed(1).replace(/\.0$/, "")}万`
  }
  return `${(value / 100000000).toFixed(1).replace(/\.0$/, "")}亿`
}
