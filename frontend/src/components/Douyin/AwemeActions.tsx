import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { MessageCircle, RefreshCw, UserRoundSearch } from "lucide-react"
import { useState } from "react"

import {
  type DouyinAwemePublic,
  type DouyinBrowserMode,
  DouyinService,
} from "@/client"
import { InteractionComposerDialog } from "@/components/Douyin/InteractionComposerDialog"
import { Button } from "@/components/ui/button"
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

const commentPageSize = 10
type FollowupMode = "comments" | "creator"
type BrowserChoice = DouyinBrowserMode | "default"

export function AwemeActions({
  taskId,
  aweme,
  active,
}: {
  taskId: string
  aweme: DouyinAwemePublic
  active: boolean
}) {
  const [commentsOpen, setCommentsOpen] = useState(false)
  const [commentPage, setCommentPage] = useState(0)
  const [followupMode, setFollowupMode] = useState<FollowupMode | null>(null)
  const [browserMode, setBrowserMode] = useState<BrowserChoice>("default")
  const [cookies, setCookies] = useState("")
  const [maxComments, setMaxComments] = useState(10)
  const [includeSubComments, setIncludeSubComments] = useState(false)
  const [maxAwemes, setMaxAwemes] = useState(20)
  const [fetchCreatorComments, setFetchCreatorComments] = useState(false)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { showErrorToast, showSuccessToast } = useCustomToast()

  const comments = useQuery({
    queryKey: ["douyin-aweme-comments", taskId, aweme.aweme_id, commentPage],
    queryFn: () =>
      DouyinService.listComments({
        taskId,
        awemeId: aweme.aweme_id,
        skip: commentPage * commentPageSize,
        limit: commentPageSize,
      }),
    enabled: commentsOpen,
    placeholderData: (previous) => previous,
    refetchInterval: commentsOpen && active ? 3_000 : false,
  })

  const followup = useMutation({
    mutationFn: async () => {
      const common = {
        browser_mode: browserMode === "default" ? undefined : browserMode,
        cookies: cookies.trim() || undefined,
      }
      if (followupMode === "comments") {
        return DouyinService.recrawlAwemeComments({
          taskId,
          awemeId: aweme.aweme_id,
          requestBody: {
            ...common,
            max_comments_per_aweme: maxComments,
            fetch_sub_comments: includeSubComments,
          },
        })
      }
      return DouyinService.crawlAwemeCreator({
        taskId,
        awemeId: aweme.aweme_id,
        requestBody: {
          ...common,
          max_awemes: maxAwemes,
          fetch_comments: fetchCreatorComments,
          fetch_sub_comments: fetchCreatorComments && includeSubComments,
          max_comments_per_aweme: maxComments,
        },
      })
    },
    onSuccess: async (task) => {
      const label = followupMode === "comments" ? "评论重爬" : "作者作品抓取"
      showSuccessToast(`${label}任务已创建`)
      setFollowupMode(null)
      setCookies("")
      await queryClient.invalidateQueries({ queryKey: ["douyin-tasks"] })
      await navigate({
        to: "/douyin/$taskId",
        params: { taskId: task.id },
      })
    },
    onError: handleError.bind(showErrorToast),
  })

  const openComments = () => {
    setCommentPage(0)
    setCommentsOpen(true)
  }

  const openFollowup = (mode: FollowupMode) => {
    setBrowserMode("default")
    setCookies("")
    setMaxComments(10)
    setIncludeSubComments(false)
    setMaxAwemes(20)
    setFetchCreatorComments(false)
    setFollowupMode(mode)
  }

  const commentCount = comments.data?.count ?? 0
  const commentPages = Math.max(1, Math.ceil(commentCount / commentPageSize))

  return (
    <>
      <div className="flex flex-wrap justify-end gap-1">
        <Button size="sm" variant="outline" onClick={openComments}>
          <MessageCircle />
          查看评论
        </Button>
        <InteractionComposerDialog
          taskId={taskId}
          aweme={aweme}
          interactionType="video_comment"
        />
        <InteractionComposerDialog
          taskId={taskId}
          aweme={aweme}
          interactionType="creator_message"
        />
        <Button
          size="sm"
          variant="outline"
          onClick={() => openFollowup("comments")}
        >
          <RefreshCw />
          重爬评论
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => openFollowup("creator")}
        >
          <UserRoundSearch />
          作者作品
        </Button>
      </div>

      <Dialog open={commentsOpen} onOpenChange={setCommentsOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle>视频对应评论</DialogTitle>
            <DialogDescription>
              {aweme.title || aweme.aweme_id} · 已保存 {commentCount} 条评论
            </DialogDescription>
          </DialogHeader>
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>评论内容</TableHead>
                  <TableHead>用户</TableHead>
                  <TableHead>点赞</TableHead>
                  <TableHead>回复</TableHead>
                  <TableHead>发布时间</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {comments.data?.data.length ? (
                  comments.data.data.map((comment) => (
                    <TableRow key={comment.id}>
                      <TableCell className="max-w-md whitespace-normal">
                        {comment.content || "-"}
                      </TableCell>
                      <TableCell>{comment.nickname || "匿名"}</TableCell>
                      <TableCell>{comment.like_count}</TableCell>
                      <TableCell>{comment.sub_comment_count}</TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {formatUnixDate(comment.create_time)}
                      </TableCell>
                      <TableCell className="text-right">
                        <InteractionComposerDialog
                          taskId={taskId}
                          aweme={aweme}
                          interactionType="comment_reply"
                          targetComment={comment}
                          compact
                        />
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell
                      colSpan={6}
                      className="h-28 text-center text-muted-foreground"
                    >
                      {comments.isLoading ? "加载中…" : "该视频暂无已保存评论"}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          {commentCount > commentPageSize && (
            <DialogFooter className="items-center sm:justify-between">
              <span className="text-sm text-muted-foreground">
                第 {commentPage + 1} / {commentPages} 页
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={commentPage === 0}
                  onClick={() => setCommentPage((page) => page - 1)}
                >
                  上一页
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={commentPage + 1 >= commentPages}
                  onClick={() => setCommentPage((page) => page + 1)}
                >
                  下一页
                </Button>
              </div>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={followupMode !== null}
        onOpenChange={(open) => !open && setFollowupMode(null)}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {followupMode === "comments"
                ? "重新爬取视频评论"
                : "抓取作者作品"}
            </DialogTitle>
            <DialogDescription>
              将创建独立任务并保留当前任务结果。创建成功后自动进入新任务详情页。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-5 py-2">
            <div className="space-y-2">
              <Label>CDP 浏览器</Label>
              <Select
                value={browserMode}
                onValueChange={(value) =>
                  setBrowserMode(value as BrowserChoice)
                }
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="default">跟随服务配置</SelectItem>
                  <SelectItem value="local">本机 Chrome</SelectItem>
                  <SelectItem value="remote">Docker 远程 Chrome</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {followupMode === "creator" && (
              <NumberField
                id={`creator-aweme-limit-${aweme.id}`}
                label="最大作者作品数"
                value={maxAwemes}
                min={1}
                max={1000}
                onChange={setMaxAwemes}
              />
            )}

            {followupMode === "creator" && (
              <CheckField
                id={`creator-comments-${aweme.id}`}
                checked={fetchCreatorComments}
                label="同时抓取每个作品的评论"
                onChange={(checked) => {
                  setFetchCreatorComments(checked)
                  if (!checked) setIncludeSubComments(false)
                }}
              />
            )}

            {(followupMode === "comments" || fetchCreatorComments) && (
              <>
                <NumberField
                  id={`comment-limit-${aweme.id}`}
                  label="每个视频最大评论数"
                  value={maxComments}
                  min={1}
                  max={1000}
                  onChange={setMaxComments}
                />
                <CheckField
                  id={`sub-comments-${aweme.id}`}
                  checked={includeSubComments}
                  label="抓取子评论"
                  onChange={setIncludeSubComments}
                />
              </>
            )}

            <div className="space-y-2">
              <Label htmlFor={`followup-cookie-${aweme.id}`}>
                Cookie（可选）
              </Label>
              <Textarea
                id={`followup-cookie-${aweme.id}`}
                value={cookies}
                autoComplete="off"
                placeholder="留空时使用 CDP 浏览器登录状态；也可提供一次性 Cookie"
                onChange={(event) => setCookies(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Cookie 只在新任务内存中使用，不写入数据库或响应。
              </p>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setFollowupMode(null)}>
              取消
            </Button>
            <Button
              disabled={followup.isPending}
              onClick={() => followup.mutate()}
            >
              {followup.isPending ? "创建中…" : "创建并进入任务"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function NumberField({
  id,
  label,
  value,
  min,
  max,
  onChange,
}: {
  id: string
  label: string
  value: number
  min: number
  max: number
  onChange: (value: number) => void
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(event) =>
          onChange(
            Math.min(max, Math.max(min, Number(event.target.value) || min)),
          )
        }
      />
    </div>
  )
}

function CheckField({
  id,
  checked,
  label,
  onChange,
}: {
  id: string
  checked: boolean
  label: string
  onChange: (checked: boolean) => void
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border p-3">
      <Checkbox
        id={id}
        checked={checked}
        onCheckedChange={(value) => onChange(value === true)}
      />
      <Label htmlFor={id}>{label}</Label>
    </div>
  )
}

function formatUnixDate(value: number | null) {
  return value
    ? new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "short",
        timeStyle: "medium",
      }).format(new Date(value * 1_000))
    : "-"
}
