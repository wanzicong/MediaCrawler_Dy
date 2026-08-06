import { useQuery } from "@tanstack/react-query"
import { ExternalLink } from "lucide-react"
import { useState } from "react"

import { DouyinService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

const pageSize = 20

export function TaskResults({
  taskId,
  active,
}: {
  taskId: string
  active: boolean
}) {
  const [tab, setTab] = useState("awemes")
  const [awemePage, setAwemePage] = useState(0)
  const [commentPage, setCommentPage] = useState(0)
  const [actionPage, setActionPage] = useState(0)

  const awemes = useQuery({
    queryKey: ["douyin-awemes", taskId, awemePage],
    queryFn: () =>
      DouyinService.listAwemes({
        taskId,
        skip: awemePage * pageSize,
        limit: pageSize,
      }),
    enabled: tab === "awemes",
    placeholderData: (previous) => previous,
    refetchInterval: active ? 3_000 : false,
  })
  const comments = useQuery({
    queryKey: ["douyin-comments", taskId, commentPage],
    queryFn: () =>
      DouyinService.listComments({
        taskId,
        skip: commentPage * pageSize,
        limit: pageSize,
      }),
    enabled: tab === "comments",
    placeholderData: (previous) => previous,
    refetchInterval: active ? 3_000 : false,
  })
  const actions = useQuery({
    queryKey: ["douyin-actions", taskId, actionPage],
    queryFn: () =>
      DouyinService.listActions({
        taskId,
        skip: actionPage * pageSize,
        limit: pageSize,
      }),
    enabled: tab === "actions",
    placeholderData: (previous) => previous,
    refetchInterval: active ? 3_000 : false,
  })

  return (
    <Tabs value={tab} onValueChange={setTab}>
      <TabsList className="w-full justify-start overflow-x-auto sm:w-fit">
        <TabsTrigger value="awemes">作品</TabsTrigger>
        <TabsTrigger value="comments">评论</TabsTrigger>
        <TabsTrigger value="actions">点赞/收藏</TabsTrigger>
      </TabsList>

      <TabsContent value="awemes" className="mt-4">
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>作品</TableHead>
                <TableHead>作者</TableHead>
                <TableHead>点赞</TableHead>
                <TableHead>收藏</TableHead>
                <TableHead>评论</TableHead>
                <TableHead>抓取时间</TableHead>
                <TableHead className="text-right">链接</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {awemes.data?.data.length ? (
                awemes.data.data.map((aweme) => (
                  <TableRow key={aweme.id}>
                    <TableCell className="max-w-80">
                      <p className="line-clamp-2 font-medium">
                        {aweme.title || aweme.aweme_id}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {aweme.aweme_id}
                      </p>
                    </TableCell>
                    <TableCell>{aweme.nickname || "匿名"}</TableCell>
                    <TableCell>{aweme.liked_count}</TableCell>
                    <TableCell>{aweme.collected_count}</TableCell>
                    <TableCell>{aweme.comment_count}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {formatDate(aweme.fetched_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      {aweme.aweme_url && (
                        <Button size="icon-sm" variant="ghost" asChild>
                          <a
                            href={aweme.aweme_url}
                            target="_blank"
                            rel="noreferrer"
                            aria-label="打开抖音作品"
                          >
                            <ExternalLink />
                          </a>
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <EmptyRow columns={7} loading={awemes.isLoading} />
              )}
            </TableBody>
          </Table>
        </div>
        <Pager
          page={awemePage}
          count={awemes.data?.count ?? 0}
          onChange={setAwemePage}
        />
      </TabsContent>

      <TabsContent value="comments" className="mt-4">
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>评论内容</TableHead>
                <TableHead>用户</TableHead>
                <TableHead>作品 ID</TableHead>
                <TableHead>点赞</TableHead>
                <TableHead>回复</TableHead>
                <TableHead>发布时间</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {comments.data?.data.length ? (
                comments.data.data.map((comment) => (
                  <TableRow key={comment.id}>
                    <TableCell className="max-w-md">
                      <p className="line-clamp-3">{comment.content || "-"}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {comment.comment_id}
                      </p>
                    </TableCell>
                    <TableCell>{comment.nickname || "匿名"}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {comment.aweme_id}
                    </TableCell>
                    <TableCell>{comment.like_count}</TableCell>
                    <TableCell>{comment.sub_comment_count}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {formatUnixDate(comment.create_time)}
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <EmptyRow columns={6} loading={comments.isLoading} />
              )}
            </TableBody>
          </Table>
        </div>
        <Pager
          page={commentPage}
          count={comments.data?.count ?? 0}
          onChange={setCommentPage}
        />
      </TabsContent>

      <TabsContent value="actions" className="mt-4">
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>类型</TableHead>
                <TableHead>作品 ID</TableHead>
                <TableHead>匿名账号</TableHead>
                <TableHead>记录时间</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {actions.data?.data.length ? (
                actions.data.data.map((action) => (
                  <TableRow key={action.id}>
                    <TableCell>
                      {action.action_type === "liked" ? "点赞" : "收藏"}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {action.aweme_id}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {action.account_hash}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {formatDate(action.observed_at)}
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <EmptyRow columns={4} loading={actions.isLoading} />
              )}
            </TableBody>
          </Table>
        </div>
        <Pager
          page={actionPage}
          count={actions.data?.count ?? 0}
          onChange={setActionPage}
        />
      </TabsContent>
    </Tabs>
  )
}

function EmptyRow({ columns, loading }: { columns: number; loading: boolean }) {
  return (
    <TableRow>
      <TableCell
        colSpan={columns}
        className="h-32 text-center text-muted-foreground"
      >
        {loading ? "加载中…" : "暂无数据"}
      </TableCell>
    </TableRow>
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
  const pageCount = Math.max(1, Math.ceil(count / pageSize))
  if (count <= pageSize) return null

  return (
    <div className="mt-4 flex items-center justify-end gap-3">
      <span className="text-sm text-muted-foreground">
        第 {page + 1} / {pageCount} 页，共 {count} 条
      </span>
      <Button
        variant="outline"
        size="sm"
        disabled={page === 0}
        onClick={() => onChange(page - 1)}
      >
        上一页
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={page + 1 >= pageCount}
        onClick={() => onChange(page + 1)}
      >
        下一页
      </Button>
    </div>
  )
}

function formatDate(value: string | null) {
  return value
    ? new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "short",
        timeStyle: "medium",
      }).format(new Date(value))
    : "-"
}

function formatUnixDate(value: number | null) {
  return value ? formatDate(new Date(value * 1_000).toISOString()) : "-"
}
