import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Film, RefreshCw, Search } from "lucide-react"
import { useState } from "react"

import { DouyinTagsService } from "@/client"
import { PageHero } from "@/components/Common/PageShell"
import { allTracksValue, TrackSelect } from "@/components/Douyin/TrackSelect"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
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
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/douyin-tags")({
  component: DouyinTagManagement,
})

const pageSize = 50

function DouyinTagManagement() {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const [page, setPage] = useState(0)
  const [trackId, setTrackId] = useState(allTracksValue)
  const [search, setSearch] = useState("")
  const [sort, setSort] = useState<
    "aweme_count:desc" | "task_count:desc" | "last_seen_at:desc" | "name:asc"
  >("aweme_count:desc")
  const [sortBy, sortOrder] = sort.split(":") as [
    "aweme_count" | "task_count" | "last_seen_at" | "name",
    "asc" | "desc",
  ]
  const tagsQuery = useQuery({
    queryKey: ["douyin-tags", trackId, page, search, sort],
    queryFn: () =>
      DouyinTagsService.listTags({
        trackId: trackId === allTracksValue ? undefined : trackId,
        search: search.trim() || undefined,
        sortBy,
        sortOrder,
        skip: page * pageSize,
        limit: pageSize,
      }),
    placeholderData: (previous) => previous,
  })
  const sync = useMutation({
    mutationFn: () => DouyinTagsService.syncTags(),
    onSuccess: async (result) => {
      showSuccessToast(
        `已扫描 ${result.aweme_count} 个作品，新增 ${result.created_count} 个标签、${result.binding_count} 条关联`,
      )
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["douyin-tags"] }),
        queryClient.invalidateQueries({ queryKey: ["douyin-library-tags"] }),
        queryClient.invalidateQueries({ queryKey: ["douyin-works-tags"] }),
        queryClient.invalidateQueries({ queryKey: ["douyin-library-works"] }),
      ])
    },
    onError: handleError.bind(showErrorToast),
  })
  const rows = tagsQuery.data?.data ?? []
  return (
    <div className="page-stack">
      <PageHero
        compact
        title="标签管理"
        actions={
          <Button
            size="sm"
            onClick={() => sync.mutate()}
            disabled={sync.isPending}
          >
            <RefreshCw className={sync.isPending ? "animate-spin" : ""} />
            同步历史标签
          </Button>
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="whitespace-nowrap text-xs text-muted-foreground">
            标签{" "}
            <strong className="text-foreground">
              {tagsQuery.data?.count ?? 0}
            </strong>{" "}
            · 本页视频{" "}
            <strong className="text-foreground">
              {rows.reduce((total, item) => total + item.aweme_count, 0)}
            </strong>{" "}
            · 本页任务{" "}
            <strong className="text-foreground">
              {rows.reduce((total, item) => total + item.task_count, 0)}
            </strong>
          </span>
          <div className="relative min-w-64 flex-[2]">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value)
                setPage(0)
              }}
              placeholder="搜索标签"
              className="h-9 pl-9"
            />
          </div>
          <TrackSelect
            value={trackId}
            onValueChange={(value) => {
              setTrackId(value)
              setPage(0)
            }}
            includeAll
            allowDisabled
            autoSelectDefault={false}
            className="h-9 min-w-44 flex-1"
            ariaLabel="按赛道筛选标签"
          />
          <Select
            value={sort}
            onValueChange={(value) => {
              setSort(value as typeof sort)
              setPage(0)
            }}
          >
            <SelectTrigger className="h-9 w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="aweme_count:desc">关联视频最多</SelectItem>
              <SelectItem value="task_count:desc">关联任务最多</SelectItem>
              <SelectItem value="last_seen_at:desc">最近发现</SelectItem>
              <SelectItem value="name:asc">标签名称</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </PageHero>

      <Card>
        <CardContent className="space-y-3 p-3">
          <div className="overflow-hidden rounded-xl border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>标签</TableHead>
                  <TableHead>视频</TableHead>
                  <TableHead>任务</TableHead>
                  <TableHead>最近发现</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.length ? (
                  rows.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className="font-medium">
                        #{item.name}
                      </TableCell>
                      <TableCell>{item.aweme_count}</TableCell>
                      <TableCell>{item.task_count}</TableCell>
                      <TableCell>{formatDate(item.last_seen_at)}</TableCell>
                      <TableCell className="text-right">
                        <Button size="sm" variant="outline" asChild>
                          <Link
                            to="/douyin-library"
                            search={{
                              track:
                                trackId === allTracksValue
                                  ? undefined
                                  : trackId,
                              q: undefined,
                              task: undefined,
                              creator: undefined,
                              tag: item.id,
                              storage: undefined,
                              subtitle: undefined,
                              sort: undefined,
                            }}
                          >
                            <Film />
                            查看视频
                          </Link>
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className="h-32 text-center text-muted-foreground"
                    >
                      {tagsQuery.isLoading
                        ? "正在加载标签…"
                        : "暂无标签，可点击“同步历史标签”从已有作品中抽取"}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          <div className="flex items-center justify-end gap-2">
            <span className="mr-auto text-sm text-muted-foreground">
              共 {tagsQuery.data?.count ?? 0} 个标签
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
              disabled={(page + 1) * pageSize >= (tagsQuery.data?.count ?? 0)}
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

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value))
}
