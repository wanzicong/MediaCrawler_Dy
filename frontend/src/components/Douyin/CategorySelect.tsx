import { useQuery } from "@tanstack/react-query"
import { FolderTree, RefreshCw } from "lucide-react"
import type { DouyinCategoryPublic } from "@/client"
import { DouyinService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { cn } from "@/lib/utils"

export const allCategoriesValue = "all"

/**
 * 内容分类目录（用户私有资产，最多两级）。
 *
 * 返回扁平列表：一级分类在前、其子类紧跟其后，供下拉按组渲染。
 * 选一级分类时后端会自动带出它的全部子类，所以下拉里只列节点、不做多选。
 */
export function useCategoryCatalog(enabled = true) {
  return useQuery({
    queryKey: ["douyin-category-options"],
    queryFn: () => DouyinService.listCategoriesRoute(),
    enabled,
    retry: false,
    staleTime: 15_000,
  })
}

export type CategoryTreeNode = {
  parent: DouyinCategoryPublic
  children: DouyinCategoryPublic[]
}

/** 把扁平分类列表按 parent_id 组成两级树（父级不存在时按一级处理）。 */
export function buildCategoryTree(
  rows: DouyinCategoryPublic[],
): CategoryTreeNode[] {
  const parents = rows
    .filter((row) => !row.parent_id)
    .sort(
      (a, b) =>
        a.sort_order - b.sort_order || a.created_at.localeCompare(b.created_at),
    )
  const childrenByParent = new Map<string, DouyinCategoryPublic[]>()
  for (const row of rows) {
    if (!row.parent_id) continue
    const bucket = childrenByParent.get(row.parent_id) ?? []
    bucket.push(row)
    childrenByParent.set(row.parent_id, bucket)
  }
  const nodes = parents.map((parent) => ({
    parent,
    children: (childrenByParent.get(parent.id) ?? []).sort(
      (a, b) =>
        a.sort_order - b.sort_order || a.created_at.localeCompare(b.created_at),
    ),
  }))
  // 父级被删/数据异常时，孤立子类退化成一级节点，避免整条数据在下拉里消失
  const known = new Set(parents.map((row) => row.id))
  for (const [parentId, children] of childrenByParent) {
    if (known.has(parentId)) continue
    for (const child of children) {
      nodes.push({ parent: child, children: [] })
    }
  }
  return nodes
}

/** 分类名（含大类前缀），用于筛选 chips 的文案。 */
export function categoryDisplayName(
  rows: DouyinCategoryPublic[],
  categoryId: string,
): string {
  const target = rows.find((row) => row.id === categoryId)
  if (!target) return categoryId.slice(0, 8)
  if (!target.parent_id) return target.name
  const parent = rows.find((row) => row.id === target.parent_id)
  return parent ? `${parent.name} / ${target.name}` : target.name
}

export function CategorySelect({
  value,
  onValueChange,
  includeAll = false,
  enabled = true,
  ariaLabel = "选择内容分类",
  className,
}: {
  value: string
  onValueChange: (value: string) => void
  includeAll?: boolean
  enabled?: boolean
  ariaLabel?: string
  className?: string
}) {
  const categoriesQuery = useCategoryCatalog(enabled)
  const nodes = buildCategoryTree(categoriesQuery.data?.data ?? [])

  if (categoriesQuery.isError) {
    return (
      <div className={cn("flex w-full items-center gap-2", className)}>
        <div
          role="alert"
          className="flex h-9 min-w-0 flex-1 items-center rounded-md border border-destructive/35 bg-destructive/5 px-3 text-sm text-destructive"
        >
          分类加载失败
        </div>
        <Button
          type="button"
          size="icon"
          variant="outline"
          aria-label="重新加载分类"
          disabled={categoriesQuery.isFetching}
          onClick={() => void categoriesQuery.refetch()}
        >
          <RefreshCw
            className={categoriesQuery.isFetching ? "animate-spin" : ""}
          />
        </Button>
      </div>
    )
  }

  const placeholder = categoriesQuery.isLoading
    ? "正在加载分类…"
    : nodes.length === 0
      ? "暂无内容分类"
      : "选择内容分类"

  return (
    <Select
      value={value}
      onValueChange={onValueChange}
      disabled={!enabled || categoriesQuery.isLoading}
    >
      <SelectTrigger
        className={cn("min-h-9 w-full", className)}
        aria-label={ariaLabel}
      >
        <FolderTree aria-hidden="true" />
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {includeAll && (
          <>
            <SelectItem value={allCategoriesValue}>全部分类</SelectItem>
            <SelectSeparator />
          </>
        )}
        {nodes.map((node) => (
          <SelectGroup key={node.parent.id}>
            <SelectItem value={node.parent.id}>
              {node.parent.name}
              <Badge variant="secondary" className="ml-2 font-normal">
                {node.parent.video_count} 视频 · {node.parent.creator_count}{" "}
                达人
              </Badge>
            </SelectItem>
            {node.children.map((child) => (
              <SelectItem key={child.id} value={child.id} className="pl-6">
                {child.name}
                <Badge variant="secondary" className="ml-2 font-normal">
                  {child.video_count} 视频 · {child.creator_count} 达人
                </Badge>
              </SelectItem>
            ))}
          </SelectGroup>
        ))}
        {nodes.length === 0 && (
          // 空态文案必须包在 SelectGroup 里：Radix 的 SelectLabel 脱离 Group 会抛错，
          // 抛错会被路由/React 反复重渲染，最终把页面主线程卡死。
          <SelectGroup>
            <div className="px-2 py-1.5 text-xs text-muted-foreground">
              还没有分类，先去「内容分类」新建
            </div>
          </SelectGroup>
        )}
      </SelectContent>
    </Select>
  )
}
