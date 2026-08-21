import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ChevronLeft,
  ChevronRight,
  Eye,
  FileSearch,
  RefreshCw,
  ScrollText,
} from "lucide-react"
import { useState } from "react"

import {
  type DouyinListRequestLogsData,
  type DouyinRequestLogPublic,
  DouyinService,
} from "@/client"
import { PageHero } from "@/components/Common/PageShell"
import {
  type ListViewMode,
  usePersistentViewMode,
  ViewModeToggle,
} from "@/components/Common/ViewModeToggle"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
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

export const Route = createFileRoute("/_layout/douyin-request-logs")({
  component: DouyinRequestLogsPage,
  head: () => ({ meta: [{ title: "请求日志 - 灵感采集台" }] }),
})

const PAGE_SIZE = 50
const ALL_TASKS = "all"

type MethodFilter = "all" | "GET" | "POST"

type AppliedFilters = {
  taskId?: string
  method?: string
  path?: string
  responseStatus?: number
  createdFrom?: string
  createdTo?: string
}

function DouyinRequestLogsPage() {
  const [taskId, setTaskId] = useState(ALL_TASKS)
  const [method, setMethod] = useState<MethodFilter>("all")
  const [pathContains, setPathContains] = useState("")
  const [responseStatus, setResponseStatus] = useState("")
  const [createdFrom, setCreatedFrom] = useState("")
  const [createdTo, setCreatedTo] = useState("")
  const [applied, setApplied] = useState<AppliedFilters>({})
  const [skip, setSkip] = useState(0)
  const [detail, setDetail] = useState<DouyinRequestLogPublic | null>(null)
  const [viewMode, setViewMode] = usePersistentViewMode(
    "douyin-request-logs-view",
  )

  const tasks = useQuery({
    queryKey: ["douyin-task-options"],
    queryFn: () => DouyinService.listTasks({ limit: 200 }),
  })
  const taskMap = new Map(
    (tasks.data?.data ?? []).map((item) => [
      item.id,
      item.display_title || item.track_name || item.id.slice(0, 8),
    ]),
  )

  const logs = useQuery({
    queryKey: ["douyin-request-logs", applied, skip],
    queryFn: () => DouyinService.listRequestLogs(buildQuery(applied, skip)),
  })
  const rows = logs.data?.data ?? []
  const total = logs.data?.count ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const currentPage = Math.floor(skip / PAGE_SIZE) + 1

  const applyFilters = () => {
    const status =
      responseStatus.trim() === ""
        ? undefined
        : Number.parseInt(responseStatus.trim(), 10)
    setSkip(0)
    setApplied({
      taskId: taskId === ALL_TASKS ? undefined : taskId,
      method: method === "all" ? undefined : method,
      path: pathContains.trim() || undefined,
      responseStatus: status && !Number.isNaN(status) ? status : undefined,
      createdFrom: createdFrom || undefined,
      createdTo: createdTo || undefined,
    })
  }

  return (
    <div className="page-stack">
      <PageHero
        eyebrow="运营与风控"
        icon={ScrollText}
        title="请求日志"
        description="记录采集过程中对抖音数据接口的每次调用；失败请求会保留经过脱敏和限长处理的返回信息。"
        actions={
          <Button
            variant="outline"
            onClick={() => logs.refetch()}
            disabled={logs.isFetching}
          >
            <RefreshCw
              className={logs.isFetching ? "animate-spin" : undefined}
            />
            刷新
          </Button>
        }
      />

      <Card>
        <CardContent className="space-y-4 p-5">
          <div className="flex flex-wrap items-end gap-2">
            <div className="flex flex-col gap-1.5">
              <label
                htmlFor="request-log-task"
                className="text-xs text-muted-foreground"
              >
                采集任务
              </label>
              <Select value={taskId} onValueChange={setTaskId}>
                <SelectTrigger id="request-log-task" className="w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_TASKS}>全部任务</SelectItem>
                  {(tasks.data?.data ?? []).map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.display_title ||
                        item.track_name ||
                        item.id.slice(0, 8)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label
                htmlFor="request-log-method"
                className="text-xs text-muted-foreground"
              >
                请求方法
              </label>
              <Select
                value={method}
                onValueChange={(value) => setMethod(value as MethodFilter)}
              >
                <SelectTrigger id="request-log-method" className="w-36">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部方法</SelectItem>
                  <SelectItem value="GET">GET</SelectItem>
                  <SelectItem value="POST">POST</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label
                htmlFor="request-log-path"
                className="text-xs text-muted-foreground"
              >
                路径包含
              </label>
              <Input
                id="request-log-path"
                placeholder="如 aweme/detail"
                className="w-48"
                value={pathContains}
                onChange={(event) => setPathContains(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label
                htmlFor="request-log-status"
                className="text-xs text-muted-foreground"
              >
                响应状态码
              </label>
              <Input
                id="request-log-status"
                placeholder="如 403"
                className="w-28"
                inputMode="numeric"
                value={responseStatus}
                onChange={(event) => setResponseStatus(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label
                htmlFor="request-log-from"
                className="text-xs text-muted-foreground"
              >
                开始时间
              </label>
              <Input
                id="request-log-from"
                type="datetime-local"
                className="w-48"
                value={createdFrom}
                onChange={(event) => setCreatedFrom(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label
                htmlFor="request-log-to"
                className="text-xs text-muted-foreground"
              >
                结束时间
              </label>
              <Input
                id="request-log-to"
                type="datetime-local"
                className="w-48"
                value={createdTo}
                onChange={(event) => setCreatedTo(event.target.value)}
              />
            </div>
            <Button onClick={applyFilters}>
              <FileSearch />
              查询
            </Button>
          </div>

          <div className="flex justify-end">
            <ViewModeToggle value={viewMode} onChange={setViewMode} />
          </div>

          {viewMode === "table" ? (
            <div className="overflow-x-auto rounded-xl border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>时间</TableHead>
                    <TableHead>方法</TableHead>
                    <TableHead>路径</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>耗时</TableHead>
                    <TableHead>任务</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.length ? (
                    rows.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                          {formatDate(item.created_at)}
                        </TableCell>
                        <TableCell>
                          <span className="font-mono text-xs">
                            {item.method}
                          </span>
                        </TableCell>
                        <TableCell className="max-w-md">
                          <p
                            className="truncate font-mono text-xs"
                            title={item.path}
                          >
                            {item.path}
                          </p>
                          {item.error && (
                            <p className="mt-1 text-xs text-destructive">
                              {item.error}
                            </p>
                          )}
                          {item.failure_detail && (
                            <p
                              className="mt-1 truncate text-xs text-destructive/85"
                              title={failureSummary(item.failure_detail)}
                            >
                              返回：{failureSummary(item.failure_detail)}
                            </p>
                          )}
                        </TableCell>
                        <TableCell>
                          <StatusBadge status={item.response_status} />
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-xs">
                          {item.duration_ms} ms
                        </TableCell>
                        <TableCell>
                          {item.task_id ? (
                            <Link
                              to="/douyin/$taskId"
                              params={{ taskId: item.task_id }}
                              className="text-xs text-muted-foreground hover:text-primary"
                            >
                              {taskMap.get(item.task_id) ??
                                item.task_id.slice(0, 8)}
                            </Link>
                          ) : (
                            <span className="text-xs text-muted-foreground">
                              —
                            </span>
                          )}
                        </TableCell>
                        <TableCell>
                          <div className="flex justify-end">
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              aria-label="查看请求详情"
                              onClick={() => setDetail(item)}
                            >
                              <Eye />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell
                        colSpan={7}
                        className="h-36 text-center text-muted-foreground"
                      >
                        {logs.isLoading
                          ? "加载请求日志..."
                          : "没有符合筛选条件的请求日志"}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          ) : rows.length ? (
            <div
              className={
                viewMode === "cards"
                  ? "grid gap-3 md:grid-cols-2 xl:grid-cols-3"
                  : "space-y-2"
              }
            >
              {rows.map((item) => (
                <RequestLogPreview
                  key={item.id}
                  log={item}
                  taskLabel={
                    item.task_id
                      ? (taskMap.get(item.task_id) ?? item.task_id.slice(0, 8))
                      : null
                  }
                  viewMode={viewMode}
                  onOpen={() => setDetail(item)}
                />
              ))}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed py-16 text-center text-sm text-muted-foreground">
              {logs.isLoading
                ? "加载请求日志..."
                : "没有符合筛选条件的请求日志"}
            </div>
          )}

          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              共 {total} 条记录 · 第 {currentPage} / {pageCount} 页
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={skip === 0}
                onClick={() => setSkip(Math.max(0, skip - PAGE_SIZE))}
              >
                <ChevronLeft />
                上一页
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={skip + PAGE_SIZE >= total}
                onClick={() => setSkip(skip + PAGE_SIZE)}
              >
                下一页
                <ChevronRight />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <RequestLogDetail
        log={detail}
        taskLabel={
          detail?.task_id ? (taskMap.get(detail.task_id) ?? null) : null
        }
        onClose={() => setDetail(null)}
      />
    </div>
  )
}

function RequestLogPreview({
  log,
  taskLabel,
  viewMode,
  onOpen,
}: {
  log: DouyinRequestLogPublic
  taskLabel: string | null
  viewMode: Exclude<ListViewMode, "table">
  onOpen: () => void
}) {
  return (
    <div
      className={`rounded-xl border bg-card p-4 ${
        viewMode === "rows" ? "flex items-center gap-4" : "space-y-3"
      }`}
    >
      <div className={viewMode === "rows" ? "min-w-0 flex-1" : "min-w-0"}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs font-semibold">{log.method}</span>
          <StatusBadge status={log.response_status} />
          <span className="text-xs text-muted-foreground">
            {log.duration_ms} ms
          </span>
        </div>
        <p className="mt-2 truncate font-mono text-xs" title={log.path}>
          {log.path}
        </p>
        {log.error && (
          <p className="mt-1 truncate text-xs text-destructive">{log.error}</p>
        )}
        {log.failure_detail && (
          <p className="mt-1 line-clamp-2 text-xs text-destructive/85">
            返回：{failureSummary(log.failure_detail)}
          </p>
        )}
      </div>
      <div
        className={`flex items-center gap-3 text-xs text-muted-foreground ${
          viewMode === "rows" ? "shrink-0" : "justify-between"
        }`}
      >
        <span>{formatDate(log.created_at)}</span>
        {taskLabel && <span className="max-w-32 truncate">{taskLabel}</span>}
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label="查看请求详情"
          onClick={onOpen}
        >
          <Eye />
        </Button>
      </div>
    </div>
  )
}

function buildQuery(
  applied: AppliedFilters,
  skip: number,
): DouyinListRequestLogsData {
  return {
    ...applied,
    skip,
    limit: PAGE_SIZE,
  }
}

function StatusBadge({ status }: { status: number | null }) {
  if (status === null) {
    return <Badge variant="destructive">异常</Badge>
  }
  if (status >= 500) {
    return <Badge variant="destructive">{status}</Badge>
  }
  if (status >= 400) {
    return <Badge variant="secondary">{status}</Badge>
  }
  return <Badge variant="outline">{status}</Badge>
}

function RequestLogDetail({
  log,
  taskLabel,
  onClose,
}: {
  log: DouyinRequestLogPublic | null
  taskLabel: string | null
  onClose: () => void
}) {
  return (
    <Dialog open={Boolean(log)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>抖音接口请求详情</DialogTitle>
          <DialogDescription>
            请求信息和失败返回均经过脱敏；超长失败正文只保留诊断预览，日志仅对任务所有者可见。
          </DialogDescription>
        </DialogHeader>
        {log && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm font-semibold">
                {log.method}
              </span>
              <StatusBadge status={log.response_status} />
              <span className="text-xs text-muted-foreground">
                {log.duration_ms} ms · {formatDate(log.created_at)}
              </span>
              {taskLabel && (
                <span className="text-xs text-muted-foreground">
                  任务：{taskLabel}
                </span>
              )}
            </div>
            {log.error && (
              <p className="text-sm text-destructive">异常类型：{log.error}</p>
            )}
            <JsonSection title="完整请求地址" value={log.url} mono />
            <JsonSection title="查询参数" value={log.query_params} />
            <JsonSection title="请求头" value={log.request_headers} />
            {log.request_body !== null && (
              <JsonSection title="请求体" value={log.request_body} />
            )}
            {log.failure_detail !== null && (
              <JsonSection
                title="失败返回信息（已脱敏）"
                value={log.failure_detail}
              />
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function JsonSection({
  title,
  value,
  mono = false,
}: {
  title: string
  value: unknown
  mono?: boolean
}) {
  const text =
    typeof value === "string" ? value : (JSON.stringify(value, null, 2) ?? "{}")
  return (
    <div>
      <h3 className="mb-1.5 text-sm font-medium">{title}</h3>
      <pre
        className={`max-h-56 overflow-auto rounded-lg border bg-muted/25 p-3 text-xs ${
          mono ? "font-mono" : ""
        }`}
      >
        {text}
      </pre>
    </div>
  )
}

function failureSummary(value: Record<string, unknown>) {
  const body = value.body
  if (typeof body === "string" && body.trim()) return body.trim().slice(0, 120)
  if (body && typeof body === "object" && !Array.isArray(body)) {
    const payload = body as Record<string, unknown>
    const messageKeys = [
      "status_msg",
      "message",
      "msg",
      "detail",
      "description",
    ]
    for (const key of messageKeys) {
      if (typeof payload[key] === "string" && payload[key]) {
        return String(payload[key]).slice(0, 120)
      }
    }
    const nilInfo = payload.search_nil_info
    if (nilInfo && typeof nilInfo === "object" && !Array.isArray(nilInfo)) {
      const nilType = (nilInfo as Record<string, unknown>).search_nil_type
      if (typeof nilType === "string" && nilType) return nilType
    }
    if (payload.status_code !== undefined) {
      return `业务状态 ${String(payload.status_code)}`
    }
  }
  if (typeof value.message === "string" && value.message) {
    return value.message.slice(0, 120)
  }
  return "已记录失败返回信息"
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(new Date(value))
}
