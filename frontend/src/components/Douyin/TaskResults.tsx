import { useQuery } from "@tanstack/react-query"
import type { LucideIcon } from "lucide-react"
import {
  ExternalLink,
  Film,
  Heart,
  MessageSquare,
  RefreshCw,
} from "lucide-react"
import { memo, useState } from "react"

import { type DouyinAwemePublic, DouyinService } from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import { Pager } from "@/components/Common/Pager"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import { AwemeActions } from "@/components/Douyin/AwemeActions"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { formatDateTime, formatUnix } from "@/lib/time"

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
        {awemes.isError ? (
          // 请求失败时给出可操作的重试入口，而不是停在一张空表格上
          <QueryErrorState
            title="作品列表加载失败"
            description="无法读取该任务抓取到的作品，请检查网络后重试。"
            onRetry={() => awemes.refetch()}
            retrying={awemes.isFetching}
          />
        ) : (
          <>
            <div className="overflow-x-auto rounded-lg border">
              {/* 列较多：给表格一个最小宽度，窄屏下横向滚动而不是把列压扁 */}
              <Table className="min-w-[840px]">
                <TableHeader>
                  <TableRow>
                    <TableHead>作品</TableHead>
                    <TableHead>作者</TableHead>
                    <TableHead>点赞</TableHead>
                    <TableHead>收藏</TableHead>
                    <TableHead>评论</TableHead>
                    <TableHead>抓取时间</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {awemes.data?.data.length ? (
                    awemes.data.data.map((aweme) => (
                      <AwemeRow
                        key={aweme.id}
                        taskId={taskId}
                        aweme={aweme}
                        active={active}
                      />
                    ))
                  ) : awemes.isLoading ? (
                    <SkeletonRows columns={7} media />
                  ) : (
                    <EmptyResults
                      columns={7}
                      icon={Film}
                      subject="作品"
                      active={active}
                      refreshing={awemes.isFetching}
                      page={awemePage}
                      onRefresh={() => void awemes.refetch()}
                      onResetPage={() => setAwemePage(0)}
                    />
                  )}
                </TableBody>
              </Table>
            </div>
            <Pager
              page={awemePage}
              pageSize={pageSize}
              total={awemes.data?.count ?? 0}
              onPageChange={setAwemePage}
              alwaysShow={false}
              className="mt-4"
            />
          </>
        )}
      </TabsContent>

      <TabsContent value="comments" className="mt-4">
        {comments.isError ? (
          // 请求失败时给出可操作的重试入口，而不是停在一张空表格上
          <QueryErrorState
            title="评论列表加载失败"
            description="无法读取该任务抓取到的评论，请检查网络后重试。"
            onRetry={() => comments.refetch()}
            retrying={comments.isFetching}
          />
        ) : (
          <>
            <div className="overflow-x-auto rounded-lg border">
              {/* 列较多：给表格一个最小宽度，窄屏下横向滚动而不是把列压扁 */}
              <Table className="min-w-[720px]">
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
                          <p className="line-clamp-3">
                            {comment.content || "-"}
                          </p>
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
                          {formatUnix(comment.create_time)}
                        </TableCell>
                      </TableRow>
                    ))
                  ) : comments.isLoading ? (
                    <SkeletonRows columns={6} />
                  ) : (
                    <EmptyResults
                      columns={6}
                      icon={MessageSquare}
                      subject="评论"
                      active={active}
                      refreshing={comments.isFetching}
                      page={commentPage}
                      onRefresh={() => void comments.refetch()}
                      onResetPage={() => setCommentPage(0)}
                    />
                  )}
                </TableBody>
              </Table>
            </div>
            <Pager
              page={commentPage}
              pageSize={pageSize}
              total={comments.data?.count ?? 0}
              onPageChange={setCommentPage}
              alwaysShow={false}
              className="mt-4"
            />
          </>
        )}
      </TabsContent>

      <TabsContent value="actions" className="mt-4">
        {actions.isError ? (
          // 请求失败时给出可操作的重试入口，而不是停在一张空表格上
          <QueryErrorState
            title="点赞/收藏记录加载失败"
            description="无法读取该任务抓取到的互动记录，请检查网络后重试。"
            onRetry={() => actions.refetch()}
            retrying={actions.isFetching}
          />
        ) : (
          <>
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
                          {formatDateTime(action.observed_at)}
                        </TableCell>
                      </TableRow>
                    ))
                  ) : actions.isLoading ? (
                    <SkeletonRows columns={4} />
                  ) : (
                    <EmptyResults
                      columns={4}
                      icon={Heart}
                      subject="互动记录"
                      active={active}
                      refreshing={actions.isFetching}
                      page={actionPage}
                      onRefresh={() => void actions.refetch()}
                      onResetPage={() => setActionPage(0)}
                    />
                  )}
                </TableBody>
              </Table>
            </div>
            <Pager
              page={actionPage}
              pageSize={pageSize}
              total={actions.data?.count ?? 0}
              onPageChange={setActionPage}
              alwaysShow={false}
              className="mt-4"
            />
          </>
        )}
      </TabsContent>
    </Tabs>
  )
}

