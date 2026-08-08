import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  BookOpen,
  Braces,
  Check,
  Copy,
  ExternalLink,
  KeyRound,
  Search,
  Server,
  TerminalSquare,
  Wrench,
} from "lucide-react"
import { useMemo, useState } from "react"

import {
  type ApiOperationDocPublic,
  type McpToolDocPublic,
  SystemIntegrationsService,
} from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

export const Route = createFileRoute("/_layout/developer-tools")({
  component: DeveloperToolsPage,
  head: () => ({ meta: [{ title: "开发者中心 - Douyin Crawler" }] }),
})

const methodStyles: Record<string, string> = {
  GET: "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300",
  POST: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  PUT: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  PATCH:
    "border-violet-500/30 bg-violet-500/10 text-violet-700 dark:text-violet-300",
  DELETE: "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300",
}

function DeveloperToolsPage() {
  const [search, setSearch] = useState("")
  const [apiTag, setApiTag] = useState("all")
  const [swaggerOpen, setSwaggerOpen] = useState(false)
  const query = useQuery({
    queryKey: ["system-integration-docs"],
    queryFn: () => SystemIntegrationsService.getIntegrationDocs(),
    staleTime: 30_000,
  })
  const data = query.data
  const normalizedSearch = search.trim().toLocaleLowerCase()
  const tags = useMemo(
    () =>
      Array.from(
        new Set(data?.api_operations.flatMap((item) => item.tags) ?? []),
      ).sort(),
    [data?.api_operations],
  )
  const apiOperations = useMemo(
    () =>
      (data?.api_operations ?? []).filter((item) => {
        const matchesTag = apiTag === "all" || item.tags.includes(apiTag)
        const haystack = [
          item.method,
          item.path,
          item.summary,
          item.description,
          ...item.tags,
        ]
          .join(" ")
          .toLocaleLowerCase()
        return (
          matchesTag &&
          (!normalizedSearch || haystack.includes(normalizedSearch))
        )
      }),
    [apiTag, data?.api_operations, normalizedSearch],
  )
  const mcpTools = useMemo(
    () =>
      (data?.mcp_tools ?? []).filter((item) =>
        [item.name, item.title ?? "", item.description]
          .join(" ")
          .toLocaleLowerCase()
          .includes(normalizedSearch),
      ),
    [data?.mcp_tools, normalizedSearch],
  )

  if (query.isLoading) {
    return (
      <div className="py-24 text-center text-muted-foreground">
        正在读取接口与 MCP 注册表…
      </div>
    )
  }
  if (query.isError || !data) {
    return (
      <Card className="mx-auto max-w-xl">
        <CardHeader>
          <CardTitle>文档加载失败</CardTitle>
          <CardDescription>
            无法从后端读取集成目录，请确认 API 服务已启动。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => query.refetch()}>重新加载</Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      <section className="overflow-hidden rounded-3xl border bg-gradient-to-br from-primary/10 via-card to-card p-6 shadow-sm md:p-8">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <div className="mb-3 flex items-center gap-2 text-sm font-medium text-primary">
              <BookOpen className="size-4" /> API & MCP catalog
            </div>
            <h1 className="text-3xl font-semibold tracking-tight">
              开发者中心
            </h1>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              从运行中的 OpenAPI 和 MCP
              注册表实时生成，接口或工具更新后无需手工维护文档。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" asChild>
              <a href={data.api_openapi_url} target="_blank" rel="noreferrer">
                <Braces /> OpenAPI JSON <ExternalLink />
              </a>
            </Button>
            <Button onClick={() => setSwaggerOpen(true)}>
              <BookOpen /> 交互式 API 文档
            </Button>
          </div>
        </div>
        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          <Metric
            icon={Server}
            label="API 接口"
            value={data.api_operation_count}
          />
          <Metric icon={Wrench} label="MCP 工具" value={data.mcp_tool_count} />
          <Metric icon={Check} label="文档来源" value="实时注册表" />
        </div>
      </section>

      <div className="relative">
        <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="搜索接口路径、说明或 MCP 工具名称"
          className="pl-9"
        />
      </div>

      <Tabs defaultValue="api" className="gap-4">
        <TabsList>
          <TabsTrigger value="api">
            <Server /> API 文档
          </TabsTrigger>
          <TabsTrigger value="mcp">
            <Wrench /> MCP 工具
          </TabsTrigger>
        </TabsList>

        <TabsContent value="api" className="space-y-4">
          <Card>
            <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="font-medium">{data.api_title}</p>
                <p className="text-sm text-muted-foreground">
                  当前显示 {apiOperations.length} / {data.api_operation_count}{" "}
                  个接口
                </p>
              </div>
              <Select value={apiTag} onValueChange={setApiTag}>
                <SelectTrigger className="w-full sm:w-64">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部接口分组</SelectItem>
                  {tags.map((tag) => (
                    <SelectItem key={tag} value={tag}>
                      {tag}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </CardContent>
          </Card>
          <div className="space-y-3">
            {apiOperations.map((operation) => (
              <ApiOperationCard
                key={`${operation.method}-${operation.path}`}
                operation={operation}
              />
            ))}
            {!apiOperations.length && <EmptySearch />}
          </div>
        </TabsContent>

        <TabsContent value="mcp" className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-2">
            <ConnectionCard
              icon={TerminalSquare}
              title="STDIO 接入"
              description="适用于在项目目录内启动的本地 Agent 客户端。"
              value={data.mcp_stdio_command}
            />
            <ConnectionCard
              icon={Server}
              title="Streamable HTTP 接入"
              description={`服务地址：${data.mcp_streamable_http_url}`}
              value={data.mcp_http_command}
            />
          </div>
          <Card>
            <CardContent className="flex flex-col gap-2 p-4 text-sm sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="font-medium">MCP 服务端点</p>
                <p className="mt-1 break-all font-mono text-xs text-muted-foreground">
                  {data.mcp_streamable_http_url}
                </p>
              </div>
              <CopyButton value={data.mcp_streamable_http_url} />
            </CardContent>
          </Card>
          <div className="grid gap-3 xl:grid-cols-2">
            {mcpTools.map((tool) => (
              <McpToolCard key={tool.name} tool={tool} />
            ))}
          </div>
          {!mcpTools.length && <EmptySearch />}
        </TabsContent>
      </Tabs>

      <Dialog open={swaggerOpen} onOpenChange={setSwaggerOpen}>
        <DialogContent className="h-[88vh] max-w-[calc(100vw-2rem)] grid-rows-[auto_minmax(0,1fr)] gap-3 p-4 sm:max-w-6xl">
          <DialogHeader>
            <DialogTitle>交互式 API 文档</DialogTitle>
            <DialogDescription>
              Swagger UI 已嵌入系统；调用受保护接口前请在文档中完成 Authorize。
            </DialogDescription>
          </DialogHeader>
          <iframe
            title="FastAPI Swagger 文档"
            src={data.api_swagger_url}
            className="h-full min-h-0 w-full rounded-xl border bg-white"
          />
        </DialogContent>
      </Dialog>
    </div>
  )
}

function Metric({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Server
  label: string
  value: number | string
}) {
  return (
    <div className="rounded-2xl border bg-card/80 p-4 shadow-sm">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Icon className="size-4 text-primary" /> {label}
      </div>
      <p className="mt-2 text-2xl font-semibold">{value}</p>
    </div>
  )
}

function ApiOperationCard({ operation }: { operation: ApiOperationDocPublic }) {
  return (
    <details className="group rounded-2xl border bg-card shadow-sm open:ring-1 open:ring-primary/15">
      <summary className="flex cursor-pointer list-none flex-col gap-3 p-4 sm:flex-row sm:items-center">
        <Badge
          variant="outline"
          className={`w-20 justify-center font-mono ${methodStyles[operation.method] ?? ""}`}
        >
          {operation.method}
        </Badge>
        <code className="min-w-0 flex-1 break-all text-sm font-semibold">
          {operation.path}
        </code>
        <span className="text-sm text-muted-foreground">
          {operation.summary}
        </span>
        {operation.auth_required && (
          <Badge variant="secondary">
            <KeyRound /> 鉴权
          </Badge>
        )}
      </summary>
      <div className="space-y-4 border-t p-4">
        {operation.description && (
          <p className="text-sm leading-6 text-muted-foreground">
            {operation.description}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          {operation.tags.map((tag) => (
            <Badge key={tag} variant="outline">
              {tag}
            </Badge>
          ))}
          {operation.response_codes.map((code) => (
            <Badge key={code} variant="secondary">
              HTTP {code}
            </Badge>
          ))}
        </div>
        <ParameterGrid parameters={operation.parameters} />
        {operation.request_body && (
          <SchemaPreview
            title="请求体"
            schema={requestBodySchema(operation.request_body)}
          />
        )}
        {operation.operation_id && (
          <p className="break-all font-mono text-xs text-muted-foreground">
            operationId: {operation.operation_id}
          </p>
        )}
      </div>
    </details>
  )
}

function McpToolCard({ tool }: { tool: McpToolDocPublic }) {
  const schema = tool.input_schema as JsonObject
  const properties = asObject(schema.properties)
  const required = new Set(
    Array.isArray(schema.required) ? schema.required.map(String) : [],
  )
  return (
    <details className="group rounded-2xl border bg-card shadow-sm open:ring-1 open:ring-primary/15">
      <summary className="cursor-pointer list-none p-5">
        <div className="flex items-start gap-3">
          <div className="rounded-xl bg-primary/10 p-2 text-primary">
            <Wrench className="size-4" />
          </div>
          <div className="min-w-0">
            <code className="break-all text-sm font-semibold">{tool.name}</code>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              {tool.description || "暂无工具说明"}
            </p>
          </div>
        </div>
      </summary>
      <div className="space-y-3 border-t p-4">
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          输入参数 · {Object.keys(properties).length}
        </p>
        {Object.entries(properties).map(([name, value]) => (
          <div key={name} className="rounded-xl border bg-muted/20 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <code className="text-sm font-medium">{name}</code>
              <Badge variant="outline">{schemaLabel(asObject(value))}</Badge>
              {required.has(name) && <Badge>必填</Badge>}
            </div>
            {"default" in asObject(value) && (
              <p className="mt-2 text-xs text-muted-foreground">
                默认值：{formatValue(asObject(value).default)}
              </p>
            )}
            {schemaEnum(value).length > 0 && (
              <p className="mt-1 break-all text-xs text-muted-foreground">
                可选值：{schemaEnum(value).map(formatValue).join(" / ")}
              </p>
            )}
          </div>
        ))}
        {!Object.keys(properties).length && (
          <p className="text-sm text-muted-foreground">该工具没有输入参数。</p>
        )}
      </div>
    </details>
  )
}

type JsonObject = Record<string, unknown>

function ParameterGrid({
  parameters,
}: {
  parameters: Array<Record<string, unknown>>
}) {
  if (!parameters.length) return null
  return (
    <div>
      <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        请求参数
      </p>
      <div className="grid gap-2 md:grid-cols-2">
        {parameters.map((parameter, index) => (
          <div
            key={`${String(parameter.name)}-${index}`}
            className="rounded-xl border bg-muted/20 p-3"
          >
            <div className="flex flex-wrap items-center gap-2">
              <code className="text-sm font-medium">
                {String(parameter.name ?? "parameter")}
              </code>
              <Badge variant="outline">{String(parameter.in ?? "query")}</Badge>
              <Badge variant="secondary">
                {schemaLabel(asObject(parameter.schema))}
              </Badge>
              {Boolean(parameter.required) && <Badge>必填</Badge>}
            </div>
            {typeof parameter.description === "string" && (
              <p className="mt-2 text-xs text-muted-foreground">
                {parameter.description}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function SchemaPreview({
  title,
  schema,
}: {
  title: string
  schema: JsonObject
}) {
  return (
    <div className="rounded-xl border bg-muted/20 p-3">
      <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
        {title}
      </p>
      <code className="mt-2 block break-all text-sm">
        {schemaLabel(schema)}
      </code>
    </div>
  )
}

function ConnectionCard({
  icon: Icon,
  title,
  description,
  value,
}: {
  icon: typeof Server
  title: string
  description: string
  value: string
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Icon className="size-5 text-primary" />
          <CardTitle className="text-base">{title}</CardTitle>
        </div>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-start gap-2 rounded-xl bg-zinc-950 p-3 text-zinc-100">
          <code className="min-w-0 flex-1 break-all text-xs leading-5">
            {value}
          </code>
          <CopyButton value={value} inverted />
        </div>
      </CardContent>
    </Card>
  )
}

function CopyButton({
  value,
  inverted = false,
}: {
  value: string
  inverted?: boolean
}) {
  const [copied, setCopied] = useState(false)
  return (
    <Button
      type="button"
      size="icon-sm"
      variant="ghost"
      className={
        inverted ? "text-zinc-100 hover:bg-white/10 hover:text-white" : ""
      }
      aria-label="复制"
      onClick={async () => {
        await navigator.clipboard.writeText(value)
        setCopied(true)
        window.setTimeout(() => setCopied(false), 1500)
      }}
    >
      {copied ? <Check /> : <Copy />}
    </Button>
  )
}

function EmptySearch() {
  return (
    <Card>
      <CardContent className="py-16 text-center text-muted-foreground">
        没有匹配的接口或工具，请调整搜索条件。
      </CardContent>
    </Card>
  )
}

function asObject(value: unknown): JsonObject {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
    : {}
}

function schemaLabel(schema: JsonObject): string {
  if (typeof schema.$ref === "string")
    return schema.$ref.split("/").pop() ?? "object"
  if (typeof schema.type === "string") {
    if (schema.type === "array")
      return `${schemaLabel(asObject(schema.items))}[]`
    return schema.type
  }
  if (Array.isArray(schema.anyOf)) {
    return schema.anyOf
      .map((value) => schemaLabel(asObject(value)))
      .filter((value, index, all) => all.indexOf(value) === index)
      .join(" | ")
  }
  return "object"
}

function schemaEnum(value: unknown): unknown[] {
  const schema = asObject(value)
  if (Array.isArray(schema.enum)) return schema.enum
  if (!Array.isArray(schema.anyOf)) return []
  return schema.anyOf.flatMap((item) => {
    const enumValues = asObject(item).enum
    return Array.isArray(enumValues) ? enumValues : []
  })
}

function requestBodySchema(body: Record<string, unknown>): JsonObject {
  const content = asObject(body.content)
  const mediaType = asObject(
    content["application/json"] ?? Object.values(content)[0],
  )
  return asObject(mediaType.schema)
}

function formatValue(value: unknown): string {
  if (value === undefined) return "-"
  return typeof value === "string" ? value : JSON.stringify(value)
}