// 作品行抽成独立组件并 memo：三个 tab 共用同一个父组件，
// 切换页码 / 切换 tab 会触发父组件整体重渲染，未变化的行不必跟着重建。
const AwemeRow = memo(function AwemeRow({
  taskId,
  aweme,
  active,
}: {
  taskId: string
  aweme: DouyinAwemePublic
  active: boolean
}) {
  return (
    <TableRow>
      <TableCell className="max-w-96">
        <div className="flex min-w-64 items-center gap-3">
          {aweme.cover_url ? (
            <img
              src={aweme.cover_url}
              alt=""
              loading="lazy"
              className="h-16 w-12 shrink-0 rounded object-cover"
            />
          ) : (
            <div className="h-16 w-12 shrink-0 rounded bg-muted" />
          )}
          <div className="min-w-0">
            <p className="line-clamp-2 font-medium">
              {aweme.title || aweme.aweme_id}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {aweme.aweme_id}
            </p>
          </div>
        </div>
      </TableCell>
      <TableCell>{aweme.nickname || "匿名"}</TableCell>
      <TableCell>{aweme.liked_count}</TableCell>
      <TableCell>{aweme.collected_count}</TableCell>
      <TableCell>{aweme.comment_count}</TableCell>
      <TableCell className="whitespace-nowrap text-muted-foreground">
        {formatDateTime(aweme.fetched_at)}
      </TableCell>
      <TableCell className="text-right">
        <div className="flex min-w-max justify-end gap-1">
          <AwemeActions taskId={taskId} aweme={aweme} active={active} />
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
        </div>
      </TableCell>
    </TableRow>
  )
})

/**
 * 结果表加载态（O8）。
 *
 * 原来是单元格里一句「加载中…」，数据到达后整张表高度骤变。
 * 改成占位行撑住表格结构，并把「正在加载」留给屏幕阅读器。
 */
function SkeletonRows({
  columns,
  rows = 6,
  media = false,
}: {
  columns: number
  rows?: number
  /** 作品行第一格带封面缩略图，骨架也要撑到接近真实行高 */
  media?: boolean
}) {
  return (
    <>
      {Array.from({ length: rows }, (_, rowIndex) => (
        <TableRow key={`skeleton-${rowIndex}`} className="hover:bg-transparent">
          {Array.from({ length: columns }, (_, cellIndex) => (
            <TableCell key={`skeleton-cell-${cellIndex}`}>
              {rowIndex === 0 && cellIndex === 0 && (
                <span className="sr-only">正在加载…</span>
              )}
              {media && cellIndex === 0 ? (
                <div className="flex min-w-64 items-center gap-3">
                  <Skeleton className="h-16 w-12 shrink-0 rounded" />
                  <div className="w-full space-y-2">
                    <Skeleton className="h-4 w-3/4" />
                    <Skeleton className="h-3 w-1/2" />
                  </div>
                </div>
              ) : (
                <Skeleton className="h-4 w-full" />
              )}
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  )
}

/**
 * 结果表空态（A4）。
 *
 * 三种情形分开引导，不让用户停在「暂无数据」上：
 * - 当前页超出数据范围 → 「回到第一页」；
 * - 任务仍在运行 → 说明会自动刷新，并给「立即刷新」；
 * - 任务已结束且无记录 → 给「重新加载」。
 *
 * 本页没有筛选条件，所以不存在「清除筛选」这一支。
 */
function EmptyResults({
  columns,
  icon,
  subject,
  active,
  refreshing,
  page,
  onRefresh,
  onResetPage,
}: {
  columns: number
  icon: LucideIcon
  /** 数据类别，用于拼文案，如「作品」「评论」 */
  subject: string
  active: boolean
  refreshing: boolean
  /** 当前页码（0 起），大于 0 说明是翻页翻空了 */
  page: number
  onRefresh: () => void
  onResetPage: () => void
}) {
  const outOfRange = page > 0
  const title = outOfRange
    ? `这一页没有${subject}记录`
    : active
      ? `${subject}还在采集`
      : `这次任务没有采集到${subject}`
  const description = outOfRange
    ? "当前页码已超出数据的实际范围，可能是任务重新统计过，回到第一页即可看到最新数据。"
    : active
      ? "任务正在运行，采集到的内容会自动出现在这里，通常无需手动操作。"
      : "任务已结束且没有留下这一类记录，可以重新加载确认，或回到任务列表检查采集配置。"

  return (
    <TableRow className="hover:bg-transparent">
      <TableCell colSpan={columns} className="p-0">
        <EmptyState
          compact
          icon={icon}
          title={title}
          description={description}
          action={
            outOfRange ? (
              <Button size="sm" variant="outline" onClick={onResetPage}>
                回到第一页
              </Button>
            ) : (
              <Button
                size="sm"
                variant="outline"
                disabled={refreshing}
                onClick={onRefresh}
              >
                <RefreshCw
                  aria-hidden="true"
                  className={refreshing ? "animate-spin" : undefined}
                />
                {refreshing ? "刷新中…" : active ? "立即刷新" : "重新加载"}
              </Button>
            )
          }
        />
      </TableCell>
    </TableRow>
  )
}
